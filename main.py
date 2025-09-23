import math
import pandas as pd
from pathlib import Path
from typing import Dict, List

from settings import Settings
from utils import ensure_dirs, setup_logger, write_jsonl, sleep_until_next_cycle, now_iso
from bybit_data import build_exchange, fetch_top_by_volatility_24h
from indicators import ema, rsi, macd
from reporter import build_report_txt, build_signals_txt, write_file
from telegram_utils import send_document, send_text, TelegramError
from patterns import BULL_PATTERNS, BEAR_PATTERNS


def fetch_ohlcv_df(exchange, symbol: str, timeframe: str, limit: int = 300) -> pd.DataFrame:
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=min(max(limit, 50), 1000))
    df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms")
    return df


def evaluate_indicators(close: pd.Series, direction: str) -> Dict[str, bool]:
    """
    Возвращает словарь {"EMA": bool, "RSI": bool, "MACD": bool}
    (только для включённых индикаторов).
    """
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
        if Settings.RELAX_MODE in ("relaxed", "debug"):
            overbought = Settings.RSI_RELAXED_OVERBOUGHT
            oversold = Settings.RSI_RELAXED_OVERSOLD
        else:
            overbought = Settings.RSI_OVERBOUGHT
            oversold = Settings.RSI_OVERSOLD
        ok = (rv <= oversold) if direction == "BULL" else (rv >= overbought)
        checks["RSI"] = bool(ok)

    if Settings.ENABLE_MACD:
        _, _, hist = macd(close, Settings.MACD_FAST, Settings.MACD_SLOW, Settings.MACD_SIGNAL)
        if len(hist) >= 2:
            h1, h2 = float(hist.iloc[-2]), float(hist.iloc[-1])
            if Settings.RELAX_MODE in ("relaxed", "debug"):
                ok = (h2 > h1) if direction == "BULL" else (h2 < h1)   # тренд гистограммы
            else:
                ok = (h2 >= 0) if direction == "BULL" else (h2 <= 0)   # знак гистограммы
            checks["MACD"] = bool(ok)
        else:
            checks["MACD"] = False

    return checks


def indicators_pass(checks: Dict[str, bool]) -> bool:
    """
    CONFIRM_MODE:
      - auto: debug -> any, normal/relaxed -> all
      - all: все True
      - any: любой True
      - two_of_three: минимум 2 True среди включённых (если включено <2, требуем все True)
    """
    if not checks:
        return True  # индикаторы выключены — пропускаем для отладки

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
        if enabled_cnt >= 2:
            return true_cnt >= 2
        else:
            return all(vals)

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


def process_symbol(exchange, symbol: str) -> List[Dict]:
    df = fetch_ohlcv_df(exchange, symbol, Settings.WORK_TF, limit=300)
    if len(df) < 50:
        return []
    close = df["close"]

    out = []

    # BULL
    pats_bull = find_patterns(df.tail(5), "BULL")
    if pats_bull:
        checks = evaluate_indicators(close, "BULL")
        if indicators_pass(checks):
            out.append({
                "symbol": symbol,
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
            out.append({
                "symbol": symbol,
                "direction": "BEAR",
                "rsi": float(rsi(close, Settings.RSI_LEN).iloc[-1]),
                "patterns": pats_bear,
                "checks": checks,
            })

    return out


def cycle_once(exchange, logger, data_dir: Path):
    logger.info("=== Новый цикл ===")
    universe_rows = fetch_top_by_volatility_24h(exchange)
    universe_symbols = [r["symbol"] for r in universe_rows]
    logger.info("Universe (top %d by 24h vol): %s",
                len(universe_rows),
                ", ".join(universe_symbols[:10]) + (" ..." if len(universe_symbols) > 10 else ""))

    signals: List[Dict] = []
    for sym in universe_symbols:
        try:
            signals.extend(process_symbol(exchange, sym))
        except Exception as e:
            logger.warning("Ошибка по %s: %s", sym, e)

    # Репорт universe
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

    # Сигналы
    sig_txt = build_signals_txt(Settings.WORK_TF, signals)
    sig_path = data_dir / "signals" / f"signals_{Settings.WORK_TF}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.txt"
    write_file(sig_path, sig_txt)
    logger.info("Signals saved: %s", sig_path)

    # Логи + телега
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


def main():
    data_dir = ensure_dirs(Settings.DATA_DIR)
    logger = setup_logger("vola-trend-bot")
    exchange = build_exchange()
    logger.info("Биржа подключена: %s | market=%s | mode=%s | confirm=%s | RSI=%s EMA=%s MACD=%s",
                Settings.EXCHANGE, Settings.MARKET_TYPE, Settings.RELAX_MODE, Settings.CONFIRM_MODE,
                Settings.ENABLE_RSI, Settings.ENABLE_EMA, Settings.ENABLE_MACD)
    while True:
        try:
            cycle_once(exchange, logger, data_dir)
        except Exception as e:
            logger.exception("Критическая ошибка цикла: %s", e)
        finally:
            sleep_until_next_cycle(Settings.ITER_SECONDS)


if __name__ == "__main__":
    main()
