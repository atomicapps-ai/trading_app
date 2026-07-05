"""system_health router — single-page rollup of "is everything wired?".

Pulls together state from:
  * Scheduler — running flag, last-tick age, registered job count
  * Broker adapter — connected flag, broker_name
  * Data freshness — most recent 30m bar age, daily bar age (per heartbeat sym)
  * Alert pipeline — last alert ts, last ntfy push outcome
  * Disk usage — trade_logs/, data/historical/, data/news_cache/, sqlite db size
  * Errors — counts pulled from job_log_buffer over the last 1h / 24h

Designed to be the page operators check before market open. Each section
captures its own errors so the page renders even if multiple subsystems
are degraded.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from services.settings_service import (
    DATA_DIR, LOCAL_DB_PATH, PROJECT_ROOT, TEMPLATES_DIR, TRADE_LOG_DIR,
    Settings, get_settings,
)

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Symbols whose bar age we use as a "data freshness" heartbeat.
# Pinned to liquid mega-caps + SPY because they trade every session.
_HEARTBEAT_SYMBOLS = ("SPY", "AAPL")


@router.get("/system-health", response_class=HTMLResponse)
async def system_health_page(request: Request, s: Settings = Depends(get_settings)):
    started = time.monotonic()

    sched = _scheduler_block()
    broker = await _broker_block()
    data = await _data_freshness_block()
    alerts = await _alert_pipeline_block()
    disk = _disk_block()
    errors = _errors_block()

    overall = _overall_health(sched, broker, data, alerts)

    return templates.TemplateResponse(
        request=request,
        name="system_health.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "system_health",
            "overall": overall,
            "scheduler": sched,
            "broker":    broker,
            "data":      data,
            "alerts":    alerts,
            "disk":      disk,
            "errors":    errors,
            "render_ms": round((time.monotonic() - started) * 1000, 1),
            "now_utc":   datetime.now(timezone.utc).isoformat(),
        },
    )


# --------------------------------------------------------------------------- #
# Section blocks
# --------------------------------------------------------------------------- #


def _scheduler_block() -> dict:
    try:
        from services.scheduler import get_scheduler
        sched = get_scheduler()
        if not sched:
            return {"ok": False, "running": False, "reason": "scheduler not initialized"}
        jobs = sched.get_jobs()
        next_fires = [j.next_run_time for j in jobs if j.next_run_time is not None]
        next_one = min(next_fires) if next_fires else None
        return {
            "ok":         sched.running,
            "running":    sched.running,
            "job_count":  len(jobs),
            "active_jobs": sum(1 for j in jobs if j.next_run_time is not None),
            "paused":     sum(1 for j in jobs if j.next_run_time is None),
            "next_fire":  next_one.isoformat() if next_one else None,
        }
    except Exception as e:                                            # noqa: BLE001
        return {"ok": False, "error": str(e)}


async def _broker_block() -> dict:
    try:
        from services.broker_service import get_adapter, TRADING_HALTED
        adapter = get_adapter()
        if not adapter.connected:
            try:
                await adapter.connect()
            except Exception as e:                                    # noqa: BLE001
                return {"ok": False, "broker_name": adapter.broker_name,
                        "connected": False, "halted": TRADING_HALTED, "error": str(e)}
        st = await adapter.get_account_state()
        return {
            "ok":          True,
            "broker_name": adapter.broker_name,
            "connected":   True,
            "halted":      TRADING_HALTED,
            "account_id":  st.account_id,
            "equity":      st.equity,
            "buying_power": st.buying_power,
            "open_positions": len(st.open_positions),
        }
    except Exception as e:                                            # noqa: BLE001
        return {"ok": False, "error": str(e)}


@router.get("/api/data-freshness", response_class=JSONResponse)
async def api_data_freshness() -> dict:
    """Compact market-data freshness for the whole app (heartbeat symbols,
    daily bars): {as_of, stale, ...}. Powers the topbar badge."""
    import asyncio as _a
    from services import data_service
    return await _a.to_thread(
        data_service.market_data_freshness, list(_HEARTBEAT_SYMBOLS), "1d")


@router.get("/api/data-freshness/badge", response_class=HTMLResponse)
async def api_data_freshness_badge() -> HTMLResponse:
    """HTML partial for the topbar 'Data as of …' badge (HTMX-polled)."""
    import asyncio as _a
    from services import data_service
    f = await _a.to_thread(
        data_service.market_data_freshness, list(_HEARTBEAT_SYMBOLS), "1d")
    if f["as_of"] is None:
        return HTMLResponse(
            '<span class="dot gray"></span>'
            '<span title="no cached market data yet">Data —</span>')
    stale = f["stale"]
    cls = "red" if stale else "green"
    label = ("⚠ Data " if stale else "Data ") + f["as_of"]
    title = (f"Market data as of {f['as_of']} "
             f"(heartbeat: {', '.join(_HEARTBEAT_SYMBOLS)}). "
             + ("STALE — refresh is failing; strategies SKIP stale symbols so "
                "no trade is created on old data."
                if stale else "fresh."))
    return HTMLResponse(f'<span class="dot {cls}"></span>'
                        f'<span title="{title}">{label}</span>')


async def _data_freshness_block() -> dict:
    """Return age (seconds) of the most recent bar per heartbeat sym + interval.

    Stale 30m data on a trading day is the most common reason DL silently
    misfires — surface it loudly here.
    """
    out = {"ok": True, "rows": []}
    try:
        from services import data_service
        for sym in _HEARTBEAT_SYMBOLS:
            for interval in ("30m", "1d"):
                try:
                    df = await data_service.get_bars(sym, interval, min_bars=1)
                    if df is None or df.empty:
                        out["rows"].append({"symbol": sym, "interval": interval,
                                            "ok": False, "reason": "empty"})
                        out["ok"] = False
                        continue
                    last_ts = df.index[-1]
                    if last_ts.tz is None:
                        last_ts = last_ts.tz_localize("UTC")
                    age = pd.Timestamp.now(tz="UTC") - last_ts.tz_convert("UTC")
                    age_h = age.total_seconds() / 3600.0
                    out["rows"].append({
                        "symbol":   sym,
                        "interval": interval,
                        "ok":       True,
                        "last_ts":  last_ts.isoformat(),
                        "age_hours": round(age_h, 1),
                        "stale":    age_h > (50 if interval == "30m" else 120),
                    })
                except Exception as e:                                # noqa: BLE001
                    out["rows"].append({"symbol": sym, "interval": interval,
                                        "ok": False, "reason": str(e)})
                    out["ok"] = False
    except Exception as e:                                            # noqa: BLE001
        return {"ok": False, "error": str(e)}
    return out


async def _alert_pipeline_block() -> dict:
    try:
        from services import alert_service
        recent = await alert_service.list_alerts(only_unread=False, limit=1)
        last_alert = recent[0] if recent else None
        return {
            "ok": True,
            "last_alert_ts": (last_alert or {}).get("ts"),
            "last_alert_kind": (last_alert or {}).get("kind"),
            "last_alert_symbol": (last_alert or {}).get("symbol"),
            "ntfy_topic": None,  # populated below
        }
    except Exception as e:                                            # noqa: BLE001
        return {"ok": False, "error": str(e)}


def _disk_block() -> dict:
    """Disk usage rollup — how big is each thing."""
    out = {"ok": True, "rows": []}
    candidates = [
        ("trade_logs",      TRADE_LOG_DIR),
        ("data/historical", DATA_DIR / "historical"),
        ("data/news_cache", DATA_DIR / "news_cache"),
        ("data/edgar_cache", DATA_DIR / "edgar_cache"),
        ("sqlite db",       LOCAL_DB_PATH),
    ]
    for label, path in candidates:
        try:
            if not path.exists():
                out["rows"].append({"label": label, "exists": False, "size_mb": 0, "files": 0})
                continue
            if path.is_file():
                size = path.stat().st_size
                out["rows"].append({"label": label, "exists": True,
                                    "size_mb": round(size / 1024 / 1024, 2), "files": 1})
            else:
                total = 0
                count = 0
                for p in path.rglob("*"):
                    if p.is_file():
                        try:
                            total += p.stat().st_size
                            count += 1
                        except OSError:
                            pass
                out["rows"].append({"label": label, "exists": True,
                                    "size_mb": round(total / 1024 / 1024, 2), "files": count})
        except Exception as e:                                        # noqa: BLE001
            out["rows"].append({"label": label, "exists": False, "error": str(e)})
            out["ok"] = False
    return out


def _errors_block() -> dict:
    """Read recent log lines from job_log_buffer and count error-level entries."""
    try:
        from services.job_log_buffer import _buffers
        # Crude scan: count lines with "ERROR" or "WARNING" in the global buffer
        # (the buffer is per-job; aggregate across all of them).
        total_lines = 0
        warns = 0
        errs = 0
        last_err = None
        for job_id, buf in _buffers.items():
            for line in buf:
                total_lines += 1
                if "ERROR" in line or "Traceback" in line:
                    errs += 1
                    last_err = (job_id, line)
                elif "WARNING" in line:
                    warns += 1
        return {
            "ok": True,
            "lines_buffered": total_lines,
            "errors": errs,
            "warnings": warns,
            "last_error_job": last_err[0] if last_err else None,
            "last_error_line": last_err[1] if last_err else None,
        }
    except Exception as e:                                            # noqa: BLE001
        return {"ok": False, "error": str(e)}


def _overall_health(*sections) -> dict:
    """Roll up section.ok flags into a single status."""
    failed = [s for s in sections if not s.get("ok", False)]
    return {
        "all_ok":     not failed,
        "fail_count": len(failed),
        "verdict":    "OK" if not failed else f"DEGRADED ({len(failed)} subsystem{'s' if len(failed) != 1 else ''})",
    }
