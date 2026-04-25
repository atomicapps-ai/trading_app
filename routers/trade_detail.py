"""trade_detail router — unified detail page for any trade by id.

Resolves an id across both backends (pending_approvals + JSONL trade
journal) via ``services.trade_lookup`` and renders the same template
in either case. Active trades get the edit form (Phase 6 lights it
up); closed trades get the postmortem card.

Companion partials in templates/_partials/:
  _probability_card.html — backtest WR + live WR + blended
  _news_card.html         — VADER-scored Alpaca News + EDGAR
  _postmortem_card.html   — closed trades only
  _indicator_picker.html  — chart overlay/subplot picker
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from services import (
    news_service,
    probability_service,
    sentiment_service,
    trade_lookup,
    widget_settings,
)
from services.indicator_registry import (
    DEFAULT_OVERLAY_IDS,
    DEFAULT_SUBPLOT_IDS,
    INDICATORS,
    indicators_by_category,
    overlay_indicators,
    subplot_indicators,
)
from services.settings_service import TEMPLATES_DIR, Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Hold for trade-chart indicator picks. Reuses the widget_settings
# storage with a synthetic widget_id so the indicator selection
# persists per user across machines.
_TRADE_CHART_WIDGET_ID = "trade_chart"


@router.get("/trades/{trade_id}", response_class=HTMLResponse)
async def trade_detail(
    trade_id: str, request: Request,
    s: Settings = Depends(get_settings),
):
    """Single-trade detail page. Works for pending OR closed trades."""
    trade = await trade_lookup.get(trade_id)
    if trade is None:
        raise HTTPException(404, f"trade {trade_id} not found")

    # ── Probability of success (strategy-level) ─────────────────────────
    prob = None
    if trade.strategy_name:
        try:
            prob = (await probability_service.compute(trade.strategy_name)).to_dict()
        except Exception as e:                                # noqa: BLE001
            logger.warning("trade_detail: probability failed for %s: %s",
                           trade.strategy_name, e)

    # ── News + sentiment (last 24h, scored) ─────────────────────────────
    news_items: list[dict] = []
    news_summary: dict = {}
    news_error: str | None = None
    try:
        end   = datetime.now(timezone.utc)
        start = end - timedelta(hours=24)
        items = await news_service.get_news(trade.symbol, start=start, end=end)
        if items:
            scored = sentiment_service.score_items(items)
            news_items = [s.to_dict() for s in scored]
            news_summary = sentiment_service.summarize(items).to_dict()
    except Exception as e:                                    # noqa: BLE001
        news_error = f"News fetch failed: {e}"
        logger.warning("trade_detail: news fetch failed for %s: %s",
                       trade.symbol, e)

    # ── Indicator picks (per-user, persisted via widget_settings) ───────
    saved_overlays = await widget_settings.get_with_default(
        "default", _TRADE_CHART_WIDGET_ID, "selected_overlays",
        DEFAULT_OVERLAY_IDS,
    )
    saved_subplots = await widget_settings.get_with_default(
        "default", _TRADE_CHART_WIDGET_ID, "selected_subplots",
        DEFAULT_SUBPLOT_IDS,
    )
    overlays_by_cat = {
        cat: [s for s in specs if s.pane == "overlay"]
        for cat, specs in indicators_by_category().items()
        if any(s.pane == "overlay" for s in specs)
    }

    return templates.TemplateResponse(
        request=request,
        name="trades/detail.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "trades",
            "trade": trade,
            "probability": prob,
            "news_items": news_items,
            "news_summary": news_summary,
            "news_error": news_error,
            "overlays_by_category": overlays_by_cat,
            "subplots": subplot_indicators(),
            "selected_overlays": saved_overlays,
            "selected_subplots": saved_subplots,
        },
    )


# --------------------------------------------------------------------------- #
# Indicator-pick persistence — POST {ids} for the trade chart picker
# --------------------------------------------------------------------------- #


@router.post("/api/trades/chart/indicators", response_class=JSONResponse)
async def save_trade_chart_indicators(request: Request):
    """Persist the indicator-pick state for the trade detail chart.

    Body shape:
        {"selected_overlays": ["sma_20", "vwap"],
         "selected_subplots": ["rsi_14"]}

    Validates ids against the global registry (defensive — drops unknown).
    """
    try:
        payload = await request.json()
    except Exception:                                          # noqa: BLE001
        raise HTTPException(400, "invalid JSON body")

    valid_ids = set(INDICATORS.keys())
    overlays = [
        i for i in (payload.get("selected_overlays") or [])
        if i in valid_ids and INDICATORS[i].pane == "overlay"
    ]
    subplots = [
        i for i in (payload.get("selected_subplots") or [])
        if i in valid_ids and INDICATORS[i].pane == "subplot"
    ]

    await widget_settings.set_many(
        "default", _TRADE_CHART_WIDGET_ID,
        {"selected_overlays": overlays, "selected_subplots": subplots},
    )
    return {"saved": True, "overlays": overlays, "subplots": subplots}
