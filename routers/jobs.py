"""jobs router — view + manage scheduled jobs running inside the app.

Surfaces every APScheduler job registered by ``services.scheduler`` —
workflow runs (cron-driven from each workflows/*.yaml), Capitol Trades
polling, Senate eFD diff, and any future jobs added to the scheduler.

The page shows for each job:
  * id / name
  * trigger expression (cron / date)
  * next_run_time
  * last-run timestamp + result, pulled from the right backing store:
      - ``wf_*`` jobs   → ``pipeline_runs`` SQLite table
      - ``ct_*`` jobs   → copy_trading_config keys
      - ``senate_*`` job → copy_trading_config keys

Run-now: ``POST /api/jobs/{job_id}/run`` invokes the job's stored
function immediately (off the scheduler's cadence) and reports the
return value or exception. Useful for debugging and for users who don't
want to wait for the next 06:00 ET fire.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from services import db_service
from services.scheduler import get_scheduler
from services.settings_service import TEMPLATES_DIR, Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# --------------------------------------------------------------------------- #
# Job categorization + last-run lookups
# --------------------------------------------------------------------------- #


def _categorize(job_id: str) -> str:
    if job_id.startswith("wf_"):       return "workflow"
    if job_id.startswith("ct_"):       return "capitol_trades"
    if job_id.startswith("senate_"):   return "senate"
    return "other"


async def _last_run_for(job_id: str, runs_by_wf: dict[str, dict],
                        copy_cfg: dict) -> dict[str, Any] | None:
    cat = _categorize(job_id)
    if cat == "workflow":
        wf_id = job_id[len("wf_"):]
        r = runs_by_wf.get(wf_id)
        if not r:
            return None
        return {
            "ts": r.get("ts_start") or r.get("ts_end"),
            "status": r.get("status"),
            "summary": (
                f"{r.get('plans_proposed', 0)} plans proposed"
                if r.get("plans_proposed") is not None else None
            ),
            "duration_seconds": r.get("duration_seconds"),
        }
    if cat == "capitol_trades":
        return {
            "ts": copy_cfg.get("last_scan_ts"),
            "status": ("error" if copy_cfg.get("last_scan_error") else "ok"),
            "summary": (
                f"{copy_cfg.get('last_scan_count', '0')} disclosures"
                if copy_cfg.get("last_scan_ts") else None
            ),
        }
    if cat == "senate":
        return {
            "ts": copy_cfg.get("senate_last_diff_at"),
            "status": ("error" if copy_cfg.get("senate_last_diff_error") else "ok"),
            "summary": (
                f"{copy_cfg.get('senate_new_filings_count', '0')} cumulative new PTRs"
                if copy_cfg.get("senate_last_diff_at") else None
            ),
        }
    return None


def _job_descriptor(job, last_run: dict | None) -> dict[str, Any]:
    return {
        "id": job.id,
        "name": job.name or job.id,
        "category": _categorize(job.id),
        "trigger": str(job.trigger),
        "next_run_time": (
            job.next_run_time.isoformat() if job.next_run_time else None
        ),
        "pending": job.pending,                # True before scheduler.start()
        "misfire_grace_time": job.misfire_grace_time,
        "coalesce": getattr(job, "coalesce", None),
        "last_run": last_run,
        "args": list(job.args) if job.args else [],
    }


# --------------------------------------------------------------------------- #
# HTML page
# --------------------------------------------------------------------------- #


@router.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request, s: Settings = Depends(get_settings)):
    sched = get_scheduler()
    jobs = sched.get_jobs() if sched else []

    # Pre-fetch the two backing stores so per-job lookup is sync
    runs = await db_service.list_pipeline_runs(limit=200)
    runs_by_wf: dict[str, dict] = {}
    for r in runs:
        wf_id = r.get("workflow_id")
        if wf_id and wf_id not in runs_by_wf:
            runs_by_wf[wf_id] = r
    copy_cfg = await db_service.get_all_copy_config()

    descriptors: list[dict] = []
    for job in jobs:
        last = await _last_run_for(job.id, runs_by_wf, copy_cfg)
        descriptors.append(_job_descriptor(job, last))

    # Stable sort: pending jobs first (clearly call-out unstarted state),
    # then by next_run_time ascending.
    descriptors.sort(key=lambda d: (
        not d["pending"],
        d["next_run_time"] or "9999-99",
    ))

    # Pull a flat recent-runs feed for the bottom panel
    recent = runs[:25]

    return templates.TemplateResponse(
        request=request,
        name="jobs.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "jobs",
            "jobs": descriptors,
            "recent_runs": recent,
            "scheduler_running": (sched.running if sched else False),
            "now_utc": datetime.now(timezone.utc).isoformat(),
        },
    )


# --------------------------------------------------------------------------- #
# JSON API + run-now
# --------------------------------------------------------------------------- #


@router.get("/api/jobs", response_class=JSONResponse)
async def list_jobs() -> dict:
    sched = get_scheduler()
    jobs = sched.get_jobs() if sched else []
    runs = await db_service.list_pipeline_runs(limit=100)
    runs_by_wf: dict[str, dict] = {}
    for r in runs:
        wf = r.get("workflow_id")
        if wf and wf not in runs_by_wf:
            runs_by_wf[wf] = r
    copy_cfg = await db_service.get_all_copy_config()

    out = []
    for j in jobs:
        last = await _last_run_for(j.id, runs_by_wf, copy_cfg)
        out.append(_job_descriptor(j, last))
    return {
        "scheduler_running": (sched.running if sched else False),
        "jobs": out,
    }


@router.post("/api/jobs/{job_id}/run", response_class=JSONResponse)
async def run_job_now(job_id: str) -> dict:
    """Fire a registered job immediately, off-schedule.

    Calls the job's stored function with whatever args the scheduler
    has on file. Awaits coroutines, runs sync funcs in the default
    threadpool.
    """
    sched = get_scheduler()
    job = sched.get_job(job_id) if sched else None
    if job is None:
        raise HTTPException(404, f"unknown job {job_id!r}")

    fn = job.func
    args = list(job.args) if job.args else []
    kwargs = dict(job.kwargs) if job.kwargs else {}

    started = datetime.now(timezone.utc)
    try:
        result = fn(*args, **kwargs)
        if asyncio.iscoroutine(result):
            result = await result
    except Exception as e:                                    # noqa: BLE001
        logger.exception("manual run %s failed", job_id)
        raise HTTPException(500, f"job raised: {e}")

    ended = datetime.now(timezone.utc)
    return {
        "job_id": job_id,
        "ts_start": started.isoformat(),
        "ts_end": ended.isoformat(),
        "duration_seconds": round((ended - started).total_seconds(), 2),
        "result": (
            result if isinstance(result, (dict, list, str, int, float, bool))
            else str(result) if result is not None else None
        ),
    }


@router.post("/api/jobs/{job_id}/pause", response_class=JSONResponse)
async def pause_job(job_id: str) -> dict:
    """Pause a registered job. The job stays in the scheduler but won't fire
    until ``/resume`` is called. Survives until the process restarts (jobstore
    is in-memory)."""
    sched = get_scheduler()
    job = sched.get_job(job_id) if sched else None
    if job is None:
        raise HTTPException(404, f"unknown job {job_id!r}")
    sched.pause_job(job_id)
    logger.info("paused job %s", job_id)
    return {"job_id": job_id, "paused": True}


@router.post("/api/jobs/{job_id}/resume", response_class=JSONResponse)
async def resume_job(job_id: str) -> dict:
    """Resume a previously-paused job. Recomputes ``next_run_time`` from
    the trigger as if it had been running all along."""
    sched = get_scheduler()
    job = sched.get_job(job_id) if sched else None
    if job is None:
        raise HTTPException(404, f"unknown job {job_id!r}")
    sched.resume_job(job_id)
    refreshed = sched.get_job(job_id)
    logger.info("resumed job %s", job_id)
    return {
        "job_id": job_id,
        "paused": False,
        "next_run_time": (
            refreshed.next_run_time.isoformat()
            if refreshed and refreshed.next_run_time else None
        ),
    }


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(job_id: str, request: Request,
                     s: Settings = Depends(get_settings)):
    """Detail page for one job: Status / Logs / Run history tabs."""
    sched = get_scheduler()
    job = sched.get_job(job_id) if sched else None
    if job is None:
        raise HTTPException(404, f"unknown job {job_id!r}")

    runs = await db_service.list_pipeline_runs(limit=200)
    runs_by_wf: dict[str, dict] = {}
    for r in runs:
        wf = r.get("workflow_id")
        if wf and wf not in runs_by_wf:
            runs_by_wf[wf] = r
    copy_cfg = await db_service.get_all_copy_config()
    last = await _last_run_for(job_id, runs_by_wf, copy_cfg)
    descriptor = _job_descriptor(job, last)

    # Run history specific to this job. For workflow jobs, filter by wf id;
    # for ct_/senate_ jobs, history lives only in their config keys (no run
    # ledger), so we surface a single "last run" row instead.
    cat = _categorize(job_id)
    if cat == "workflow":
        wf_id = job_id[len("wf_"):]
        history = [r for r in runs if r.get("workflow_id") == wf_id][:50]
    else:
        history = [last] if last and last.get("ts") else []

    # Recent log lines for this job (in-memory ring buffer fed by scheduler).
    try:
        from services.job_log_buffer import get_log_lines
        log_lines = get_log_lines(job_id, limit=200)
    except Exception:                                       # noqa: BLE001
        log_lines = []

    return templates.TemplateResponse(
        request=request,
        name="jobs/detail.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "jobs",
            "job": descriptor,
            "history": history,
            "log_lines": log_lines,
            "is_paused": (descriptor.get("next_run_time") is None
                          and not descriptor.get("pending")),
            "scheduler_running": (sched.running if sched else False),
            "now_utc": datetime.now(timezone.utc).isoformat(),
        },
    )
