"""data_fetch router — bulk OHLCV fetch + cache UI.

Page: ``GET /data-fetch`` — symbol entry, source picker, results table,
                            list of cached files in data/historical/.

APIs:
  ``POST /api/data-fetch/save``    — fetch + persist (multi-symbol)
  ``GET  /api/data-fetch/cached``  — JSON list of cached CSVs
  ``POST /api/data-fetch/delete``  — delete one cached CSV by filename
"""
from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from services import hf_data_service
from services.settings_service import TEMPLATES_DIR, Settings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)

_SYM_SPLIT = re.compile(r"[\s,;]+")


def _parse_symbols(raw: str) -> list[str]:
    if not raw:
        return []
    seen: list[str] = []
    out: list[str] = []
    for part in _SYM_SPLIT.split(raw.strip()):
        sym = part.strip().upper()
        if not sym or sym in seen:
            continue
        seen.append(sym)
        out.append(sym)
    return out


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #


@router.get("/data-fetch", response_class=HTMLResponse)
async def data_fetch_page(
    request: Request,
    s: Settings = Depends(get_settings),
) -> HTMLResponse:
    cached = hf_data_service.list_cached()
    return templates.TemplateResponse(
        request=request,
        name="data_fetch.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "data_fetch",
            "cached": cached,
        },
    )


# --------------------------------------------------------------------------- #
# APIs
# --------------------------------------------------------------------------- #


@router.post("/api/data-fetch/save")
async def api_fetch_save(
    symbols: str = Form(...),
    source: str = Form("auto"),
    interval: str = Form("1d"),
    start: str = Form("2010-01-01"),
    end: str = Form(""),
) -> JSONResponse:
    syms = _parse_symbols(symbols)
    if not syms:
        return JSONResponse(
            {"ok": False, "error": "no symbols supplied"}, status_code=422
        )
    if source not in ("auto", "hf", "yfinance", "alpaca", "ibkr"):
        return JSONResponse(
            {"ok": False, "error": f"bad source {source!r}"}, status_code=422
        )
    if interval not in ("1d", "1h", "30m", "15m", "5m"):
        return JSONResponse(
            {"ok": False, "error": f"bad interval {interval!r}"}, status_code=422
        )

    end_arg = end.strip() or None
    start_arg = start.strip() or None

    results = await hf_data_service.fetch_many_and_save(
        syms, source=source, start=start_arg, end=end_arg, interval=interval
    )
    cached = hf_data_service.list_cached()
    return JSONResponse({"ok": True, "results": results, "cached": cached})


@router.get("/api/data-fetch/cached")
async def api_cached() -> JSONResponse:
    return JSONResponse({"cached": hf_data_service.list_cached()})


@router.post("/api/data-fetch/delete")
async def api_delete(filename: str = Form(...)) -> JSONResponse:
    ok = hf_data_service.delete_cached(filename)
    return JSONResponse(
        {"ok": ok, "filename": filename, "cached": hf_data_service.list_cached()},
        status_code=200 if ok else 404,
    )
