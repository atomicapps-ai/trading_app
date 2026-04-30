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


from fastapi.responses import RedirectResponse


# /strategies is now a parent; redirect to the default child (Validated)
async def _strategies_root(request: Request):
    return RedirectResponse(url="/strategies/validated", status_code=307)


router.add_api_route("/strategies", _strategies_root,
                     methods=["GET"], response_class=RedirectResponse)
# /strategies/validated, /strategies/in-progress, /strategies/archived
# are owned by routers/strategies.py (real implementation in Ship 3).
# /today is owned by routers/today.py (real implementation in Ship 5).
router.add_api_route(
    "/favorites", _placeholder(
        "favorites", "Favorites",
        "Later",
        "Independent watchlist. Any symbol from anywhere in the app can be starred; the source is recorded and shown on hover.",
    ),
    methods=["GET"], response_class=HTMLResponse,
)
# /replay is owned by routers/replay.py (real implementation in Ship 4).
# /system-health is owned by routers/system_health.py (real implementation in Ship 6).
