"""signals.py — the scan-signal archive + per-setup backtest.

Every setup the scanner ever produced lives in ``pending_approvals`` (any
status). This surfaces them as a searchable archive and lets the operator
replay any one forward over historical bars to see how it would have turned
out — via ``services.setup_backtest_service``.

Routes:
    GET  /signals                          → archive page (search + table)
    GET  /api/signals                      → filtered table partial
    POST /api/signals/{plan_id}/backtest   → run the forward replay, render card
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from services import db_service, setup_backtest_service
from services.settings_service import TEMPLATES_DIR, get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _fmt_date(ts: str | None) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%b %d, %Y")
    except ValueError:
        return ts[:10]


async def _load_setups() -> list[dict]:
    plans = await db_service.get_pending_plans(status_filter=None, limit=5000)
    out: list[dict] = []
    for p in plans:
        out.append({
            "plan_id": p.get("plan_id"),
            "symbol": p.get("symbol", ""),
            "direction": p.get("direction", "long"),
            "strategy": p.get("strategy", "") or "manual",
            "status": p.get("status", ""),
            "entry": p.get("entry"),
            "stop": p.get("stop"),
            "tp1": p.get("tp1"),
            "tp2": p.get("tp2"),
            "conviction": p.get("conviction"),
            "ts_created": p.get("ts_created", ""),
            "date_fmt": _fmt_date(p.get("ts_created")),
        })
    out.sort(key=lambda x: x.get("ts_created", ""), reverse=True)
    return out


def _filter(setups: list[dict], symbol: str | None, strategy: str | None,
            direction: str | None) -> list[dict]:
    if symbol:
        s = symbol.strip().upper()
        setups = [x for x in setups if s in (x.get("symbol") or "").upper()]
    if strategy and strategy != "all":
        setups = [x for x in setups if x.get("strategy") == strategy]
    if direction and direction != "all":
        setups = [x for x in setups if (x.get("direction") or "") == direction]
    return setups


@router.get("/signals", response_class=HTMLResponse)
async def signals_page(request: Request):
    setups = await _load_setups()
    strategies = sorted({s["strategy"] for s in setups if s.get("strategy")})
    return templates.TemplateResponse(
        request=request, name="signals.html",
        context={
            "settings": get_settings(), "active_page": "signals",
            "strategies": strategies, "total": len(setups),
        },
    )


@router.get("/api/signals", response_class=HTMLResponse)
async def signals_table(
    request: Request,
    symbol: str | None = None,
    strategy: str | None = None,
    direction: str | None = None,
    limit: int = 500,
):
    setups = _filter(await _load_setups(), symbol, strategy, direction)[:limit]
    return templates.TemplateResponse(
        request=request, name="signals/_table.html", context={"rows": setups},
    )


@router.post("/api/signals/{plan_id}/backtest", response_class=HTMLResponse)
async def signals_backtest(plan_id: str, request: Request):
    plan = await db_service.get_plan_by_id(plan_id)
    if plan is None:
        return HTMLResponse(
            '<div class="bt-result bt-err">Setup not found.</div>', status_code=404)
    # get_plan_by_id returns the flat UI dict (entry/stop/tp1/tp2/direction/…).
    result = await setup_backtest_service.backtest_setup(plan)
    return templates.TemplateResponse(
        request=request, name="signals/_result.html",
        context={"r": result, "plan_id": plan_id},
    )
