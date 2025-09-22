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
    logger.setLevel(level)
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    sh = logging.StreamHandler(sys.stdout); sh.setFormatter(fmt); logger.addHandler(sh)
    return logger

def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def write_jsonl(path, obj):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

def sleep_until_next_cycle(seconds):
    # мягкое выравнивание цикла
    time.sleep(seconds)
