import numpy as np
import pandas as pd

def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()

def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    up = np.where(delta > 0, delta, 0.0)
    dn = np.where(delta < 0, -delta, 0.0)
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

def slope(series: pd.Series, length: int = 8) -> float:
    if len(series) < max(3, length):
        return 0.0
    y = series.iloc[-length:].to_numpy(dtype=float)
    x = np.arange(length, dtype=float)
    x -= x.mean()
    y -= y.mean()
    denom = (x ** 2).sum()
    if denom == 0:
        return 0.0
    return float((x * y).sum() / denom)

def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """
    df: columns ['open','high','low','close']
    ATR (Wilder) для SL/TP.
    """
    h, l, c = df["high"], df["low"], df["close"]
    prev_close = c.shift(1)
    tr = pd.concat([
        (h - l).abs(),
        (h - prev_close).abs(),
        (l - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, adjust=False).mean()
