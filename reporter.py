from pathlib import Path
from typing import List, Dict
from utils import now_iso

def build_report_txt(cycle_info: Dict, bull_list: List[Dict], bear_list: List[Dict]) -> str:
    lines = []
    lines.append(f"VOLATILITY/TREND/RSI SCAN — {now_iso()}")
    lines.append(f"TF(work)={cycle_info['work_tf']} | VOL_TF={cycle_info['vol_tf']} | Trend TFs={cycle_info['trend_tfs']}")
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
