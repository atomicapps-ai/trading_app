"""Pending-approvals router.

Phase 2 ships the split-layout UI with stub data. The full approval state
machine (compliance → risk → notify → ack → execute) wires up in Phase 5.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates

from services.settings_service import TEMPLATES_DIR, Settings, get_settings
from services.stub_data import STUB_PENDING, time_ago

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _decorate(p: dict) -> dict:
    """Attach UI-friendly derived fields to a pending plan dict."""
    return {**p, "ts_ago": time_ago(p["ts_created"])}


@router.get("/pending", response_class=HTMLResponse)
async def pending_page(request: Request, s: Settings = Depends(get_settings)):
    return templates.TemplateResponse(
        request=request,
        name="pending.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "pending",
            "pending": [_decorate(p) for p in STUB_PENDING],
            "selected": None,
        },
    )


@router.get("/pending/{plan_id}", response_class=HTMLResponse)
async def pending_detail(plan_id: str, request: Request, s: Settings = Depends(get_settings)):
    selected = next((p for p in STUB_PENDING if p["plan_id"] == plan_id), None)
    return templates.TemplateResponse(
        request=request,
        name="pending.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "pending",
            "pending": [_decorate(p) for p in STUB_PENDING],
            "selected": _decorate(selected) if selected else None,
            "not_found": selected is None,
        },
    )


@router.post("/pending/{plan_id}/ack", response_class=HTMLResponse)
async def pending_ack(plan_id: str, action: str = Form(...)):
    """Phase 2 stub. Real flow (HumanAckRecord → executioner) lands in Phase 5."""
    color = {"approve": "toast-ok", "reject": "toast-fail", "modify": "toast-ok"}.get(action, "toast-ok")
    return HTMLResponse(
        f'<span class="toast {color}">Action <strong>{action}</strong> recorded for {plan_id} (stub).</span>'
    )


@router.get("/api/pending/count", response_class=PlainTextResponse)
async def pending_count() -> str:
    return str(len(STUB_PENDING))
