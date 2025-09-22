import os
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
from telegram_utils import send_document

def select_top_by_vol(exchange, symbols: List[str]) -> List[str]:
    # считаем ATR% на VOL_TF и выбираем TOP_N
    rows = []
    for s in symbols:
        try:
            df = fetch_ohlcv_df(exchange, s, Settings.VOL_TF, limit=Settings.ATR_LEN*3)
            a = atr(df, Settings.ATR_LEN).iloc[-1]
            close = df["close"].iloc[-1]
            atr_pct = float(a / close * 100)
            rows.append((s, atr_pct))
        except Exception:
            continue
    rows.sort(key=lambda x: x[1], reverse=True)
    return [s for s,_ in rows[:Settings.TOP_N_BY_VOL]]

def compute_trend(exchange, symbol: str) -> str:
    df1 = fetch_ohlcv_df(exchange, symbol, Settings.TREND_TF1, limit=250)
    df2 = fetch_ohlcv_df(exchange, symbol, Settings.TREND_TF2, limit=250)
    t1 = classify_trend(df1)
    t2 = classify_trend(df2)
    return combine_trends(t1, t2)

def rsi_on_work_tf(exchange, symbol: str) -> float:
    d = fetch_ohlcv_df(exchange, symbol, Settings.WORK_TF, limit=max(200, Settings.RSI_LEN*4))
    return float(rsi(d["close"], Settings.RSI_LEN).iloc[-1]), d

def find_patterns(df: pd.DataFrame, trend: str) -> List[str]:
    if len(df) < 5: return []
    pats = []
    if trend == "BULL":
        for name, fn in BULL_PATTERNS.items():
            try:
                if (name in ("Morning Star","Evening Star","Three White Soldiers","Three Black Crows",
                             "Bullish Three Line Strike","Bearish Three Line Strike",
                             "Three Inside Up","Three Inside Down","Three Outside Up","Three Outside Down")):
                    if len(df) < 5: pass
                if fn(df):
                    pats.append(name)
            except Exception:
                continue
    elif trend == "BEAR":
        for name, fn in BEAR_PATTERNS.items():
            try:
                if fn(df):
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
                Settings.TOP_N_BY_VOL, Settings.VOL_TF, ", ".join(universe[:10]) + (" ..." if len(universe)>10 else ""))

    bull, bear = [], []
    for sym in universe:
        try:
            trend = compute_trend(exchange, sym)
            if trend == "NEUTRAL": continue
            rsi_val, df_work = rsi_on_work_tf(exchange, sym)

            if trend == "BULL" and rsi_val >= Settings.RSI_OVERBOUGHT:
                bull.append({"symbol": sym, "trend": trend, "rsi": rsi_val, "df": df_work})
            elif trend == "BEAR" and rsi_val <= Settings.RSI_OVERSOLD:
                bear.append({"symbol": sym, "trend": trend, "rsi": rsi_val, "df": df_work})
        except Exception as e:
            logger.warning("Ошибка по %s: %s", sym, e)

    # соритруем по RSI как просил раньше: BULL сверху наибольшие, BEAR сверху наименьшие
    bull.sort(key=lambda x: x["rsi"], reverse=True)
    bear.sort(key=lambda x: x["rsi"])

    # отчётный .txt
    report_txt = build_report_txt(
        cycle_info={
            "work_tf": Settings.WORK_TF,
            "vol_tf": Settings.VOL_TF,
            "trend_tfs": f"{Settings.TREND_TF1}+{Settings.TREND_TF2}",
            "top_n": Settings.TOP_N_BY_VOL
        },
        bull_list=bull,
        bear_list=bear
    )
    rep_path = data_dir / "reports" / f"report_{Settings.WORK_TF}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.txt"
    write_file(rep_path, report_txt)
    logger.info("Report saved: %s", rep_path)

    # лог jsonl
    write_jsonl(data_dir / "logs" / "iterations.jsonl", {
        "ts": now_iso(),
        "work_tf": Settings.WORK_TF,
        "vol_tf": Settings.VOL_TF,
        "trend_tfs": [Settings.TREND_TF1, Settings.TREND_TF2],
        "universe": universe,
        "bull": [{"symbol":x["symbol"],"rsi":round(x["rsi"],2)} for x in bull],
        "bear": [{"symbol":x["symbol"],"rsi":round(x["rsi"],2)} for x in bear],
    })

    # отправка отчёта в Telegram
    if Settings.TG_REPORT_BOT_TOKEN and Settings.TG_REPORT_CHAT_ID:
        send_document(Settings.TG_REPORT_BOT_TOKEN, Settings.TG_REPORT_CHAT_ID, rep_path, caption="Volatility/Trend/RSI report")

    # проверка паттернов и формирование сигналов
    signals = []
    # только последние свечи текущего ТФ — проверяем соответствующие паттерны
    for row in bull:
        pats = find_patterns(row["df"].tail(5), "BULL")
        if pats:
            signals.append({"symbol": row["symbol"], "trend":"BULL", "rsi": row["rsi"], "patterns": pats})
    for row in bear:
        pats = find_patterns(row["df"].tail(5), "BEAR")
        if pats:
            signals.append({"symbol": row["symbol"], "trend":"BEAR", "rsi": row["rsi"], "patterns": pats})

    if signals:
        sig_txt = build_signals_txt(Settings.WORK_TF, signals)
        sig_path = data_dir / "signals" / f"signals_{Settings.WORK_TF}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.txt"
        write_file(sig_path, sig_txt)
        logger.info("Signals saved: %s", sig_path)

        # лог jsonl
        write_jsonl(data_dir / "logs" / "iterations.jsonl", {
            "ts": now_iso(),
            "signals": signals
        })

        # отправка сигналов
        if Settings.TG_SIGNAL_BOT_TOKEN and Settings.TG_SIGNAL_CHAT_ID:
            send_document(Settings.TG_SIGNAL_BOT_TOKEN, Settings.TG_SIGNAL_CHAT_ID, sig_path, caption="Confirmed candle patterns")
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
