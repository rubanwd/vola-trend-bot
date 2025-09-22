import math
import pandas as pd
from pathlib import Path
from typing import Dict, List

from settings import Settings
from utils import ensure_dirs, setup_logger, write_jsonl, sleep_until_next_cycle, now_iso
from bybit_data import build_exchange, list_symbols_usdt, fetch_ohlcv_df
from indicators import atr, rsi
from trend import classify_trend, combine_trends
from patterns import BULL_PATTERNS, BEAR_PATTERNS
from reporter import build_report_txt, build_signals_txt, write_file
from telegram_utils import send_document, send_text, TelegramError


def _pct(a, b):
    if b == 0 or math.isnan(b) or math.isnan(a):
        return 0.0
    return (a - b) / b * 100.0


def is_anomalous(exchange, symbol: str) -> Dict:
    """
    Проверка на аномальные пампы/дампы.
    Считаем % изменений за 24ч и 7д (по 1d свечам).
    """
    from bybit_data import fetch_ohlcv_df
    res = {"anomalous": False, "change_24h": None, "change_7d": None}
    try:
        df1d = fetch_ohlcv_df(exchange, symbol, "1d", limit=10)
        if len(df1d) < 8:
            return res
        last = df1d["close"].iloc[-1]
        prev = df1d["close"].iloc[-2]
        wago = df1d["close"].iloc[-8]
        c24 = _pct(last, prev)
        c7d = _pct(last, wago)
        res["change_24h"] = c24
        res["change_7d"] = c7d
        if Settings.ANOMALY_FILTER_ENABLED:
            if (abs(c24) >= Settings.MAX_24H_ABS_CHANGE_PCT) or (abs(c7d) >= Settings.MAX_7D_ABS_CHANGE_PCT):
                res["anomalous"] = True
        return res
    except Exception:
        return res


def select_top_by_vol(exchange, symbols: List[str]) -> List[str]:
    rows = []
    for s in symbols:
        try:
            df = fetch_ohlcv_df(exchange, s, Settings.VOL_TF, limit=Settings.ATR_LEN * 3)
            a = atr(df, Settings.ATR_LEN).iloc[-1]
            close = df["close"].iloc[-1]
            atr_pct = float(a / close * 100)
            rows.append((s, atr_pct))
        except Exception:
            continue
    rows.sort(key=lambda x: x[1], reverse=True)
    return [s for s, _ in rows[:Settings.TOP_N_BY_VOL]]


def compute_trend(exchange, symbol: str) -> str:
    df1 = fetch_ohlcv_df(exchange, symbol, Settings.TREND_TF1, limit=250)
    df2 = fetch_ohlcv_df(exchange, symbol, Settings.TREND_TF2, limit=250)
    t1 = classify_trend(df1)
    t2 = classify_trend(df2)
    return combine_trends(t1, t2)


def rsi_on_work_tf(exchange, symbol: str) -> (float, pd.DataFrame):
    d = fetch_ohlcv_df(exchange, symbol, Settings.WORK_TF, limit=max(200, Settings.RSI_LEN * 4))
    return float(rsi(d["close"], Settings.RSI_LEN).iloc[-1]), d


def find_patterns(df: pd.DataFrame, trend: str) -> List[str]:
    if len(df) < 5:
        return []
    pats = []
    if trend == "BULL":
        for name, fn in BULL_PATTERNS.items():
            try:
                if fn(df, trend_hint="BULL"):
                    pats.append(name)
            except Exception:
                continue
    elif trend == "BEAR":
        for name, fn in BEAR_PATTERNS.items():
            try:
                if fn(df, trend_hint="BEAR"):
                    pats.append(name)
            except Exception:
                continue
    return pats

