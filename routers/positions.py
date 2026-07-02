"""positions.py — operator actions on broker positions.

Two actions exposed here:

    POST /api/positions/{symbol}/close          → flatten via market order
    POST /api/positions/{symbol}/take-profit    → flatten via market order
                                                  but recorded as a deliberate
                                                  profit-taking action (different
                                                  alert kind, separate audit)

Both bypass the full agent pipeline (no compliance / risk gates) because
the user has explicitly asked to act on an existing position — not open
a new one. Both refuse in research mode and when TRADING_HALTED is set.

Each action records an alert (``manual_close`` or ``manual_take_profit``)
which fires an ntfy phone push automatically via alert_service. Live
mode requires the enhanced-live-safeguards confirmation client-side
before the request even reaches here.

Why direct broker access (not via the executioner): the executioner
expects a TradePlan, which only exists for positions that came through
the agent pipeline. Manual / smoke-script positions (like the leftover
SPY 1-share from the order roundtrip smoke) have no plan. The close
path needs to work for those too.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from models.account import Order
from services import broker_service
from services.settings_service import TEMPLATES_DIR, get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


async def _flatten_position(symbol: str, *, intent: str) -> dict:
    """Shared close logic. ``intent`` is "close" or "take_profit"; it
    drives the alert kind and the log line — broker order is identical."""
    symbol = symbol.upper().strip()

    # Refuse in research mode — no real broker means no real close.
    s = get_settings()
    if s.app.mode == "research":
        raise HTTPException(
            status_code=400,
            detail="research mode: no broker, cannot close positions",
        )
    if broker_service.TRADING_HALTED:
        raise HTTPException(
            status_code=400,
            detail="trading is HALTED — un-halt before closing positions",
        )

    adapter = broker_service.get_adapter()
    if not adapter.connected:
        await adapter.connect()
    if not adapter.connected:
        raise HTTPException(status_code=503, detail="broker not connected")

    # Find the position
    state = await adapter.get_account_state()
    pos = next((p for p in state.open_positions if p.symbol.upper() == symbol), None)
    if pos is None or pos.shares == 0:
        raise HTTPException(status_code=404, detail=f"no open position in {symbol}")

    # Determine close side. Long positions sell; short positions buy.
    qty = abs(int(pos.shares))
    close_side = "sell" if pos.shares > 0 else "buy"
    order = Order(
        client_order_id=f"close-{symbol.lower()}-{uuid4().hex[:8]}",
        symbol=symbol,
        side=close_side,        # type: ignore[arg-type]
        order_type="market",
        quantity=qty,
        time_in_force="day",
    )

    try:
        ack = await adapter.place_order(order)
    except Exception as exc:                                          # noqa: BLE001
        logger.exception("close_position: place_order raised")
        raise HTTPException(status_code=502, detail=str(exc))

    if not ack.accepted:
        return JSONResponse(
            status_code=502,
            content={
                "ok": False,
                "symbol": symbol,
                "reject_reason": ack.reject_reason or "broker rejected order",
            },
        )

    logger.warning(
        "Position %s requested | symbol=%s shares=%d side=%s "
        "broker_order_id=%s ts=%s",
        intent, symbol, qty, close_side, ack.broker_order_id,
        datetime.now(timezone.utc).isoformat(),
    )

    # Record alert + fire ntfy push. alert_service.record_alert handles
    # both. We use distinct alert kinds so the dashboard banner can
    # color-code intent and the audit trail is clean.
    try:
        from services import alert_service
        # Compute current P&L for richer alert body (best-effort)
        entry = float(getattr(pos, "avg_entry_price", 0) or 0)
        market = float(getattr(pos, "market_price", 0) or 0)
        pnl_per_share = (market - entry) * (1 if pos.shares > 0 else -1)
        pnl_total = pnl_per_share * qty
        kind = "closed" if intent == "close" else "manual_take_profit"
        title = (
            f"{symbol} {('LONG' if pos.shares > 0 else 'SHORT')} "
            f"{('CLOSED' if intent == 'close' else 'TP')} — "
            f"{qty} sh @ market"
        )
        body = (
            f"Manual {intent.replace('_', ' ')} via dashboard. "
            f"Entry ${entry:.2f} -> Mkt ${market:.2f} "
            f"(unrealized {('+' if pnl_total >= 0 else '')}{pnl_total:.2f}). "
            f"Order id: {ack.broker_order_id or 'pending'}."
        )
        await alert_service.record_alert(
            kind=kind, strategy="manual", symbol=symbol,
            direction="long" if pos.shares > 0 else "short",
            plan_id=None, title=title, body=body,
            payload={
                "intent": intent,
                "shares": qty,
                "entry_price": entry,
                "market_price": market,
                "broker_order_id": ack.broker_order_id,
                "estimated_pnl_usd": round(pnl_total, 2),
            },
        )
    except Exception as exc:                                          # noqa: BLE001
        logger.warning("alert recording for %s failed: %s", intent, exc)

    return {
        "ok": True,
        "symbol": symbol,
        "shares_closed": qty,
        "side": close_side,
        "broker_order_id": ack.broker_order_id,
        "intent": intent,
    }


@router.get("/positions/{symbol}")
async def position_detail(symbol: str, request: Request):
    """Detail page for a broker position that has no linked TradePlan.

    Positions opened through the agent pipeline route straight to
    ``/trades/{plan_id}`` (the full plan view). This page is the landing
    spot for *orphan* positions — manual buys, smoke-script leftovers, or
    broker-side fills — so the operator isn't left staring at a row that
    can't be opened. If a plan for this symbol turns up after all, we
    redirect to the richer trade-detail page.

    It shows what the broker actually knows (entry, qty, market, unrealized
    P&L), states plainly that there's no strategy/stop/TP attached, and
    exposes Close / Take-profit so the operator can act on it.
    """
    symbol = symbol.upper().strip()
    s = get_settings()

    # If a plan exists for this symbol in ANY status, prefer the full
    # trade-detail page (which carries strategy / stop / TP / thesis).
    try:
        from services import db_service
        latest = await db_service.get_latest_plan_for_symbol(symbol)
        if latest and latest.get("plan_id"):
            return RedirectResponse(url=f"/trades/{latest['plan_id']}", status_code=307)
    except Exception as e:                                             # noqa: BLE001
        logger.warning("position_detail: plan lookup failed for %s: %s", symbol, e)

    # No plan — fetch the raw broker position + recover the entry time from
    # the broker's fill history so Entered/Held aren't blank.
    pos_data: dict | None = None
    fetch_error: str | None = None
    if s.app.mode == "research":
        fetch_error = "research mode — no live broker positions"
    else:
        try:
            adapter = broker_service.get_adapter()
            if not adapter.connected:
                await adapter.connect()
            state = await adapter.get_account_state()
            p = next((x for x in state.open_positions
                      if x.symbol.upper() == symbol), None)
            if p is not None:
                shares = int(p.shares or 0)
                entry = float(p.avg_entry_price or 0.0)
                current = float(p.market_price or 0.0)
                direction = "long" if shares >= 0 else "short"
                pnl_pct = ((current - entry) / entry * 100.0) if entry else 0.0
                if direction == "short":
                    pnl_pct = -pnl_pct

                # Entry timestamp from the most-recent buy fill (best-effort).
                entry_ts = None
                try:
                    fills = await adapter.get_fills()
                    buys = [f for f in fills
                            if str(getattr(f, "symbol", "")).upper() == symbol
                            and str(getattr(f, "side", "")).lower() == "buy"
                            and getattr(f, "ts", None)]
                    if buys:
                        entry_ts = max(f.ts for f in buys)
                except Exception:                                     # noqa: BLE001
                    pass

                from services.dashboard_widgets import _humanize_since
                pos_data = {
                    "symbol": p.symbol,
                    "direction": direction,
                    "shares": abs(shares),
                    "entry": entry,
                    "current": current,
                    "pnl_usd": float(p.unrealized_pnl_usd or 0.0),
                    "pnl_pct": pnl_pct,
                    "sector": p.sector or "",
                    "entry_ts": entry_ts,
                    "held": _humanize_since(entry_ts) if entry_ts else "—",
                }
        except Exception as e:                                        # noqa: BLE001
            fetch_error = str(e)
            logger.warning("position_detail: broker fetch failed for %s: %s", symbol, e)

    return templates.TemplateResponse(
        request=request,
        name="positions/detail.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "dashboard",
            "symbol": symbol,
            "position": pos_data,
            "fetch_error": fetch_error,
        },
    )


@router.post("/api/positions/{symbol}/close", response_class=JSONResponse)
async def close_position(symbol: str):
    return await _flatten_position(symbol, intent="close")


@router.post("/api/positions/{symbol}/take-profit", response_class=JSONResponse)
async def take_profit(symbol: str):
    """Same broker action as close, but explicitly tagged as a
    deliberate profit-taking decision so the audit trail can
    distinguish operator intent."""
    return await _flatten_position(symbol, intent="take_profit")
