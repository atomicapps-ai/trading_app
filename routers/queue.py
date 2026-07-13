"""queue router — durable async job queue for strategy runs.

All endpoints live under ``/api/queue`` — deliberately distinct from
``routers/jobs.py`` (which is a read-only view of APScheduler cron jobs and
owns ``/jobs`` + ``/api/jobs/...``).

Flow: a button POSTs an enqueue endpoint → the job persists to the
``job_queue`` table and runs server-side via the ``job_queue`` worker pool →
the global Jobs tray (in ``base.html``, polled on every page) reflects live
status. Nothing is bound to the launching page.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from services import db_service, job_queue
from services.settings_service import TEMPLATES_DIR

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _summary(status: str, result: dict | None, error: str | None) -> str:
    if status == "error":
        return (error or "failed")[:120]
    if status == "queued":
        return "queued"
    if status == "running":
        return "running…"
    if status == "canceled":
        return "canceled"
    # done
    res = result or {}
    if res.get("replay_only"):
        return res.get("note") or "replay-only (no live workflow)"
    runs = res.get("runs") or []
    signals = sum((r.get("result") or {}).get("signals_generated", 0) for r in runs)
    plans = sum((r.get("result") or {}).get("plans_proposed", 0) for r in runs)
    approved = sum((r.get("result") or {}).get("plans_approved", 0) for r in runs)
    return f"{signals} signals · {plans} plans · {approved} approved"


def _fmt_job(j: dict) -> dict:
    result = None
    if j.get("result_json"):
        try:
            result = json.loads(j["result_json"])
        except Exception:  # noqa: BLE001
            result = None
    status = j.get("status") or "queued"
    return {
        "job_id": j["job_id"],
        "kind": j.get("kind"),
        "target": j.get("target"),
        "label": j.get("label") or j.get("target"),
        "status": status,
        "batch_id": j.get("batch_id"),
        "created_at": j.get("created_at"),
        "started_at": j.get("started_at"),
        "ended_at": j.get("ended_at"),
        "error": j.get("error"),
        "result": result,
        "summary": _summary(status, result, j.get("error")),
    }


# --------------------------------------------------------------------------- #
# Enqueue
# --------------------------------------------------------------------------- #


@router.post("/api/queue/strategy/{name}")
async def enqueue_strategy(name: str, mode: str | None = Query(default=None)) -> dict:
    job_id = await job_queue.enqueue_strategy_run(name, mode=mode, label=name)
    return {"job_id": job_id, "status": "queued", "strategy": name}


@router.post("/api/queue/run-active")
async def enqueue_run_active(mode: str | None = Query(default=None)) -> dict:
    return await job_queue.enqueue_active_strategies(mode=mode)


# --------------------------------------------------------------------------- #
# Read (tray + JSON). GET /api/queue/tray and /menu MUST precede /{job_id}.
# --------------------------------------------------------------------------- #


@router.get("/api/queue/tray", response_class=HTMLResponse)
async def queue_tray(request: Request):
    """The topbar button label — dot + running/queued counts."""
    counts = await db_service.count_jobs_by_status()
    return templates.TemplateResponse(
        "_partials/_job_tray.html", {"request": request, "counts": counts},
    )


@router.get("/api/queue/menu", response_class=HTMLResponse)
async def queue_menu(request: Request):
    """The dropdown list of recent jobs."""
    jobs = [_fmt_job(j) for j in await db_service.list_jobs(limit=12)]
    return templates.TemplateResponse(
        "_partials/_job_tray_menu.html", {"request": request, "jobs": jobs},
    )


@router.get("/api/queue")
async def list_queue(limit: int = 50) -> dict:
    jobs = [_fmt_job(j) for j in await db_service.list_jobs(limit=limit)]
    counts = await db_service.count_jobs_by_status()
    return {"jobs": jobs, "counts": counts}


@router.post("/api/queue/{job_id}/cancel")
async def cancel_queue_job(job_id: str) -> dict:
    ok = await db_service.cancel_job(job_id)
    if not ok:
        raise HTTPException(409, "job is not cancelable (already running or finished)")
    return {"job_id": job_id, "status": "canceled"}


@router.get("/api/queue/{job_id}")
async def get_queue_job(job_id: str) -> dict:
    j = await db_service.get_job(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    return _fmt_job(j)
