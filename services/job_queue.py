"""job_queue.py — durable, cross-page async job queue for strategy runs.

Unlike ``run_jobs.py`` (transient, page-scoped, lost on navigation/restart),
this persists every job to the ``job_queue`` SQLite table and runs it via an
in-process asyncio worker pool. Jobs therefore survive:

  * navigating away from the launching page (the tray on every page reflects
    live status from the DB), and
  * an app restart mid-run — ``start_workers`` requeues anything left
    ``running`` (killed by a dev hot-reload) and re-feeds every ``queued`` job.

Single-worker uvicorn only (matches the app's broker-singleton constraint) —
the queue lives in this process, so no Redis/Celery is needed. Concurrency is
bounded so overlapping yfinance bar downloads don't thrash the event loop.
"""
from __future__ import annotations

import asyncio
import json
import logging
from uuid import uuid4

from services import db_service

logger = logging.getLogger(__name__)

DEFAULT_CONCURRENCY = 2

_queue: asyncio.Queue | None = None
_workers: list[asyncio.Task] = []
_started = False


# --------------------------------------------------------------------------- #
# Enqueue
# --------------------------------------------------------------------------- #


async def enqueue_strategy_run(
    name: str,
    *,
    mode: str | None = None,
    as_of: str | None = None,
    refresh: bool | None = None,
    batch_id: str | None = None,
    label: str | None = None,
) -> str:
    """Persist a queued strategy-run job and hand it to the workers."""
    job_id = uuid4().hex
    await db_service.enqueue_job(
        job_id=job_id,
        kind="strategy_run",
        target=name,
        label=label or name,
        batch_id=batch_id,
        params={"mode": mode, "as_of": as_of, "refresh": refresh},
    )
    await _push(job_id)
    return job_id


async def enqueue_active_strategies(*, mode: str | None = None) -> dict:
    """Enqueue every *active* strategy that has a runnable workflow.

    Returns {batch_id, job_ids, enqueued, skipped}. ``skipped`` lists active
    strategies with no scan workflow (e.g. fvg_continuation) so the UI can say
    why they weren't run.
    """
    picks = await _active_runnable_strategies()
    batch_id = uuid4().hex
    job_ids: list[str] = []
    for name in picks["run"]:
        job_ids.append(
            await enqueue_strategy_run(name, mode=mode, batch_id=batch_id, label=name)
        )
    return {
        "batch_id": batch_id,
        "job_ids": job_ids,
        "enqueued": picks["run"],
        "skipped": picks["skipped"],
    }


async def _active_runnable_strategies() -> dict:
    """Resolve which strategies are active AND have a matching scan workflow.

    Lazy-imports the strategies router helpers so the active-flag resolution
    (widget-setting override → YAML default) matches exactly what the
    /strategies page shows.
    """
    from routers.strategies import (
        _load_strategy,
        _load_workflows,
        _resolve_active,
        _strategy_files,
    )

    workflows = await _load_workflows()
    have_wf: set[str] = set()
    for wf in workflows:
        for sname in wf["strategies_used"]:
            have_wf.add(sname)

    run: list[str] = []
    skipped: list[str] = []
    for path in _strategy_files():
        cfg = _load_strategy(path)
        name = cfg["_name"]
        eff_active, _ = await _resolve_active(name, bool(cfg.get("active", False)))
        if not eff_active:
            continue
        sname = cfg.get("strategy_name", name)
        if sname in have_wf or name in have_wf:
            run.append(name)
        else:
            skipped.append(name)
    return {"run": run, "skipped": skipped}


# --------------------------------------------------------------------------- #
# Worker pool
# --------------------------------------------------------------------------- #


async def _push(job_id: str) -> None:
    global _queue
    if _queue is None:
        _queue = asyncio.Queue()
    await _queue.put(job_id)


async def start_workers(concurrency: int = DEFAULT_CONCURRENCY) -> None:
    """Start the worker pool + recover interrupted jobs. Idempotent."""
    global _queue, _workers, _started
    if _started:
        return
    _queue = asyncio.Queue()
    try:
        requeued = await db_service.requeue_orphaned_jobs()
        if requeued:
            logger.info("job_queue: requeued %d interrupted job(s)", len(requeued))
        for jid in await db_service.load_queued_job_ids():
            _queue.put_nowait(jid)
    except Exception as exc:  # noqa: BLE001
        logger.warning("job_queue: startup recovery failed: %s", exc)
    _workers = [asyncio.create_task(_worker(i)) for i in range(max(1, concurrency))]
    _started = True
    logger.info("job_queue: started %d worker(s)", len(_workers))


async def stop_workers() -> None:
    global _workers, _started
    for task in _workers:
        task.cancel()
    _workers = []
    _started = False


async def _worker(idx: int) -> None:
    assert _queue is not None
    while True:
        job_id = await _queue.get()
        try:
            job = await db_service.get_job(job_id)
            if not job or job["status"] in ("canceled", "done", "error"):
                continue
            await db_service.mark_job_running(job_id)
            result = await _run_job(job)
            await db_service.mark_job_done(job_id, result)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("job_queue: job %s failed", job_id)
            try:
                await db_service.mark_job_error(job_id, str(exc))
            except Exception:  # noqa: BLE001
                pass
        finally:
            _queue.task_done()


async def _run_job(job: dict) -> dict:
    """Execute one job and return its summary dict."""
    kind = job.get("kind")
    if kind == "strategy_run":
        # Lazy import avoids a router<->service import cycle at module load.
        from routers.strategies import _do_strategy_run
        from services.settings_service import get_settings

        params = json.loads(job.get("params_json") or "{}")
        settings = get_settings()
        return await _do_strategy_run(
            job["target"],
            params.get("mode"),
            params.get("as_of"),
            params.get("refresh"),
            settings,
        )
    raise ValueError(f"unknown job kind: {kind!r}")
