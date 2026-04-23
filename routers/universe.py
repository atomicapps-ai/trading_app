"""universe router — Universe Preset Manager + legacy YAML views.

Routes
------
HTML pages:
    GET  /universe                          — list all presets (SQLite)
    GET  /universe/new                      — blank preset editor
    GET  /universe/{name}/edit              — edit preset
    GET  /universe/{name}/detail            — legacy YAML detail (read-only)

JSON API:
    POST /api/universe/presets              — create preset
    POST /api/universe/presets/{name}       — update preset filters
    POST /api/universe/presets/{name}/delete        — delete
    POST /api/universe/presets/{name}/set-active    — mark as active
    POST /api/universe/presets/{name}/test-run      — scrape Finviz, return list
    POST /api/universe/presets/{name}/save-tickers  — persist last test-run result
    GET  /api/universe/catalog              — full Finviz filter catalog JSON
    GET  /api/universe/legacy               — JSON list (YAML-backed, read-only)
    GET  /api/universe/legacy/{preset}      — JSON detail (YAML-backed)
    GET  /api/universe/legacy/{preset}/history/{kind}/{ts} — snapshot
"""
from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
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
    presets = await universe_service.list_presets_db()
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


@router.get("/universe/new", response_class=HTMLResponse)
async def universe_new(request: Request, s: Settings = Depends(get_settings)):
    return templates.TemplateResponse(
        request=request,
        name="universe_edit.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "universe",
            "preset": None,
            "catalog_flat": universe_service.get_catalog_flat(),
            "default_filter_ids": universe_service.load_filter_config(),
            "catalog_grouped": universe_service.get_catalog_grouped(),
            "is_new": True,
        },
    )


@router.get("/universe/{preset_name}/edit", response_class=HTMLResponse)
async def universe_edit(
    preset_name: str,
    request: Request,
    s: Settings = Depends(get_settings),
):
    preset = await universe_service.get_preset_db(preset_name)
    if preset is None:
        raise HTTPException(status_code=404, detail=f"preset {preset_name!r} not found")
    # Merge: default visible IDs + any preset-specific IDs not in defaults
    default_ids = universe_service.load_filter_config()
    extra_ids = [fid for fid in preset["filters"] if fid not in default_ids]
    return templates.TemplateResponse(
        request=request,
        name="universe_edit.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "universe",
            "preset": preset,
            "catalog_flat": universe_service.get_catalog_flat(),
            "default_filter_ids": default_ids,
            "extra_filter_ids": extra_ids,
            "catalog_grouped": universe_service.get_catalog_grouped(),
            "is_new": False,
        },
    )


@router.get("/universe/{preset_name}", response_class=HTMLResponse)
async def universe_preset(
    preset_name: str,
    request: Request,
    s: Settings = Depends(get_settings),
):
    """If the preset exists in SQLite redirect to its edit page,
    otherwise show the legacy YAML detail view."""
    from fastapi.responses import RedirectResponse
    db_preset = await universe_service.get_preset_db(preset_name)
    if db_preset is not None:
        return RedirectResponse(url=f"/universe/{preset_name}/edit", status_code=302)
    return await universe_detail_legacy(preset_name, request, s)


