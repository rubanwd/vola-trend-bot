# bybit_data.py
import ccxt
import pandas as pd
from typing import List
from settings import Settings

def build_exchange():
    """
    Возвращает инстанс ccxt.<exchange> с нужными опциями для Bybit.
    MARKET_TYPE: 'spot' или 'swap' (USDT-perp). По умолчанию 'swap'.
    """
    if not hasattr(ccxt, Settings.EXCHANGE):
        raise RuntimeError(f"Unknown exchange in ccxt: {Settings.EXCHANGE}")

    exchange_class = getattr(ccxt, Settings.EXCHANGE)
    exchange = exchange_class({
        "enableRateLimit": True,
        "options": {
            # важно для Bybit: выбираем тип рынка по умолчанию
            "defaultType": Settings.MARKET_TYPE,   # 'spot' | 'swap'
        }
    })

    # загрузим рынки один раз
    exchange.load_markets()
    return exchange

def list_symbols_usdt(exchange) -> List[str]:
    """
    Возвращает список активных символов к QUOTE (по умолчанию USDT),
    фильтруя опционы/инверсные/неактивные рынки.
    """
    out: List[str] = []
    for sym, m in exchange.markets.items():
        if not m.get("active", True):
            continue
        if m.get("quote") != Settings.QUOTE:
            continue
        if m.get("option", False):
            continue
        t = m.get("type")
        # оставляем только указанный тип (spot/swap)
        if t != Settings.MARKET_TYPE:
            continue
        out.append(sym)
    return sorted(set(out))

def fetch_ohlcv_df(exchange, symbol: str, timeframe: str, limit: int = 300) -> pd.DataFrame:
    """
    Загружает OHLCV и возвращает DataFrame с колонками:
    ts, open, high, low, close, volume
    """
    if not exchange.has.get("fetchOHLCV", False):
        raise RuntimeError(f"{exchange.id} has no fetchOHLCV")

    # ccxt иногда может кинуть эксепшн при слишком большом лимите
    limit = max(50, min(1000, int(limit)))

    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    if not ohlcv or len(ohlcv) == 0:
        raise RuntimeError(f"Empty OHLCV for {symbol} {timeframe}")

    df = pd.DataFrame(ohlcv, columns=["ts","open","high","low","close","volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms")
    return df
