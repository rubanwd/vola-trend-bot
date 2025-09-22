# patterns.py — точная детекция с контекстом

import pandas as pd
from typing import Optional

# === Параметры детекции (при желании можно вынести в .env) ===
TOL_PCT = 0.001        # 0.1% допуск по High/Low для пинцетов и т.п.
SMALL_BODY_FRAC = 0.4  # «малое тело» = доля от среднего тела последних N
AVG_N = 10             # окно для среднего тела/теней
STRONG_BODY_FRAC = 0.6 # «сильное тело» = >= 60% от среднего тела
STAR_GAP_OK = False    # в крипте гэпы редки — не требуем

# ---------- базовые хелперы ----------
def bull(o, c): return c > o
def bear(o, c): return c < o
def body(o, c): return abs(c - o)
def upper_shadow(h, o, c): return h - max(o, c)
def lower_shadow(l, o, c): return min(o, c) - l

def avg_body(df, n=AVG_N):
    return body(df["open"], df["close"]).rolling(n).mean().iloc[-1]

def recent_upmove(df, n=5):
    cl = df["close"]
    return (cl.iloc[-1] > cl.iloc[-n]) and (cl.diff().tail(n - 1) > 0).sum() >= (n // 2)

def recent_downmove(df, n=5):
    cl = df["close"]
    return (cl.iloc[-1] < cl.iloc[-n]) and (cl.diff().tail(n - 1) < 0).sum() >= (n // 2)

def price_tol(df):
    p = float(df["close"].iloc[-1])
    return max(p * TOL_PCT, 1e-9)

# ---------- 2-свечные ----------
def bullish_engulfing(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 2: return False
    o1, c1 = df["open"].iat[-2], df["close"].iat[-2]
    o2, c2 = df["open"].iat[-1], df["close"].iat[-1]
    ab = avg_body(df)
    cond = bear(o1, c1) and bull(o2, c2) and (o2 <= c1) and (c2 >= o1) \
           and (body(o2, c2) >= STRONG_BODY_FRAC * ab) and (body(o1, c1) >= 0.3 * ab)
    if trend_hint == "BULL":  # бычье поглощение уместно после снижения
        cond = cond and recent_downmove(df, 5)
    return bool(cond)

def bearish_engulfing(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 2: return False
    o1, c1 = df["open"].iat[-2], df["close"].iat[-2]
    o2, c2 = df["open"].iat[-1], df["close"].iat[-1]
    ab = avg_body(df)
    cond = bull(o1, c1) and bear(o2, c2) and (o2 >= c1) and (c2 <= o1) \
           and (body(o2, c2) >= STRONG_BODY_FRAC * ab) and (body(o1, c1) >= 0.3 * ab)
    if trend_hint == "BEAR":
        cond = cond and recent_upmove(df, 5)
    return bool(cond)

def piercing_line(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 2: return False
    o1, c1 = df["open"].iat[-2], df["close"].iat[-2]
    o2, c2 = df["open"].iat[-1], df["close"].iat[-1]
    mid = (o1 + c1) / 2
    cond = bear(o1, c1) and bull(o2, c2) and (c2 > mid) and (o2 <= c1)
    if trend_hint == "BULL":
        cond = cond and recent_downmove(df, 5)
    return bool(cond)

def dark_cloud_cover(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 2: return False
    o1, c1 = df["open"].iat[-2], df["close"].iat[-2]
    o2, c2 = df["open"].iat[-1], df["close"].iat[-1]
    mid = (o1 + c1) / 2
    cond = bull(o1, c1) and bear(o2, c2) and (c2 < mid) and (o2 >= c1)
    if trend_hint == "BEAR":
        cond = cond and recent_upmove(df, 5)
    return bool(cond)

def bullish_harami(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 2: return False
    o1, c1 = df["open"].iat[-2], df["close"].iat[-2]
    o2, c2 = df["open"].iat[-1], df["close"].iat[-1]
    ab = avg_body(df)
    inside = (min(o2, c2) > min(o1, c1)) and (max(o2, c2) < max(o1, c1))
    cond = bear(o1, c1) and inside and (body(o2, c2) <= SMALL_BODY_FRAC * ab)
    if trend_hint == "BULL": cond = cond and recent_downmove(df, 5)
    return bool(cond)

def bearish_harami(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 2: return False
    o1, c1 = df["open"].iat[-2], df["close"].iat[-2]
    o2, c2 = df["open"].iat[-1], df["close"].iat[-1]
    ab = avg_body(df)
    inside = (min(o2, c2) > min(o1, c1)) and (max(o2, c2) < max(o1, c1))
    cond = bull(o1, c1) and inside and (body(o2, c2) <= SMALL_BODY_FRAC * ab)
    if trend_hint == "BEAR": cond = cond and recent_upmove(df, 5)
    return bool(cond)

def tweezer_bottom(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 2: return False
    l1, l2 = df["low"].iat[-2], df["low"].iat[-1]
    o1, c1 = df["open"].iat[-2], df["close"].iat[-2]
    o2, c2 = df["open"].iat[-1], df["close"].iat[-1]
    tol = price_tol(df)
    cond = abs(l1 - l2) <= tol and bear(o1, c1) and bull(o2, c2)
    if trend_hint == "BULL": cond = cond and recent_downmove(df, 5)
    return bool(cond)

def tweezer_top(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 2: return False
    h1, h2 = df["high"].iat[-2], df["high"].iat[-1]
    o1, c1 = df["open"].iat[-2], df["close"].iat[-2]
    o2, c2 = df["open"].iat[-1], df["close"].iat[-1]
    tol = price_tol(df)
    cond = abs(h1 - h2) <= tol and bull(o1, c1) and bear(o2, c2)
    if trend_hint == "BEAR": cond = cond and recent_upmove(df, 5)
    return bool(cond)

def bullish_kicker(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    # сильная смена направления: второе тело > среднего, цвета противоположны
    if len(df) < 2: return False
    o1, c1 = df["open"].iat[-2], df["close"].iat[-2]
    o2, c2 = df["open"].iat[-1], df["close"].iat[-1]
    ab = avg_body(df)
    cond = bear(o1, c1) and bull(o2, c2) and (body(o2, c2) >= STRONG_BODY_FRAC * ab) and (c2 > o1)
    if trend_hint == "BULL": cond = cond and recent_downmove(df, 5)
    return bool(cond)

def bearish_kicker(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 2: return False
    o1, c1 = df["open"].iat[-2], df["close"].iat[-2]
    o2, c2 = df["open"].iat[-1], df["close"].iat[-1]
    ab = avg_body(df)
    cond = bull(o1, c1) and bear(o2, c2) and (body(o2, c2) >= STRONG_BODY_FRAC * ab) and (c2 < o1)
    if trend_hint == "BEAR": cond = cond and recent_upmove(df, 5)
    return bool(cond)

# ---------- 3-свечные и подтверждения ----------
def morning_star(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 3: return False
    o1, c1 = df["open"].iat[-3], df["close"].iat[-3]
    o2, c2 = df["open"].iat[-2], df["close"].iat[-2]
    o3, c3 = df["open"].iat[-1], df["close"].iat[-1]
    ab = avg_body(df)
    cond = bear(o1, c1) and (body(o2, c2) <= SMALL_BODY_FRAC * ab) and bull(o3, c3) and c3 > (o1 + c1) / 2
    if trend_hint == "BULL": cond = cond and recent_downmove(df, 5)
    return bool(cond)

def evening_star(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 3: return False
    o1, c1 = df["open"].iat[-3], df["close"].iat[-3]
    o2, c2 = df["open"].iat[-2], df["close"].iat[-2]
    o3, c3 = df["open"].iat[-1], df["close"].iat[-1]
    ab = avg_body(df)
    cond = bull(o1, c1) and (body(o2, c2) <= SMALL_BODY_FRAC * ab) and bear(o3, c3) and c3 < (o1 + c1) / 2
    if trend_hint == "BEAR": cond = cond and recent_upmove(df, 5)
    return bool(cond)

def three_white_soldiers(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 3: return False
    o, c = df["open"], df["close"]
    cond = bull(o.iat[-3], c.iat[-3]) and bull(o.iat[-2], c.iat[-2]) and bull(o.iat[-1], c.iat[-1]) \
           and (c.iat[-1] > c.iat[-2] > c.iat[-3])
    if trend_hint == "BULL": cond = cond and recent_downmove(df, 5)  # как разворотный после снижения
    return bool(cond)

def three_black_crows(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 3: return False
    o, c = df["open"], df["close"]
    cond = bear(o.iat[-3], c.iat[-3]) and bear(o.iat[-2], c.iat[-2]) and bear(o.iat[-1], c.iat[-1]) \
           and (c.iat[-1] < c.iat[-2] < c.iat[-3])
    if trend_hint == "BEAR": cond = cond and recent_upmove(df, 5)
    return bool(cond)

def three_line_strike_bull(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 4: return False
    o, c = df["open"], df["close"]
    cond = bull(o.iat[-4], c.iat[-4]) and bull(o.iat[-3], c.iat[-3]) and bull(o.iat[-2], c.iat[-2]) \
           and bear(o.iat[-1], c.iat[-1]) and (c.iat[-1] < o.iat[-4]) and (o.iat[-1] > c.iat[-2])
    if trend_hint == "BULL": cond = cond and recent_downmove(df, 5)
    return bool(cond)

def three_line_strike_bear(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 4: return False
    o, c = df["open"], df["close"]
    cond = bear(o.iat[-4], c.iat[-4]) and bear(o.iat[-3], c.iat[-3]) and bear(o.iat[-2], c.iat[-2]) \
           and bull(o.iat[-1], c.iat[-1]) and (c.iat[-1] > o.iat[-4]) and (o.iat[-1] < c.iat[-2])
    if trend_hint == "BEAR": cond = cond and recent_upmove(df, 5)
    return bool(cond)

def three_inside_up(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 3: return False
    o1, c1 = df["open"].iat[-3], df["close"].iat[-3]
    o2, c2 = df["open"].iat[-2], df["close"].iat[-2]
    o3, c3 = df["open"].iat[-1], df["close"].iat[-1]
    harami = (c1 < o1) and (min(o2, c2) > min(o1, c1)) and (max(o2, c2) < max(o1, c1))
    cond = harami and bull(o3, c3) and (c3 > c2)
    if trend_hint == "BULL": cond = cond and recent_downmove(df, 5)
    return bool(cond)

def three_inside_down(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 3: return False
    o1, c1 = df["open"].iat[-3], df["close"].iat[-3]
    o2, c2 = df["open"].iat[-2], df["close"].iat[-2]
    o3, c3 = df["open"].iat[-1], df["close"].iat[-1]
    harami = (c1 > o1) and (min(o2, c2) > min(o1, c1)) and (max(o2, c2) < max(o1, c1))
    cond = harami and bear(o3, c3) and (c3 < c2)
    if trend_hint == "BEAR": cond = cond and recent_upmove(df, 5)
    return bool(cond)

def three_outside_up(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 3: return False
    o1, c1 = df["open"].iat[-3], df["close"].iat[-3]
    o2, c2 = df["open"].iat[-2], df["close"].iat[-2]
    engulf = (c1 < o1) and (c2 > o2) and (o2 <= c1) and (c2 >= o1)
    cond = engulf and bull(o2, c2) and bull(df["open"].iat[-1], df["close"].iat[-1])
    if trend_hint == "BULL": cond = cond and recent_downmove(df, 5)
    return bool(cond)

def three_outside_down(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 3: return False
    o1, c1 = df["open"].iat[-3], df["close"].iat[-3]
    o2, c2 = df["open"].iat[-2], df["close"].iat[-2]
    engulf = (c1 > o1) and (c2 < o2) and (o2 >= c1) and (c2 <= o1)
    cond = engulf and bear(o2, c2) and bear(df["open"].iat[-1], df["close"].iat[-1])
    if trend_hint == "BEAR": cond = cond and recent_upmove(df, 5)
    return bool(cond)

# ---------- реестры паттернов ----------
BULL_PATTERNS = {
    "Bullish Engulfing": bullish_engulfing,
    "Piercing Line":     piercing_line,
    "Bullish Harami":    bullish_harami,
    "Tweezer Bottom":    tweezer_bottom,
    "Bullish Kicker":    bullish_kicker,
    "Morning Star":      morning_star,
    "Three White Soldiers": three_white_soldiers,
    "Bullish Three Line Strike": three_line_strike_bull,
    "Three Inside Up":   three_inside_up,
    "Three Outside Up":  three_outside_up,
}

BEAR_PATTERNS = {
    "Bearish Engulfing": bearish_engulfing,
    "Dark Cloud Cover":  dark_cloud_cover,
    "Bearish Harami":    bearish_harami,
    "Tweezer Top":       tweezer_top,
    "Bearish Kicker":    bearish_kicker,
    "Evening Star":      evening_star,
    "Three Black Crows": three_black_crows,
    "Bearish Three Line Strike": three_line_strike_bear,
    "Three Inside Down": three_inside_down,
    "Three Outside Down": three_outside_down,
}
