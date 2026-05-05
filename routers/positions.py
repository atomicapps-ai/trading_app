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

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from models.account import Order
from services import broker_service
from services.settings_service import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()


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


@router.post("/api/positions/{symbol}/close", response_class=JSONResponse)
async def close_position(symbol: str):
    return await _flatten_position(symbol, intent="close")


@router.post("/api/positions/{symbol}/take-profit", response_class=JSONResponse)
async def take_profit(symbol: str):
    """Same broker action as close, but explicitly tagged as a
    deliberate profit-taking decision so the audit trail can
    distinguish operator intent."""
    return await _flatten_position(symbol, intent="take_profit")
