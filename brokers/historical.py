"""HistoricalAdapter — research mode only.

Returns stub account state and stub quotes. Orders are simulated (accepted
immediately, no real fill). Fills are synthetic. In Phase 4 this will read
from the local OHLCV cache written by `scripts/download_history.py`; for
Phase 3 we only need the adapter contract to be honored so research-mode
agent code runs without error.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from brokers.base import BrokerAdapter
from models.account import AccountState, Fill, Order, OrderAck, Quote

logger = logging.getLogger(__name__)

STUB_EQUITY = 162_480.00


class HistoricalAdapter(BrokerAdapter):
    """Fake broker for research / backtesting."""

    def __init__(self) -> None:
        self._connected = False

    async def connect(self) -> bool:
        self._connected = True
        logger.info("HistoricalAdapter: connected (research mode)")
        return True

    async def disconnect(self) -> None:
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def broker_name(self) -> str:
        return "historical_research"

    async def get_account_state(self) -> AccountState:
        return AccountState(
            account_id="RESEARCH-001",
            broker=self.broker_name,
            type="cash",
            equity=STUB_EQUITY,
            cash=STUB_EQUITY,
            buying_power=STUB_EQUITY,
            realized_pnl_today=0.0,
            unrealized_pnl_today=0.0,
            trades_today=0,
            day_trade_count_rolling_5d=0,
            trading_halted=False,
            ts_snapshot=datetime.now(timezone.utc).isoformat(),
        )

    async def get_quote(self, symbol: str) -> Quote:
        # Stub — Phase 4 will read from OHLCV cache in data/historical/
        return Quote(
            symbol=symbol,
            ts=datetime.now(timezone.utc).isoformat(),
            bid=100.00,
            ask=100.05,
            bid_size=500,
            ask_size=500,
        )

    async def place_order(self, order: Order) -> OrderAck:
        ack_id = str(uuid4())
        logger.info(
            "HistoricalAdapter: simulated order %s %s %s",
            order.side, order.quantity, order.symbol,
        )
        return OrderAck(
            client_order_id=order.client_order_id,
            broker_order_id=ack_id,
            accepted=True,
            ts=datetime.now(timezone.utc).isoformat(),
        )

    async def modify_order(self, broker_order_id: str, changes: dict) -> OrderAck:
        return OrderAck(
            client_order_id="",
            broker_order_id=broker_order_id,
            accepted=True,
            ts=datetime.now(timezone.utc).isoformat(),
        )

    async def cancel_order(self, broker_order_id: str) -> OrderAck:
        return OrderAck(
            client_order_id="",
            broker_order_id=broker_order_id,
            accepted=True,
            ts=datetime.now(timezone.utc).isoformat(),
        )

    async def cancel_all_orders(self) -> list[OrderAck]:
        return []

    async def get_fills(self, since_ts: str | None = None) -> list[Fill]:
        return []
