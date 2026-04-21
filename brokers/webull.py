"""WebullAdapter — stub for v1.

Real implementation in a future phase when Webull API access is set up.
Every method raises NotImplementedError so the seam stays visible.
"""
from __future__ import annotations

from brokers.base import BrokerAdapter
from models.account import AccountState, Fill, Order, OrderAck, Quote


class WebullAdapter(BrokerAdapter):
    """Not implemented in v1. Raises NotImplementedError on all calls."""

    async def connect(self) -> bool:
        raise NotImplementedError("WebullAdapter not implemented in v1")

    async def disconnect(self) -> None:
        raise NotImplementedError("WebullAdapter not implemented in v1")

    @property
    def connected(self) -> bool:
        return False

    @property
    def broker_name(self) -> str:
        return "webull_stub"

    async def get_account_state(self) -> AccountState:
        raise NotImplementedError("WebullAdapter not implemented in v1")

    async def get_quote(self, symbol: str) -> Quote:
        raise NotImplementedError("WebullAdapter not implemented in v1")

    async def place_order(self, order: Order) -> OrderAck:
        raise NotImplementedError("WebullAdapter not implemented in v1")

    async def modify_order(self, broker_order_id: str, changes: dict) -> OrderAck:
        raise NotImplementedError("WebullAdapter not implemented in v1")

    async def cancel_order(self, broker_order_id: str) -> OrderAck:
        raise NotImplementedError("WebullAdapter not implemented in v1")

    async def cancel_all_orders(self) -> list[OrderAck]:
        raise NotImplementedError("WebullAdapter not implemented in v1")

    async def get_fills(self, since_ts: str | None = None) -> list[Fill]:
        raise NotImplementedError("WebullAdapter not implemented in v1")
