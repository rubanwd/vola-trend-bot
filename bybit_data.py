import ccxt
from typing import List, Dict
from settings import Settings

def build_exchange():
    if not hasattr(ccxt, Settings.EXCHANGE):
        raise RuntimeError(f"Unknown exchange in ccxt: {Settings.EXCHANGE}")
    exchange_class = getattr(ccxt, Settings.EXCHANGE)
    exchange = exchange_class({
        "enableRateLimit": True,
        "options": {"defaultType": Settings.MARKET_TYPE}
    })
    exchange.load_markets()
    return exchange

def _is_symbol_ok(mkt: dict) -> bool:
    if not mkt.get("active", True): return False
    if mkt.get("quote") != Settings.QUOTE: return False
    if mkt.get("option", False): return False
    if mkt.get("type") != Settings.MARKET_TYPE: return False
    return True

def fetch_top_by_volatility_24h(exchange) -> List[Dict]:
    """
    Быстрое формирование universe через tickers:
    vol24h_pct = (high24h - low24h) / last * 100
    Возвращает список словарей: {"symbol", "vol24h_pct"}
    """
    tickers = exchange.fetch_tickers()  # единоразово
    rows = []
    for sym, t in tickers.items():
        m = exchange.markets.get(sym)
        if not m or not _is_symbol_ok(m): 
            continue
        last = t.get("last")
        high = t.get("high")
        low  = t.get("low")
        if last and high and low and last > 0:
            vol_pct = float((high - low) / last * 100.0)
            rows.append({"symbol": sym, "vol24h_pct": vol_pct})
    rows.sort(key=lambda x: x["vol24h_pct"], reverse=True)
    return rows[:Settings.TOP_N_BY_VOL]
