"""refresh_scan_service.py — one-click "Refresh & Scan".

Orchestrates the manual button on the top nav strip: pull the latest candles
for everything the live scans read, then run every active strategy scan and
queue any new setups to ``/pending``.

Three stages, run in a single background task:

  1. **Daily candles** — batched Alpaca top-up for the scan universe (the
     ``liquid_momentum_core`` / active screener tickers). Fast: one request
     per 50 symbols, merged into the CSVs so deep history is preserved.
  2. **FX candles** — best-effort IBKR top-up of the FX/gold majors at 30m/5m
     (for the ``fvg_continuation`` sleeve). Skipped silently if no gateway.
  3. **Scans** — run the four daily scan workflows (momentum_breakout,
     fear_dip_reversion, macd_run, coil_breakout) through the gate pipeline.

Only one run at a time. Progress lives in-memory (single-worker app), so the
topbar button can poll ``GET /api/refresh-and-scan/status`` and show a toast
when it finishes.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from services.settings_service import Settings, get_settings

logger = logging.getLogger(__name__)

# The scan workflows to run (mirrors workflows/*_scan.yaml — the active
# daily strategies). FX/fvg has no scan workflow yet, so it is refresh-only.
SCAN_WORKFLOWS: list[str] = [
    "momentum_breakout_scan",
    "fear_dip_reversion_scan",
    "macd_run_scan",
    "coil_breakout_scan",
]

_FX_INTERVALS = ["30m", "5m"]

# Single in-memory run record (the app runs one uvicorn worker).
_STATE: dict[str, Any] = {"run": None}
_LOCK = asyncio.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_run() -> dict[str, Any]:
    return {
        "id": _now(),
        "status": "running",          # running | done | error
        "stage": "starting",          # daily | fx | scans | done
        "detail": "",
        "pct": 0,
        "started_at": _now(),
        "finished_at": None,
        "error": None,
        "daily": None,
        "fx": None,
        "scans": [],                  # [{workflow, signals, plans, approved, error}]
        "totals": {"signals": 0, "plans": 0, "approved": 0},
    }


def get_status() -> dict[str, Any] | None:
    """Current (or most recent) run state, or None if nothing has run."""
    return _STATE["run"]


def is_running() -> bool:
    run = _STATE["run"]
    return bool(run and run.get("status") == "running")


async def _resolve_scan_universe() -> list[str]:
    """The equity symbols the daily scans will read — mirrors the workflow's
    universe resolution (named ``liquid_momentum_core`` else active screener)."""
    from services import db_service

    named = await db_service.get_universe_preset("liquid_momentum_core")
    tickers = list((named or {}).get("tickers") or [])
    if not tickers:
        active = await db_service.get_active_universe_preset()
        tickers = list((active or {}).get("tickers") or [])
    # de-dupe, preserve order, upper-case
    seen: set[str] = set()
    out: list[str] = []
    for t in tickers:
        u = str(t).upper()
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _fx_symbols() -> list[str]:
    try:
        from services.fvg_scan_service import DEFAULT_SYMBOLS
        return list(DEFAULT_SYMBOLS)
    except Exception:  # noqa: BLE001
        return ["XAUUSD", "EURUSD", "USDJPY", "GBPUSD", "AUDUSD"]


async def _do_run(settings: Settings) -> None:
    from services import candle_refresh_service as crs
    from services import pipeline_service

    run = _STATE["run"]
    try:
        # ---------- Stage 1: daily equity candles ----------
        run["stage"] = "daily"
        run["detail"] = "resolving scan universe"
        symbols = await _resolve_scan_universe()
        run["detail"] = f"refreshing daily candles ({len(symbols)} symbols)"

        def _daily_progress(done: int, total: int, note: str) -> None:
            run["detail"] = f"daily candles {done}/{total}"
            # daily stage spans 0-45%
            run["pct"] = int(45 * (done / total)) if total else 45

        if symbols:
            run["daily"] = await crs.refresh_daily_batched(
                symbols, lookback_days=20, chunk=50, progress=_daily_progress,
            )
        else:
            run["daily"] = {"symbols": 0, "note": "no universe tickers resolved"}
        run["pct"] = 45

        # ---------- Stage 2: FX candles (best-effort) ----------
        run["stage"] = "fx"
        run["detail"] = "refreshing FX/gold candles (IBKR)"
        try:
            run["fx"] = await crs.refresh_many(
                _fx_symbols(), _FX_INTERVALS, daily_source="yfinance", pace_s=0.1,
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("refresh_scan: FX refresh skipped: %s", exc)
            run["fx"] = {"ok": 0, "failed": 0, "note": f"skipped: {exc}"}
        run["pct"] = 55

        # ---------- Stage 3: run the scans ----------
        run["stage"] = "scans"
        n = len(SCAN_WORKFLOWS)
        for i, wf in enumerate(SCAN_WORKFLOWS):
            run["detail"] = f"scan {i + 1}/{n}: {wf}"
            entry: dict[str, Any] = {"workflow": wf}
            try:
                summary = await pipeline_service.run_workflow_by_id(
                    wf, mode="paper", settings=settings,
                )
                sig = int(summary.get("signals_generated", 0) or 0)
                plans = int(summary.get("plans_proposed", 0) or 0)
                appr = int(summary.get("plans_approved", 0) or 0)
                entry.update(signals=sig, plans=plans, approved=appr,
                             symbols=int(summary.get("symbols_in_shortlist", 0) or 0),
                             data_freshness=summary.get("data_freshness"))
                run["totals"]["signals"] += sig
                run["totals"]["plans"] += plans
                run["totals"]["approved"] += appr
            except Exception as exc:  # noqa: BLE001
                logger.warning("refresh_scan: %s failed: %s", wf, exc)
                entry["error"] = f"{type(exc).__name__}: {exc}"
            run["scans"].append(entry)
            run["pct"] = 55 + int(45 * ((i + 1) / n))

        # ---------- Stage 4: dedup + expire stale pending setups ----------
        # A re-scan re-evaluates the same setups; collapse any duplicate rows and
        # drop stale ones so the pending queue never accretes the same trade twice.
        try:
            from services import db_service
            run["cleanup"] = await db_service.dedupe_pending_plans()
        except Exception as exc:  # noqa: BLE001
            logger.warning("refresh_scan: dedupe_pending_plans failed: %s", exc)

        run["stage"] = "done"
        run["status"] = "done"
        run["detail"] = "complete"
        run["pct"] = 100
    except Exception as exc:  # noqa: BLE001
        logger.exception("refresh_scan run failed")
        run["status"] = "error"
        run["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        run["finished_at"] = _now()


async def start_run(settings: Settings | None = None) -> dict[str, Any]:
    """Kick off a run in the background. Returns the run record. If one is
    already in flight, returns that one unchanged (idempotent button)."""
    async with _LOCK:
        if is_running():
            return _STATE["run"]
        _STATE["run"] = _new_run()
    s = settings or get_settings()
    asyncio.create_task(_do_run(s))
    return _STATE["run"]