def cycle_once(exchange, logger, data_dir: Path):
    logger.info("=== Новый цикл ===")
    all_symbols = list_symbols_usdt(exchange)
    logger.info("Всего активов к %s: %d", Settings.QUOTE, len(all_symbols))

    universe = select_top_by_vol(exchange, all_symbols)
    logger.info("Выбрано TOP %d по ATR%% (%s): %s",
                Settings.TOP_N_BY_VOL, Settings.VOL_TF,
                ", ".join(universe[:10]) + (" ..." if len(universe) > 10 else ""))

    # фильтр аномалий
    filtered_universe, anomal_stats = [], {}
    for sym in universe:
        st = is_anomalous(exchange, sym)
        anomal_stats[sym] = st
        if st["anomalous"]:
            continue
        filtered_universe.append(sym)

    logger.info("После фильтра аномалий: %d из %d (отсеяно %d)",
                len(filtered_universe), len(universe), len(universe) - len(filtered_universe))

    bull, bear = [], []
    for sym in filtered_universe:
        try:
            trend = compute_trend(exchange, sym)
            if trend == "NEUTRAL":
                continue
            rsi_val, df_work = rsi_on_work_tf(exchange, sym)

            if trend == "BULL" and rsi_val >= Settings.RSI_OVERBOUGHT:
                bull.append({"symbol": sym, "trend": trend, "rsi": rsi_val, "df": df_work})
            elif trend == "BEAR" and rsi_val <= Settings.RSI_OVERSOLD:
                bear.append({"symbol": sym, "trend": trend, "rsi": rsi_val, "df": df_work})
        except Exception as e:
            logger.warning("Ошибка по %s: %s", sym, e)

    bull.sort(key=lambda x: x["rsi"], reverse=True)
    bear.sort(key=lambda x: x["rsi"])

    report_txt = build_report_txt(
        cycle_info={
            "work_tf": Settings.WORK_TF,
            "vol_tf": Settings.VOL_TF,
            "trend_tfs": f"{Settings.TREND_TF1}+{Settings.TREND_TF2}",
            "top_n": Settings.TOP_N_BY_VOL,
            "params": {
                "WORK_TF": Settings.WORK_TF,
                "VOL_TF": Settings.VOL_TF,
                "TREND_TF1": Settings.TREND_TF1,
                "TREND_TF2": Settings.TREND_TF2,
                "TOP_N_BY_VOL": Settings.TOP_N_BY_VOL,
                "RSI_LEN": Settings.RSI_LEN,
                "RSI_OVERBOUGHT": Settings.RSI_OVERBOUGHT,
                "RSI_OVERSOLD": Settings.RSI_OVERSOLD,
                "ATR_LEN": Settings.ATR_LEN,
                "ANOMALY_FILTER_ENABLED": Settings.ANOMALY_FILTER_ENABLED,
                "MAX_24H_ABS_CHANGE_PCT": Settings.MAX_24H_ABS_CHANGE_PCT,
                "MAX_7D_ABS_CHANGE_PCT": Settings.MAX_7D_ABS_CHANGE_PCT,
            }
        },
        bull_list=bull,
        bear_list=bear
    )
    rep_path = data_dir / "reports" / f"report_{Settings.WORK_TF}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.txt"
    write_file(rep_path, report_txt)
    logger.info("Report saved: %s", rep_path)

    write_jsonl(data_dir / "logs" / "iterations.jsonl", {
        "ts": now_iso(),
        "work_tf": Settings.WORK_TF,
        "vol_tf": Settings.VOL_TF,
        "trend_tfs": [Settings.TREND_TF1, Settings.TREND_TF2],
        "universe": universe,
        "bull": [{"symbol": x["symbol"], "rsi": round(x["rsi"], 2)} for x in bull],
        "bear": [{"symbol": x["symbol"], "rsi": round(x["rsi"], 2)} for x in bear],
    })

    if Settings.TG_REPORT_BOT_TOKEN and Settings.TG_REPORT_CHAT_ID:
        try:
            send_text(Settings.TG_REPORT_BOT_TOKEN, Settings.TG_REPORT_CHAT_ID, "Report incoming…")
            send_document(Settings.TG_REPORT_BOT_TOKEN, Settings.TG_REPORT_CHAT_ID, rep_path,
                          caption="Volatility/Trend/RSI report")
        except TelegramError as te:
            logger.error("Telegram REPORT error: %s", te)

    signals = []
    for row in bull:
        pats = find_patterns(row["df"].tail(5), "BULL")
        if pats:
            signals.append({"symbol": row["symbol"], "trend": "BULL", "rsi": row["rsi"], "patterns": pats})
    for row in bear:
        pats = find_patterns(row["df"].tail(5), "BEAR")
        if pats:
            signals.append({"symbol": row["symbol"], "trend": "BEAR", "rsi": row["rsi"], "patterns": pats})

    if signals:
        sig_txt = build_signals_txt(Settings.WORK_TF, signals)
        sig_path = data_dir / "signals" / f"signals_{Settings.WORK_TF}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.txt"
        write_file(sig_path, sig_txt)
        logger.info("Signals saved: %s", sig_path)

        write_jsonl(data_dir / "logs" / "iterations.jsonl", {
            "ts": now_iso(),
            "signals": signals
        })

        if Settings.TG_SIGNAL_BOT_TOKEN and Settings.TG_SIGNAL_CHAT_ID:
            try:
                send_text(Settings.TG_SIGNAL_BOT_TOKEN, Settings.TG_SIGNAL_CHAT_ID, "Signals incoming…")
                send_document(Settings.TG_SIGNAL_BOT_TOKEN, Settings.TG_SIGNAL_CHAT_ID, sig_path,
                              caption="Confirmed candle patterns")
            except TelegramError as te:
                logger.error("Telegram SIGNAL error: %s", te)
    else:
        logger.info("Сигналов по паттернам нет в этом цикле.")


def main():
    data_dir = ensure_dirs(Settings.DATA_DIR)
    logger = setup_logger("vola-trend-bot")
    exchange = build_exchange()
    logger.info("Биржа подключена: %s | market=%s", Settings.EXCHANGE, Settings.MARKET_TYPE)
    while True:
        try:
            cycle_once(exchange, logger, data_dir)
        except Exception as e:
            logger.exception("Критическая ошибка цикла: %s", e)
        finally:
            sleep_until_next_cycle(Settings.ITER_SECONDS)


if __name__ == "__main__":
    main()
