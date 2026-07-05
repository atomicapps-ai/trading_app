"""run_jobs.py — in-memory registry for async strategy-run jobs.

A strategy scan can take minutes (universe bar downloads + pandas), which blows
past Cloudflare's ~100s request timeout (HTTP 524) when the app is reached
through the tunnel. So the /run endpoint starts the scan as a background task
and returns a job id immediately; the UI polls this registry for the result.

The scan runs on the main event loop, and its heavy I/O (yfinance) is wrapped in
asyncio.to_thread, so the loop stays responsive to the status polls while it
runs. The scan's actual output (pending plans) lands in the shared DB — only the
transient run *status* lives here, so it doesn't need to be shared or durable.
In-memory + single-worker: a job is lost only if the app restarts mid-run
(rare; the operator just re-runs).
"""
from __future__ import annotations

import time
from uuid import uuid4

_JOBS: dict[str, dict] = {}
_MAX_JOBS = 200  # keep the newest N; prune older completed ones beyond that


def create(strategy: str) -> str:
    job_id = uuid4().hex
    _JOBS[job_id] = {
        "job_id": job_id, "strategy": strategy, "status": "running",
        "result": None, "error": None,
        "started_at": time.time(), "ended_at": None,
    }
    _prune()
    return job_id


def mark_done(job_id: str, result: dict) -> None:
    j = _JOBS.get(job_id)
    if j is not None:
        j["status"] = "done"
        j["result"] = result
        j["ended_at"] = time.time()


def mark_error(job_id: str, error: str) -> None:
    j = _JOBS.get(job_id)
    if j is not None:
        j["status"] = "error"
        j["error"] = error
        j["ended_at"] = time.time()


def get(job_id: str) -> dict | None:
    return _JOBS.get(job_id)


def _prune() -> None:
    if len(_JOBS) <= _MAX_JOBS:
        return
    # Drop the oldest jobs (by start time) beyond the cap.
    for k in sorted(_JOBS, key=lambda x: _JOBS[x]["started_at"])[: len(_JOBS) - _MAX_JOBS]:
        _JOBS.pop(k, None)
