"""replay router — UI wrapper for ``scripts/replay_dl.py``.

Lets the operator run the same date-range replay end-to-end inside the
app, without dropping to a terminal. Reuses the script's ``replay``
function directly so the simulation logic lives in exactly one place.

Endpoints
---------
GET  /replay                      → page with date pickers + form + empty results region
POST /api/replay/run              → run the replay; returns JSON {trades, summary}

Defaults match the CLI: this Monday → today, default 16-symbol universe,
strategy=double_lock.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from scripts.replay_dl import (
    DEFAULT_UNIVERSE, _last_completed_weekday, replay,
)
from services.settings_service import TEMPLATES_DIR, Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _default_range() -> tuple[date, date]:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return monday, _last_completed_weekday(today)


@router.get("/replay", response_class=HTMLResponse)
async def replay_page(request: Request, s: Settings = Depends(get_settings)):
    since, until = _default_range()
    return templates.TemplateResponse(
        request=request,
        name="replay.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "replay",
            "default_since": since.isoformat(),
            "default_until": until.isoformat(),
            "default_symbols": ", ".join(DEFAULT_UNIVERSE),
        },
    )


@router.post("/api/replay/run", response_class=JSONResponse)
async def run_replay(
    since: str,
    until: str,
    symbols: str | None = None,
    strategy: str = "double_lock",
    refresh: bool = False,
) -> dict:
    """Run the date-range replay. Returns trades + aggregate stats."""
    try:
        since_d = datetime.strptime(since, "%Y-%m-%d").date()
        until_d = datetime.strptime(until, "%Y-%m-%d").date()
    except ValueError as e:
        return JSONResponse({"error": f"bad date: {e}"}, status_code=400)
    if until_d < since_d:
        return JSONResponse(
            {"error": f"until ({until_d}) before since ({since_d})"}, status_code=400,
        )

    syms: list[str]
    if symbols:
        syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    else:
        syms = list(DEFAULT_UNIVERSE)

    started = datetime.utcnow().isoformat()
    try:
        trades = await replay(syms, since_d, until_d, strategy, refresh=bool(refresh))
    except Exception as e:                                            # noqa: BLE001
        logger.exception("replay failed")
        return JSONResponse({"error": f"replay raised: {e}"}, status_code=500)

    # Aggregate stats — mirror the CLI's _print_summary
    n = len(trades)
    summary: dict = {
        "n": n,
        "wins": sum(1 for t in trades if t.win),
        "losses": sum(1 for t in trades if not t.win),
        "win_rate": (sum(1 for t in trades if t.win) / n * 100.0) if n else 0.0,
        "avg_pnl_pct": (sum(t.pnl_pct for t in trades) / n) if n else 0.0,
        "total_pnl_pct": sum(t.pnl_pct for t in trades),
        "stop_hits": sum(1 for t in trades if t.exit_reason == "STOP"),
        "longs": sum(1 for t in trades if t.direction == "LONG"),
        "shorts": sum(1 for t in trades if t.direction == "SHORT"),
        "best_pnl_pct": max((t.pnl_pct for t in trades), default=0.0),
        "worst_pnl_pct": min((t.pnl_pct for t in trades), default=0.0),
    }

    return {
        "trades": [asdict(t) for t in trades],
        "summary": summary,
        "since": since_d.isoformat(),
        "until": until_d.isoformat(),
        "strategy": strategy,
        "symbols": syms,
        "started_utc": started,
        "completed_utc": datetime.utcnow().isoformat(),
    }
