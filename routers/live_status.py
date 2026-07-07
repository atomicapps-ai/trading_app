"""live_status.py — persistent top-of-app totals bar.

Always-visible HTMX-polled strip above the topbar showing:
  - Account equity, cash, day P&L
  - Per-position mini-chips: symbol · direction · P&L (% or $) · TP / SL

Renders only symbols that have an open position. Refreshes every 5s.
A toggle button switches between % and $ for the per-position display
(persisted client-side in localStorage).

TP/SL extraction: when a position was opened via a bracket order, the
broker keeps the take-profit and stop-loss as live child orders for
that symbol. We fetch open orders once per refresh and match by symbol
to surface the bracket levels alongside the position.

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
    open_pnl_usd = 0.0
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
            # TRUE day P&L = equity − prior-close equity (realized + unrealized
            # booked today), via AccountState.day_pnl_usd. Falls back to
            # realized+unrealized for brokers that don't report last_equity.
            day_pnl_usd = float(state.day_pnl_usd or 0.0)
            # OPEN P&L = live unrealized across current open positions (the
            # "how much am I up right now" number, independent of the day).
            open_pnl_usd = float(state.unrealized_pnl_today or 0.0)

            # Pull the open-orders book once so we can hang TP/SL prices
            # off each position in a single broker call. Bracket orders
            # in Alpaca persist as separate take_profit / stop_loss orders
            # after the parent fills; matching them by symbol is enough
            # for one-position-per-symbol cases, which is the usual
            # state for this app.
            open_orders = await _open_orders_by_symbol(adapter)

            for p in state.open_positions:
                entry = float(p.avg_entry_price or 0.0)
                cur   = float(p.market_price or 0.0)
                shares = int(p.shares or 0)
                direction = "long" if shares >= 0 else "short"
                pct = ((cur - entry) / entry * 100.0) if entry else 0.0
                if direction == "short":
                    pct = -pct
                tp_price, sl_price = _extract_tp_sl(
                    open_orders.get(p.symbol, []),
                    direction=direction,
                )
                positions.append({
                    "symbol":     p.symbol,
                    "shares":     abs(shares),
                    "direction":  direction,
                    "entry":      entry,
                    "current":    cur,
                    "pnl_usd":    float(p.unrealized_pnl_usd or 0.0),
                    "pnl_pct":    pct,
                    "tp_price":   tp_price,
                    "sl_price":   sl_price,
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
    open_pnl_pct = (open_pnl_usd / equity * 100.0) if equity else 0.0

    return templates.TemplateResponse(
        request=request,
        name="_partials/_live_status_bar.html",
        context={
            "error":        error,
            "equity":       equity,
            "cash":         cash,
            "day_pnl_usd":  day_pnl_usd,
            "day_pnl_pct":  day_pnl_pct,
            "open_pnl_usd": open_pnl_usd,
            "open_pnl_pct": open_pnl_pct,
            "positions":    positions,
        },
    )


# --------------------------------------------------------------------------- #
# Bracket order helpers
# --------------------------------------------------------------------------- #


async def _open_orders_by_symbol(adapter) -> dict[str, list]:
    """Return open orders grouped by symbol. Best-effort: any error
    yields an empty dict (the live bar still renders, just without
    TP/SL price tags)."""
    try:
        # Only AlpacaAdapter has the underlying trading client we
        # need. TradeStation / historical lack the introspection.
        tc = getattr(adapter, "_trading_client", None)
        if tc is None:
            return {}
        import asyncio as _asyncio
        orders = await _asyncio.to_thread(tc.get_orders)
    except Exception as exc:                                          # noqa: BLE001
        logger.debug("live_status: open-orders fetch failed: %s", exc)
        return {}

    out: dict[str, list] = {}
    for o in orders or []:
        sym = getattr(o, "symbol", None)
        if not sym:
            continue
        out.setdefault(sym, []).append(o)
    return out


def _extract_tp_sl(
    orders: list, *, direction: str,
) -> tuple[float | None, float | None]:
    """Pull take-profit + stop-loss prices out of the open orders for a
    single symbol. Bracket order children are typed: take-profit is a
    LIMIT on the closing side; stop-loss is a STOP / STOP_LIMIT on
    the same side. We pick whichever pair matches direction.

    Returns (tp_price, sl_price). Either may be None if not bracketed.
    """
    tp_price = None
    sl_price = None
    closing_side = "sell" if direction == "long" else "buy"
    for o in orders:
        side = str(getattr(o, "side", "")).lower()
        if "sell" in side and direction == "long":
            pass
        elif "buy" in side and direction == "short":
            pass
        else:
            # Same-side pending — that's the unfilled parent of a new
            # order, not a bracket child. Skip.
            continue

        otype = str(getattr(o, "order_type", "")).lower()
        # alpaca-py exposes order_type as the OrderType enum string
        if "limit" in otype and "stop" not in otype:
            try:
                tp_price = float(getattr(o, "limit_price", None) or 0) or tp_price
            except (TypeError, ValueError):
                pass
        elif "stop" in otype:
            try:
                sl_price = (
                    float(getattr(o, "stop_price", None) or 0)
                    or float(getattr(o, "limit_price", None) or 0)
                    or sl_price
                )
            except (TypeError, ValueError):
                pass
    return tp_price, sl_price
