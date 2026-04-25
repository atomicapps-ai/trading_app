"""Dashboard router — stat cards, agent status, today's activity, open positions.

Plus the new modular widget system (services.dashboard_widgets):
  GET /api/dashboard/widgets/{id} dispatches to the matching Widget
  subclass; the dashboard template iterates ``WIDGETS`` and renders an
  HTMX-driven placeholder for each. New monitoring tiles (sector heatmap,
  Fear/Greed, SPY trend, etc.) ship as Widget subclasses without
  touching this router.

Stub-backed sections (Pending, Open positions, Agent status, Activity)
will migrate to widgets as they're touched. v1 keeps both side-by-side
to minimize blast radius.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from services import widget_settings as ws
from services.dashboard_widgets import TAB_ORDER, get_widget, widgets_by_tab
from services.indicator_registry import INDICATORS, indicators_by_category
from services.settings_service import TEMPLATES_DIR, Settings, get_settings
from services.stub_data import (
    STUB_ACCOUNT,
    STUB_ACTIVITY,
    STUB_AGENTS,
    STUB_OPEN_POSITIONS,
    STUB_PENDING,
)

logger = logging.getLogger(__name__)

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
            # Widgets organized by tab. Template iterates TAB_ORDER + this dict.
            "tabs": TAB_ORDER,
            "widgets_by_tab": widgets_by_tab(),
        },
    )


@router.get("/api/dashboard/widgets/{widget_id}", response_class=HTMLResponse)
async def dashboard_widget(widget_id: str, request: Request):
    """Dispatch to the registered Widget — render its partial with its data.

    Failures inside a single widget are isolated: the widget renders an
    error card, the rest of the dashboard is unaffected.
    """
    widget = get_widget(widget_id)
    if widget is None:
        raise HTTPException(status_code=404, detail=f"unknown widget: {widget_id}")
    try:
        ctx = await widget.get_data()
    except Exception as exc:                              # noqa: BLE001
        logger.exception("widget %s get_data raised", widget_id)
        return templates.TemplateResponse(
            request=request,
            name="dashboard/widgets/_error.html",
            context={"widget_id": widget_id, "error": str(exc)},
        )
    return templates.TemplateResponse(
        request=request, name=widget.template, context=ctx,
    )


# --------------------------------------------------------------------------- #
# Per-widget user settings (⚙ panel)
# --------------------------------------------------------------------------- #


@router.get("/api/dashboard/widgets/{widget_id}/settings", response_class=HTMLResponse)
async def widget_settings_panel(widget_id: str, request: Request):
    """Render the settings modal body for one widget.

    Schema-driven: iterates ``widget.settings_schema`` and emits a control
    per declared key (multiselect, number, bool, text). Current values
    come from ``widget.resolve_settings()`` so the form prefills with
    whatever the user previously saved.
    """
    widget = get_widget(widget_id)
    if widget is None or not widget.user_configurable:
        raise HTTPException(404, f"widget {widget_id} not configurable")
    current = await widget.resolve_settings()
    return templates.TemplateResponse(
        request=request,
        name="dashboard/_widget_settings.html",
        context={
            "widget": widget,
            "current": current,
            "indicators_by_category": indicators_by_category(),
            "all_indicators": list(INDICATORS.values()),
        },
    )


@router.post("/api/dashboard/widgets/{widget_id}/settings", response_class=JSONResponse)
async def widget_settings_save(widget_id: str, request: Request):
    """Persist user settings for a widget. Body: JSON dict of key->value.

    Only keys declared in the widget's ``settings_schema`` are accepted —
    extra keys are silently dropped (defensive).
    """
    widget = get_widget(widget_id)
    if widget is None or not widget.user_configurable:
        raise HTTPException(404, f"widget {widget_id} not configurable")
    try:
        payload: dict[str, Any] = await request.json()
    except Exception:                                          # noqa: BLE001
        raise HTTPException(400, "invalid JSON body")

    allowed = set(widget.settings_schema.keys())
    accepted = {k: v for k, v in payload.items() if k in allowed}
    if accepted:
        await ws.set_many("default", widget_id, accepted)
    return {"saved": list(accepted.keys()), "ignored":
            [k for k in payload if k not in allowed]}


@router.delete("/api/dashboard/widgets/{widget_id}/settings",
               response_class=JSONResponse)
async def widget_settings_reset(widget_id: str):
    """Drop every saved override for this widget — falls back to defaults."""
    widget = get_widget(widget_id)
    if widget is None or not widget.user_configurable:
        raise HTTPException(404, f"widget {widget_id} not configurable")
    await ws.reset_widget("default", widget_id)
    return {"reset": True}


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
