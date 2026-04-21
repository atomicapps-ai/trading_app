"""Pending-approvals router.

Reads live plans from SQLite via db_service. Each row carries both the
full TradePlan JSON and the compliance/risk verdicts, so the template
can render the decision context alongside the trade setup.

Ack flow today: records the human action in pending_approvals. The
real executioner handoff (HumanAckRecord → adapter.place_order) lands
in C3.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates

from services import db_service
from services.settings_service import TEMPLATES_DIR, Settings, get_settings
from services.stub_data import time_ago

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _decorate(p: dict) -> dict:
    """Attach UI-friendly derived fields to a pending plan dict."""
    if not p:
        return p
    try:
        ts_ago = time_ago(p["ts_created"])
    except Exception:
        ts_ago = ""
    return {**p, "ts_ago": ts_ago}


@router.get("/pending", response_class=HTMLResponse)
async def pending_page(request: Request, s: Settings = Depends(get_settings)):
    rows = await db_service.get_pending_plans(status_filter="pending")
    return templates.TemplateResponse(
        request=request,
        name="pending.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "pending",
            "pending": [_decorate(p) for p in rows],
            "selected": None,
        },
    )


@router.get("/pending/{plan_id}", response_class=HTMLResponse)
async def pending_detail(
    plan_id: str, request: Request, s: Settings = Depends(get_settings),
):
    rows = await db_service.get_pending_plans(status_filter="pending")
    selected = await db_service.get_plan_by_id(plan_id)
    return templates.TemplateResponse(
        request=request,
        name="pending.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "pending",
            "pending": [_decorate(p) for p in rows],
            "selected": _decorate(selected) if selected else None,
            "not_found": selected is None,
        },
    )


@router.post("/pending/{plan_id}/ack", response_class=HTMLResponse)
async def pending_ack(plan_id: str, action: str = Form(...)):
    """Record the ack. C3 wires the executioner handoff; for now we just
    flip status in the DB and show a confirmation toast."""
    if action not in {"approve", "reject", "modify"}:
        return HTMLResponse(
            f'<span class="toast toast-fail">Unknown action: {action}</span>',
            status_code=400,
        )
    ok = await db_service.ack_plan(plan_id, action)
    if not ok:
        return HTMLResponse(
            f'<span class="toast toast-fail">Plan {plan_id} not found.</span>',
            status_code=404,
        )
    color = {"approve": "toast-ok", "reject": "toast-fail", "modify": "toast-ok"}[action]
    return HTMLResponse(
        f'<span class="toast {color}">Action <strong>{action}</strong> recorded for {plan_id}.</span>'
    )


@router.get("/api/pending/count", response_class=PlainTextResponse)
async def pending_count() -> str:
    n = await db_service.get_pending_count()
    return str(n)
