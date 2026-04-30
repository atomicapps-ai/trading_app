"""Broker router — accounts, connection, account snapshot, HALT.

Multi-account credential registry lives in ``broker_accounts`` table;
the active row drives ``broker_service.build_adapter()``. The ``/broker``
page now exposes a CRUD UI over that table.

Routes:
    GET  /broker                          → broker.html (full page)
    GET  /api/broker/status               → JSON or HTMX partial (HX-Request aware)
    GET  /api/broker/accounts             → HTML list partial (HTMX-polled)
    POST /api/broker/accounts             → create account (form-encoded)
    POST /api/broker/accounts/{slug}/activate
                                          → switch active account + rebuild adapter
    POST /api/broker/accounts/{slug}/edit → update label/key/secret
    POST /api/broker/accounts/{slug}/delete
                                          → remove account
    POST /broker/halt                     → cancel-all + set TRADING_HALTED flag
    POST /api/broker/connect              → adapter.connect()
    POST /api/broker/disconnect           → adapter.disconnect()
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from services import account_service, broker_service
from services.settings_service import TEMPLATES_DIR, Settings, get_settings, save_settings

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
    accounts = await account_service.list_accounts_redacted()
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
            "accounts": accounts,
        },
    )


# --------------------------------------------------------------------------- #
# Accounts CRUD
# --------------------------------------------------------------------------- #


@router.get("/api/broker/account-picker", response_class=HTMLResponse)
async def broker_account_picker(request: Request):
    """Topbar account-picker button content. Renders the active account
    label with a colored dot for paper/live."""
    active = await account_service.get_active_account()
    return templates.TemplateResponse(
        request=request,
        name="broker/_account_picker.html",
        context={"active": active},
    )


@router.get("/api/broker/account-picker-menu", response_class=HTMLResponse)
async def broker_account_picker_menu(request: Request):
    """Dropdown body — every account, click to activate."""
    return templates.TemplateResponse(
        request=request,
        name="broker/_account_picker_menu.html",
        context={
            "accounts": await account_service.list_accounts_redacted(),
        },
    )


@router.get("/api/broker/accounts", response_class=HTMLResponse)
async def broker_accounts_list(request: Request):
    """HTML partial listing all accounts. Used by HTMX after activate/save."""
    return templates.TemplateResponse(
        request=request,
        name="broker/_accounts_list.html",
        context={
            "accounts": await account_service.list_accounts_redacted(),
            "current_broker_name": broker_service.get_adapter().broker_name,
        },
    )


@router.post("/api/broker/accounts")
async def broker_accounts_create(
    label: str = Form(...),
    provider: str = Form(...),
    account_type: str = Form(...),
    key_id: str = Form(...),
    secret: str = Form(...),
    activate: bool = Form(False),
):
    try:
        acct = await account_service.create_account(
            label=label.strip(),
            provider=provider,
            account_type=account_type,
            key_id=key_id.strip(),
            secret=secret.strip(),
            activate=activate,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if activate:
        await _apply_active_account(acct["slug"])
    return JSONResponse({"created": True, "slug": acct["slug"]})


@router.post("/api/broker/accounts/{slug}/activate")
async def broker_accounts_activate(slug: str):
    ok = await account_service.set_active(slug)
    if not ok:
        raise HTTPException(status_code=404, detail=f"unknown account: {slug}")
    await _apply_active_account(slug)
    adapter = broker_service.get_adapter()
    return JSONResponse({
        "activated": slug,
        "broker_name": adapter.broker_name,
        "connected": adapter.connected,
    })


@router.post("/api/broker/accounts/{slug}/edit")
async def broker_accounts_edit(
    slug: str,
    label: str | None = Form(None),
    key_id: str | None = Form(None),
    secret: str | None = Form(None),
):
    ok = await account_service.update_account(
        slug,
        label=label.strip() if label else None,
        # Empty strings on PATCH-style edits mean "leave unchanged" — UI
        # form submits empty fields when the user only updated one of
        # the three text inputs.
        key_id=key_id.strip() if key_id else None,
        secret=secret.strip() if secret else None,
    )
    if not ok:
        raise HTTPException(status_code=404, detail=f"unknown account: {slug}")
    # If the active account's creds changed we need to rebuild.
    active = await account_service.get_active_account()
    if active and active["slug"] == slug:
        await broker_service.reset_adapter()
        await broker_service.connect_adapter()
    return JSONResponse({"updated": slug})


@router.post("/api/broker/accounts/{slug}/delete")
async def broker_accounts_delete(slug: str):
    ok = await account_service.delete_account(slug)
    if not ok:
        raise HTTPException(status_code=404, detail=f"unknown account: {slug}")
    # If we deleted the active row, account_service promoted another. Rebuild.
    await broker_service.reset_adapter()
    await broker_service.connect_adapter()
    return JSONResponse({"deleted": slug})


async def _apply_active_account(slug: str) -> None:
    """Rebuild the adapter with new creds and align settings.app.mode
    with the new active account_type. Idempotent on repeat calls."""
    active = await account_service.get_active_account()
    if active is None:
        return
    # Align mode with account_type so the topbar badge + executioner gates
    # stay consistent with what the active account can actually do.
    s = get_settings()
    target_mode = active["account_type"]  # 'paper' or 'live'
    if s.app.mode != target_mode and s.app.mode != "research":
        # Don't override research mode automatically — the user is
        # explicitly off-broker. They'd flip mode in Settings to come back.
        s.app.mode = target_mode  # type: ignore[assignment]
        save_settings(s)
        logger.info("settings.app.mode aligned with active account: %s", target_mode)
    await broker_service.reset_adapter()
    await broker_service.connect_adapter()


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
