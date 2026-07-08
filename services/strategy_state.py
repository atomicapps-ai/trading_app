"""strategy_state — shared resolver for a strategy's *effective* enabled state.

The `/strategies` UI toggle persists an override under the synthetic ``__strategies__``
widget-id (so the YAML + its comments aren't rewritten). The effective enabled flag is:
    override if set, else the config's ``active:`` value.

This module is the single source of truth so BOTH the UI (routers/strategies.py) and the
scheduler (services/scheduler.py) agree on whether a strategy should scan. Making the scheduler
consult this is what turns the UI Enable/Disable button into the real on-switch: a scheduled
workflow only runs when its strategy is effectively enabled — checked at fire-time, so no app
restart is needed to arm/disarm.
"""
from __future__ import annotations

import yaml

from services import widget_settings as ws
from services.settings_service import STRATEGY_CONFIG_DIR

_STRATEGY_OVERRIDES_KEY = "__strategies__"


async def get_effective_active(name: str) -> bool:
    """True if strategy ``name`` should scan: UI override if present, else YAML ``active:``."""
    saved = await ws.get("default", _STRATEGY_OVERRIDES_KEY, f"{name}.active")
    if saved is not None:
        return bool(saved)
    path = STRATEGY_CONFIG_DIR / f"{name}.yaml"
    if not path.exists():
        return False
    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return False
    return bool(cfg.get("active", False))


def workflow_strategies(wf: dict) -> list[str]:
    """Strategy names a workflow drives (from its analyze/plan step params)."""
    out: list[str] = []
    for step in wf.get("steps", []) or []:
        s = (step.get("params") or {}).get("strategy")
        if s and s not in out:
            out.append(s)
    return out
