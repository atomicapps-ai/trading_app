"""broker_service.py — adapter factory and singleton access.

The active adapter is selected at startup based on `settings.app.mode`
and the `TS_SIM` environment variable. All other code that needs broker
access calls `get_adapter()` — never instantiates adapters directly.

Also owns the module-level `TRADING_HALTED` flag set by `/broker/halt`
and read by the executioner in Phase 5.
"""
from __future__ import annotations

import logging
import os

from brokers.base import BrokerAdapter
from brokers.historical import HistoricalAdapter
from brokers.tradestation import TradeStationAdapter
from services.settings_service import get_settings

logger = logging.getLogger(__name__)

_adapter: BrokerAdapter | None = None

# HALT flag — set True by POST /broker/halt; checked by executioner.
TRADING_HALTED: bool = False


def build_adapter() -> BrokerAdapter:
    s = get_settings()
    mode = s.app.mode
    if mode == "research":
        logger.info("Broker: using HistoricalAdapter (research mode)")
        return HistoricalAdapter()
    ts_sim = os.getenv("TS_SIM", "true").lower() == "true"
    label = "sim" if ts_sim else "live"
    logger.info("Broker: using TradeStationAdapter (%s)", label)
    return TradeStationAdapter(sim=ts_sim)


def get_adapter() -> BrokerAdapter:
    global _adapter
    if _adapter is None:
        _adapter = build_adapter()
    return _adapter


async def connect_adapter() -> bool:
    adapter = get_adapter()
    if adapter.connected:
        return True
    return await adapter.connect()


async def reset_adapter() -> None:
    """Force re-creation of the adapter (e.g. after mode change)."""
    global _adapter
    if _adapter is not None:
        try:
            await _adapter.disconnect()
        except Exception as e:
            logger.warning("disconnect raised during reset: %s", e)
    _adapter = None


def set_halted(value: bool) -> None:
    """Mutate the global HALT flag. Called by /broker/halt."""
    global TRADING_HALTED
    TRADING_HALTED = value
    logger.warning("TRADING_HALTED set to %s", value)
