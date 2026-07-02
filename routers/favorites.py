"""favorites router — pin any page OR item; render them as nav sublinks.

Favorites are stored in SQLite (``favorites`` table) and surfaced two ways:
  * the sidebar "Favorites" group hx-loads ``/api/favorites/nav`` (this router)
  * a ★ toggle in the topbar favorites the CURRENT page

Any item-level star (a screener, a symbol chart, …) can reuse
``POST /api/favorites/toggle`` with its own ``href`` + ``label`` + ``kind=item``.
"""
from __future__ import annotations

import html
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from services import db_service
from services.settings_service import TEMPLATES_DIR, Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/api/favorites/nav", response_class=HTMLResponse)
async def favorites_nav() -> HTMLResponse:
    """Sidebar sublinks partial for the Favorites group."""
    favs = await db_service.list_favorites()
    if not favs:
        return HTMLResponse(
            '<a href="/favorites" class="nav-item nav-child text-tertiary" '
            'style="font-size:11px;">No favorites yet — ★ a page to pin it</a>'
        )
    rows = []
    for f in favs:
        label = html.escape(f["label"])
        href = html.escape(f["href"])
        dot = "◆" if f.get("kind") == "item" else "•"
        rows.append(
            f'<a href="{href}" class="nav-item nav-child" title="{label}">'
            f'<span style="opacity:.5;margin-right:6px;">{dot}</span>'
            f'<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{label}</span></a>'
        )
    return HTMLResponse("".join(rows))


@router.get("/api/favorites/status", response_class=JSONResponse)
async def favorites_status(href: str) -> dict:
    return {"href": href, "favorited": await db_service.is_favorite(href)}


@router.get("/api/favorites/hrefs", response_class=JSONResponse)
async def favorites_hrefs() -> dict:
    """All favorited hrefs — lets item stars set their ★/☆ state in one call."""
    favs = await db_service.list_favorites()
    return {"hrefs": [f["href"] for f in favs]}


@router.post("/api/favorites/toggle", response_class=JSONResponse)
async def favorites_toggle(request: Request) -> dict:
    """Add/remove a favorite. Body: {href, label, kind?, ref_key?}."""
    body = await request.json()
    href = (body.get("href") or "").strip()
    label = (body.get("label") or "").strip()
    kind = body.get("kind") or "page"
    ref_key = body.get("ref_key")
    if not href:
        return JSONResponse({"ok": False, "error": "href required"}, status_code=422)
    now_fav = await db_service.toggle_favorite(href, label or href, kind=kind, ref_key=ref_key)
    return {"ok": True, "href": href, "favorited": now_fav}


@router.get("/favorites", response_class=HTMLResponse)
async def favorites_page(request: Request, s: Settings = Depends(get_settings)):
    favs = await db_service.list_favorites()
    return templates.TemplateResponse(
        request=request,
        name="favorites.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "favorites",
            "favorites": favs,
        },
    )
