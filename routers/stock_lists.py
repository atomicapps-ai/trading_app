"""Stock Lists router — curated/dynamic ticker collections under /universe."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from services import stock_lists_service
from services.settings_service import TEMPLATES_DIR, Settings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #


@router.get("/universe/stock-lists", response_class=HTMLResponse)
async def stock_lists_page(
    request: Request,
    s: Settings = Depends(get_settings),
) -> HTMLResponse:
    # Seed defaults on first visit (idempotent)
    await stock_lists_service.seed_defaults()
    lists = await stock_lists_service.list_all()
    return templates.TemplateResponse(
        request=request,
        name="stock_lists.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "stock_lists",
            "active_section": "universe",
            "lists": lists,
        },
    )


@router.get("/universe/stock-lists/{slug}", response_class=HTMLResponse)
async def stock_list_detail(
    slug: str,
    request: Request,
    s: Settings = Depends(get_settings),
) -> HTMLResponse:
    record = await stock_lists_service.get(slug)
    if not record:
        raise HTTPException(404, detail=f"stock list {slug} not found")
    return templates.TemplateResponse(
        request=request,
        name="stock_list_detail.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "stock_lists",
            "active_section": "universe",
            "list": record,
        },
    )


# --------------------------------------------------------------------------- #
# JSON API
# --------------------------------------------------------------------------- #


@router.get("/api/stock-lists")
async def api_list_all() -> dict:
    await stock_lists_service.seed_defaults()
    return {"ok": True, "lists": await stock_lists_service.list_all()}


@router.get("/api/stock-lists/{slug}")
async def api_get_one(slug: str) -> dict:
    record = await stock_lists_service.get(slug)
    if not record:
        raise HTTPException(404, detail=f"stock list {slug} not found")
    return {"ok": True, "list": record}


@router.post("/api/stock-lists/{slug}/refresh")
async def api_refresh(slug: str) -> dict:
    try:
        updated = await stock_lists_service.refresh(slug)
        return {
            "ok": True,
            "slug": slug,
            "ticker_count": updated.get("ticker_count", 0),
            "last_refreshed_at": updated.get("last_refreshed_at"),
        }
    except KeyError as exc:
        raise HTTPException(404, detail=str(exc))
    except Exception as exc:
        logger.exception("refresh(%s) failed", slug)
        raise HTTPException(502, detail=f"refresh failed: {exc}")


@router.post("/api/stock-lists/refresh-all")
async def api_refresh_all() -> dict:
    """Refresh every dynamic list (Wikipedia-sourced). Static lists skipped."""
    lists = await stock_lists_service.list_all()
    refreshed, failed, skipped = 0, [], 0
    for lst in lists:
        if lst.get("source_type") != "wikipedia":
            skipped += 1
            continue
        try:
            await stock_lists_service.refresh(lst["slug"])
            refreshed += 1
        except Exception as exc:
            logger.warning("refresh-all: %s failed: %s", lst["slug"], exc)
            failed.append({"slug": lst["slug"], "error": str(exc)})
    return {"ok": True, "refreshed": refreshed, "failed": failed, "skipped_static": skipped}
