"""Trades router — history + overall performance over the real trade stores.

Merges closed trades (the JSONL journal, written by ``trade_recorder`` on every
close) with the open book (executed/approved plans in ``pending_approvals``) via
``services.trade_history_service``. The page leads with a performance summary +
a strategy ranking, then a filterable table (default: all trades, no date limit).

Analysis tab (``/trades/analysis``) is owned by ``routers/analysis.py``.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from services import trade_history_service as history
from services.settings_service import TEMPLATES_DIR, Settings, get_settings
from services.stub_data import hold_seconds_to_human

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)
# Money filters — Jinja's printf-style ``|format`` can't do the ``,`` thousands
# separator, so expose str.format-based helpers instead.
templates.env.filters["usd"] = lambda v: f"{(v or 0):,.0f}"
templates.env.filters["usd_signed"] = lambda v: f"{(v or 0):+,.0f}"


_EXIT_REASON_BADGE = {
    "tp1_hit":              "badge-green",
    "tp2_hit":              "badge-green",
    "trailing_stop_hit":    "badge-blue",
    "time_stop":            "badge-amber",
    "thesis_invalidation":  "badge-red",
    "manual":               "badge-gray",
    "manual_take_profit":   "badge-green",
}


def _format_for_table(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for t in rows:
        ts = t.get("ts_exited") or t.get("ts_entered") or ""
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            date_str = dt.strftime("%b %d %H:%M")
        except (KeyError, ValueError, AttributeError):
            date_str = ""
        is_closed = bool(t.get("is_closed"))
        out.append({
            **t,
            "entry":       t.get("entry") or 0.0,
            "exit_avg":    t.get("exit_avg") or 0.0,
            "pnl_usd":     t.get("pnl_usd"),          # may be None (open)
            "pnl_r":       t.get("pnl_r"),
            "mfe_r":       t.get("mfe_r"),
            "mae_r":       t.get("mae_r"),
            "is_closed":   is_closed,
            "date_fmt":    date_str,
            "hold_fmt":    hold_seconds_to_human(t.get("hold_seconds", 0)) if is_closed else "—",
            "exit_badge":  _EXIT_REASON_BADGE.get(t.get("exit_reason", ""), "badge-gray"),
            "status_badge": "badge-blue" if not is_closed else "badge-gray",
        })
    return out


def _filter_trades(
    trades: list[dict],
    symbol: str | None,
    strategy: str | None,
    outcome: str,
    date_from: str | None,
    date_to: str | None,
    limit: int,
) -> list[dict]:
    if symbol:
        sub = symbol.strip().upper()
        trades = [t for t in trades if sub in (t.get("symbol") or "").upper()]
    if strategy and strategy != "all":
        trades = [t for t in trades if t.get("strategy") == strategy]
    if outcome == "win":
        trades = [t for t in trades if (t.get("pnl_usd") or 0) > 0]
    elif outcome == "loss":
        trades = [t for t in trades if (t.get("pnl_usd") or 0) < 0]
    elif outcome == "open":
        trades = [t for t in trades if not t.get("is_closed")]
    elif outcome == "closed":
        trades = [t for t in trades if t.get("is_closed")]

    def _day(t: dict) -> str:
        return (t.get("ts_exited") or t.get("ts_entered") or "")[:10]

    if date_from:
        trades = [t for t in trades if _day(t) >= date_from]
    if date_to:
        trades = [t for t in trades if _day(t) <= date_to]
    return trades[:limit]


@router.get("/trades", response_class=HTMLResponse)
async def trades_page(request: Request, s: Settings = Depends(get_settings)):
    all_trades = await history.load_all()
    strategies = sorted({t["strategy"] for t in all_trades if t.get("strategy")})
    return templates.TemplateResponse(
        request=request,
        name="trades.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "trades",
            "strategies": strategies,
            "tabs": _trade_tabs(),
            "active_tab": "recent",
            "summary": history.summary(all_trades),
            "ranking": history.rank_strategies(all_trades),
        },
    )


def _trade_tabs() -> list[dict]:
    """Shared horizontal tabs for the Trade History group of pages."""
    return [
        {"key": "recent",   "label": "History",  "href": "/trades",          "count": None},
        {"key": "analysis", "label": "Analysis", "href": "/trades/analysis", "count": None},
    ]


@router.get("/api/trades", response_class=HTMLResponse)
async def trades_table(
    request: Request,
    symbol: str | None = None,
    strategy: str | None = None,
    outcome: Literal["all", "win", "loss", "open", "closed"] = "all",
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 1000,
):
    all_trades = await history.load_all()
    rows = _filter_trades(
        all_trades, symbol, strategy, outcome, date_from, date_to, limit,
    )
    return templates.TemplateResponse(
        request=request,
        name="trades/_table.html",
        context={"rows": _format_for_table(rows)},
    )


# /trades/analysis moved to routers/analysis.py — real failure-analysis surface
# replaces the Phase 6 placeholder. Registered in app.py.
