"""live_status.py — persistent top-of-app totals bar.

Always-visible HTMX-polled strip above the topbar showing:
  - Account equity, cash, day P&L
  - Per-position mini-chips: symbol · current price · P&L (% or $)

Renders only symbols that have an open position. Refreshes every 5s.
A toggle button switches between % and $ for the per-position display
(persisted client-side in localStorage).

Routes:
    GET /api/live-status   → HTML partial (HTMX target)
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from services.settings_service import TEMPLATES_DIR

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/api/live-status", response_class=HTMLResponse)
async def live_status(request: Request):
    """Build the live-totals strip from the active broker adapter.

    Errors are caught and rendered as a small "broker offline" placeholder
    so a flaky connection doesn't break the rest of the app's chrome.
    """
    equity = None
    cash = None
    day_pnl_usd = 0.0
    positions: list[dict] = []
    error: str | None = None

    try:
        from services import broker_service
        adapter = await broker_service.get_adapter_async()
        if not adapter.connected:
            await adapter.connect()
        if not adapter.connected:
            error = "broker not connected"
        else:
            state = await adapter.get_account_state()
            equity = float(state.equity or 0.0)
            cash   = float(state.cash or 0.0)
            day_pnl_usd = float(state.unrealized_pnl_today or 0.0)
            for p in state.open_positions:
                entry = float(p.avg_entry_price or 0.0)
                cur   = float(p.market_price or 0.0)
                shares = int(p.shares or 0)
                direction = "long" if shares >= 0 else "short"
                pct = ((cur - entry) / entry * 100.0) if entry else 0.0
                if direction == "short":
                    pct = -pct
                positions.append({
                    "symbol":     p.symbol,
                    "shares":     abs(shares),
                    "direction":  direction,
                    "entry":      entry,
                    "current":    cur,
                    "pnl_usd":    float(p.unrealized_pnl_usd or 0.0),
                    "pnl_pct":    pct,
                })
    except Exception as exc:                                          # noqa: BLE001
        logger.warning("live_status: broker fetch failed: %s", exc)
        error = f"{type(exc).__name__}: {exc}"

    # Sort positions by abs P&L descending so the loudest ones show first.
    positions.sort(key=lambda p: abs(p.get("pnl_usd", 0.0)), reverse=True)

    # Day P&L %: the unrealized component as a fraction of equity. Not the
    # same as Alpaca's true daily P&L (which separates realized and prior
    # equity from unrealized) — we'll improve once Phase 6 trade journal
    # derivations land. For now this is a meaningful proxy.
    day_pnl_pct = (day_pnl_usd / equity * 100.0) if equity else 0.0

    return templates.TemplateResponse(
        request=request,
        name="_partials/_live_status_bar.html",
        context={
            "error":        error,
            "equity":       equity,
            "cash":         cash,
            "day_pnl_usd":  day_pnl_usd,
            "day_pnl_pct":  day_pnl_pct,
            "positions":    positions,
        },
    )
