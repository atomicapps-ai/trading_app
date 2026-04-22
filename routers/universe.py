"""universe router — list, detail, and history views for filter presets.

Routes
------
    GET  /universe                               — list of all presets
    GET  /universe/{preset}                      — single preset detail
    GET  /api/universe/presets                   — JSON list
    GET  /api/universe/{preset}                  — JSON detail
    GET  /api/universe/{preset}/history/{kind}/{ts}
                                                 — load one archived snapshot
                                                   (kind = criteria | tickers)

All reads are safe to call at any time. Write endpoints (edit / clone /
restore) are not part of this router yet — they land in the follow-up
commit that adds the edit flow.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from services import universe_service
from services.settings_service import TEMPLATES_DIR, Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# --------------------------------------------------------------------------- #
# HTML views
# --------------------------------------------------------------------------- #


@router.get("/universe", response_class=HTMLResponse)
async def universe_index(request: Request, s: Settings = Depends(get_settings)):
    presets = universe_service.list_presets()
    return templates.TemplateResponse(
        request=request,
        name="universe.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "universe",
            "presets": presets,
        },
    )


@router.get("/universe/{preset_name}", response_class=HTMLResponse)
async def universe_detail(
    preset_name: str,
    request: Request,
    s: Settings = Depends(get_settings),
):
    preset = universe_service.get_preset(preset_name)
    if preset is None:
        # Render the list with a "not found" notice instead of 404-ing
        return templates.TemplateResponse(
            request=request,
            name="universe.html",
            context={
                "settings": s,
                "app_version": "0.1.0",
                "active_page": "universe",
                "presets": universe_service.list_presets(),
                "not_found": preset_name,
            },
            status_code=404,
        )
    return templates.TemplateResponse(
        request=request,
        name="universe_detail.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "universe",
            "preset": preset,
        },
    )


# --------------------------------------------------------------------------- #
# JSON API
# --------------------------------------------------------------------------- #


@router.get("/api/universe/presets")
async def api_list_presets() -> dict:
    return {"presets": universe_service.list_presets()}


@router.get("/api/universe/{preset_name}")
async def api_get_preset(preset_name: str) -> dict:
    preset = universe_service.get_preset(preset_name)
    if preset is None:
        raise HTTPException(status_code=404, detail=f"preset {preset_name!r} not found")
    return preset


@router.get("/api/universe/{preset_name}/history/{kind}/{ts}")
async def api_history_snapshot(
    preset_name: str, kind: str, ts: str,
) -> dict:
    if kind not in ("criteria", "tickers"):
        raise HTTPException(status_code=400, detail="kind must be criteria or tickers")
    snap = universe_service.load_history_snapshot(preset_name, kind, ts)
    if snap is None:
        raise HTTPException(status_code=404, detail="snapshot not found")
    return {"preset_name": preset_name, "kind": kind, "ts": ts, "payload": snap}
