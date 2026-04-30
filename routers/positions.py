"""positions.py — operator actions on broker positions.

Currently exposes one action: flatten a position via a market order.
This is the dashboard's "Close" button path. Bypasses the full agent
pipeline (no compliance / risk gates) because the user has explicitly
asked to close an existing position — not open a new one. We DO refuse
in research mode and when TRADING_HALTED is set.

Why direct broker access (not via the executioner): the executioner
expects a TradePlan, which only exists for positions that came through
the agent pipeline. Manual / smoke-script positions (like the leftover
SPY 1-share from the order roundtrip smoke) have no plan. The close
path needs to work for those too.

Routes
------
    POST /api/positions/{symbol}/close   → flatten via market order
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


@router.post("/api/positions/{symbol}/close", response_class=JSONResponse)
async def close_position(symbol: str):
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
        "Position close requested | symbol=%s shares=%d side=%s "
        "broker_order_id=%s ts=%s",
        symbol, qty, close_side, ack.broker_order_id,
        datetime.now(timezone.utc).isoformat(),
    )
    return {
        "ok": True,
        "symbol": symbol,
        "shares_closed": qty,
        "side": close_side,
        "broker_order_id": ack.broker_order_id,
    }
