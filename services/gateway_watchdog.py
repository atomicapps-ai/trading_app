"""gateway_watchdog.py — proactively watch the broker connection and alert.

Unattended operation (traveling, away for days) needs the app to NOTICE when
the IBKR gateway drops. IBKR force-restarts the gateway daily, and it can die
for other reasons. The executioner already fails safe — it refuses to place an
order against a disconnected gateway (see executioner._reject "broker_disconnected")
— but nothing proactively told the operator, and reconnection only happened
lazily on the next order attempt or page load.

This module runs on a scheduler interval: it checks whether the active broker
adapter is really alive, tries to reconnect if not, and pushes an ntfy alert on
each state TRANSITION (healthy→down, down→recovered) so the operator can remotely
restart the gateway. It alerts only on transitions, not every tick, so a long
outage is one alert rather than a stream.

Research mode has no broker, so the watchdog no-ops there.
"""
from __future__ import annotations

import logging

from services import broker_service
from services.ntfy_service import push
from services.settings_service import get_settings

logger = logging.getLogger(__name__)

# How often the scheduler ticks this check.
CHECK_INTERVAL_MINUTES = 5

# Last known health, so we alert only on transitions. None = unknown (startup):
# we establish the baseline silently on the first tick so a fresh boot in a
# healthy state doesn't fire a spurious "reconnected" alert.
_last_healthy: bool | None = None


def _reset_state() -> None:
    """Test hook — forget the remembered health so the next tick re-baselines."""
    global _last_healthy
    _last_healthy = None


async def _is_alive(adapter) -> bool:
    """Best-effort liveness. ``connected`` can be a stale flag on a half-open
    socket, so when it claims connected we do one cheap real call (account
    state) and treat any exception as 'not alive'."""
    if not getattr(adapter, "connected", False):
        return False
    try:
        await adapter.get_account_state()
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("gateway_watchdog: liveness probe failed: %s", e)
        return False


def _broker_url() -> str | None:
    """Deep link to /broker in the alert, if a public base URL is configured
    (added with the web deployment). Falls back to no link."""
    s = get_settings()
    base = getattr(getattr(s, "app", None), "public_base_url", None)
    return base.rstrip("/") + "/broker" if base else None


async def check_gateway_health() -> dict:
    """One health tick. Reconnect if down; ntfy on transitions. Never raises."""
    global _last_healthy
    s = get_settings()
    if s.app.mode == "research":
        return {"mode": "research", "checked": False}

    try:
        adapter = await broker_service.get_adapter_async()
    except Exception as e:  # noqa: BLE001
        logger.warning("gateway_watchdog: get_adapter_async failed: %s", e)
        return {"checked": False, "error": str(e)}

    broker = getattr(adapter, "broker_name", "broker")
    healthy = await _is_alive(adapter)

    if not healthy:
        # Try to bring it back. A stale socket (connected flag true but the
        # probe failed) needs a clean rebuild before reconnecting.
        try:
            if getattr(adapter, "connected", False):
                await broker_service.reset_adapter()
            await broker_service.connect_adapter()
            adapter = await broker_service.get_adapter_async()
            healthy = await _is_alive(adapter)
        except Exception as e:  # noqa: BLE001
            logger.warning("gateway_watchdog: reconnect raised: %s", e)
            healthy = False

    # Alert only on transitions.
    if _last_healthy is None:
        _last_healthy = healthy  # silent baseline on first tick
    elif healthy != _last_healthy:
        if healthy:
            await push(
                f"✓ {broker} gateway reconnected",
                "The broker connection recovered — trading can resume.",
                priority="default", tags=["white_check_mark"],
                click_url=_broker_url(),
            )
            logger.info("gateway_watchdog: %s recovered", broker)
        else:
            await push(
                f"⚠ {broker} gateway DOWN",
                "The broker connection dropped and auto-reconnect failed. "
                "Orders are paused until it recovers — restart the gateway.",
                priority="high", tags=["warning"],
                click_url=_broker_url(),
            )
            logger.warning("gateway_watchdog: %s DOWN (reconnect failed)", broker)
        _last_healthy = healthy

    return {"checked": True, "healthy": healthy, "broker": broker}
