# main.py
import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

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
            ok = (h2 > h1) if Settings.RELAX_MODE in ("relaxed", "debug") else (h2 >= 0)
            if direction == "BEAR":
                ok = (h2 < h1) if Settings.RELAX_MODE in ("relaxed", "debug") else (h2 <= 0)
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
# Trading helpers (state, Bybit ops)
# =========================
def _state_file(data_dir: Path) -> Path:
    return data_dir / "state" / "last_signals.json"


def load_last_signals(data_dir: Path) -> List[Dict]:
    p = _state_file(data_dir)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def save_last_signals(data_dir: Path, signals: List[Dict]):
    p = _state_file(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(signals, ensure_ascii=False), encoding="utf-8")


def _signal_key(sig: Dict) -> str:
    return f"{sig['symbol']}|{sig['direction']}"


def count_open_positions(bybit: BybitAPI) -> int:
    try:
        pos = bybit.get_open_positions()
        return sum(1 for p in pos if abs(float(p.get("size") or 0)) > 0)
    except Exception:
        return 0


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


def compute_atr_levels(df: pd.DataFrame, atr_len: int, sl_k: float, tp_k: float, side: str, entry_price: float):
    a = float(atr(df, atr_len).iloc[-1])
    if side == "Buy":
        sl = entry_price - sl_k * a
        tp = entry_price + tp_k * a
    else:
        sl = entry_price + sl_k * a
        tp = entry_price - tp_k * a
    return a, sl, tp


def usd_to_qty(bybit: BybitAPI, bybit_symbol: str, usd: float) -> float:
    last = bybit.get_last_price(bybit_symbol)
    raw_qty = usd / last
    return bybit.round_qty(bybit_symbol, raw_qty)


