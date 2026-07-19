"""mining.py — the Video Mining page: see the YouTube research library, what's
been reviewed, and add more videos.

Routes:
    GET  /mining                     → page (summary + filterable table)
    GET  /api/mining/videos          → filtered table partial
    POST /api/mining/add             → start ingesting a YouTube URL (background)
    GET  /api/mining/add/status      → poll the ingest run
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from services import video_library_service as vlib
from services.settings_service import TEMPLATES_DIR, get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _filter(rows: list[dict], status: str | None, lane: str | None,
            q: str | None) -> list[dict]:
    if status and status != "all":
        rows = [r for r in rows if r["status"] == status]
    if lane and lane != "all":
        rows = [r for r in rows if r["lane"] == lane]
    if q:
        s = q.strip().lower()
        rows = [r for r in rows if s in r["id"].lower() or s in (r["reason"] or "").lower()]
    return rows


@router.get("/mining", response_class=HTMLResponse)
async def mining_page(request: Request):
    rows = vlib.load_library()
    lanes = sorted({r["lane"] for r in rows if r["lane"] and r["lane"] != "—"})
    return templates.TemplateResponse(
        request=request, name="mining.html",
        context={"settings": get_settings(), "active_page": "mining",
                 "summary": vlib.summary(rows), "lanes": lanes},
    )


@router.get("/api/mining/videos", response_class=HTMLResponse)
async def mining_videos(
    request: Request,
    status: str | None = None,
    lane: str | None = None,
    q: str | None = None,
    limit: int = 500,
):
    rows = _filter(vlib.load_library(), status, lane, q)[:limit]
    return templates.TemplateResponse(
        request=request, name="mining/_table.html", context={"rows": rows},
    )


@router.post("/api/mining/add")
async def mining_add(
    url: str = Form(...),
    lane: str = Form("swing"),
    transcript_only: bool = Form(True),
) -> JSONResponse:
    run = await vlib.add_video(url, transcript_only=transcript_only, lane=lane)
    code = 400 if run.get("status") == "error" and not run.get("video_id") else 200
    return JSONResponse(run, status_code=code)


@router.get("/api/mining/add/status")
async def mining_add_status() -> JSONResponse:
    return JSONResponse({"run": vlib.add_status(), "running": vlib.is_adding()})
