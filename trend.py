from dataclasses import dataclass
import pandas as pd
from indicators import ema, slope

@dataclass
class TrendConfig:
    ema_fast:int=50
    ema_slow:int=200
    slope_len:int=8

def classify_trend(df: pd.DataFrame, cfg: TrendConfig = TrendConfig()) -> str:
    """
    Критерии (действенная и устойчивая логика):
    - BULL: close > EMA200, EMA50 > EMA200, slope(EMA50) > 0
    - BEAR: close < EMA200, EMA50 < EMA200, slope(EMA50) < 0
    - иначе NEUTRAL
    """
    c = df["close"]
    e50 = ema(c, cfg.ema_fast)
    e200= ema(c, cfg.ema_slow)
    s = slope(e50, cfg.slope_len)
    last = len(c)-1
    if c.iat[last] > e200.iat[last] and e50.iat[last] > e200.iat[last] and s > 0:
        return "BULL"
    if c.iat[last] < e200.iat[last] and e50.iat[last] < e200.iat[last] and s < 0:
        return "BEAR"
    return "NEUTRAL"

def combine_trends(t1: str, t2: str) -> str:
    if t1 == t2 and t1 in ("BULL","BEAR"): return t1
    return "NEUTRAL"
