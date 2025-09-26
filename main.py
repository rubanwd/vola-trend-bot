# main.py
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from settings import Settings
from utils import ensure_dirs, setup_logger, write_jsonl, sleep_until_next_cycle, now_iso
from bybit_data import build_exchange, fetch_top_by_volatility_24h
from indicators import ema, rsi, macd, atr
from reporter import build_report_txt, build_signals_txt, write_file
from telegram_utils import send_document, send_text, TelegramError
from patterns import BULL_PATTERNS, BEAR_PATTERNS
from bybit_api import BybitAPI


# =========================
# OHLCV helpers
# =========================
def fetch_ohlcv_df(exchange, symbol: str, timeframe: str, limit: int = 300) -> pd.DataFrame:
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=min(max(limit, 50), 1000))
    df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms")
    return df


# =========================
# Indicators & patterns
# =========================
def evaluate_indicators(close: pd.Series, direction: str) -> Dict[str, bool]:
    checks = {}
    if Settings.ENABLE_EMA:
        e50 = ema(close, Settings.EMA_FAST)
        e200 = ema(close, Settings.EMA_SLOW)
        i = -1
        if Settings.RELAX_MODE in ("relaxed", "debug"):
            ok = (close.iat[i] > e200.iat[i]) or (e50.iat[i] > e200.iat[i]) if direction == "BULL" \
                else (close.iat[i] < e200.iat[i]) or (e50.iat[i] < e200.iat[i])
        else:
            ok = (close.iat[i] > e200.iat[i]) and (e50.iat[i] > e200.iat[i]) if direction == "BULL" \
                else (close.iat[i] < e200.iat[i]) and (e50.iat[i] < e200.iat[i])
        checks["EMA"] = bool(ok)

    if Settings.ENABLE_RSI:
        rv = float(rsi(close, Settings.RSI_LEN).iloc[-1])
        overbought = Settings.RSI_RELAXED_OVERBOUGHT if Settings.RELAX_MODE in ("relaxed", "debug") else Settings.RSI_OVERBOUGHT
        oversold   = Settings.RSI_RELAXED_OVERSOLD   if Settings.RELAX_MODE in ("relaxed", "debug") else Settings.RSI_OVERSOLD
        ok = (rv <= oversold) if direction == "BULL" else (rv >= overbought)
        checks["RSI"] = bool(ok)

    if Settings.ENABLE_MACD:
        _, _, hist = macd(close, Settings.MACD_FAST, Settings.MACD_SLOW, Settings.MACD_SIGNAL)
        if len(hist) >= 2:
            h1, h2 = float(hist.iloc[-2]), float(hist.iloc[-1])
            if Settings.RELAX_MODE in ("relaxed", "debug"):
                ok = (h2 > h1) if direction == "BULL" else (h2 < h1)
            else:
                ok = (h2 >= 0) if direction == "BULL" else (h2 <= 0)
            checks["MACD"] = bool(ok)
        else:
            checks["MACD"] = False

    return checks


def indicators_pass(checks: Dict[str, bool]) -> bool:
    if not checks:
        return True

    vals = [bool(v) for v in checks.values()]
    true_cnt = sum(vals)
    enabled_cnt = len(vals)

    mode = Settings.CONFIRM_MODE
    if mode == "auto":
        mode = "any" if Settings.RELAX_MODE == "debug" else "all"

    if mode == "all":
        return all(vals)
    if mode == "any":
        return any(vals)
    if mode in ("two_of_three", "2of3", "twoofthree"):
        return true_cnt >= 2 if enabled_cnt >= 2 else all(vals)
    return all(vals)


def find_patterns(df: pd.DataFrame, direction: str) -> List[str]:
    pats = []
    registry = BULL_PATTERNS if direction == "BULL" else BEAR_PATTERNS
    for name, fn in registry.items():
        try:
            if fn(df, trend_hint=direction):
                pats.append(name)
        except Exception:
            continue
    return pats


