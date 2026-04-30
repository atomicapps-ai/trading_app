"""AlpacaAdapter — paper + live broker via Alpaca Trading API.

Why Alpaca instead of TradeStation for paper mode
-------------------------------------------------
TradeStation gates API access behind a $10,000 funded account (even for
the simulator). Alpaca gives paper-trading API access at zero minimum,
zero funding, same day. The paper endpoint returns real-looking responses
for accounts, positions, quotes, and orders — switching to live is a
single env-var flip.

Authentication
--------------
Simpler than TradeStation: just an API key + secret pair. No OAuth dance,
no refresh rotation. Keys come from ``.env`` in this order:

    ALPACA_TRADING_KEY_ID / ALPACA_TRADING_SECRET   — optional, used if set
    ALPACA_API_KEY        / ALPACA_API_SECRET       — fallback (the pair
                                                      Alpaca issues on signup)

On Alpaca's side, one key pair works for Trading + Market Data + News —
there's no need for two pairs. The TRADING_* vars exist only for users
who have multiple Alpaca accounts and want to segregate execution keys
from data keys.

    ALPACA_PAPER   — "true" (default) for paper-api.alpaca.markets/v2
                     "false" to route to api.alpaca.markets/v2 (LIVE)

SDK
---
``alpaca-py`` (already in requirements.txt for the news service). The
trading client is synchronous; we wrap calls in ``asyncio.to_thread``
so the FastAPI event loop stays unblocked.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from brokers.base import BrokerAdapter, BrokerConnectionError
from models.account import AccountState, Fill, Order, OrderAck, Position, Quote

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Enum translation — our model's string enums -> alpaca-py enums.
# Imports are deferred to runtime so module import succeeds even if the user
# hasn't installed alpaca-py yet (parity with TradeStation adapter style).
# --------------------------------------------------------------------------- #


def _alpaca_side(side: str):
    from alpaca.trading.enums import OrderSide
    mapping = {
        "buy": OrderSide.BUY,
        "buy_to_cover": OrderSide.BUY,   # Alpaca handles shorts transparently
        "sell": OrderSide.SELL,
        "sell_short": OrderSide.SELL,
    }
    if side not in mapping:
        raise ValueError(f"unsupported order side for Alpaca: {side!r}")
    return mapping[side]


def _alpaca_tif(tif: str):
    from alpaca.trading.enums import TimeInForce
    mapping = {
        "day": TimeInForce.DAY,
        "gtc": TimeInForce.GTC,
        "ioc": TimeInForce.IOC,
        "fok": TimeInForce.FOK,
    }
    if tif not in mapping:
        raise ValueError(f"unsupported TIF for Alpaca: {tif!r}")
    return mapping[tif]


def _build_order_request(order: Order):
    """Translate our ``Order`` model into the matching alpaca-py request."""
    from alpaca.trading.requests import (
        LimitOrderRequest,
        MarketOrderRequest,
        StopLimitOrderRequest,
        StopOrderRequest,
    )
    kwargs: dict[str, Any] = {
        "symbol": order.symbol,
        "qty": order.quantity,
        "side": _alpaca_side(order.side),
        "time_in_force": _alpaca_tif(order.time_in_force),
        "client_order_id": order.client_order_id,
        "extended_hours": order.extended_hours,
    }
    t = order.order_type
    if t == "market":
        return MarketOrderRequest(**kwargs)
    if t == "limit":
        if order.limit_price is None:
            raise ValueError("limit order requires limit_price")
        return LimitOrderRequest(limit_price=order.limit_price, **kwargs)
    if t == "stop":
        if order.stop_price is None:
            raise ValueError("stop order requires stop_price")
        return StopOrderRequest(stop_price=order.stop_price, **kwargs)
    if t == "stop_limit":
        if order.stop_price is None or order.limit_price is None:
            raise ValueError("stop_limit order requires stop_price + limit_price")
        return StopLimitOrderRequest(
            stop_price=order.stop_price,
            limit_price=order.limit_price,
            **kwargs,
        )
    # Algo types (vwap/twap/pov) — Alpaca doesn't support these natively; the
    # executioner may downgrade to a plain limit/market and drive the algo
    # itself. For now, reject cleanly so callers can pick an alternative.
    raise ValueError(f"order type {t!r} not supported by Alpaca native routing")


# --------------------------------------------------------------------------- #
# Adapter
# --------------------------------------------------------------------------- #


class AlpacaAdapter(BrokerAdapter):
    """Alpaca paper (default) or live adapter."""

    def __init__(
        self,
        paper: bool = True,
        *,
        key_id: str | None = None,
        secret: str | None = None,
        label: str | None = None,
    ) -> None:
        """Construct the adapter.

        Credentials precedence:
            1. ``key_id`` + ``secret`` kwargs (passed by ``broker_service``
               from the active ``broker_accounts`` row)
            2. ``ALPACA_TRADING_KEY_ID`` / ``ALPACA_TRADING_SECRET`` env
            3. ``ALPACA_API_KEY`` / ``ALPACA_API_SECRET`` env
        """
        self._paper = paper
        self._explicit_key_id = key_id
        self._explicit_secret = secret
        self._label = label
        self._trading_client = None  # alpaca.trading.client.TradingClient
        self._data_client = None  # alpaca.data.historical.stock.StockHistoricalDataClient
        self._account_id: str | None = None
        self._connected: bool = False

    # ── Connection ──────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def broker_name(self) -> str:
        if self._label:
            return self._label
        return "alpaca_paper" if self._paper else "alpaca_live"

    async def connect(self) -> bool:
        key_id = (
            self._explicit_key_id
            or os.getenv("ALPACA_TRADING_KEY_ID")
            or os.getenv("ALPACA_API_KEY")
        )
        secret = (
            self._explicit_secret
            or os.getenv("ALPACA_TRADING_SECRET")
            or os.getenv("ALPACA_API_SECRET")
        )
        if not key_id or not secret:
            logger.error(
                "Alpaca connect failed: no credentials. Add an account on "
                "/broker or set ALPACA_API_KEY + ALPACA_API_SECRET in .env."
            )
            return False

        # Import inside the method so missing alpaca-py doesn't break import.
        try:
            from alpaca.data.historical.stock import StockHistoricalDataClient
            from alpaca.trading.client import TradingClient
        except ImportError as e:
            logger.error("alpaca-py not installed: %s", e)
            return False

        def _connect_sync():
            tc = TradingClient(api_key=key_id, secret_key=secret, paper=self._paper)
            account = tc.get_account()
            dc = StockHistoricalDataClient(api_key=key_id, secret_key=secret)
            return tc, dc, str(account.id)

        try:
            self._trading_client, self._data_client, self._account_id = (
                await asyncio.to_thread(_connect_sync)
            )
        except Exception as e:  # noqa: BLE001
            logger.error("Alpaca connect failed: %s", e)
            return False

        self._connected = True
        logger.info(
            "Alpaca connected (%s) account_id=%s",
            "paper" if self._paper else "LIVE",
            self._account_id,
        )
        return True

    async def disconnect(self) -> None:
        self._trading_client = None
        self._data_client = None
        self._connected = False

    # ── Account ─────────────────────────────────────────────────────

    async def get_account_state(self) -> AccountState:
        if not self._connected or self._trading_client is None:
            raise BrokerConnectionError("Alpaca not connected")

        def _fetch_sync():
            acct = self._trading_client.get_account()
            positions = self._trading_client.get_all_positions()
            return acct, positions

        try:
            acct, raw_positions = await asyncio.to_thread(_fetch_sync)
        except Exception as e:  # noqa: BLE001
            raise BrokerConnectionError(f"Alpaca get_account_state failed: {e}")

        positions = [_position_from_alpaca(p) for p in raw_positions]

        # Wash-sale tracking: Alpaca doesn't expose this directly. Populated
        # by the executioner in Phase 6 based on the trade log. Leave [].
        return AccountState(
            account_id=str(acct.id),
            broker=self.broker_name,
            type="margin" if getattr(acct, "multiplier", 1) and float(acct.multiplier) > 1 else "cash",
            equity=float(acct.equity or 0),
            cash=float(acct.cash or 0),
            buying_power=float(acct.buying_power or 0),
            open_positions=positions,
            realized_pnl_today=0.0,  # Alpaca computes on their side; derive in Phase 6
            unrealized_pnl_today=sum(p.unrealized_pnl_usd for p in positions),
            trades_today=int(getattr(acct, "daytrade_count", 0) or 0),
            day_trade_count_rolling_5d=int(getattr(acct, "daytrade_count", 0) or 0),
            wash_sale_window=[],
            trading_halted=bool(getattr(acct, "trading_blocked", False)),
            ts_snapshot=datetime.now(timezone.utc).isoformat(),
        )

    # ── Market data ─────────────────────────────────────────────────

    async def get_quote(self, symbol: str) -> Quote:
        if not self._connected or self._data_client is None:
            raise BrokerConnectionError("Alpaca not connected")
        from alpaca.data.requests import StockLatestQuoteRequest

        def _fetch_sync():
            req = StockLatestQuoteRequest(symbol_or_symbols=[symbol])
            result = self._data_client.get_stock_latest_quote(req)
            return result.get(symbol)

        try:
            q = await asyncio.to_thread(_fetch_sync)
        except Exception as e:  # noqa: BLE001
            raise BrokerConnectionError(f"Alpaca get_quote {symbol} failed: {e}")
        if q is None:
            raise BrokerConnectionError(f"no quote for {symbol}")

        ts = q.timestamp.isoformat() if hasattr(q, "timestamp") else datetime.now(timezone.utc).isoformat()
        return Quote(
            symbol=symbol,
            ts=ts,
            bid=float(q.bid_price or 0),
            ask=float(q.ask_price or 0),
            bid_size=int(q.bid_size or 0),
            ask_size=int(q.ask_size or 0),
        )

    # ── Orders ──────────────────────────────────────────────────────

    async def place_order(self, order: Order) -> OrderAck:
        if not self._connected or self._trading_client is None:
            raise BrokerConnectionError("Alpaca not connected")

        try:
            req = _build_order_request(order)
        except ValueError as e:
            return OrderAck(
                client_order_id=order.client_order_id,
                broker_order_id=None,
                accepted=False,
                ts=datetime.now(timezone.utc).isoformat(),
                reject_reason=str(e),
            )

        def _submit_sync():
            return self._trading_client.submit_order(order_data=req)

        try:
            placed = await asyncio.to_thread(_submit_sync)
        except Exception as e:  # noqa: BLE001
            logger.error("Alpaca place_order rejected: %s", e)
            return OrderAck(
                client_order_id=order.client_order_id,
                broker_order_id=None,
                accepted=False,
                ts=datetime.now(timezone.utc).isoformat(),
                reject_reason=str(e),
            )

        return OrderAck(
            client_order_id=order.client_order_id,
            broker_order_id=str(placed.id),
            accepted=True,
            ts=datetime.now(timezone.utc).isoformat(),
        )

    async def modify_order(self, broker_order_id: str, changes: dict) -> OrderAck:
        if not self._connected or self._trading_client is None:
            raise BrokerConnectionError("Alpaca not connected")
        from alpaca.trading.requests import ReplaceOrderRequest

        req_kwargs: dict[str, Any] = {}
        if "qty" in changes:
            req_kwargs["qty"] = int(changes["qty"])
        if "limit_price" in changes:
            req_kwargs["limit_price"] = float(changes["limit_price"])
        if "stop_price" in changes:
            req_kwargs["stop_price"] = float(changes["stop_price"])
        if "time_in_force" in changes:
            req_kwargs["time_in_force"] = _alpaca_tif(changes["time_in_force"])
        replacement = ReplaceOrderRequest(**req_kwargs) if req_kwargs else None

        def _replace_sync():
            return self._trading_client.replace_order_by_id(
                order_id=broker_order_id, order_data=replacement,
            )

        try:
            replaced = await asyncio.to_thread(_replace_sync)
        except Exception as e:  # noqa: BLE001
            return OrderAck(
                client_order_id=str(uuid4()),
                broker_order_id=broker_order_id,
                accepted=False,
                ts=datetime.now(timezone.utc).isoformat(),
                reject_reason=f"modify failed: {e}",
            )
        return OrderAck(
            client_order_id=str(getattr(replaced, "client_order_id", "") or uuid4()),
            broker_order_id=str(replaced.id),
            accepted=True,
            ts=datetime.now(timezone.utc).isoformat(),
        )

    async def cancel_order(self, broker_order_id: str) -> OrderAck:
        if not self._connected or self._trading_client is None:
            raise BrokerConnectionError("Alpaca not connected")

        def _cancel_sync():
            self._trading_client.cancel_order_by_id(order_id=broker_order_id)
            return True

        try:
            await asyncio.to_thread(_cancel_sync)
        except Exception as e:  # noqa: BLE001
            return OrderAck(
                client_order_id="",
                broker_order_id=broker_order_id,
                accepted=False,
                ts=datetime.now(timezone.utc).isoformat(),
                reject_reason=f"cancel failed: {e}",
            )
        return OrderAck(
            client_order_id="",
            broker_order_id=broker_order_id,
            accepted=True,
            ts=datetime.now(timezone.utc).isoformat(),
        )

    async def cancel_all_orders(self) -> list[OrderAck]:
        if not self._connected or self._trading_client is None:
            raise BrokerConnectionError("Alpaca not connected")

        def _cancel_all_sync():
            return self._trading_client.cancel_orders()

        try:
            responses = await asyncio.to_thread(_cancel_all_sync)
        except Exception as e:  # noqa: BLE001
            logger.error("Alpaca cancel_all_orders failed: %s", e)
            return []

        ts = datetime.now(timezone.utc).isoformat()
        return [
            OrderAck(
                client_order_id="",
                broker_order_id=str(r.id),
                accepted=r.status == 200,
                ts=ts,
                reject_reason=None if r.status == 200 else f"status={r.status}",
            )
            for r in responses
        ]

    # ── Fills ───────────────────────────────────────────────────────

    async def get_fills(self, since_ts: str | None = None) -> list[Fill]:
        if not self._connected or self._trading_client is None:
            raise BrokerConnectionError("Alpaca not connected")
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        after_dt = None
        if since_ts:
            try:
                after_dt = datetime.fromisoformat(since_ts.replace("Z", "+00:00"))
            except ValueError:
                after_dt = None

        req = GetOrdersRequest(status=QueryOrderStatus.CLOSED, after=after_dt)

        def _fetch_sync():
            return self._trading_client.get_orders(filter=req)

        try:
            orders = await asyncio.to_thread(_fetch_sync)
        except Exception as e:  # noqa: BLE001
            logger.error("Alpaca get_fills failed: %s", e)
            return []

        fills: list[Fill] = []
        for o in orders:
            if not getattr(o, "filled_at", None):
                continue
            avg_price = float(getattr(o, "filled_avg_price", 0) or 0)
            filled_qty = int(float(getattr(o, "filled_qty", 0) or 0))
            if filled_qty <= 0:
                continue
            fills.append(Fill(
                fill_id=str(o.id),
                broker_order_id=str(o.id),
                client_order_id=str(getattr(o, "client_order_id", "") or ""),
                symbol=o.symbol,
                ts=o.filled_at.isoformat(),
                side="buy" if str(o.side).lower().endswith("buy") else "sell",
                price=avg_price,
                shares=filled_qty,
                commission_usd=0.0,  # Alpaca commission-free on equities
                fees_usd=0.0,
            ))
        return fills


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _position_from_alpaca(p: Any) -> Position:
    qty = int(float(p.qty))
    return Position(
        symbol=p.symbol,
        shares=qty,
        avg_entry_price=float(p.avg_entry_price or 0),
        market_price=float(getattr(p, "current_price", 0) or 0),
        unrealized_pnl_usd=float(getattr(p, "unrealized_pl", 0) or 0),
        sector=None,  # Alpaca doesn't return sector — we enrich elsewhere
    )
