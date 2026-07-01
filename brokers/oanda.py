"""oanda.py — OANDA v20 FX (+ metals/CFD) broker adapter.

SKELETON: real v20 REST endpoints wired against the BrokerAdapter seam, reading
creds from .env. Built for the validated FVG-continuation FX strategy. Not yet
exercised against a live OANDA account — connect()/get_account_state() are the
safe read paths to smoke first; place_order() is real and must only be used on a
PRACTICE account until verified.

Env (.env):
    OANDA_API_TOKEN   personal access token (AMP → Manage API Access)
    OANDA_ACCOUNT_ID  v20 account id, e.g. 101-001-1234567-001
    OANDA_ENV         "practice" (default) | "live"

Conventions vs the equity model:
    * FX "units" map to Order.quantity (signed by side: buy=+, sell=-).
    * Symbols: app uses EURUSD; OANDA uses EUR_USD. _to_oanda()/_from_oanda() map.
    * Brackets: stopLossOnFill / takeProfitOnFill attached to the entry order
      (server-side OCO) when stop_loss_price / take_profit_price are set.
    * No PDT / wash-sale concepts in FX; those AccountState fields stay 0/empty.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import httpx

from brokers.base import BrokerAdapter, BrokerConnectionError
from models.account import AccountState, Fill, Order, OrderAck, Position, Quote

logger = logging.getLogger(__name__)

_HOSTS = {
    "practice": "https://api-fxpractice.oanda.com",
    "live": "https://api-fxtrade.oanda.com",
}


def _to_oanda(symbol: str) -> str:
    """EURUSD -> EUR_USD ; XAUUSD -> XAU_USD. Already-underscored passes through."""
    s = symbol.upper().replace("/", "")
    return s if "_" in s else f"{s[:3]}_{s[3:]}"


def _from_oanda(instr: str) -> str:
    return instr.replace("_", "")


class OandaAdapter(BrokerAdapter):
    def __init__(self, *, paper: bool = True, token: str | None = None,
                 account_id: str | None = None, env: str | None = None,
                 label: str | None = None):
        self._paper = paper
        self._token = token or os.getenv("OANDA_API_TOKEN", "")
        self._account_id = account_id or os.getenv("OANDA_ACCOUNT_ID", "")
        env = (env or os.getenv("OANDA_ENV") or ("practice" if paper else "live")).lower()
        self._host = _HOSTS.get(env, _HOSTS["practice"])
        self._label = label or f"oanda_{env}"
        self._connected = False
        self._client: httpx.AsyncClient | None = None

    # ── helpers ──────────────────────────────────────────────────────
    def _hdrs(self) -> dict:
        return {"Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json"}

    async def _c(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self._host, headers=self._hdrs(), timeout=15.0)
        return self._client

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    # ── connection ───────────────────────────────────────────────────
    async def connect(self) -> bool:
        if not self._token or not self._account_id:
            raise BrokerConnectionError("OANDA_API_TOKEN / OANDA_ACCOUNT_ID missing in .env")
        try:
            c = await self._c()
            r = await c.get(f"/v3/accounts/{self._account_id}/summary")
            r.raise_for_status()
            self._connected = True
            logger.info("OANDA connected (%s) account=%s", self._label, self._account_id)
            return True
        except httpx.HTTPError as e:
            self._connected = False
            raise BrokerConnectionError(f"OANDA connect failed: {e}") from e

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def broker_name(self) -> str:
        return self._label

    # ── account ──────────────────────────────────────────────────────
    async def get_account_state(self) -> AccountState:
        c = await self._c()
        r = await c.get(f"/v3/accounts/{self._account_id}/summary")
        r.raise_for_status()
        a = r.json()["account"]
        positions: list[Position] = []
        try:
            pr = await c.get(f"/v3/accounts/{self._account_id}/openPositions")
            pr.raise_for_status()
            for p in pr.json().get("positions", []):
                long_u = float(p["long"]["units"]); short_u = float(p["short"]["units"])
                units = long_u + short_u  # signed
                if units == 0:
                    continue
                side = p["long"] if units > 0 else p["short"]
                positions.append(Position(
                    symbol=_from_oanda(p["instrument"]),
                    shares=int(units),
                    avg_entry_price=float(side.get("averagePrice", 0) or 0),
                    market_price=0.0,
                    unrealized_pnl_usd=float(p.get("unrealizedPL", 0) or 0),
                ))
        except httpx.HTTPError as e:
            logger.debug("OANDA openPositions failed: %s", e)
        return AccountState(
            account_id=self._account_id, broker=self._label, type="margin",
            equity=float(a.get("NAV", 0) or 0), cash=float(a.get("balance", 0) or 0),
            buying_power=float(a.get("marginAvailable", 0) or 0),
            open_positions=positions,
            unrealized_pnl_today=float(a.get("unrealizedPL", 0) or 0),
            trades_today=int(a.get("openTradeCount", 0) or 0),
            trading_halted=False, ts_snapshot=self._now(),
        )

    # ── market data ──────────────────────────────────────────────────
    async def get_quote(self, symbol: str) -> Quote:
        c = await self._c()
        r = await c.get(f"/v3/accounts/{self._account_id}/pricing",
                        params={"instruments": _to_oanda(symbol)})
        r.raise_for_status()
        p = r.json()["prices"][0]
        bid = float(p["bids"][0]["price"]); ask = float(p["asks"][0]["price"])
        return Quote(symbol=symbol, ts=p.get("time", self._now()),
                     bid=bid, ask=ask, bid_size=0, ask_size=0)

    # ── orders ───────────────────────────────────────────────────────
    async def place_order(self, order: Order) -> OrderAck:
        """MARKET (and limit) orders with optional server-side SL/TP bracket.
        units sign: buy/buy_to_cover = +, sell/sell_short = -."""
        c = await self._c()
        units = order.quantity if order.side in ("buy", "buy_to_cover") else -order.quantity
        otype = "MARKET" if order.order_type == "market" else "LIMIT"
        body: dict = {"order": {
            "type": otype, "instrument": _to_oanda(order.symbol),
            "units": str(units), "timeInForce": "FOK" if otype == "MARKET" else "GTC",
            "positionFill": "DEFAULT",
        }}
        if otype == "LIMIT" and order.limit_price is not None:
            body["order"]["price"] = f"{order.limit_price}"
            body["order"]["timeInForce"] = "GTC"
        if order.stop_loss_price is not None:
            body["order"]["stopLossOnFill"] = {"price": f"{order.stop_loss_price}"}
        if order.take_profit_price is not None:
            body["order"]["takeProfitOnFill"] = {"price": f"{order.take_profit_price}"}
        try:
            r = await c.post(f"/v3/accounts/{self._account_id}/orders", json=body)
            r.raise_for_status()
            data = r.json()
            txid = (data.get("orderFillTransaction") or data.get("orderCreateTransaction") or {}).get("id")
            return OrderAck(client_order_id=order.client_order_id, broker_order_id=txid,
                            accepted=True, ts=self._now())
        except httpx.HTTPError as e:
            return OrderAck(client_order_id=order.client_order_id, broker_order_id=None,
                            accepted=False, ts=self._now(), reject_reason=str(e))

    async def modify_order(self, broker_order_id: str, changes: dict) -> OrderAck:
        # v20 modifies by cancel+replace; left for the full build.
        raise NotImplementedError("OANDA modify_order: cancel+replace — TODO in full build")

    async def cancel_order(self, broker_order_id: str) -> OrderAck:
        c = await self._c()
        try:
            r = await c.put(f"/v3/accounts/{self._account_id}/orders/{broker_order_id}/cancel")
            r.raise_for_status()
            return OrderAck(client_order_id="", broker_order_id=broker_order_id, accepted=True, ts=self._now())
        except httpx.HTTPError as e:
            return OrderAck(client_order_id="", broker_order_id=broker_order_id,
                            accepted=False, ts=self._now(), reject_reason=str(e))

    async def cancel_all_orders(self) -> list[OrderAck]:
        c = await self._c()
        acks: list[OrderAck] = []
        try:
            r = await c.get(f"/v3/accounts/{self._account_id}/pendingOrders")
            r.raise_for_status()
            for o in r.json().get("orders", []):
                acks.append(await self.cancel_order(o["id"]))
        except httpx.HTTPError as e:
            logger.warning("OANDA cancel_all failed: %s", e)
        return acks

    # ── fills ────────────────────────────────────────────────────────
    async def get_fills(self, since_ts: str | None = None) -> list[Fill]:
        c = await self._c()
        params = {"type": "ORDER_FILL"}
        if since_ts:
            params["from"] = since_ts
        out: list[Fill] = []
        try:
            r = await c.get(f"/v3/accounts/{self._account_id}/transactions", params=params)
            r.raise_for_status()
            for t in r.json().get("transactions", []):
                if t.get("type") != "ORDER_FILL":
                    continue
                units = float(t.get("units", 0))
                out.append(Fill(
                    fill_id=t["id"], broker_order_id=str(t.get("orderID", "")),
                    client_order_id=str(t.get("clientOrderID", "")),
                    symbol=_from_oanda(t.get("instrument", "")), ts=t.get("time", self._now()),
                    side="buy" if units > 0 else "sell", price=float(t.get("price", 0) or 0),
                    shares=int(abs(units)), commission_usd=float(t.get("commission", 0) or 0),
                    fees_usd=float(t.get("financing", 0) or 0),
                ))
        except httpx.HTTPError as e:
            logger.debug("OANDA get_fills failed: %s", e)
        return out
