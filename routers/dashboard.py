"""Dashboard router — stat cards, agent status, today's activity, open positions.

All data Phase-2-stubbed via services.stub_data. Real wiring in Phases 4–5.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from services.settings_service import TEMPLATES_DIR, Settings, get_settings
from services.stub_data import (
    STUB_ACCOUNT,
    STUB_ACTIVITY,
    STUB_AGENTS,
    STUB_OPEN_POSITIONS,
    STUB_PENDING,
)

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, s: Settings = Depends(get_settings)):
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "dashboard",
            "account": STUB_ACCOUNT,
            "pending": STUB_PENDING,
            "open_positions": STUB_OPEN_POSITIONS,
        },
    )


@router.get("/api/dashboard/stats", response_class=HTMLResponse)
async def dashboard_stats(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="dashboard/_stats.html",
        context={"account": STUB_ACCOUNT},
    )


@router.get("/api/dashboard/agents", response_class=HTMLResponse)
async def dashboard_agents(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="dashboard/_agents.html",
        context={"agents": STUB_AGENTS},
    )


@router.get("/api/dashboard/activity", response_class=HTMLResponse)
async def dashboard_activity(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="dashboard/_activity.html",
        context={"activity": STUB_ACTIVITY[:10]},
    )
