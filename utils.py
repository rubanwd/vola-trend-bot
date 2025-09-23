import os, sys, time, json, logging
from pathlib import Path
from datetime import datetime, timezone

def ensure_dirs(base="./data"):
    base = Path(base)
    (base / "logs").mkdir(parents=True, exist_ok=True)
    (base / "reports").mkdir(parents=True, exist_ok=True)
    (base / "signals").mkdir(parents=True, exist_ok=True)
    return base

def setup_logger(name="bot", level=logging.INFO):
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.setLevel(level)
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    sh = logging.StreamHandler(sys.stdout); sh.setFormatter(fmt); logger.addHandler(sh)
    return logger

def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

# --- JSON helpers ---
def _json_default(o):
    try:
        import numpy as np
        if isinstance(o, (np.bool_, np.bool8,
                          np.int_,  np.int8,  np.int16, np.int32, np.int64,
                          np.uint8, np.uint16, np.uint32, np.uint64,
                          np.float_, np.float16, np.float32, np.float64)):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
    except Exception:
        pass
    if hasattr(o, "isoformat"):
        try:
            return o.isoformat()
        except Exception:
            pass
    if isinstance(o, set):
        return list(o)
    if isinstance(o, Path):
        return str(o)
    return str(o)

def write_jsonl(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, default=_json_default) + "\n")

def sleep_until_next_cycle(seconds):
    time.sleep(seconds)