@router.get("/universe/{preset_name}/detail", response_class=HTMLResponse)
async def universe_detail_legacy(
    preset_name: str,
    request: Request,
    s: Settings = Depends(get_settings),
):
    """Legacy read-only detail view backed by YAML files."""
    preset = universe_service.get_preset(preset_name)
    if preset is None:
        return templates.TemplateResponse(
            request=request,
            name="universe.html",
            context={
                "settings": s,
                "app_version": "0.1.0",
                "active_page": "universe",
                "presets": await universe_service.list_presets_db(),
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
# JSON API — preset CRUD
# --------------------------------------------------------------------------- #


@router.post("/api/universe/presets")
async def api_create_preset(
    name: Annotated[str, Form()],
    title: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
    output_tags: Annotated[str, Form()] = "",
) -> dict:
    name = name.strip().lower().replace(" ", "_")
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    existing = await universe_service.get_preset_db(name)
    if existing:
        raise HTTPException(status_code=409, detail=f"preset '{name}' already exists")
    tags = [t.strip() for t in output_tags.split(",") if t.strip()]
    pid = await universe_service.create_preset_db(
        name=name, title=title or name, description=description,
        notes=notes, output_tags=tags,
    )
    return {"id": pid, "name": name, "redirect": f"/universe/{name}/edit"}


@router.post("/api/universe/presets/{preset_name}")
async def api_update_preset(
    preset_name: str,
    request: Request,
) -> dict:
    """Update preset description/notes/filters from a form or JSON body.

    Accepts multipart/form-data (from the edit form) or
    application/json (from direct API calls).
    Filters are submitted as fields named ``f_{filter_id}`` where the
    value is the chosen option string (empty string = not set / Any).
    """
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        title = body.get("title")
        description = body.get("description", "")
        notes = body.get("notes", "")
        output_tags = body.get("output_tags", [])
        filters = body.get("filters", {})
    else:
        form = await request.form()
        title = str(form.get("title", "")) or None
        description = str(form.get("description", ""))
        notes = str(form.get("notes", ""))
        raw_tags = str(form.get("output_tags", ""))
        output_tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        filters = {}
        for key, val in form.multi_items():
            if key.startswith("f_") and val:
                fid = key[2:]
                filters[fid] = str(val)

    ok = await universe_service.update_preset_db(
        preset_name,
        title=title,
        description=description,
        filters=filters,
        output_tags=output_tags,
        notes=notes,
    )
    if not ok:
        raise HTTPException(status_code=404, detail=f"preset {preset_name!r} not found")
    return {"ok": True, "name": preset_name}


@router.post("/api/universe/presets/{preset_name}/delete")
async def api_delete_preset(preset_name: str) -> dict:
    ok = await universe_service.delete_preset_db(preset_name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"preset {preset_name!r} not found")
    return {"ok": True, "redirect": "/universe"}


@router.post("/api/universe/presets/{preset_name}/set-active")
async def api_set_active(preset_name: str, request: Request) -> JSONResponse:
    ok = await universe_service.set_active_preset_db(preset_name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"preset {preset_name!r} not found")
    # HTMX: trigger a full page reload via HX-Redirect header
    return JSONResponse(
        content={"ok": True},
        headers={"HX-Redirect": "/universe"},
    )


@router.post("/api/universe/presets/{preset_name}/test-run")
async def api_test_run(
    preset_name: str,
    request: Request,
) -> dict:
    """Scrape Finviz with the preset's current filters; return tickers without saving."""
    preset = await universe_service.get_preset_db(preset_name)
    if preset is None:
        raise HTTPException(status_code=404, detail=f"preset {preset_name!r} not found")
    filters: dict[str, str] = preset["filters"]
    if not filters:
        return {"count": 0, "tickers": [], "message": "No filters configured — all tickers would match"}
    try:
        tickers, truncated = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: universe_service.scrape_finviz_filters(filters, max_pages=15, delay_seconds=1.5),
        )
    except Exception as e:
        logger.exception("test-run failed for %s", preset_name)
        raise HTTPException(status_code=502, detail=f"Finviz scrape failed: {e}") from e
    return {
        "count": len(tickers),
        "tickers": tickers[:500],
        "truncated": truncated,
        "max_results": 300,
    }


@router.post("/api/universe/presets/{preset_name}/run-agent")
async def api_run_agent(
    preset_name: str,
    s: Settings = Depends(get_settings),
) -> dict:
    """Run the UniverseFilter agent on this preset's saved tickers.

    Reads tickers from SQLite, applies the in-process prescreen (price /
    volume / SMA / RSI filters + momentum scoring), and returns the ranked
    shortlist without touching Finviz or any broker.
    """
    from agents.universe_filter import UniverseFilter

    preset = await universe_service.get_preset_db(preset_name)
    if preset is None:
        raise HTTPException(status_code=404, detail=f"preset {preset_name!r} not found")
    if not preset.get("tickers"):
        raise HTTPException(
            status_code=422,
            detail="No saved tickers — run the Finviz scrape and save first",
        )
    agent = UniverseFilter(s)
    result = await agent.run(preset_name)
    return {
        "preset_name": preset_name,
        "universe_size": result.universe_size,
        "shortlist_size": result.shortlist_size,
        "shortlist": result.shortlist,
        "universe": result.universe,
        "total_screened": result.total_screened,
        "rejected_count": result.rejected_count,
        "rejection_reasons": result.rejection_reasons,
        "run_duration_seconds": result.run_duration_seconds,
    }


@router.post("/api/universe/presets/{preset_name}/save-tickers")
async def api_save_tickers(
    preset_name: str,
    request: Request,
) -> dict:
    """Persist a ticker list (from a previous test-run) as the preset's universe."""
    body = await request.json()
    tickers = body.get("tickers") or []
    if not isinstance(tickers, list):
        raise HTTPException(status_code=422, detail="tickers must be a list")
    source = body.get("source", "finviz:manual")
    ok = await universe_service.save_preset_tickers_db(preset_name, tickers, source)
    if not ok:
        raise HTTPException(status_code=404, detail=f"preset {preset_name!r} not found")
    archive_existing = universe_service._load_tickers_doc().get(preset_name)
    if archive_existing:
        try:
            universe_service.archive_snapshot("tickers", preset_name, archive_existing)
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True, "count": len(tickers)}


# --------------------------------------------------------------------------- #
# JSON API — catalog + legacy YAML
# --------------------------------------------------------------------------- #


@router.get("/api/universe/catalog")
async def api_catalog() -> dict:
    return universe_service.load_finviz_catalog()


@router.get("/api/universe/presets")
async def api_list_presets() -> dict:
    return {"presets": await universe_service.list_presets_db()}


@router.get("/api/universe/presets/{preset_name}")
async def api_get_preset(preset_name: str) -> dict:
    preset = await universe_service.get_preset_db(preset_name)
    if preset is None:
        raise HTTPException(status_code=404, detail=f"preset {preset_name!r} not found")
    return preset


@router.get("/api/universe/legacy")
async def api_list_legacy() -> dict:
    return {"presets": universe_service.list_presets()}


@router.get("/api/universe/legacy/{preset_name}")
async def api_get_legacy(preset_name: str) -> dict:
    preset = universe_service.get_preset(preset_name)
    if preset is None:
        raise HTTPException(status_code=404, detail=f"preset {preset_name!r} not found")
    return preset


@router.get("/api/universe/legacy/{preset_name}/history/{kind}/{ts}")
async def api_history_snapshot(
    preset_name: str, kind: str, ts: str,
) -> dict:
    if kind not in ("criteria", "tickers"):
        raise HTTPException(status_code=400, detail="kind must be criteria or tickers")
    snap = universe_service.load_history_snapshot(preset_name, kind, ts)
    if snap is None:
        raise HTTPException(status_code=404, detail="snapshot not found")
    return {"preset_name": preset_name, "kind": kind, "ts": ts, "payload": snap}
