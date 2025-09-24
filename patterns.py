# patterns.py — ЧИСТАЯ ГЕОМЕТРИЯ СВЕЧЕЙ (без контекста тренда/объёма/зон)
# Добавлены паттерны:
# - Hammer / Inverted Hammer / Hanging Man / Shooting Star
# - Doji / Dragonfly Doji / Gravestone Doji
# - Marubozu (Bullish/Bearish)
# - Doji Star (Bullish/Bearish)
# - Matching High / Matching Low
# - Rising Three Methods / Falling Three Methods
#
# Параметры строгости задаются через .env:
#   PAT_TOL_PCT, PAT_AVG_N, PAT_STRONG_BODY_FRAC, PAT_SMALL_BODY_FRAC,
#   PAT_MAX_UPPER_WICK_FRAC, PAT_MAX_LOWER_WICK_FRAC,
#   PAT_DOJI_BODY_FRAC, PAT_LONG_WICK_FRAC, PAT_INSIDE_FRAC, PAT_METHODS_MIN_INSIDE
# и RELAX_MODE = normal | relaxed | debug (влияет на дефолтные допуски).

import os
from typing import Optional, Dict, Callable
import pandas as pd

# ===== helpers: env =====
def _env_float(name, default):
    try:
        return float(os.getenv(name, default))
    except Exception:
        return default

def _env_int(name, default):
    try:
        return int(os.getenv(name, default))
    except Exception:
        return default

RELAX_MODE = os.getenv("RELAX_MODE", "debug").lower()  # 'normal' | 'relaxed' | 'debug'

# Базовый ценовой допуск для "равенства" уровней:
TOL_PCT = _env_float("PAT_TOL_PCT",
                     0.001 if RELAX_MODE == "normal" else (0.0015 if RELAX_MODE == "relaxed" else 0.002))

# Среднее тело по окну:
AVG_N = _env_int("PAT_AVG_N", 14)

# Сильное/малое тело (доля от среднего тела):
STRONG_BODY_FRAC = _env_float("PAT_STRONG_BODY_FRAC",
                              0.60 if RELAX_MODE == "normal" else (0.55 if RELAX_MODE == "relaxed" else 0.50))
SMALL_BODY_FRAC  = _env_float("PAT_SMALL_BODY_FRAC",
                              0.40 if RELAX_MODE == "normal" else (0.50 if RELAX_MODE == "relaxed" else 0.60))

# Ограничения на относительные тени у "сильных" свечей:
MAX_UPPER_WICK_FRAC = _env_float("PAT_MAX_UPPER_WICK_FRAC",
                                 0.40 if RELAX_MODE == "normal" else (0.50 if RELAX_MODE == "relaxed" else 0.60))
MAX_LOWER_WICK_FRAC = _env_float("PAT_MAX_LOWER_WICK_FRAC",
                                 0.40 if RELAX_MODE == "normal" else (0.50 if RELAX_MODE == "relaxed" else 0.60))

# Doji: как малая доля от среднего тела
DOJI_BODY_FRAC = _env_float("PAT_DOJI_BODY_FRAC",
                            0.15 if RELAX_MODE == "normal" else (0.20 if RELAX_MODE == "relaxed" else 0.25))

# «Длинная тень» как доля от тела (для Hammer/Shooting Star)
LONG_WICK_FRAC = _env_float("PAT_LONG_WICK_FRAC",
                            2.5 if RELAX_MODE == "normal" else (2.0 if RELAX_MODE == "relaxed" else 1.8))

# Насколько внутренняя свеча «должна помещаться» (для Methods)
INSIDE_FRAC = _env_float("PAT_INSIDE_FRAC", 0.95)  # 95% диапазона первой свечи
METHODS_MIN_INSIDE = _env_int("PAT_METHODS_MIN_INSIDE", 3)  # минимум «малых» свечей внутри

# ===== базовые хелперы свечей =====
def bull(o, c): return c > o
def bear(o, c): return c < o
def body(o, c): return abs(c - o)
def upper_wick(h, o, c): return h - max(o, c)
def lower_wick(l, o, c): return min(o, c) - l

