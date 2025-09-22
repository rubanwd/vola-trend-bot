import pandas as pd

# Помощники
def is_bull(c1o,c1c): return c1c>c1o
def is_bear(c1o,c1c): return c1c<c1o
def body(o,c): return abs(c-o)
def upper_shadow(h,o,c): return h - max(o,c)
def lower_shadow(l,o,c): return min(o,c) - l

# === 2-свечные ===
def bullish_engulfing(df):
    o1,c1 = df["open"].iat[-2], df["close"].iat[-2]
    o2,c2 = df["open"].iat[-1], df["close"].iat[-1]
    return is_bear(o1,c1) and is_bull(o2,c2) and o2<=c1 and c2>=o1

def bearish_engulfing(df):
    o1,c1 = df["open"].iat[-2], df["close"].iat[-2]
    o2,c2 = df["open"].iat[-1], df["close"].iat[-1]
    return is_bull(o1,c1) and is_bear(o2,c2) and o2>=c1 and c2<=o1

def piercing_line(df):
    # вторая свеча бычья и закрывается выше середины тела первой медвежьей
    o1,c1 = df["open"].iat[-2], df["close"].iat[-2]
    o2,c2 = df["open"].iat[-1], df["close"].iat[-1]
    mid = (o1+c1)/2
    return is_bear(o1,c1) and is_bull(o2,c2) and c2>mid and o2<c1

def dark_cloud_cover(df):
    o1,c1 = df["open"].iat[-2], df["close"].iat[-2]
    o2,c2 = df["open"].iat[-1], df["close"].iat[-1]
    mid = (o1+c1)/2
    return is_bull(o1,c1) and is_bear(o2,c2) and c2<mid and o2>c1

def bullish_harami(df):
    o1,c1 = df["open"].iat[-2], df["close"].iat[-2]
    o2,c2 = df["open"].iat[-1], df["close"].iat[-1]
    return is_bear(o1,c1) and (min(o2,c2) > min(o1,c1)) and (max(o2,c2) < max(o1,c1))

def bearish_harami(df):
    o1,c1 = df["open"].iat[-2], df["close"].iat[-2]
    o2,c2 = df["open"].iat[-1], df["close"].iat[-1]
    return is_bull(o1,c1) and (min(o2,c2) > min(o1,c1)) and (max(o2,c2) < max(o1,c1))

def tweezer_bottom(df, eps=1e-8):
    l1 = df["low"].iat[-2]
    l2 = df["low"].iat[-1]
    return abs(l1 - l2) <= max(0.0001, eps*max(l1,l2))

def tweezer_top(df, eps=1e-8):
    h1 = df["high"].iat[-2]
    h2 = df["high"].iat[-1]
    return abs(h1 - h2) <= max(0.0001, eps*max(h1,h2))

def bullish_kicker(df):
    # в крипте "гэпы" редки, используем сильное противоположное тело и смену направления
    o1,c1 = df["open"].iat[-2], df["close"].iat[-2]
    o2,c2 = df["open"].iat[-1], df["close"].iat[-1]
    return is_bear(o1,c1) and is_bull(o2,c2) and c2>o1 and (c1-o1)/o1<-0.01 and (c2-o2)/o2>0.01

def bearish_kicker(df):
    o1,c1 = df["open"].iat[-2], df["close"].iat[-2]
    o2,c2 = df["open"].iat[-1], df["close"].iat[-1]
    return is_bull(o1,c1) and is_bear(o2,c2) and c2<o1 and (c1-o1)/o1>0.01 and (c2-o2)/o2<-0.01

# === 3-свечные ===
def morning_star(df):
    o1,c1 = df["open"].iat[-3], df["close"].iat[-3]
    o2,c2 = df["open"].iat[-2], df["close"].iat[-2]
    o3,c3 = df["open"].iat[-1], df["close"].iat[-1]
    return is_bear(o1,c1) and abs(c2-o2) < body(o1,c1)*0.6 and is_bull(o3,c3) and c3> (o1+c1)/2

