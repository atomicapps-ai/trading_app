"""alerts router — strategy notifications API + test affordances.

Endpoints
---------
GET  /api/alerts                  → JSON list of recent alerts (?unread_only=)
GET  /api/alerts/banner           → HTML partial for the dashboard banner
POST /api/alerts/{id}/ack         → mark one alert acknowledged
POST /api/alerts/ack-all          → mark every unread alert acknowledged
POST /api/alerts/test             → inject a synthetic alert (for UI testing)
POST /api/alerts/run-dl-now       → fire wf_double_lock_1030 ad-hoc
POST /api/alerts/run-lock1-now    → fire dl_lock1_scout ad-hoc

The two run-now endpoints exist so the operator can verify the full
detection-to-banner path without waiting for the next 10:00 / 10:30 ET
cron tick. Useful for first-deploy smoke tests + after-hours debugging.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from services import alert_service
from services.settings_service import TEMPLATES_DIR

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# --------------------------------------------------------------------------- #
# Listing + banner partial
# --------------------------------------------------------------------------- #


@router.get("/api/alerts", response_class=JSONResponse)
async def list_alerts(unread_only: bool = False, limit: int = 50) -> dict:
    rows = await alert_service.list_alerts(
        only_unread=unread_only, limit=limit,
    )
    return {
        "alerts": rows,
        "unread_count": await alert_service.unread_count(),
    }


@router.get("/api/alerts/banner", response_class=HTMLResponse)
async def alerts_banner(request: Request):
    """HTML partial that renders the unread-alerts banner.

    Polled by the dashboard via HTMX every 30s. Returns empty markup
    when the unread count is 0 so the banner just disappears.
    """
    rows = await alert_service.list_alerts(only_unread=True, limit=10)
    return templates.TemplateResponse(
        request=request,
        name="dashboard/_alerts_banner.html",
        context={"alerts": rows, "unread_count": len(rows)},
    )


# --------------------------------------------------------------------------- #
# Acknowledgement
# --------------------------------------------------------------------------- #


@router.post("/api/alerts/{alert_id}/ack", response_class=HTMLResponse)
async def ack_alert(alert_id: int, request: Request):
    """Acknowledge one alert, return the refreshed banner partial.

    HTMX swaps the response straight into ``#alerts-banner`` so the
    dismissed row disappears in-place and the unread count updates
    in a single round trip — no JSON flash, no follow-up poll.
    """
    await alert_service.acknowledge(alert_id)
    rows = await alert_service.list_alerts(only_unread=True, limit=10)
    return templates.TemplateResponse(
        request=request,
        name="dashboard/_alerts_banner.html",
        context={"alerts": rows, "unread_count": len(rows)},
    )


@router.post("/api/alerts/ack-all", response_class=HTMLResponse)
async def ack_all(request: Request):
    """Acknowledge every unread alert, return the (now empty) banner partial."""
    await alert_service.acknowledge_all_unread()
    rows = await alert_service.list_alerts(only_unread=True, limit=10)
    return templates.TemplateResponse(
        request=request,
        name="dashboard/_alerts_banner.html",
        context={"alerts": rows, "unread_count": len(rows)},
    )


# --------------------------------------------------------------------------- #
# Test affordances — ad-hoc fire of jobs / synthetic alerts
# --------------------------------------------------------------------------- #


@router.post("/api/alerts/test", response_class=JSONResponse)
async def inject_test_alert(kind: str = "armed",
                            symbol: str = "AAPL",
                            direction: str = "long") -> dict:
    """Drop a synthetic alert into the table — useful for verifying the
    banner / sound / dismiss flow without running the strategy."""
    if kind not in ("lock1_scouted", "armed", "filled", "closed", "test"):
        raise HTTPException(400, f"unsupported kind: {kind}")
    new_id = await alert_service.record_alert(
        kind=kind,                                 # type: ignore[arg-type]
        strategy="double_lock",
        symbol=symbol.upper(),
        direction=direction.lower(),
        title=f"TEST · {symbol.upper()} {direction.upper()} · {kind}",
        body="Synthetic alert injected via /api/alerts/test",
        payload={"injected_at": datetime.now(timezone.utc).isoformat()},
    )
    return {"id": new_id, "ok": True}


@router.post("/api/alerts/run-dl-now", response_class=JSONResponse)
async def run_dl_now() -> dict:
    """Trigger ``wf_double_lock_1030`` immediately, off-schedule.

    Exercises the full pipeline: detector → portfolio_manager →
    compliance → risk → upsert pending plan → record armed alert. The
    only difference from a 10:30 ET fire is the timestamp — the
    detector itself enforces the 10:30 time gate, so on a sandbox
    where time isn't 10:30 ET this completes with 0 plans (which is
    the correct outcome). Use the lock1 scout endpoint for a check
    that returns rows outside market hours via cached fixtures.
    """
    from services.pipeline_service import run_workflow_by_id
    started = datetime.now(timezone.utc)
    try:
        result = await run_workflow_by_id("double_lock_1030")
    except Exception as e:                                    # noqa: BLE001
        raise HTTPException(500, f"workflow raised: {e}")
    return {
        "ts_start": started.isoformat(),
        "ts_end": datetime.now(timezone.utc).isoformat(),
        "result": result,
    }


@router.post("/api/alerts/run-lock1-now", response_class=JSONResponse)
async def run_lock1_now() -> dict:
    """Trigger the DL Lock 1 scout immediately, off-schedule."""
    from services.scheduler import _dl_lock1_scout_job
    started = datetime.now(timezone.utc)
    try:
        await _dl_lock1_scout_job()
    except Exception as e:                                    # noqa: BLE001
        raise HTTPException(500, f"scout raised: {e}")
    return {
        "ts_start": started.isoformat(),
        "ts_end": datetime.now(timezone.utc).isoformat(),
        "ok": True,
    }
