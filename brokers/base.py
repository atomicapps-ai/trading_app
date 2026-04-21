"""BrokerAdapter — the seam between executioner and any broker.

CLAUDE.md rule: executioner.py calls ONLY these methods. It never imports
a concrete adapter directly. Mode determines which adapter is injected at
startup (research → Historical, paper → TradeStation sim, live → TradeStation
live) via `services.broker_service.get_adapter()`.

Every method is async so adapters can do real I/O without blocking the
FastAPI event loop. `connected` and `broker_name` are sync properties —
callers expect cheap synchronous reads for status / UI.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from models.account import AccountState, Fill, Order, OrderAck, Quote


class BrokerConnectionError(Exception):
    """Network / auth failure when talking to the broker. Routers surface
    this as connected=false rather than crashing the app."""


class BrokerAdapter(ABC):
    """Interface every broker adapter must implement."""

    # ── Connection ──────────────────────────────────────────────────
    @abstractmethod
    async def connect(self) -> bool:
        """Open connection / authenticate. Returns True on success."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully close connection."""

    @property
    @abstractmethod
    def connected(self) -> bool:
        """True if connection is live and authenticated."""

    @property
    @abstractmethod
    def broker_name(self) -> str:
        """Human-readable name. e.g. 'tradestation_sim'."""

    # ── Account ─────────────────────────────────────────────────────
    @abstractmethod
    async def get_account_state(self) -> AccountState:
        """Return current account snapshot."""

    # ── Market data ─────────────────────────────────────────────────
    @abstractmethod
    async def get_quote(self, symbol: str) -> Quote:
        """Return current NBBO quote for symbol."""

    # ── Orders ──────────────────────────────────────────────────────
    @abstractmethod
    async def place_order(self, order: Order) -> OrderAck:
        """Submit an order. Returns ack (accepted or rejected)."""

    @abstractmethod
    async def modify_order(self, broker_order_id: str, changes: dict) -> OrderAck:
        """Modify a live order."""

    @abstractmethod
    async def cancel_order(self, broker_order_id: str) -> OrderAck:
        """Cancel a live order."""

    @abstractmethod
    async def cancel_all_orders(self) -> list[OrderAck]:
        """Cancel every open order. Used by HALT."""

    # ── Fills ───────────────────────────────────────────────────────
    @abstractmethod
    async def get_fills(self, since_ts: str | None = None) -> list[Fill]:
        """Return fills since `since_ts` (ISO8601). None = today."""
