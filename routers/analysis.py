"""Analysis router — failure analysis surface for closed trades.

Replaces the Phase 6 placeholder. Reads from
``services.analysis_service`` which auto-detects the data source
(JSONL trade logs in production, the backtest dump CSV pre-launch).

Endpoints
---------
    GET /trades/analysis              — main page (full server render)
    GET /api/analysis/equity_curve    — JSON for the equity-curve chart
    GET /api/analysis/per_trade       — JSON ledger (filterable: ?losses=1)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from services import analysis_service as A
from services.settings_service import TEMPLATES_DIR, Settings, get_settings

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/trades/analysis", response_class=HTMLResponse)
async def trades_analysis(
    request: Request,
    raw: int = 0,
    s: Settings = Depends(get_settings),
):
    df = A.load_trades(source="auto", filter_to_production=not bool(raw))

    summary = A.summary(df)
    direction = A.by_direction(df)
    quartiles = []
    quartiles.extend(A.by_quartile(df, "rsi14_d", "RSI(14) daily"))
    quartiles.extend(A.by_quartile(df, "vix_level", "VIX prev close"))
    quartiles.extend(A.by_quartile(df, "adx14_d", "ADX(14) daily"))
    binaries = []
    binaries.extend(A.by_binary(df, "spy_aligned"))
    binaries.extend(A.by_binary(df, "above_sma50_d"))
    binaries.extend(A.by_binary(df, "prior_day_match"))

    return templates.TemplateResponse(
        request=request,
        name="trades/analysis.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "analysis",
            "summary": summary,
            "direction": direction,
            "quartiles": quartiles,
            "binaries": binaries,
            "by_symbol": A.by_symbol(df),
            "loser_clusters": A.loser_clusters(df),
            "ledger": A.per_trade(df)[:200],
            "view_raw": bool(raw),
        },
    )


@router.get("/api/analysis/equity_curve", response_class=JSONResponse)
async def equity_curve():
    df = A.load_trades(source="auto")
    return {"points": A.equity_curve(df)}


@router.get("/api/analysis/per_trade", response_class=JSONResponse)
async def per_trade(losses: int = 0, limit: int = 500):
    df = A.load_trades(source="auto")
    return {"rows": A.per_trade(df, only_losses=bool(losses))[:limit]}