def open_trade_if_ok(
    bybit: BybitAPI,
    logger,
    data_dir: Path,
    new_sigs: List[Dict],
    df_cache: Dict[str, pd.DataFrame],
    market_id_map: Dict[str, str],
):
    """
    new_sigs: только новые сигналы этой итерации (symbol, direction, rsi, patterns, checks)
    df_cache: кэш df по WORK_TF (для ATR)
    market_id_map: ccxt symbol -> bybit v5 symbol (e.g., 'BTC/USDT:USDT' -> 'BTCUSDT')
    """
    if not new_sigs:
        return

    current_open = count_open_positions(bybit)
    slots_left = max(Settings.MAX_OPEN_POSITIONS - current_open, 0)
    if slots_left <= 0:
        logger.info("Лимит позиций достигнут (%d). Входы пропущены.", Settings.MAX_OPEN_POSITIONS)
        return

    for sig in new_sigs[:slots_left]:
        ccxt_symbol = sig["symbol"]
        bybit_symbol = market_id_map.get(ccxt_symbol) or ccxt_symbol.replace("/", "").replace(":USDT", "")
        direction = sig["direction"]
        side = "Buy" if direction == "BULL" else "Sell"

        # анти-реэнтри по bybit_symbol
        age_h = last_closed_age_hours(bybit, bybit_symbol)
        if age_h < Settings.REENTRY_COOLDOWN_HOURS:
            logger.info("Cooldown по %s: %.1fч < %dч — пропускаем.", bybit_symbol, age_h, Settings.REENTRY_COOLDOWN_HOURS)
            continue

        # плечо
        try:
            bybit.set_leverage(bybit_symbol, Settings.LEVERAGE)
        except Exception as e:
            logger.warning("set_leverage %s: %s (продолжаем)", bybit_symbol, e)

        # qty из USD
        try:
            qty = usd_to_qty(bybit, bybit_symbol, Settings.POSITION_USD)
        except Exception as e:
            logger.error("Не удалось посчитать qty для %s: %s", bybit_symbol, e)
            continue

        # ATR уровни
        df = df_cache.get(ccxt_symbol)
        if df is None or len(df) < 20:
            logger.info("Нет df в кэше для %s — пропуск", ccxt_symbol)
            continue

        try:
            entry_ref = bybit.get_last_price(bybit_symbol)
            atr_val, sl_price, tp_price = compute_atr_levels(
                df, Settings.ATR_LEN, Settings.SL_ATR_MULT, Settings.TP_ATR_MULT, side, entry_ref
            )
            sl_price = bybit.round_price(bybit_symbol, sl_price)
            tp_price = bybit.round_price(bybit_symbol, tp_price)
        except Exception as e:
            logger.error("ATR/levels error %s: %s", bybit_symbol, e)
            continue

        # Маркет-вход
        try:
            bybit.place_market_order(bybit_symbol, side, qty)
            logger.info("Открыта позиция: %s %s qty=%s", bybit_symbol, side, qty)
        except Exception as e:
            logger.error("Не удалось открыть позицию %s %s: %s", bybit_symbol, side, e)
            continue

        # TP/SL на позицию
        try:
            bybit.set_tp_sl(bybit_symbol, take_profit=tp_price, stop_loss=sl_price)
            logger.info("TP/SL проставлены: TP=%s SL=%s", tp_price, sl_price)
        except Exception as e:
            logger.warning("Не удалось проставить TP/SL для %s: %s", bybit_symbol, e)

        # Телега (уведомление о сделке)
        if Settings.TG_TRADE_BOT_TOKEN and Settings.TG_TRADE_CHAT_ID:
            try:
                pats = ", ".join(sig.get("patterns", [])) or "-"
                ch = sig.get("checks", {})
                flags = ", ".join([f"{k}={str(v)}" for k, v in ch.items()]) if ch else "-"
                text = (
                    "✅ ОТКРЫТА СДЕЛКА\n"
                    f"Пара: {ccxt_symbol} (Bybit: {bybit_symbol})\n"
                    f"Направление: {'LONG' if side=='Buy' else 'SHORT'}\n"
                    f"Объём: ${Settings.POSITION_USD} (~ qty {qty}) | Плечо x{Settings.LEVERAGE}\n"
                    f"Entry≈: {entry_ref}\n"
                    f"SL: {sl_price} | TP: {tp_price}\n"
                    f"ATR({Settings.ATR_LEN}): {atr_val:.4f}\n"
                    f"TF: {Settings.WORK_TF}\n"
                    f"Паттерны: {pats}\n"
                    f"Индикаторы: {flags}\n"
                    f"RSI: {sig.get('rsi'):.1f}\n"
                    f"Условие входа: новая пара в списке сигналов; cooldown {Settings.REENTRY_COOLDOWN_HOURS}ч"
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
# The main cycle
# =========================
def cycle_once(exchange, logger, data_dir: Path, bybit: BybitAPI):
    logger.info("=== Новый цикл ===")
    universe_rows = fetch_top_by_volatility_24h(exchange)
    universe_symbols = [r["symbol"] for r in universe_rows]
    logger.info("Universe (top %d by 24h vol): %s",
                len(universe_rows),
                ", ".join(universe_symbols[:10]) + (" ..." if len(universe_symbols) > 10 else ""))

    # Построим маппинг ccxt -> bybit (важно для всех торговых вызовов)
    market_id_map: Dict[str, str] = {}
    for sym in universe_symbols:
        try:
            # наиболее корректно: использовать id из описания рынка
            m = exchange.markets.get(sym) or {}
            bybit_symbol = m.get("id") or sym.replace("/", "").replace(":USDT", "")
            market_id_map[sym] = bybit_symbol
        except Exception:
            market_id_map[sym] = sym.replace("/", "").replace(":USDT", "")

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

    # Новые сигналы
    prev = load_last_signals(data_dir)
    prev_keys = {_signal_key(s) for s in prev}
    curr_keys = {_signal_key(s) for s in signals}
    new_keys = curr_keys - prev_keys
    new_sigs = [s for s in signals if _signal_key(s) in new_keys]

    # Торговля
    try:
        open_trade_if_ok(bybit, logger, data_dir, new_sigs, df_cache, market_id_map)
    except Exception as e:
        logger.exception("Trade pipeline error: %s", e)

    # Сохранить текущие сигналы
    save_last_signals(data_dir, signals)

    # Репорты
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
    exchange = build_exchange()  # ccxt для маркет-данных
    bybit = BybitAPI()          # прямой Bybit v5 (demo) для торговли

    try:
        bybit.get_instruments()  # прогрев шагов цены/лота
    except Exception as e:
        logger.warning("Не удалось прогреть инструменты Bybit: %s", e)

    logger.info("Старт: exchange=%s | market=%s | mode=%s | confirm=%s | RSI=%s EMA=%s MACD=%s",
                Settings.EXCHANGE, Settings.MARKET_TYPE, Settings.RELAX_MODE, Settings.CONFIRM_MODE,
                Settings.ENABLE_RSI, Settings.ENABLE_EMA, Settings.ENABLE_MACD)

    while True:
        try:
            cycle_once(exchange, logger, data_dir, bybit)
        except Exception as e:
            logger.exception("Критическая ошибка цикла: %s", e)
        finally:
            sleep_until_next_cycle(Settings.ITER_SECONDS)


if __name__ == "__main__":
    main()
