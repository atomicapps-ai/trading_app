"""Trades router — history table (filterable) over the real JSONL pool.

Reads ``trade_logs/*.jsonl`` via ``services.log_service``. Each closed
trade has a TradeRecord row written by the executioner / risk_manager
post-trade hook. The page tolerates an empty pool (e.g. fresh checkout
or research mode) by rendering an empty table — no stub data here.

Analysis tab (``/trades/analysis``) is owned by ``routers/analysis.py``.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from services import log_service
from services.settings_service import TEMPLATES_DIR, Settings, get_settings
from services.stub_data import hold_seconds_to_human

logger = logging.getLogger(__name__)

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
            dt = datetime.fromisoformat((t.get("ts_entered") or "").replace("Z", "+00:00"))
            date_str = dt.strftime("%b %d %H:%M")
        except (KeyError, ValueError):
            date_str = ""
        out.append({
            **t,
            # Defensive None→0 coercion for numeric template fields. Real
            # closed TradeRecords always carry these, but a partial write
            # shouldn't 500 the page.
            "entry":       t.get("entry") or 0.0,
            "exit_avg":    t.get("exit_avg") or 0.0,
            "pnl_usd":     t.get("pnl_usd") or 0.0,
            "pnl_r":       t.get("pnl_r") or 0.0,
            "mfe_r":       t.get("mfe_r") or 0.0,
            "mae_r":       t.get("mae_r") or 0.0,
            "date_fmt":    date_str,
            "hold_fmt":    hold_seconds_to_human(t.get("hold_seconds", 0)),
            "exit_badge":  _EXIT_REASON_BADGE.get(t.get("exit_reason", ""), "badge-gray"),
        })
    return out


async def _load_real_trades() -> list[dict]:
    """Read every TradeRecord from the JSONL pool and flatten to the
    UI row shape that ``trades/_table.html`` expects.

    Returns ``[]`` (not stub data) when the pool is empty — fresh checkout
    or research mode.
    """
    try:
        records = await log_service.read_records()
    except Exception as e:                                            # noqa: BLE001
        logger.warning("trades: log_service read failed (%s)", e)
        return []

    rows: list[dict] = []
    for r in records:
        instr = r.instrument or {}
        lc = r.lifecycle or {}
        setup = r.setup_snapshot or {}
        execn = r.execution or {}
        outc = r.outcome or {}

        ts_entered = lc.get("ts_entered") or lc.get("ts_planned") or ""
        ts_exited = lc.get("ts_exited_last") or lc.get("ts_exited_first") or ""
        hold_seconds = 0
        if ts_entered and ts_exited:
            try:
                t1 = datetime.fromisoformat(ts_entered.replace("Z", "+00:00"))
                t2 = datetime.fromisoformat(ts_exited.replace("Z", "+00:00"))
                hold_seconds = max(0, int((t2 - t1).total_seconds()))
            except ValueError:
                hold_seconds = 0

        rows.append({
            "trade_id":     r.trade_id,
            "plan_id":      r.plan_id,
            "symbol":       instr.get("symbol", ""),
            "direction":    setup.get("direction", "long"),
            "strategy":     setup.get("strategy_name", ""),
            "entry":        execn.get("avg_entry_price") or execn.get("planned_entry"),
            "exit_avg":     execn.get("avg_exit_price"),
            "pnl_usd":      outc.get("pnl_usd", 0.0),
            "pnl_r":        outc.get("pnl_r_multiple", 0.0),
            "mfe_r":        outc.get("mfe_r_multiple", 0.0),
            "mae_r":        outc.get("mae_r_multiple", 0.0),
            "hold_seconds": hold_seconds,
            "exit_reason":  outc.get("exit_reason", ""),
            "mode":         r.mode,
            "ts_entered":   ts_entered,
        })
    rows.sort(key=lambda x: x.get("ts_entered", ""), reverse=True)
    return rows


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
    if date_from:
        trades = [t for t in trades if (t.get("ts_entered") or "")[:10] >= date_from]
    if date_to:
        trades = [t for t in trades if (t.get("ts_entered") or "")[:10] <= date_to]
    return trades[:limit]


@router.get("/trades", response_class=HTMLResponse)
async def trades_page(request: Request, s: Settings = Depends(get_settings)):
    all_trades = await _load_real_trades()
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
        },
    )


def _trade_tabs() -> list[dict]:
    """Shared horizontal tabs for the Trade History group of pages."""
    return [
        {"key": "recent",   "label": "Recent",   "href": "/trades",          "count": None},
        {"key": "analysis", "label": "Analysis", "href": "/trades/analysis", "count": None},
    ]


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
    all_trades = await _load_real_trades()
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
