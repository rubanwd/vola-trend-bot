# bybit_api.py
import time, hmac, hashlib, json
import requests
from typing import Dict, Any, Optional
from settings import Settings

DEFAULT_BYBIT_BASE = Settings.BYBIT_BASE  # demo: https://api-demo.bybit.com

class BybitAPI:
    def __init__(self, api_key: str = "", api_secret: str = "", base_url: str = DEFAULT_BYBIT_BASE):
        self.api_key = api_key or Settings.BYBIT_API_KEY
        self.api_secret = api_secret or Settings.BYBIT_API_SECRET
        self.base = base_url.rstrip("/")
        self.session = requests.Session()
        self._instruments_cache: Dict[str, Dict[str, Any]] = {}

    # --- signing ---
    def _ts(self) -> str:
        return str(int(time.time() * 1000))

    def _sign(self, payload: str) -> str:
        return hmac.new(self.api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

    def _headers(self, sign: str, timestamp: str) -> Dict[str, str]:
        return {
            "X-BAPI-SIGN": sign,
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": "5000",
            "Content-Type": "application/json"
        }

    def _auth_request(self, method: str, path: str, body: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None):
        url = f"{self.base}{path}"
        body_str = json.dumps(body) if body else ""
        ts = self._ts()
        recv = "5000"
        query = ""  # v5 auth for POST uses empty query in payload string
        if method.upper() == "GET" and params:
            # for GET signed endpoints include query string in sign payload
            # But for most private GETs Bybit expects empty body and sign over query string
            pieces = [ts, self.api_key, recv, ""]
            sign = self._sign("".join(pieces))
            headers = self._headers(sign, ts)
            r = self.session.get(url, headers=headers, params=params, timeout=30)
        else:
            payload = f"{ts}{self.api_key}{recv}{body_str}"
            sign = self._sign(payload)
            headers = self._headers(sign, ts)
            if method.upper() == "POST":
                r = self.session.post(url, headers=headers, data=body_str, timeout=30)
            elif method.upper() == "DELETE":
                r = self.session.delete(url, headers=headers, data=body_str, timeout=30)
            else:
                r = self.session.request(method, url, headers=headers, data=body_str, timeout=30)

        if not r.ok:
            raise RuntimeError(f"Bybit HTTP {r.status_code} {r.reason}: {r.text}")

        data = r.json()
        if str(data.get("retCode")) != "0":
            raise RuntimeError(f"Bybit error {data.get('retCode')}: {data.get('retMsg')} | {data}")
        return data.get("result", data)

    # --- public (unsigned) ---
    def public_get(self, path: str, params: Optional[Dict[str, Any]] = None):
        url = f"{self.base}{path}"
        r = self.session.get(url, params=params, timeout=30)
        if not r.ok:
            raise RuntimeError(f"Bybit HTTP {r.status_code} {r.reason}: {r.text}")
        data = r.json()
        if str(data.get("retCode")) != "0":
            raise RuntimeError(f"Bybit error {data.get('retCode')}: {data.get('retMsg')} | {data}")
        return data.get("result", data)

    # --- market / instruments ---
    def get_instruments(self, category: str = "linear"):
        res = self.public_get("/v5/market/instruments-info", {"category": category})
        for item in res.get("list", []):
            self._instruments_cache[item["symbol"]] = item
        return res.get("list", [])

    def build_symbol_info_map(self, instruments_list=None):
        if instruments_list is None:
            instruments_list = self.get_instruments()
        m = {}
        for it in instruments_list:
            sym = it["symbol"]
            qty_step = float(it["lotSizeFilter"]["qtyStep"])
            tick_size = float(it["priceFilter"]["tickSize"])
            min_order_qty = float(it["lotSizeFilter"].get("minOrderQty", qty_step))
            m[sym] = {"qty_step": qty_step, "tick_size": tick_size, "min_qty": min_order_qty}
        return m

    def round_qty(self, symbol: str, qty: float) -> float:
        info = self._instruments_cache.get(symbol)
        if not info:
            self.get_instruments()
            info = self._instruments_cache.get(symbol, {})
        step = float(info.get("lotSizeFilter", {}).get("qtyStep", 0.001)) or 0.001
        return max(round(qty / step) * step, float(info.get("lotSizeFilter", {}).get("minOrderQty", step)))

    def round_price(self, symbol: str, price: float) -> float:
        info = self._instruments_cache.get(symbol)
        if not info:
            self.get_instruments()
            info = self._instruments_cache.get(symbol, {})
        tick = float(info.get("priceFilter", {}).get("tickSize", 0.01)) or 0.01
        return round(price / tick) * tick

    def get_last_price(self, symbol: str) -> float:
        res = self.public_get("/v5/market/tickers", {"category": "linear", "symbol": symbol})
        lst = res.get("list", [])
        if not lst:
            raise RuntimeError(f"No ticker for {symbol}")
        return float(lst[0]["lastPrice"])

    # --- positions / orders (private) ---
    def set_leverage(self, symbol: str, leverage: int):
        body = {"category": "linear", "symbol": symbol, "buyLeverage": str(leverage), "sellLeverage": str(leverage)}
        return self._auth_request("POST", "/v5/position/set-leverage", body)

    def get_open_positions(self):
        res = self._auth_request("POST", "/v5/position/list", {"category": "linear"})
        # normalize: only positions with size != 0
        out = []
        for p in res.get("list", []):
            if float(p.get("size", 0) or 0) != 0:
                out.append(p)
        return out

    def place_market_order(self, symbol: str, side: str, qty: float, reduce_only: bool = False):
        """
        side: 'Buy' или 'Sell'
        qty: в "coin" qty (НЕ в USD)
        """
        body = {
            "category": "linear",
            "symbol": symbol,
            "side": side,
            "orderType": "Market",
            "qty": str(qty),
            "timeInForce": "IOC",
            "reduceOnly": reduce_only
        }
        return self._auth_request("POST", "/v5/order/create", body)

    def set_tp_sl(self, symbol: str, take_profit: Optional[float], stop_loss: Optional[float], tp_trigger_by="MarkPrice", sl_trigger_by="MarkPrice"):
        body = {
            "category": "linear",
            "symbol": symbol,
        }
        if take_profit is not None:
            body["takeProfit"] = str(take_profit)
            body["tpTriggerBy"] = tp_trigger_by
        if stop_loss is not None:
            body["stopLoss"] = str(stop_loss)
            body["slTriggerBy"] = sl_trigger_by
        return self._auth_request("POST", "/v5/position/trading-stop", body)

    def get_closed_pnl(self, symbol: str, limit: int = 50):
        # используем для проверки "когда последний раз закрывали позицию"
        body = {"category": "linear", "symbol": symbol, "limit": str(limit)}
        return self._auth_request("POST", "/v5/position/closed-pnl", body)