def price_tol(df: pd.DataFrame) -> float:
    p = float(df["close"].iloc[-1])
    return max(p * TOL_PCT, 1e-9)

def avg_body(df: pd.DataFrame, n: int = AVG_N) -> float:
    return float(body(df["open"], df["close"]).rolling(n).mean().iloc[-1])

def wick_fracs(h, l, o, c):
    b = body(o, c)
    if b <= 0:
        return 1.0, 1.0
    return (upper_wick(h, o, c) / b), (lower_wick(l, o, c) / b)

def near_or_below(x, y, tol):  # x <= y + tol
    return x <= y + tol
def near_or_above(x, y, tol):  # x >= y - tol
    return x >= y - tol

# ====== 2-свечные из базового набора ======
def bullish_engulfing(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 2: return False
    o1, c1, h1, l1 = df["open"].iat[-2], df["close"].iat[-2], df["high"].iat[-2], df["low"].iat[-2]
    o2, c2, h2, l2 = df["open"].iat[-1], df["close"].iat[-1], df["high"].iat[-1], df["low"].iat[-1]
    tol = price_tol(df); ab = avg_body(df)
    cond = bear(o1, c1) and bull(o2, c2) and near_or_below(o2, c1, tol) and near_or_above(c2, o1, tol)
    up2, lo2 = wick_fracs(h2, l2, o2, c2)
    cond = cond and (body(o2, c2) >= STRONG_BODY_FRAC * ab) and (up2 <= MAX_UPPER_WICK_FRAC) and (lo2 <= MAX_LOWER_WICK_FRAC)
    return bool(cond)

def bearish_engulfing(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 2: return False
    o1, c1, h1, l1 = df["open"].iat[-2], df["close"].iat[-2], df["high"].iat[-2], df["low"].iat[-2]
    o2, c2, h2, l2 = df["open"].iat[-1], df["close"].iat[-1], df["high"].iat[-1], df["low"].iat[-1]
    tol = price_tol(df); ab = avg_body(df)
    cond = bull(o1, c1) and bear(o2, c2) and near_or_above(o2, c1, tol) and near_or_below(c2, o1, tol)
    up2, lo2 = wick_fracs(h2, l2, o2, c2)
    cond = cond and (body(o2, c2) >= STRONG_BODY_FRAC * ab) and (up2 <= MAX_UPPER_WICK_FRAC) and (lo2 <= MAX_LOWER_WICK_FRAC)
    return bool(cond)

def piercing_line(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 2: return False
    o1, c1 = df["open"].iat[-2], df["close"].iat[-2]
    o2, c2 = df["open"].iat[-1], df["close"].iat[-1]
    ab = avg_body(df); tol = price_tol(df)
    mid = (o1 + c1) / 2.0
    cond = bear(o1, c1) and bull(o2, c2) and near_or_below(o2, c1, tol) and (c2 > mid)
    cond = cond and (body(o2, c2) >= 0.5 * ab)
    return bool(cond)

def dark_cloud_cover(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 2: return False
    o1, c1 = df["open"].iat[-2], df["close"].iat[-2]
    o2, c2 = df["open"].iat[-1], df["close"].iat[-1]
    ab = avg_body(df); tol = price_tol(df)
    mid = (o1 + c1) / 2.0
    cond = bull(o1, c1) and bear(o2, c2) and near_or_above(o2, c1, tol) and (c2 < mid)
    cond = cond and (body(o2, c2) >= 0.5 * ab)
    return bool(cond)

def bullish_harami(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 2: return False
    o1, c1 = df["open"].iat[-2], df["close"].iat[-2]
    o2, c2 = df["open"].iat[-1], df["close"].iat[-1]
    ab = avg_body(df)
    inside = (min(o2, c2) > min(o1, c1)) and (max(o2, c2) < max(o1, c1))
    return bool(bear(o1, c1) and inside and (body(o2, c2) <= SMALL_BODY_FRAC * ab))

def bearish_harami(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 2: return False
    o1, c1 = df["open"].iat[-2], df["close"].iat[-2]
    o2, c2 = df["open"].iat[-1], df["close"].iat[-1]
    ab = avg_body(df)
    inside = (min(o2, c2) > min(o1, c1)) and (max(o2, c2) < max(o1, c1))
    return bool(bull(o1, c1) and inside and (body(o2, c2) <= SMALL_BODY_FRAC * ab))

def tweezer_bottom(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 2: return False
    l1, l2 = df["low"].iat[-2], df["low"].iat[-1]
    o1, c1 = df["open"].iat[-2], df["close"].iat[-2]
    o2, c2 = df["open"].iat[-1], df["close"].iat[-1]
    tol = price_tol(df)
    return bool(abs(l1 - l2) <= tol and bear(o1, c1) and bull(o2, c2))

def tweezer_top(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 2: return False
    h1, h2 = df["high"].iat[-2], df["high"].iat[-1]
    o1, c1 = df["open"].iat[-2], df["close"].iat[-2]
    o2, c2 = df["open"].iat[-1], df["close"].iat[-1]
    tol = price_tol(df)
    return bool(abs(h1 - h2) <= tol and bull(o1, c1) and bear(o2, c2))

def bullish_kicker(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 2: return False
    o1, c1 = df["open"].iat[-2], df["close"].iat[-2]
    o2, c2 = df["open"].iat[-1], df["close"].iat[-1]
    ab = avg_body(df)
    return bool(bear(o1, c1) and bull(o2, c2) and (body(o2, c2) >= STRONG_BODY_FRAC * ab) and (c2 > o1))

def bearish_kicker(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 2: return False
    o1, c1 = df["open"].iat[-2], df["close"].iat[-2]
    o2, c2 = df["open"].iat[-1], df["close"].iat[-1]
    ab = avg_body(df)
    return bool(bull(o1, c1) and bear(o2, c2) and (body(o2, c2) >= STRONG_BODY_FRAC * ab) and (c2 < o1))

# ====== 3-свечные и подтверждения из базового набора ======
def morning_star(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 3: return False
    o1, c1 = df["open"].iat[-3], df["close"].iat[-3]
    o2, c2 = df["open"].iat[-2], df["close"].iat[-2]
    o3, c3 = df["open"].iat[-1], df["close"].iat[-1]
    ab = avg_body(df)
    return bool(bear(o1, c1) and (body(o2, c2) <= SMALL_BODY_FRAC * ab) and bull(o3, c3) and (c3 > (o1 + c1) / 2))

def evening_star(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 3: return False
    o1, c1 = df["open"].iat[-3], df["close"].iat[-3]
    o2, c2 = df["open"].iat[-2], df["close"].iat[-2]
    o3, c3 = df["open"].iat[-1], df["close"].iat[-1]
    ab = avg_body(df)
    return bool(bull(o1, c1) and (body(o2, c2) <= SMALL_BODY_FRAC * ab) and bear(o3, c3) and (c3 < (o1 + c1) / 2))

def three_white_soldiers(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 3: return False
    o, c = df["open"], df["close"]
    return bool(bull(o.iat[-3], c.iat[-3]) and bull(o.iat[-2], c.iat[-2]) and bull(o.iat[-1], c.iat[-1])
                and (c.iat[-1] > c.iat[-2] > c.iat[-3]))

def three_black_crows(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 3: return False
    o, c = df["open"], df["close"]
    return bool(bear(o.iat[-3], c.iat[-3]) and bear(o.iat[-2], c.iat[-2]) and bear(o.iat[-1], c.iat[-1])
                and (c.iat[-1] < c.iat[-2] < c.iat[-3]))

def three_line_strike_bull(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 4: return False
    o, c = df["open"], df["close"]
    return bool(bull(o.iat[-4], c.iat[-4]) and bull(o.iat[-3], c.iat[-3]) and bull(o.iat[-2], c.iat[-2])
                and bear(o.iat[-1], c.iat[-1]) and (c.iat[-1] < o.iat[-4]) and (o.iat[-1] > c.iat[-2]))

def three_line_strike_bear(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 4: return False
    o, c = df["open"], df["close"]
    return bool(bear(o.iat[-4], c.iat[-4]) and bear(o.iat[-3], c.iat[-3]) and bear(o.iat[-2], c.iat[-2])
                and bull(o.iat[-1], c.iat[-1]) and (c.iat[-1] > o.iat[-4]) and (o.iat[-1] < c.iat[-2]))

def three_inside_up(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 3: return False
    o1, c1 = df["open"].iat[-3], df["close"].iat[-3]
    o2, c2 = df["open"].iat[-2], df["close"].iat[-2]
    o3, c3 = df["open"].iat[-1], df["close"].iat[-1]
    harami = (c1 < o1) and (min(o2, c2) > min(o1, c1)) and (max(o2, c2) < max(o1, c1))
    return bool(harami and bull(o3, c3) and (c3 > c2))

def three_inside_down(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 3: return False
    o1, c1 = df["open"].iat[-3], df["close"].iat[-3]
    o2, c2 = df["open"].iat[-2], df["close"].iat[-2]
    o3, c3 = df["open"].iat[-1], df["close"].iat[-1]
    harami = (c1 > o1) and (min(o2, c2) > min(o1, c1)) and (max(o2, c2) < max(o1, c1))
    return bool(harami and bear(o3, c3) and (c3 < c2))

def three_outside_up(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 3: return False
    o1, c1 = df["open"].iat[-3], df["close"].iat[-3]
    o2, c2 = df["open"].iat[-2], df["close"].iat[-2]
    engulf = (c1 < o1) and (c2 > o2) and (o2 <= c1) and (c2 >= o1)
    return bool(engulf and bull(df["open"].iat[-1], df["close"].iat[-1]))

def three_outside_down(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 3: return False
    o1, c1 = df["open"].iat[-3], df["close"].iat[-3]
    o2, c2 = df["open"].iat[-2], df["close"].iat[-2]
    engulf = (c1 > o1) and (c2 < o2) and (o2 >= c1) and (c2 <= o1)
    return bool(engulf and bear(df["open"].iat[-1], df["close"].iat[-1]))

# ===== НОВЫЕ ОДНОСВЕЧНЫЕ =====
def is_doji(o, c, ab) -> bool:
    return body(o, c) <= DOJI_BODY_FRAC * ab

def is_marubozu(h, l, o, c, tol) -> bool:
    # Почти без теней
    return (upper_wick(h, o, c) <= tol) and (lower_wick(l, o, c) <= tol)

def hammer(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    # маленькое тело вверху диапазона + длинная нижняя тень
    if len(df) < 1: return False
    o, c, h, l = df["open"].iat[-1], df["close"].iat[-1], df["high"].iat[-1], df["low"].iat[-1]
    ab = avg_body(df); tol = price_tol(df)
    up, lo = wick_fracs(h, l, o, c)
    return bool((body(o, c) <= SMALL_BODY_FRAC * ab) and (lo >= LONG_WICK_FRAC) and (upper_wick(h, o, c) <= MAX_UPPER_WICK_FRAC * max(body(o, c), tol)))

def inverted_hammer(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 1: return False
    o, c, h, l = df["open"].iat[-1], df["close"].iat[-1], df["high"].iat[-1], df["low"].iat[-1]
    ab = avg_body(df); tol = price_tol(df)
    up, lo = wick_fracs(h, l, o, c)
    return bool((body(o, c) <= SMALL_BODY_FRAC * ab) and (up >= LONG_WICK_FRAC) and (lower_wick(l, o, c) <= MAX_LOWER_WICK_FRAC * max(body(o, c), tol)))

def hanging_man(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    # как hammer, но встречается после роста — контекст мы не проверяем, только форма
    return hammer(df)

def shooting_star(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    # маленькое тело внизу + длинная верхняя тень
    if len(df) < 1: return False
    o, c, h, l = df["open"].iat[-1], df["close"].iat[-1], df["high"].iat[-1], df["low"].iat[-1]
    ab = avg_body(df); tol = price_tol(df)
    up, lo = wick_fracs(h, l, o, c)
    return bool((body(o, c) <= SMALL_BODY_FRAC * ab) and (up >= LONG_WICK_FRAC) and (lower_wick(l, o, c) <= MAX_LOWER_WICK_FRAC * max(body(o, c), tol)))

def doji(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 1: return False
    o, c = df["open"].iat[-1], df["close"].iat[-1]
    ab = avg_body(df)
    return bool(is_doji(o, c, ab))

def dragonfly_doji(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 1: return False
    o, c, h, l = df["open"].iat[-1], df["close"].iat[-1], df["high"].iat[-1], df["low"].iat[-1]
    ab = avg_body(df); tol = price_tol(df)
    # close≈open≈high, длинная нижняя тень
    return bool(is_doji(o, c, ab) and (abs(h - max(o, c)) <= tol) and (lower_wick(l, o, c) >= LONG_WICK_FRAC * max(body(o, c), tol)))

def gravestone_doji(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 1: return False
    o, c, h, l = df["open"].iat[-1], df["close"].iat[-1], df["high"].iat[-1], df["low"].iat[-1]
    ab = avg_body(df); tol = price_tol(df)
    # close≈open≈low, длинная верхняя тень
    return bool(is_doji(o, c, ab) and (abs(l - min(o, c)) <= tol) and (upper_wick(h, o, c) >= LONG_WICK_FRAC * max(body(o, c), tol)))

def bullish_marubozu(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 1: return False
    o, c, h, l = df["open"].iat[-1], df["close"].iat[-1], df["high"].iat[-1], df["low"].iat[-1]
    tol = price_tol(df)
    return bool(bull(o, c) and is_marubozu(h, l, o, c, tol))

def bearish_marubozu(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 1: return False
    o, c, h, l = df["open"].iat[-1], df["close"].iat[-1], df["high"].iat[-1], df["low"].iat[-1]
    tol = price_tol(df)
    return bool(bear(o, c) and is_marubozu(h, l, o, c, tol))

# ===== НОВЫЕ ДВУХСВЕЧНЫЕ =====
def doji_star_bullish(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    # сильная медвежья, затем doji
    if len(df) < 2: return False
    o1, c1 = df["open"].iat[-2], df["close"].iat[-2]
    o2, c2, h2, l2 = df["open"].iat[-1], df["close"].iat[-1], df["high"].iat[-1], df["low"].iat[-1]
    ab = avg_body(df)
    return bool(bear(o1, c1) and is_doji(o2, c2, ab))

def doji_star_bearish(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    if len(df) < 2: return False
    o1, c1 = df["open"].iat[-2], df["close"].iat[-2]
    o2, c2, h2, l2 = df["open"].iat[-1], df["close"].iat[-1], df["high"].iat[-1], df["low"].iat[-1]
    ab = avg_body(df)
    return bool(bull(o1, c1) and is_doji(o2, c2, ab))

def matching_high(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    # два одинаковых close подряд (уровень сопротивления)
    if len(df) < 2: return False
    c1, c2 = df["close"].iat[-2], df["close"].iat[-1]
    tol = price_tol(df)
    return bool(abs(c1 - c2) <= tol)

def matching_low(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    # два одинаковых close подряд (уровень поддержки)
    if len(df) < 2: return False
    c1, c2 = df["close"].iat[-2], df["close"].iat[-1]
    tol = price_tol(df)
    return bool(abs(c1 - c2) <= tol)

# ===== НОВЫЕ ТРЁХСВЕЧНЫЕ (CONTINUATION) =====
def rising_three_methods(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    """
    1: сильная бычья
    2..n: маленькие (обычно 3) свечи отката, тела и экстремумы остаются внутри диапазона 1-й
    последняя: бычья с закрытием выше close 1-й.
    """
    n = len(df)
    if n < 5:  # типично 5, но допустим >=5
        return False
    o, c, h, l = df["open"], df["close"], df["high"], df["low"]
    ab = avg_body(df)

    # Свеча 1 (n-5 или n-4 в зависимости от длины): возьмем n-5 как старт если >=5, иначе пересчитаем
    i0 = n - 5
    if i0 < 0:
        i0 = n - 4
    if i0 < 0:
        return False

    # найдём первую мощную бычью среди последних 5 свечей
    found = False
    for i in range(n - 5, n - 3):
        if i < 0: continue
        if bull(o.iat[i], c.iat[i]) and (body(o.iat[i], c.iat[i]) >= STRONG_BODY_FRAC * ab):
            i0 = i
            found = True
            break
    if not found:
        return False

    hi0, lo0 = h.iat[i0], l.iat[i0]
    # Свечи внутри диапазона 1-й (минимум METHODS_MIN_INSIDE штук)
    inside_cnt = 0
    last_idx = None
    for j in range(i0 + 1, n - 1):
        if (min(o.iat[j], c.iat[j]) >= lo0) and (max(o.iat[j], c.iat[j]) <= hi0):
            inside_cnt += 1
            last_idx = j
    if inside_cnt < METHODS_MIN_INSIDE:
        return False

    # Последняя свеча бычья, закрытие выше close первой
    return bool(bull(o.iat[-1], c.iat[-1]) and (c.iat[-1] > c.iat[i0]))

def falling_three_methods(df: pd.DataFrame, trend_hint: Optional[str] = None) -> bool:
    """
    Обратный вариант для падения.
    """
    n = len(df)
    if n < 5:
        return False
    o, c, h, l = df["open"], df["close"], df["high"], df["low"]
    ab = avg_body(df)

    i0 = n - 5
    if i0 < 0:
        i0 = n - 4
    if i0 < 0:
        return False

    found = False
    for i in range(n - 5, n - 3):
        if i < 0: continue
        if bear(o.iat[i], c.iat[i]) and (body(o.iat[i], c.iat[i]) >= STRONG_BODY_FRAC * ab):
            i0 = i
            found = True
            break
    if not found:
        return False

    hi0, lo0 = h.iat[i0], l.iat[i0]
    inside_cnt = 0
    for j in range(i0 + 1, n - 1):
        if (min(o.iat[j], c.iat[j]) >= lo0) and (max(o.iat[j], c.iat[j]) <= hi0):
            inside_cnt += 1
    if inside_cnt < METHODS_MIN_INSIDE:
        return False

    return bool(bear(o.iat[-1], c.iat[-1]) and (c.iat[-1] < c.iat[i0]))

# ===== РЕЕСТРЫ =====
BULL_PATTERNS: Dict[str, Callable] = {
    # базовые
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
    # # новые single
    # "Hammer":            hammer,
    # "Inverted Hammer":   inverted_hammer,
    # "Doji":              doji,
    # "Dragonfly Doji":    dragonfly_doji,
    # "Bullish Marubozu":  bullish_marubozu,
    # # двухсвечные новые
    # "Doji Star (Bullish)": doji_star_bullish,
    # # continuation
    # "Rising Three Methods": rising_three_methods,
    # # уровни
    # "Matching Low":      matching_low,
}

BEAR_PATTERNS: Dict[str, Callable] = {
    # базовые
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
    # # новые single
    # "Hanging Man":       hanging_man,
    # "Shooting Star":     shooting_star,
    # "Doji":              doji,
    # "Gravestone Doji":   gravestone_doji,
    # "Bearish Marubozu":  bearish_marubozu,
    # # двухсвечные новые
    # "Doji Star (Bearish)": doji_star_bearish,
    # # continuation
    # "Falling Three Methods": falling_three_methods,
    # # уровни
    # "Matching High":     matching_high,
}
