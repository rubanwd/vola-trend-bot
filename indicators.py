import numpy as np
import pandas as pd

def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()

def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    up = np.where(delta>0, delta, 0.0)
    dn = np.where(delta<0, -delta, 0.0)
    roll_up = pd.Series(up, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    roll_dn = pd.Series(dn, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    rs = roll_up / (roll_dn + 1e-12)
    return 100 - (100 / (1 + rs))

def macd(close: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    line = ema_fast - ema_slow
    signal_line = line.ewm(span=signal, adjust=False).mean()
    hist = line - signal_line
    return line, signal_line, hist
