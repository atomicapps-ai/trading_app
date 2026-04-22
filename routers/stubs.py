"""Placeholder routes for nav links whose real implementation is in later phases.

Universe (Phase 4), Strategies (Phase 5+), Broker (Phase 3), Console (Phase 6).
Keep them here so the sidebar links don't 404 during Phase 2.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from services.settings_service import TEMPLATES_DIR, Settings, get_settings

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _placeholder(active: str, title: str, phase: str, description: str):
    async def _route(request: Request, s: Settings = Depends(get_settings)):
        return templates.TemplateResponse(
            request=request,
            name="_placeholder.html",
            context={
                "settings": s,
                "app_version": "0.1.0",
                "active_page": active,
                "title": title,
                "phase": phase,
                "description": description,
            },
        )
    return _route


router.add_api_route(
    "/strategies", _placeholder(
        "strategies", "Strategies",
        "Phase 5",
        "Strategy config CRUD with per-strategy mode toggles (research / paper / live) and active-strategy selection.",
    ),
    methods=["GET"], response_class=HTMLResponse,
)
router.add_api_route(
    "/console", _placeholder(
        "console", "Agent Console",
        "Phase 6",
        "Live SSE stream of agent decisions tailing data/logs/.",
    ),
    methods=["GET"], response_class=HTMLResponse,
)