def evening_star(df):
    o1,c1 = df["open"].iat[-3], df["close"].iat[-3]
    o2,c2 = df["open"].iat[-2], df["close"].iat[-2]
    o3,c3 = df["open"].iat[-1], df["close"].iat[-1]
    return is_bull(o1,c1) and abs(c2-o2) < body(o1,c1)*0.6 and is_bear(o3,c3) and c3< (o1+c1)/2

def three_white_soldiers(df):
    o,c = df["open"], df["close"]
    return (c.iat[-3]>o.iat[-3]) and (c.iat[-2]>o.iat[-2]) and (c.iat[-1]>o.iat[-1]) and (c.iat[-1]>c.iat[-2]>c.iat[-3])

def three_black_crows(df):
    o,c = df["open"], df["close"]
    return (c.iat[-3]<o.iat[-3]) and (c.iat[-2]<o.iat[-2]) and (c.iat[-1]<o.iat[-1]) and (c.iat[-1]<c.iat[-2]<c.iat[-3])

def three_line_strike_bull(df):
    # три бычьих, затем одна сильная медвежья, перекрывающая диапазон
    o,c = df["open"], df["close"]
    if not ((c.iat[-4]>o.iat[-4]) and (c.iat[-3]>o.iat[-3]) and (c.iat[-2]>o.iat[-2])): return False
    return (c.iat[-1]<o.iat[-1]) and (c.iat[-1]<o.iat[-4]) and (o.iat[-1]>c.iat[-2])

def three_line_strike_bear(df):
    o,c = df["open"], df["close"]
    if not ((c.iat[-4]<o.iat[-4]) and (c.iat[-3]<o.iat[-3]) and (c.iat[-2]<o.iat[-2])): return False
    return (c.iat[-1]>o.iat[-1]) and (c.iat[-1]>o.iat[-4]) and (o.iat[-1]<c.iat[-2])

def three_inside_up(df):
    # харами (медвежья -> малая бычья) затем подтверждение бычьей свечой
    o1,c1 = df["open"].iat[-3], df["close"].iat[-3]
    o2,c2 = df["open"].iat[-2], df["close"].iat[-2]
    o3,c3 = df["open"].iat[-1], df["close"].iat[-1]
    harami = (c1<o1) and (min(o2,c2)>min(o1,c1)) and (max(o2,c2)<max(o1,c1))
    return harami and (c3>o3) and (c3>c2)

def three_inside_down(df):
    o1,c1 = df["open"].iat[-3], df["close"].iat[-3]
    o2,c2 = df["open"].iat[-2], df["close"].iat[-2]
    o3,c3 = df["open"].iat[-1], df["close"].iat[-1]
    harami = (c1>o1) and (min(o2,c2)>min(o1,c1)) and (max(o2,c2)<max(o1,c1))
    return harami and (c3<o3) and (c3<c2)

def three_outside_up(df):
    # поглощение бычье -> ещё одна бычья
    o1,c1 = df["open"].iat[-3], df["close"].iat[-3]
    o2,c2 = df["open"].iat[-2], df["close"].iat[-2]
    engulf = (c1<o1) and (c2>o2) and (o2<=c1) and (c2>=o1)
    o3,c3 = df["open"].iat[-1], df["close"].iat[-1]
    return engulf and (c3>o3) and (c3>c2)

def three_outside_down(df):
    o1,c1 = df["open"].iat[-3], df["close"].iat[-3]
    o2,c2 = df["open"].iat[-2], df["close"].iat[-2]
    engulf = (c1>o1) and (c2<o2) and (o2>=c1) and (c2<=o1)
    o3,c3 = df["open"].iat[-1], df["close"].iat[-1]
    return engulf and (c3<o3) and (c3<c2)

# Собираем списки для тренда
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
    "Three Outside Down":three_outside_down,
}
