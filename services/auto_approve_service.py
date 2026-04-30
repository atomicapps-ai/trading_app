"""auto_approve_service.py — per-strategy autonomous approval.

When a TradePlan arms in /pending, the operator normally has to click
Approve within the 15-minute approval window for the executioner to
place the order. For strategies that have been validated and the
operator trusts to run unattended (paper-only), this module lets that
auto-fire without human input.

Hard guardrails — auto-approve is REFUSED when ANY of these are true:
  - the strategy's auto_approve flag isn't set
  - the active broker account is account_type='live'
  - settings.app.mode == 'live'
  - settings.app.mode == 'research' (no broker, no real orders anyway)
  - TRADING_HALTED is set on broker_service

Flag storage piggybacks on user_widget_settings under widget_id
``__strategies__`` with key ``auto_approve.<strategy_name>``. Toggling
through the UI POSTs to /api/strategies/{name}/auto-approve which
also rebuilds the in-process snapshot.
"""
from __future__ import annotations

import logging

from services import widget_settings as ws

logger = logging.getLogger(__name__)

# Same widget id the strategies router uses for active/archived flags.
_STRATEGY_OVERRIDES_KEY = "__strategies__"


def _key(strategy_name: str) -> str:
    return f"auto_approve.{strategy_name}"


# --------------------------------------------------------------------------- #
# Read / write
# --------------------------------------------------------------------------- #


async def is_enabled(strategy_name: str) -> bool:
    val = await ws.get("default", _STRATEGY_OVERRIDES_KEY, _key(strategy_name))
    return bool(val)


async def set_enabled(strategy_name: str, enabled: bool) -> None:
    await ws.set_(
        "default", _STRATEGY_OVERRIDES_KEY, _key(strategy_name), bool(enabled),
    )
    logger.warning(
        "auto_approve toggled: strategy=%s enabled=%s", strategy_name, enabled,
    )


# --------------------------------------------------------------------------- #
# Safety check
# --------------------------------------------------------------------------- #


async def safe_to_auto_approve(strategy_name: str) -> tuple[bool, str]:
    """Return (allowed, reason). Used by pipeline_service to decide
    whether to dispatch the executioner without human input."""
    # 1. Strategy flag must be on
    if not await is_enabled(strategy_name):
        return False, "auto_approve disabled for this strategy"

    # 2. Mode must be paper. Live always requires manual ack (CLAUDE.md
    #    non-negotiable). Research has no broker.
    from services.settings_service import get_settings
    mode = get_settings().app.mode
    if mode == "live":
        return False, "live mode — manual approval required by policy"
    if mode == "research":
        return False, "research mode — no broker"

    # 3. Active account must be paper. Even if mode=paper, if the user
    #    pointed the active row at a live key pair we refuse.
    try:
        from services import account_service
        active = await account_service.get_active_account()
    except Exception as exc:                                          # noqa: BLE001
        return False, f"account lookup failed: {exc}"
    if active is None:
        return False, "no active broker account"
    if active.get("account_type") != "paper":
        return False, f"active account is {active.get('account_type')!r} — manual ack required"

    # 4. HALT must be off
    from services import broker_service
    if broker_service.TRADING_HALTED:
        return False, "trading is HALTED"

    return True, "ok"
