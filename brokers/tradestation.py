"""TradeStationAdapter — paper + live broker via TradeStation API v3.

OAuth2 refresh-token flow:
    1. User does OAuth setup ONCE offline (see /broker setup guide),
       copies `TS_REFRESH_TOKEN` into `.env`.
    2. `connect()` POSTs to the token endpoint with the stored refresh
       token to get a fresh access_token + new refresh_token.
    3. The new refresh_token is written back to `.env` (rotation).
    4. Access tokens expire in ~20min; we refresh proactively before
       every API call if expiry is within 2min.

Environment variables (read from `.env` at project root):
    TS_CLIENT_ID, TS_CLIENT_SECRET, TS_REFRESH_TOKEN, TS_ACCOUNT_ID
    TS_SIM = "true" for sim, "false" for live

Missing-env graceful behavior: `connect()` logs and returns False. The app
must remain usable for settings edits even if the broker is offline.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from dotenv import set_key

from brokers.base import BrokerAdapter, BrokerConnectionError
from models.account import AccountState, Fill, Order, OrderAck, Position, Quote
from services.settings_service import ENV_FILE

logger = logging.getLogger(__name__)

AUTH_URL = "https://signin.tradestation.com/oauth/token"
API_URL_SIM = "https://sim-api.tradestation.com/v3"
API_URL_LIVE = "https://api.tradestation.com/v3"

REFRESH_MARGIN_SECONDS = 120  # refresh 2 minutes before expiry
HTTP_TIMEOUT = 10.0

# TradeStation payload enum mappings
_SIDE_TO_TS = {
    "buy":          "BUY",
    "sell":         "SELL",
    "buy_to_cover": "BUY_TO_COVER",
    "sell_short":   "SELL_SHORT",
}
_TYPE_TO_TS = {
    "market":     "Market",
    "limit":      "Limit",
    "stop":       "StopMarket",
    "stop_limit": "StopLimit",
}
_TIF_TO_TS = {
    "day": "DAY",
    "gtc": "GTC",
    "ioc": "IOC",
    "fok": "FOK",
}


class TradeStationAdapter(BrokerAdapter):
    """TradeStation paper (sim) or live adapter."""

    def __init__(self, sim: bool = True) -> None:
        self._sim = sim
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0  # Unix timestamp
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------ #
    # Connection
    # ------------------------------------------------------------------ #

    @property
    def connected(self) -> bool:
        return bool(self._access_token) and time.time() < self._token_expires_at

    @property
    def broker_name(self) -> str:
        return "tradestation_sim" if self._sim else "tradestation_live"

    @property
    def _api_url(self) -> str:
        return API_URL_SIM if self._sim else API_URL_LIVE

    def _require_env(self) -> tuple[str, str, str]:
        client_id = os.getenv("TS_CLIENT_ID", "").strip()
        client_secret = os.getenv("TS_CLIENT_SECRET", "").strip()
        refresh_token = os.getenv("TS_REFRESH_TOKEN", "").strip()
        if not (client_id and client_secret and refresh_token):
            raise BrokerConnectionError(
                "TS_CLIENT_ID / TS_CLIENT_SECRET / TS_REFRESH_TOKEN not set in .env"
            )
        return client_id, client_secret, refresh_token

    async def connect(self) -> bool:
        """Perform OAuth token refresh. Persists rotated refresh_token back
        to `.env` and `os.environ`."""
        try:
            client_id, client_secret, refresh_token = self._require_env()
        except BrokerConnectionError as e:
            logger.error("TradeStation connect failed: %s", e)
            return False

        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as ac:
                logger.debug("POST %s (refresh_token grant)", AUTH_URL)
                r = await ac.post(
                    AUTH_URL,
                    data={
                        "grant_type":    "refresh_token",
                        "client_id":     client_id,
                        "client_secret": client_secret,
                        "refresh_token": refresh_token,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            if r.status_code != 200:
                logger.error("Token refresh HTTP %s: %s", r.status_code, r.text[:400])
                return False
            body = r.json()
        except httpx.HTTPError as e:
            logger.error("Token refresh network error: %s", e)
            return False

        self._access_token = body["access_token"]
        expires_in = int(body.get("expires_in", 1200))
        self._token_expires_at = time.time() + expires_in

        new_refresh = body.get("refresh_token")
        if new_refresh and new_refresh != refresh_token:
            os.environ["TS_REFRESH_TOKEN"] = new_refresh
            try:
                set_key(str(ENV_FILE), "TS_REFRESH_TOKEN", new_refresh)
                logger.info("TS refresh token rotated and persisted to .env")
            except Exception as e:  # don't crash if .env is read-only
                logger.warning("Could not persist rotated refresh token: %s", e)

        self._client = httpx.AsyncClient(timeout=HTTP_TIMEOUT)
        logger.info("TradeStation connected (%s); token expires in %ds",
                    "sim" if self._sim else "live", expires_in)
        return True

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._access_token = None
        self._token_expires_at = 0.0

    async def _ensure_token(self) -> str:
        """Refresh proactively if we're within the expiry margin."""
        if not self._access_token or time.time() > self._token_expires_at - REFRESH_MARGIN_SECONDS:
            ok = await self.connect()
            if not ok:
                raise BrokerConnectionError("Could not refresh TradeStation token")
        return self._access_token  # type: ignore[return-value]

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        token = await self._ensure_token()
        headers = kwargs.pop("headers", {}) | {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        url = f"{self._api_url}{path}"
        logger.debug("%s %s", method, url)
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=HTTP_TIMEOUT)
        try:
            r = await self._client.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError as e:
            logger.error("%s %s network error: %s", method, url, e)
            raise BrokerConnectionError(str(e)) from e
        if r.status_code >= 400:
            logger.error("%s %s HTTP %s: %s", method, url, r.status_code, r.text[:400])
            raise BrokerConnectionError(f"{r.status_code} {r.text[:200]}")
        return r

    def _account_id(self) -> str:
        account_id = os.getenv("TS_ACCOUNT_ID", "").strip()
        if not account_id:
            raise BrokerConnectionError("TS_ACCOUNT_ID not set in .env")
        return account_id

    # ------------------------------------------------------------------ #
    # Account
    # ------------------------------------------------------------------ #

    async def get_account_state(self) -> AccountState:
        account_id = self._account_id()
        r_bal = await self._request("GET", f"/brokerage/accounts/{account_id}/balances")
        r_pos = await self._request("GET", f"/brokerage/accounts/{account_id}/positions")
        balances = r_bal.json().get("Balances", [])
        positions_raw = r_pos.json().get("Positions", [])
        bal = balances[0] if balances else {}

        positions: list[Position] = []
        for p in positions_raw:
            qty = int(float(p.get("Quantity", 0)))
            if p.get("LongShort", "").lower() == "short":
                qty = -qty
            positions.append(Position(
                symbol=p.get("Symbol", ""),
                shares=qty,
                avg_entry_price=float(p.get("AveragePrice", 0.0)),
                market_price=float(p.get("Last", 0.0)),
                unrealized_pnl_usd=float(p.get("UnrealizedProfitLoss", 0.0)),
            ))

        return AccountState(
            account_id=account_id,
            broker=self.broker_name,
            type="margin" if bal.get("AccountType", "").lower() == "margin" else "cash",
            equity=float(bal.get("Equity", 0.0)),
            cash=float(bal.get("CashBalance", 0.0)),
            buying_power=float(bal.get("BuyingPower", 0.0)),
            open_positions=positions,
            realized_pnl_today=float(bal.get("TodaysRealizedProfitLoss", 0.0)),
            unrealized_pnl_today=sum(p.unrealized_pnl_usd for p in positions),
            trades_today=0,  # TS doesn't return this directly; filled orders count added later
            day_trade_count_rolling_5d=int(bal.get("DayTrades", 0)),
            trading_halted=False,
            ts_snapshot=datetime.now(timezone.utc).isoformat(),
        )

    # ------------------------------------------------------------------ #
    # Market data
    # ------------------------------------------------------------------ #

    async def get_quote(self, symbol: str) -> Quote:
        r = await self._request("GET", f"/marketdata/quotes/{symbol}")
        body = r.json()
        q = body.get("Quotes", [{}])[0] if body.get("Quotes") else body
        return Quote(
            symbol=symbol,
            ts=q.get("TradeTime", datetime.now(timezone.utc).isoformat()),
            bid=float(q.get("Bid", 0.0)),
            ask=float(q.get("Ask", 0.0)),
            bid_size=int(float(q.get("BidSize", 0))),
            ask_size=int(float(q.get("AskSize", 0))),
        )

    # ------------------------------------------------------------------ #
    # Orders
    # ------------------------------------------------------------------ #

    def _build_order_payload(self, order: Order) -> dict:
        account_id = self._account_id()
        payload: dict[str, Any] = {
            "AccountID":    account_id,
            "Symbol":       order.symbol,
            "Quantity":     str(order.quantity),
            "OrderType":    _TYPE_TO_TS.get(order.order_type, "Market"),
            "TradeAction":  _SIDE_TO_TS.get(order.side, "BUY"),
            "TimeInForce":  {"Duration": _TIF_TO_TS.get(order.time_in_force, "DAY")},
            "Route":        "Intelligent",
        }
        if order.limit_price is not None:
            payload["LimitPrice"] = f"{order.limit_price:.4f}"
        if order.stop_price is not None:
            payload["StopPrice"] = f"{order.stop_price:.4f}"
        return payload

    async def place_order(self, order: Order) -> OrderAck:
        payload = self._build_order_payload(order)
        try:
            r = await self._request("POST", "/orderexecution/orders", json=payload)
        except BrokerConnectionError as e:
            return OrderAck(
                client_order_id=order.client_order_id,
                broker_order_id=None,
                accepted=False,
                ts=datetime.now(timezone.utc).isoformat(),
                reject_reason=str(e),
            )
        body = r.json()
        orders = body.get("Orders", [])
        if not orders:
            return OrderAck(
                client_order_id=order.client_order_id,
                broker_order_id=None,
                accepted=False,
                ts=datetime.now(timezone.utc).isoformat(),
                reject_reason=body.get("Errors", [{}])[0].get("Error", "unknown"),
            )
        ok = orders[0]
        return OrderAck(
            client_order_id=order.client_order_id,
            broker_order_id=ok.get("OrderID"),
            accepted=True,
            ts=datetime.now(timezone.utc).isoformat(),
        )

    async def modify_order(self, broker_order_id: str, changes: dict) -> OrderAck:
        account_id = self._account_id()
        try:
            await self._request(
                "PUT",
                f"/orderexecution/orders/{broker_order_id}",
                json={"AccountID": account_id, **changes},
            )
        except BrokerConnectionError as e:
            return OrderAck(client_order_id="", broker_order_id=broker_order_id,
                            accepted=False,
                            ts=datetime.now(timezone.utc).isoformat(),
                            reject_reason=str(e))
        return OrderAck(client_order_id="", broker_order_id=broker_order_id,
                        accepted=True, ts=datetime.now(timezone.utc).isoformat())

    async def cancel_order(self, broker_order_id: str) -> OrderAck:
        try:
            await self._request("DELETE", f"/orderexecution/orders/{broker_order_id}")
        except BrokerConnectionError as e:
            return OrderAck(client_order_id="", broker_order_id=broker_order_id,
                            accepted=False,
                            ts=datetime.now(timezone.utc).isoformat(),
                            reject_reason=str(e))
        return OrderAck(client_order_id="", broker_order_id=broker_order_id,
                        accepted=True, ts=datetime.now(timezone.utc).isoformat())

    async def cancel_all_orders(self) -> list[OrderAck]:
        """Used by HALT. Fetches open orders then cancels each."""
        account_id = self._account_id()
        try:
            r = await self._request("GET", f"/brokerage/accounts/{account_id}/orders")
        except BrokerConnectionError as e:
            logger.error("cancel_all_orders: could not list orders: %s", e)
            return []
        orders = r.json().get("Orders", [])
        acks: list[OrderAck] = []
        for o in orders:
            status = (o.get("StatusDescription") or "").lower()
            if status in ("filled", "cancelled", "canceled", "rejected", "expired"):
                continue
            order_id = o.get("OrderID")
            if not order_id:
                continue
            acks.append(await self.cancel_order(order_id))
        return acks

    # ------------------------------------------------------------------ #
    # Fills
    # ------------------------------------------------------------------ #

    async def get_fills(self, since_ts: str | None = None) -> list[Fill]:
        account_id = self._account_id()
        r = await self._request("GET", f"/brokerage/accounts/{account_id}/orders")
        fills: list[Fill] = []
        for o in r.json().get("Orders", []):
            if o.get("Status") != "FLL":
                continue
            ts = o.get("ClosedDateTime") or o.get("OpenedDateTime") or ""
            if since_ts and ts < since_ts:
                continue
            legs = o.get("Legs", [{}])
            leg = legs[0] if legs else {}
            fills.append(Fill(
                fill_id=o.get("OrderID", ""),
                broker_order_id=o.get("OrderID", ""),
                client_order_id="",
                symbol=leg.get("Symbol", ""),
                ts=ts,
                side=("buy" if leg.get("BuyOrSell", "").lower() == "buy" else "sell"),
                price=float(o.get("FilledPrice", 0.0)),
                shares=int(float(leg.get("ExecQuantity", 0))),
                commission_usd=float(o.get("CommissionFee", 0.0)),
            ))
        return fills