# =========================
# State helpers (signals + last entries)
# =========================
def _signals_state_file(data_dir: Path) -> Path:
    return data_dir / "state" / "last_signals.json"

def _entries_state_file(data_dir: Path) -> Path:
    return data_dir / "state" / "last_entries.json"

def have_prev_signals_state(data_dir: Path) -> bool:
    return _signals_state_file(data_dir).exists()

def load_last_signals(data_dir: Path) -> List[Dict]:
    p = _signals_state_file(data_dir)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def save_last_signals(data_dir: Path, signals: List[Dict]):
    p = _signals_state_file(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(signals, ensure_ascii=False), encoding="utf-8")

def load_last_entries(data_dir: Path) -> Dict[str, str]:
    """
    Возвращает словарь {bybit_symbol: iso_ts_last_entry}
    """
    p = _entries_state_file(data_dir)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_last_entries(data_dir: Path, mapping: Dict[str, str]):
    p = _entries_state_file(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")

def _signal_key(sig: Dict) -> str:
    return f"{sig['symbol']}|{sig['direction']}"


# =========================
# Trading helpers (Bybit)
# =========================
def count_open_positions(bybit: BybitAPI) -> int:
    try:
        pos = bybit.get_open_positions()
        return sum(1 for p in pos if abs(float(p.get("size") or 0)) > 0)
    except Exception:
        return 0

def is_symbol_open(bybit: BybitAPI, bybit_symbol: str) -> bool:
    try:
        pos = bybit.get_open_positions()
        for p in pos:
            if p.get("symbol") == bybit_symbol and abs(float(p.get("size") or 0)) > 0:
                return True
        return False
    except Exception:
        return False

def last_closed_age_hours(bybit: BybitAPI, bybit_symbol: str) -> float:
    try:
        res = bybit.get_closed_pnl(bybit_symbol, limit=50)
        items = res.get("list", [])
        if not items:
            return 9999.0
        latest = max(items, key=lambda x: int(x.get("updatedTime", 0) or 0))
        ts_ms = int(latest.get("updatedTime", 0) or 0)
        if ts_ms <= 0:
            return 9999.0
        t = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds() / 3600.0
    except Exception:
        return 9999.0

def pair_in_cooldown(now_utc: datetime, bybit_symbol: str, last_entries: Dict[str, str], bybit: BybitAPI) -> bool:
    """
    True -> вход запрещён.
    Логика:
      1) Если у нас есть локальная отметка последнего входа < 24ч — запрещаем.
      2) Иначе смотрим закрытые позиции на Bybit — если последняя закрыта < 24ч, запрещаем.
    """
    hours = Settings.REENTRY_COOLDOWN_HOURS
    iso = last_entries.get(bybit_symbol)
    if iso:
        try:
            t_local = datetime.fromisoformat(iso)
            if t_local.tzinfo is None:
                t_local = t_local.replace(tzinfo=timezone.utc)
            if (now_utc - t_local).total_seconds() / 3600.0 < hours:
                return True
        except Exception:
            pass
    # fallback к закрытым сделкам
    return last_closed_age_hours(bybit, bybit_symbol) < hours


def calc_levels_and_qty(
    bybit: BybitAPI, bybit_symbol: str, side: str, df: pd.DataFrame
) -> Tuple[str, str, str, str, float]:
    """
    Возвращает (qty_str, entry_ref_str, tp_str, sl_str, atr_val)
    """
    last = bybit.get_last_price(bybit_symbol)
    raw_qty = Settings.POSITION_USD / last
    qty_str = bybit.round_qty(bybit_symbol, raw_qty)
    qty_str = bybit.enforce_min_notional(bybit_symbol, qty_str, last)

    a = float(atr(df, Settings.ATR_LEN).iloc[-1])
    entry_ref = last
    if side == "Buy":
        sl_f = entry_ref - Settings.SL_ATR_MULT * a
        tp_f = entry_ref + Settings.TP_ATR_MULT * a
    else:
        sl_f = entry_ref + Settings.SL_ATR_MULT * a
        tp_f = entry_ref - Settings.TP_ATR_MULT * a

    sl_str = bybit.round_price(bybit_symbol, sl_f)
    tp_str = bybit.round_price(bybit_symbol, tp_f)
    return qty_str, str(entry_ref), tp_str, sl_str, a


def place_with_auto_position_idx(
    bybit: BybitAPI,
    bybit_symbol: str,
    side: str,
    qty_str: str,
    pos_mode_hint: str,
):
    hedge = (pos_mode_hint == "HEDGE")
    idx = 1 if (hedge and side == "Buy") else (2 if hedge and side == "Sell" else 0)

    try:
        bybit.place_market_order(bybit_symbol, side, qty_str, position_idx=idx)
        return idx, ("HEDGE" if idx in (1, 2) else "ONE_WAY")
    except RuntimeError as e:
        msg = str(e)
        if "position idx not match position mode" not in msg:
            raise
        alt_idx = 0 if idx in (1, 2) else (1 if side == "Buy" else 2)
        bybit.place_market_order(bybit_symbol, side, qty_str, position_idx=alt_idx)
        return alt_idx, ("HEDGE" if alt_idx in (1, 2) else "ONE_WAY")


def open_trade_if_ok(
    bybit: BybitAPI,
    logger,
    data_dir: Path,
    new_sigs: List[Dict],
    df_cache: Dict[str, pd.DataFrame],
    market_id_map: Dict[str, str],
    pos_mode: str,
):
    """
    Открываем сделки по «новым» сигналам с лимитами, ATR SL/TP, анти-реэнтри и запретом повторного открытия по паре.
    """
    if not new_sigs:
        return

    current_open = count_open_positions(bybit)
    slots_left = max(Settings.MAX_OPEN_POSITIONS - current_open, 0)
    if slots_left <= 0:
        logger.info("Лимит позиций достигнут (%d). Входы пропущены.", Settings.MAX_OPEN_POSITIONS)
        return

    last_entries = load_last_entries(data_dir)
    now_utc = datetime.now(timezone.utc)

    for sig in new_sigs[:slots_left]:
        ccxt_symbol = sig["symbol"]
        bybit_symbol = market_id_map.get(ccxt_symbol) or ccxt_symbol.replace("/", "").replace(":USDT", "")
        direction = sig["direction"]
        side = "Buy" if direction == "BULL" else "Sell"

        # 0) если уже есть открытая позиция по паре — запрет
        if is_symbol_open(bybit, bybit_symbol):
            logger.info("По %s уже есть открытая позиция — вход пропущен.", bybit_symbol)
            continue

        # 1) кулдаун 24ч по нашей локальной отметке + по закрытым сделкам на Bybit
        if pair_in_cooldown(now_utc, bybit_symbol, last_entries, bybit):
            logger.info("Cooldown по %s — менее %d часов с последнего входа/закрытия. Пропуск.",
                        bybit_symbol, Settings.REENTRY_COOLDOWN_HOURS)
            continue

        # 2) плечо (best-effort)
        try:
            bybit.set_leverage(bybit_symbol, Settings.LEVERAGE)
        except Exception as e:
            logger.warning("set_leverage %s: %s (продолжаем)", bybit_symbol, e)

        # 3) проверка данных
        df = df_cache.get(ccxt_symbol)
        if df is None or len(df) < 20:
            logger.info("Нет df в кэше для %s — пропуск", ccxt_symbol)
            continue

        # 4) уровни и qty
        try:
            qty_str, entry_ref_str, tp_str, sl_str, atr_val = calc_levels_and_qty(bybit, bybit_symbol, side, df)
        except RuntimeError as e:
            logger.error("Подготовка ордера %s: %s", bybit_symbol, e)
            continue

        # 5) вход
        try:
            used_idx, final_mode = place_with_auto_position_idx(bybit, bybit_symbol, side, qty_str, pos_mode)
            logger.info("Открыта позиция: %s %s qty=%s (idx=%d, mode=%s)", bybit_symbol, side, qty_str, used_idx, final_mode)
        except RuntimeError as e:
            logger.error("Не удалось открыть позицию %s %s: %s", bybit_symbol, side, e)
            continue

        # 6) TP/SL
        try:
            bybit.set_tp_sl(bybit_symbol, take_profit=tp_str, stop_loss=sl_str, position_idx=used_idx)
            logger.info("TP/SL проставлены: TP=%s SL=%s (idx=%d)", tp_str, sl_str, used_idx)
        except Exception as e:
            logger.warning("Не удалось проставить TP/SL для %s: %s", bybit_symbol, e)

        # 7) локальная отметка «последний вход по паре»
        last_entries[bybit_symbol] = now_utc.isoformat(timespec="seconds")
        save_last_entries(data_dir, last_entries)

        # 8) Telegram уведомление о сделке
        if Settings.TG_TRADE_BOT_TOKEN and Settings.TG_TRADE_CHAT_ID:
            try:
                pats = ", ".join(sig.get("patterns", [])) or "-"
                ch = sig.get("checks", {})
                flags = ", ".join([f"{k}={str(v)}" for k, v in ch.items()]) if ch else "-"
                text = (
                    "✅ ОТКРЫТА СДЕЛКА\n"
                    f"Пара: {ccxt_symbol} (Bybit: {bybit_symbol})\n"
                    f"Режим позиций: {final_mode} (idx={used_idx})\n"
                    f"Направление: {'LONG' if side=='Buy' else 'SHORT'}\n"
                    f"Объём: ${Settings.POSITION_USD} (~ qty {qty_str}) | Плечо x{Settings.LEVERAGE}\n"
                    f"Entry≈: {entry_ref_str}\n"
                    f"SL: {sl_str} | TP: {tp_str}\n"
                    f"ATR({Settings.ATR_LEN}): {atr_val:.4f}\n"
                    f"TF: {Settings.WORK_TF}\n"
                    f"Паттерны: {pats}\n"
                    f"Индикаторы: {flags}\n"
                    f"RSI: {sig.get('rsi'):.1f}\n"
                    f"Условие: новая пара; cooldown {Settings.REENTRY_COOLDOWN_HOURS}ч"
                )
                send_text(Settings.TG_TRADE_BOT_TOKEN, Settings.TG_TRADE_CHAT_ID, text)
            except Exception as e:
                logger.warning("TG trade notify error: %s", e)


# =========================
# Optional: anomaly filter
# =========================
def pass_anomaly_filter(exchange, symbol: str) -> bool:
    if not Settings.ANOMALY_FILTER_ENABLED:
        return True
    try:
        ddf = fetch_ohlcv_df(exchange, symbol, "1d", limit=8)
        if len(ddf) < 8:
            return True
        c = ddf["close"]
        ch24 = (c.iloc[-1] / c.iloc[-2] - 1.0) * 100.0
        ch7d = (c.iloc[-1] / c.iloc[-8] - 1.0) * 100.0
        if abs(ch24) >= Settings.MAX_24H_ABS_CHANGE_PCT or abs(ch7d) >= Settings.MAX_7D_ABS_CHANGE_PCT:
            return False
    except Exception:
        return True
    return True


# =========================
# Основной цикл
# =========================
def cycle_once(exchange, logger, data_dir: Path, bybit: BybitAPI, pos_mode: str):
    logger.info("=== Новый цикл ===")
    universe_rows = fetch_top_by_volatility_24h(exchange)
    universe_symbols = [r["symbol"] for r in universe_rows]
    logger.info(
        "Universe (top %d by 24h vol): %s",
        len(universe_rows),
        ", ".join(universe_symbols[:10]) + (" ..." if len(universe_symbols) > 10 else "")
    )

    # ccxt symbol -> bybit v5 symbol
    market_id_map: Dict[str, str] = {}
    for sym in universe_symbols:
        m = exchange.markets.get(sym) or {}
        bybit_symbol = m.get("id") or sym.replace("/", "").replace(":USDT", "")
        market_id_map[sym] = bybit_symbol

    signals: List[Dict] = []
    df_cache: Dict[str, pd.DataFrame] = {}

    for sym in universe_symbols:
        try:
            if not pass_anomaly_filter(exchange, sym):
                continue

            df = fetch_ohlcv_df(exchange, sym, Settings.WORK_TF, limit=300)
            df_cache[sym] = df
            if len(df) < 50:
                continue

            close = df["close"]

            # BULL
            pats_bull = find_patterns(df.tail(5), "BULL")
            if pats_bull:
                checks = evaluate_indicators(close, "BULL")
                if indicators_pass(checks):
                    signals.append({
                        "symbol": sym,
                        "direction": "BULL",
                        "rsi": float(rsi(close, Settings.RSI_LEN).iloc[-1]),
                        "patterns": pats_bull,
                        "checks": checks,
                    })

            # BEAR
            pats_bear = find_patterns(df.tail(5), "BEAR")
            if pats_bear:
                checks = evaluate_indicators(close, "BEAR")
                if indicators_pass(checks):
                    signals.append({
                        "symbol": sym,
                        "direction": "BEAR",
                        "rsi": float(rsi(close, Settings.RSI_LEN).iloc[-1]),
                        "patterns": pats_bear,
                        "checks": checks,
                    })

        except Exception as e:
            logger.warning("Ошибка по %s: %s", sym, e)

    # Новые сигналы против прошлой итерации
    prev_exists = have_prev_signals_state(data_dir)
    prev = load_last_signals(data_dir) if prev_exists else []
    prev_keys = {_signal_key(s) for s in prev}
    curr_keys = {_signal_key(s) for s in signals}
    new_keys = curr_keys - prev_keys
    new_sigs = [s for s in signals if _signal_key(s) in new_keys]

    # Торговля: на самом первом запуске — НЕ входим (bootstrap)
    if not prev_exists:
        logger.info("Bootstrap: первый запуск — сохраняем список сигналов, входы отключены в этом цикле.")
    else:
        try:
            open_trade_if_ok(bybit, logger, data_dir, new_sigs, df_cache, market_id_map, pos_mode)
        except Exception as e:
            logger.exception("Trade pipeline error: %s", e)

    # Сохраняем текущее состояние сигналов
    save_last_signals(data_dir, signals)

    # Отчёты / файлы / телега
    report_txt = build_report_txt(
        cycle_info={"top_n": Settings.TOP_N_BY_VOL,
                    "params": {
                        "WORK_TF": Settings.WORK_TF,
                        "EMA_FAST": Settings.EMA_FAST,
                        "EMA_SLOW": Settings.EMA_SLOW,
                        "RSI_LEN": Settings.RSI_LEN,
                        "RSI_OVERBOUGHT": Settings.RSI_OVERBOUGHT,
                        "RSI_OVERSOLD": Settings.RSI_OVERSOLD,
                        "RSI_RELAXED_OVERBOUGHT": Settings.RSI_RELAXED_OVERBOUGHT,
                        "RSI_RELAXED_OVERSOLD": Settings.RSI_RELAXED_OVERSOLD,
                        "MACD_FAST": Settings.MACD_FAST,
                        "MACD_SLOW": Settings.MACD_SLOW,
                        "MACD_SIGNAL": Settings.MACD_SIGNAL,
                        "TOP_N_BY_VOL": Settings.TOP_N_BY_VOL,
                        "RELAX_MODE": Settings.RELAX_MODE,
                        "CONFIRM_MODE": Settings.CONFIRM_MODE,
                        "ENABLE_RSI": Settings.ENABLE_RSI,
                        "ENABLE_EMA": Settings.ENABLE_EMA,
                        "ENABLE_MACD": Settings.ENABLE_MACD,
                    }},
        universe=universe_rows
    )
    rep_path = data_dir / "reports" / f"report_{Settings.WORK_TF}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.txt"
    write_file(rep_path, report_txt)
    logger.info("Report saved: %s", rep_path)

    sig_txt = build_signals_txt(Settings.WORK_TF, signals)
    sig_path = data_dir / "signals" / f"signals_{Settings.WORK_TF}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.txt"
    write_file(sig_path, sig_txt)
    logger.info("Signals saved: %s", sig_path)

    write_jsonl(data_dir / "logs" / "iterations.jsonl", {
        "ts": now_iso(),
        "signals": signals,
        "universe": universe_symbols
    })

    if Settings.TG_REPORT_BOT_TOKEN and Settings.TG_REPORT_CHAT_ID:
        try:
            send_text(Settings.TG_REPORT_BOT_TOKEN, Settings.TG_REPORT_CHAT_ID, "Report incoming…")
            send_document(Settings.TG_REPORT_BOT_TOKEN, Settings.TG_REPORT_CHAT_ID,
                          rep_path, caption="Pattern+Indicators report")
        except TelegramError as te:
            logger.error("Telegram REPORT error: %s", te)

    if signals and Settings.TG_SIGNAL_BOT_TOKEN and Settings.TG_SIGNAL_CHAT_ID:
        try:
            send_text(Settings.TG_SIGNAL_BOT_TOKEN, Settings.TG_SIGNAL_CHAT_ID, "Signals incoming…")
            send_document(Settings.TG_SIGNAL_BOT_TOKEN, Settings.TG_SIGNAL_CHAT_ID,
                          sig_path, caption="Confirmed candle patterns")
        except TelegramError as te:
            logger.error("Telegram SIGNAL error: %s", te)


# =========================
# Entrypoint
# =========================
def main():
    data_dir = ensure_dirs(Settings.DATA_DIR)
    logger = setup_logger("vola-trend-bot")
    exchange = build_exchange()   # ccxt для маркет-данных
    bybit = BybitAPI()            # прямой Bybit v5 для торговли

    # прогрев шагов цены/лота
    try:
        bybit.get_instruments()
    except Exception as e:
        logger.warning("Не удалось прогреть инструменты Bybit: %s", e)

    # Режим позиций
    pos_mode = bybit.get_position_mode()
    try:
        cfg = getattr(Settings, "BYBIT_POSITION_MODE", "auto").lower()
        if cfg in ("oneway", "one-way", "one_way", "single"):
            bybit.set_position_mode("ONE_WAY")
            pos_mode = "ONE_WAY"
        elif cfg in ("hedge", "both", "both_sides"):
            bybit.set_position_mode("HEDGE")
            pos_mode = "HEDGE"
    except Exception as e:
        logger.warning("Не удалось переключить режим позиций: %s (используем %s)", e, pos_mode)

    logger.info("Режим позиций Bybit: %s", pos_mode)
    logger.info("Старт: exchange=%s | market=%s | mode=%s | confirm=%s | RSI=%s EMA=%s MACD=%s",
                Settings.EXCHANGE, Settings.MARKET_TYPE, Settings.RELAX_MODE, Settings.CONFIRM_MODE,
                Settings.ENABLE_RSI, Settings.ENABLE_EMA, Settings.ENABLE_MACD)

    while True:
        try:
            cycle_once(exchange, logger, data_dir, bybit, pos_mode)
        except Exception as e:
            logger.exception("Критическая ошибка цикла: %s", e)
        finally:
            sleep_until_next_cycle(Settings.ITER_SECONDS)


if __name__ == "__main__":
    main()
