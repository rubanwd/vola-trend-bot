# bybit_api.py
import time
import hmac
import hashlib
import json
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Dict, Any, Optional, List

import requests

from settings import Settings


class BybitAPI:
    """
    Лёгкий клиент Bybit v5 (demo/real) для линейных USDT-перпетуалов.
    Работает напрямую с REST, без ccxt.
    """

    def __init__(self, api_key: str = "", api_secret: str = "", base_url: str = ""):
        self.api_key = api_key or Settings.BYBIT_API_KEY
        self.api_secret = api_secret or Settings.BYBIT_API_SECRET
        self.base = (base_url or Settings.BYBIT_BASE or "https://api-demo.bybit.com").rstrip("/")
        self.session = requests.Session()
        self._instruments_cache: Dict[str, Dict[str, Any]] = {}

    # -------- подпись / заголовки --------
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
            "Content-Type": "application/json",
        }

    def _auth_post(self, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Подписанный POST для приватных v5-эндпоинтов.
        """
        url = f"{self.base}{path}"
        body_str = json.dumps(body or {})
        ts = self._ts()
        recv = "5000"
        payload = f"{ts}{self.api_key}{recv}{body_str}"
        sign = self._sign(payload)
        headers = self._headers(sign, ts)

        r = self.session.post(url, headers=headers, data=body_str, timeout=30)
        if not r.ok:
            raise RuntimeError(f"Bybit HTTP {r.status_code} {r.reason}: {r.text}")

        data = r.json()
        if str(data.get("retCode")) != "0":
            raise RuntimeError(f"Bybit error {data.get('retCode')}: {data.get('retMsg')} | {data}")
        return data.get("result", data)

    def public_get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base}{path}"
        r = self.session.get(url, params=params, timeout=30)
        if not r.ok:
            raise RuntimeError(f"Bybit HTTP {r.status_code} {r.reason}: {r.text}")
        data = r.json()
        if str(data.get("retCode")) != "0":
            raise RuntimeError(f"Bybit error {data.get('retCode')}: {data.get('retMsg')} | {data}")
        return data.get("result", data)

    # -------- справочники / фильтры --------
    def get_instruments(self, category: str = "linear") -> List[Dict[str, Any]]:
        res = self.public_get("/v5/market/instruments-info", {"category": category})
        for item in res.get("list", []):
            self._instruments_cache[item["symbol"]] = item
        return res.get("list", [])

    def _get_symbol_filters(self, symbol: str) -> Dict[str, Any]:
        info = self._instruments_cache.get(symbol)
        if not info:
            self.get_instruments()
            info = self._instruments_cache.get(symbol, {})
        pf = info.get("priceFilter", {}) or {}
        lf = info.get("lotSizeFilter", {}) or {}
        return {
            "tickSize": str(pf.get("tickSize", "0.01")),
            "qtyStep": str(lf.get("qtyStep", "0.001")),
            "minOrderQty": str(lf.get("minOrderQty", lf.get("qtyStep", "0.001"))),
        }

    def _quantize(self, value: float, step_str: str, rounding=ROUND_DOWN) -> str:
        """
        Квантизация Decimal по шагу step_str (например '0.001').
        Возвращаем СТРОКУ — Bybit предпочитает строковые значения.
        """
        d = Decimal(str(value))
        step = Decimal(step_str)
        return str(d.quantize(step, rounding=rounding))

    def round_qty(self, symbol: str, qty: float) -> str:
        f = self._get_symbol_filters(symbol)
        q = Decimal(self._quantize(qty, f["qtyStep"], ROUND_DOWN))
        min_q = Decimal(f["minOrderQty"])
        if q < min_q:
            q = min_q
        return str(q)

    def round_price(self, symbol: str, price: float) -> str:
        f = self._get_symbol_filters(symbol)
        return self._quantize(price, f["tickSize"], ROUND_HALF_UP)

    # -------- маркет данные / позиции / ордера --------
    def get_last_price(self, symbol: str) -> float:
        res = self.public_get("/v5/market/tickers", {"category": "linear", "symbol": symbol})
        lst = res.get("list", [])
        if not lst:
            raise RuntimeError(f"No ticker for {symbol}")
        return float(lst[0]["lastPrice"])

    def get_position_mode(self) -> str:
        """
        Возвращает 'ONE_WAY' или 'HEDGE'.
        Эвристика: если встречаются positionIdx 1/2 — считаем HEDGE.
        """
        try:
            res = self._auth_post("/v5/position/list", {"category": "linear"})
            for p in res.get("list", []):
                pid = str(p.get("positionIdx", "0"))
                if pid in ("1", "2"):
                    return "HEDGE"
            return "ONE_WAY"
        except Exception:
            return "ONE_WAY"

    def get_open_positions(self) -> List[Dict[str, Any]]:
        res = self._auth_post("/v5/position/list", {"category": "linear"})
        out = []
        for p in res.get("list", []):
            if float(p.get("size") or 0) != 0:
                out.append(p)
        return out

    def set_leverage(self, symbol: str, leverage: int):
        body = {
            "category": "linear",
            "symbol": symbol,
            "buyLeverage": str(leverage),
            "sellLeverage": str(leverage),
        }
        return self._auth_post("/v5/position/set-leverage", body)

    def place_market_order(
        self,
        symbol: str,
        side: str,
        qty_str: str,
        position_idx: int = 0,
        reduce_only: bool = False,
    ):
        """
        side: 'Buy' или 'Sell'
        qty_str: строка, квантизированное количество
        position_idx: 0 (one-way), 1 (hedge Buy), 2 (hedge Sell)
        """
        body = {
            "category": "linear",
            "symbol": symbol,
            "side": side,
            "orderType": "Market",
            "qty": qty_str,
            "timeInForce": "IOC",
            "reduceOnly": reduce_only,
            "positionIdx": position_idx,
        }
        return self._auth_post("/v5/order/create", body)

    def set_tp_sl(
        self,
        symbol: str,
        take_profit: Optional[str],
        stop_loss: Optional[str],
        position_idx: int = 0,
        tp_trigger_by: str = "MarkPrice",
        sl_trigger_by: str = "MarkPrice",
    ):
        body = {
            "category": "linear",
            "symbol": symbol,
            "positionIdx": position_idx,
        }
        if take_profit is not None:
            body["takeProfit"] = str(take_profit)
            body["tpTriggerBy"] = tp_trigger_by
        if stop_loss is not None:
            body["stopLoss"] = str(stop_loss)
            body["slTriggerBy"] = sl_trigger_by
        return self._auth_post("/v5/position/trading-stop", body)

    def get_closed_pnl(self, symbol: str, limit: int = 50):
        body = {"category": "linear", "symbol": symbol, "limit": str(limit)}
        return self._auth_post("/v5/position/closed-pnl", body)
