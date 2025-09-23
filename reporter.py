from pathlib import Path
from typing import List, Dict
from utils import now_iso

def _kv(k, v, kpad=22):
    return f"{k:<{kpad}} : {v}"

def build_params_table(params: Dict) -> str:
    lines = ["PARAMS", "-" * 48]
    ordered = [
        ("WORK_TF", params.get("WORK_TF")),
        ("EMA_FAST", params.get("EMA_FAST")),
        ("EMA_SLOW", params.get("EMA_SLOW")),
        ("RSI_LEN", params.get("RSI_LEN")),
        ("RSI_OVERBOUGHT", params.get("RSI_OVERBOUGHT")),
        ("RSI_OVERSOLD", params.get("RSI_OVERSOLD")),
        ("RSI_RELAXED_OVERBOUGHT", params.get("RSI_RELAXED_OVERBOUGHT")),
        ("RSI_RELAXED_OVERSOLD", params.get("RSI_RELAXED_OVERSOLD")),
        ("MACD_FAST", params.get("MACD_FAST")),
        ("MACD_SLOW", params.get("MACD_SLOW")),
        ("MACD_SIGNAL", params.get("MACD_SIGNAL")),
        ("TOP_N_BY_VOL", params.get("TOP_N_BY_VOL")),
        ("RELAX_MODE", params.get("RELAX_MODE")),
        ("CONFIRM_MODE", params.get("CONFIRM_MODE")),
        ("ENABLE_RSI", params.get("ENABLE_RSI")),
        ("ENABLE_EMA", params.get("ENABLE_EMA")),
        ("ENABLE_MACD", params.get("ENABLE_MACD")),
    ]
    for k, v in ordered:
        lines.append(_kv(k, v))
    return "\n".join(lines)

def build_report_txt(cycle_info: Dict, universe: List[Dict]) -> str:
    lines = []
    lines.append(f"PATTERN+INDICATORS SCAN — {now_iso()}")
    lines.append(build_params_table(cycle_info["params"]))
    lines.append("")
    lines.append(f"Universe (Top {cycle_info['top_n']} by 24h volatility via tickers):")
    for i, row in enumerate(universe, 1):
        lines.append(f"{i:02d}. {row['symbol']:>12s} | vol24h%={row['vol24h_pct']:.1f}")
    return "\n".join(lines)

def build_signals_txt(work_tf: str, items: List[Dict]) -> str:
    lines = [f"CONFIRMED CANDLE PATTERNS — TF={work_tf} — {now_iso()}"]
    for i, it in enumerate(items, 1):
        pats = ", ".join(it["patterns"])
        checks = it.get("checks", {})
        flags = ", ".join([f"{k}={str(v)}" for k, v in checks.items()]) if checks else "no-indicators"
        lines.append(f"{i:02d}. {it['symbol']:>12s} | {it['direction']} | RSI={it['rsi']:.1f} | {flags} | {pats}")
    if len(items)==0:
        lines.append("(no signals)")
    return "\n".join(lines)

def write_file(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
