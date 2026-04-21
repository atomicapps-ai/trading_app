"""Broker router — connection status, account snapshot, HALT.

Replaces the Phase 2 stub. Active adapter via `services.broker_service`.

Routes (per phase3_prompt.md spec):
    GET  /broker                  → broker.html (full page)
    GET  /api/broker/status       → JSON or HTMX partial (HX-Request aware)
    POST /broker/halt             → cancel-all + set TRADING_HALTED flag
    POST /api/broker/connect      → adapter.connect()
    POST /api/broker/disconnect   → adapter.disconnect()
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from services import broker_service
from services.settings_service import TEMPLATES_DIR, Settings, get_settings

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)
logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _status_dict() -> dict:
    """Build the JSON shape /api/broker/status returns."""
    adapter = broker_service.get_adapter()
    payload: dict = {
        "connected": adapter.connected,
        "broker_name": adapter.broker_name,
        "mode": get_settings().app.mode,
        "trading_halted": broker_service.TRADING_HALTED,
        "ts": datetime.now(timezone.utc).isoformat(),
        "account": None,
    }
    return payload


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #

@router.get("/broker", response_class=HTMLResponse)
async def broker_page(request: Request, s: Settings = Depends(get_settings)):
    adapter = broker_service.get_adapter()
    account_id = os.getenv("TS_ACCOUNT_ID", "")
    return templates.TemplateResponse(
        request=request,
        name="broker.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "broker",
            "broker_name": adapter.broker_name,
            "connected": adapter.connected,
            "trading_halted": broker_service.TRADING_HALTED,
            "ts_account_last4": account_id[-4:] if len(account_id) >= 4 else "",
            "ts_sim": os.getenv("TS_SIM", "true").lower() == "true",
        },
    )


@router.get("/api/broker/account-card", response_class=HTMLResponse)
async def broker_account_card(request: Request):
    """HTML partial for the account snapshot card on /broker.
    Separate from /api/broker/status because that one's HX-Request response
    is the topbar dot, not an account block."""
    adapter = broker_service.get_adapter()
    ctx: dict = {
        "connected": adapter.connected,
        "broker_name": adapter.broker_name,
        "trading_halted": broker_service.TRADING_HALTED,
        "account": None,
        "error": None,
    }
    if adapter.connected:
        try:
            ctx["account"] = (await adapter.get_account_state()).model_dump()
        except Exception as e:
            ctx["error"] = f"{type(e).__name__}: {e}"
    return templates.TemplateResponse(
        request=request,
        name="broker/_account_snapshot.html",
        context=ctx,
    )


# --------------------------------------------------------------------------- #
# Status — HTMX-aware
# --------------------------------------------------------------------------- #

@router.get("/api/broker/status")
async def broker_status(request: Request):
    adapter = broker_service.get_adapter()
    status = _status_dict()
    if adapter.connected:
        try:
            status["account"] = (await adapter.get_account_state()).model_dump()
        except Exception as e:
            logger.warning("get_account_state failed: %s", e)

    if request.headers.get("HX-Request"):
        # Topbar dot needs HTML, account card needs HTML — same partial returns
        # a topbar-style row; account card uses its own partial below if needed.
        return templates.TemplateResponse(
            request=request,
            name="broker/_status_dot.html",
            context={"status": status},
        )
    return JSONResponse(status)


# --------------------------------------------------------------------------- #
# Connect / disconnect
# --------------------------------------------------------------------------- #

@router.post("/api/broker/connect")
async def broker_connect():
    ok = await broker_service.connect_adapter()
    return JSONResponse({"connected": ok, "broker_name": broker_service.get_adapter().broker_name})


@router.post("/api/broker/disconnect")
async def broker_disconnect():
    adapter = broker_service.get_adapter()
    await adapter.disconnect()
    return JSONResponse({"connected": False, "broker_name": adapter.broker_name})


# --------------------------------------------------------------------------- #
# HALT
# --------------------------------------------------------------------------- #

@router.post("/broker/halt")
async def broker_halt():
    adapter = broker_service.get_adapter()
    cancelled = 0
    try:
        acks = await adapter.cancel_all_orders()
        cancelled = sum(1 for a in acks if a.accepted)
    except NotImplementedError:
        cancelled = 0
    except Exception as e:
        logger.error("cancel_all_orders failed during HALT: %s", e)
    broker_service.set_halted(True)
    logger.warning(
        "HALT executed | broker=%s | cancelled=%d | ts=%s",
        adapter.broker_name, cancelled, datetime.now(timezone.utc).isoformat(),
    )
    return JSONResponse({"halted": True, "cancelled_orders": cancelled})
