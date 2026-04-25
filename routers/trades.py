"""Trades router — history table (filterable) + analysis stub.

Phase 2: reads from STUB_TRADES. Real JSONL aggregation lands in Phase 5
(when actual trades exist) per phase2_prompt.md. Analysis page is a Phase 6
deliverable; we ship a placeholder so the nav link works.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from services.settings_service import TEMPLATES_DIR, Settings, get_settings
from services.stub_data import STUB_TRADES, hold_seconds_to_human

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


_EXIT_REASON_BADGE = {
    "tp1_hit":              "badge-green",
    "tp2_hit":              "badge-green",
    "trailing_stop_hit":    "badge-blue",
    "time_stop":            "badge-amber",
    "thesis_invalidation":  "badge-red",
    "manual":               "badge-gray",
}


def _format_for_table(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for t in rows:
        try:
            dt = datetime.fromisoformat(t["ts_entered"])
            date_str = dt.strftime("%b %d %H:%M")
        except (KeyError, ValueError):
            date_str = ""
        out.append({
            **t,
            "date_fmt": date_str,
            "hold_fmt": hold_seconds_to_human(t.get("hold_seconds", 0)),
            "exit_badge": _EXIT_REASON_BADGE.get(t.get("exit_reason", ""), "badge-gray"),
        })
    return out


def _filter_trades(
    symbol: str | None,
    strategy: str | None,
    outcome: str,
    date_from: str | None,
    date_to: str | None,
    limit: int,
) -> list[dict]:
    trades = list(STUB_TRADES)
    if symbol:
        sub = symbol.strip().upper()
        trades = [t for t in trades if sub in t["symbol"].upper()]
    if strategy and strategy != "all":
        trades = [t for t in trades if t["strategy"] == strategy]
    if outcome == "win":
        trades = [t for t in trades if t.get("pnl_usd", 0) > 0]
    elif outcome == "loss":
        trades = [t for t in trades if t.get("pnl_usd", 0) < 0]
    if date_from:
        trades = [t for t in trades if t["ts_entered"][:10] >= date_from]
    if date_to:
        trades = [t for t in trades if t["ts_entered"][:10] <= date_to]
    return trades[:limit]


@router.get("/trades", response_class=HTMLResponse)
async def trades_page(request: Request, s: Settings = Depends(get_settings)):
    strategies = sorted({t["strategy"] for t in STUB_TRADES})
    return templates.TemplateResponse(
        request=request,
        name="trades.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "trades",
            "strategies": strategies,
        },
    )


@router.get("/api/trades", response_class=HTMLResponse)
async def trades_table(
    request: Request,
    symbol: str | None = None,
    strategy: str | None = None,
    outcome: Literal["all", "win", "loss"] = "all",
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
):
    rows = _filter_trades(symbol, strategy, outcome, date_from, date_to, limit)
    return templates.TemplateResponse(
        request=request,
        name="trades/_table.html",
        context={"rows": _format_for_table(rows)},
    )


# /trades/analysis moved to routers/analysis.py — real failure-analysis surface
# replaces the Phase 6 placeholder. Registered in app.py.
