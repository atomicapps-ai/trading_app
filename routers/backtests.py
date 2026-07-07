"""routers/backtests.py — the Strategy Backtests page.

Run per-strategy suitability backtests from the UI, see when each last ran,
and get a clear staleness signal — especially a red "strategy changed,
results invalid, re-run" alert. Re-running archives the superseded run to
CSV (data/backtest_archive/) before replacing it in the cache DB.

The replay is heavy (minutes), so a run is a background task; the page polls
progress.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from services import backtest_runner as runner
from services.settings_service import TEMPLATES_DIR, get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# In-memory run state per strategy (this process). {strategy: {...}}
_RUNS: dict[str, dict] = {}


@router.get("/strategies/backtests", response_class=HTMLResponse)
async def backtests_page(request: Request):
    statuses = await runner.all_statuses()
    for st in statuses:
        run = _RUNS.get(st["strategy"])
        st["running"] = bool(run and run.get("running"))
        st["progress"] = run.get("pct", 0) if run else 0
    return templates.TemplateResponse(
        request=request, name="backtests.html",
        context={"settings": get_settings(), "active_page": "strategies",
                 "app_version": "0.1.0", "statuses": statuses},
    )


@router.get("/api/backtests/status")
async def backtests_status() -> JSONResponse:
    statuses = await runner.all_statuses()
    for st in statuses:
        run = _RUNS.get(st["strategy"])
        st["running"] = bool(run and run.get("running"))
        st["progress"] = run.get("pct", 0) if run else 0
        st["last_summary"] = run.get("summary") if run else None
    return JSONResponse({"statuses": statuses})


@router.post("/api/backtests/{strategy}/run")
async def run_backtest(strategy: str) -> JSONResponse:
    if strategy not in runner.STRATEGIES:
        return JSONResponse({"ok": False, "error": "unknown strategy"}, status_code=404)
    cur = _RUNS.get(strategy)
    if cur and cur.get("running"):
        return JSONResponse({"ok": False, "error": "already running"}, status_code=409)

    st = await runner.strategy_status(strategy)
    total_calls = max(1, 2 * (st.get("universe_size") or 1))
    _RUNS[strategy] = {"running": True, "pct": 0, "msg": "starting…", "done": 0,
                       "summary": None}

    def _progress(i, total, sym):
        r = _RUNS.get(strategy)
        if not r:
            return
        r["done"] += 1
        r["pct"] = min(99, int(r["done"] / total_calls * 100))
        r["msg"] = f"{sym} ({r['pct']}%)"

    async def _bg():
        try:
            summary = await runner.run_strategy(strategy, force=True, progress=_progress)
            _RUNS[strategy].update({"running": False, "pct": 100,
                                    "msg": "done", "summary": summary})
            logger.info("backtest %s done: %s", strategy, summary)
        except Exception as exc:  # noqa: BLE001
            logger.exception("backtest %s failed", strategy)
            _RUNS[strategy].update({"running": False, "pct": 0,
                                    "msg": f"error: {exc}",
                                    "summary": {"ok": False, "error": str(exc)}})

    asyncio.create_task(_bg())
    return JSONResponse({"ok": True, "started": True})
