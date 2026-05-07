"""alpha_score router — UI + JSON for the quant + sentiment Alpha Score.

Three surfaces:

* ``GET /alpha-score`` — page that runs the AlphaScore agent across the
  current active screener (or a fallback bellwether list) and renders
  the four pillars side-by-side per symbol, sorted by adjusted_composite.
* ``GET /alpha-score/{symbol}`` — single-symbol detail page with the
  pillar breakdown, sub-score rationale, sentiment tags, and event
  blackout state.
* ``GET /api/alpha-score/{symbol}`` — JSON (model_dump) for programmatic
  consumers (dashboard widget, future automation hooks).

The page does NOT call agents during template render at module import
time — every request triggers a fresh ``score_universe`` so the user
sees the live macro pulse + sentiment. For 50+ symbol universes this
is a 5-15s call; the template shows a "computing…" overlay and HTMX
swaps in the result.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from agents.alpha_score_agent import (
    HIGH_THRESHOLD,
    MEDIUM_THRESHOLD,
    score_symbol,
    score_universe,
)
from services.settings_service import Settings, TEMPLATES_DIR, get_settings

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# Fallback universe when no active screener is configured. Matches the
# bellwether list the strategy currently validates against.
_FALLBACK_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO",
    "JPM",  "V",   "UNH",  "XOM",   "WMT",  "COST", "HD",   "LLY",
]


async def _resolve_universe(limit: int) -> tuple[list[str], str]:
    """Return (tickers, source_label). Falls back to the bellwether list
    when no active screener has saved tickers."""
    try:
        from services import universe_service                       # lazy
        presets = await universe_service.list_presets_db()
        active = next((p for p in presets if p.get("is_active")), None)
        if active:
            full = await universe_service.get_preset_db(active["name"])
            tickers = (full or {}).get("tickers") or []
            if tickers:
                return list(tickers)[:limit], f"screener:{active['name']}"
    except Exception as e:                         # noqa: BLE001
        logger.warning("alpha_score: active-screener lookup failed: %s", e)
    return list(_FALLBACK_UNIVERSE)[:limit], "fallback:bellwether_16"


@router.get("/alpha-score", response_class=HTMLResponse)
async def alpha_score_page(
    request: Request,
    limit: int = Query(20, ge=1, le=200),
    threshold: float = Query(HIGH_THRESHOLD, ge=0, le=100),
    s: Settings = Depends(get_settings),
):
    """Render the Alpha Score table for the active universe."""
    started = monotonic()
    symbols, source = await _resolve_universe(limit)
    try:
        results = await score_universe(symbols)
    except Exception as e:                         # noqa: BLE001
        logger.exception("alpha_score: universe scoring failed: %s", e)
        results = {}

    rows = sorted(
        results.values(),
        key=lambda r: r.adjusted_composite,
        reverse=True,
    )
    high_n = sum(1 for r in rows if r.adjusted_composite >= HIGH_THRESHOLD)
    med_n = sum(1 for r in rows if MEDIUM_THRESHOLD <= r.adjusted_composite < HIGH_THRESHOLD)
    low_n = sum(1 for r in rows if r.adjusted_composite < MEDIUM_THRESHOLD)

    return templates.TemplateResponse(
        request=request,
        name="alpha_score.html",
        context={
            "settings": s,
            "active_page": "alpha_score",
            "rows": rows,
            "source": source,
            "universe_size": len(symbols),
            "threshold": threshold,
            "high_n": high_n,
            "med_n": med_n,
            "low_n": low_n,
            "weights": {
                "price_action":  40,
                "intermarket":   25,
                "volume_profile": 20,
                "sentiment":     15,
            },
            "render_ms": round((monotonic() - started) * 1000, 1),
            "high_threshold": HIGH_THRESHOLD,
            "medium_threshold": MEDIUM_THRESHOLD,
        },
    )


@router.get("/alpha-score/{symbol}", response_class=HTMLResponse)
async def alpha_score_detail(
    request: Request,
    symbol: str,
    s: Settings = Depends(get_settings),
):
    """Single-symbol breakdown with full pillar + sub-score rationale."""
    started = monotonic()
    try:
        score = await score_symbol(symbol.upper())
    except Exception as e:                         # noqa: BLE001
        logger.exception("alpha_score detail failed for %s: %s", symbol, e)
        raise HTTPException(status_code=500, detail=f"scoring failed: {e}")

    return templates.TemplateResponse(
        request=request,
        name="alpha_score_detail.html",
        context={
            "settings": s,
            "active_page": "alpha_score",
            "score": score,
            "render_ms": round((monotonic() - started) * 1000, 1),
            "high_threshold": HIGH_THRESHOLD,
            "medium_threshold": MEDIUM_THRESHOLD,
        },
    )


@router.get("/api/alpha-score/{symbol}")
async def alpha_score_json(symbol: str):
    """JSON view of one symbol's AlphaScore (full model_dump)."""
    try:
        score = await score_symbol(symbol.upper())
    except Exception as e:                         # noqa: BLE001
        logger.exception("alpha_score json failed for %s: %s", symbol, e)
        raise HTTPException(status_code=500, detail=f"scoring failed: {e}")
    return JSONResponse(score.model_dump(mode="json"))


@router.get("/api/alpha-score")
async def alpha_score_universe_json(
    limit: int = Query(20, ge=1, le=200),
):
    """JSON view of the full active-universe ranking."""
    symbols, source = await _resolve_universe(limit)
    try:
        results = await score_universe(symbols)
    except Exception as e:                         # noqa: BLE001
        logger.exception("alpha_score universe json failed: %s", e)
        raise HTTPException(status_code=500, detail=f"scoring failed: {e}")
    rows = sorted(results.values(), key=lambda r: r.adjusted_composite, reverse=True)
    return JSONResponse({
        "source": source,
        "as_of_ts": datetime.now(timezone.utc).isoformat(),
        "rows": [r.model_dump(mode="json") for r in rows],
    })
