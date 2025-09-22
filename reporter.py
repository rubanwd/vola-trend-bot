from pathlib import Path
from typing import List, Dict
from utils import now_iso

def _kv(k, v, kpad=18):
    return f"{k:<{kpad}} : {v}"

def build_params_table(params: Dict) -> str:
    lines = []
    lines.append("PARAMS")
    lines.append("-" * 40)
    ordered = [
        ("WORK_TF", params.get("WORK_TF")),
        ("VOL_TF", params.get("VOL_TF")),
        ("TREND_TF1", params.get("TREND_TF1")),
        ("TREND_TF2", params.get("TREND_TF2")),
        ("TOP_N_BY_VOL", params.get("TOP_N_BY_VOL")),
        ("RSI_LEN", params.get("RSI_LEN")),
        ("RSI_OVERBOUGHT", params.get("RSI_OVERBOUGHT")),
        ("RSI_OVERSOLD", params.get("RSI_OVERSOLD")),
        ("ATR_LEN", params.get("ATR_LEN")),
        ("ANOMALY_FILTER", params.get("ANOMALY_FILTER_ENABLED")),
        ("MAX_24H_ABS_%", params.get("MAX_24H_ABS_CHANGE_PCT")),
        ("MAX_7D_ABS_%", params.get("MAX_7D_ABS_CHANGE_PCT")),
    ]
    for k, v in ordered:
        lines.append(_kv(k, v))
    return "\n".join(lines)

def build_report_txt(cycle_info: Dict, bull_list: List[Dict], bear_list: List[Dict]) -> str:
    lines = []
    lines.append(f"VOLATILITY/TREND/RSI SCAN — {now_iso()}")
    lines.append(build_params_table(cycle_info["params"]))
    lines.append("")
    lines.append(f"Universe: top {cycle_info['top_n']} by ATR% on {cycle_info['vol_tf']}")
    lines.append("")

    def section(title, rows):
        out = [f"=== {title} ({len(rows)}) ==="]
        for i, r in enumerate(rows, 1):
            out.append(f"{i:02d}. {r['symbol']:>12s} | RSI={r['rsi']:.1f} | trend={r['trend']}")
        return "\n".join(out)

    lines.append(section("BULL (RSI>=overbought)", bull_list))
    lines.append("")
    lines.append(section("BEAR (RSI<=oversold)", bear_list))
    return "\n".join(lines)

def build_signals_txt(work_tf: str, items: List[Dict]) -> str:
    lines = [f"CONFIRMED CANDLE PATTERNS — TF={work_tf} — {now_iso()}"]
    for i, it in enumerate(items, 1):
        pats = ", ".join(it["patterns"])
        lines.append(f"{i:02d}. {it['symbol']:>12s} | {it['trend']} | RSI={it['rsi']:.1f} | {pats}")
    if len(items)==0:
        lines.append("(no signals)")
    return "\n".join(lines)

def write_file(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
