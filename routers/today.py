"""today router — live "what's happening now" cockpit.

Single page composed of real-time data from existing services:
  * Macro context: SPY trend + VIX level + DL regime gate verdict
  * Today's pending approvals (from SQLite)
  * Today's alerts (from dl_alerts)
  * Open positions + today's fills (from broker adapter)
  * Today's scheduled jobs (next-fire times for DL Lock 1 + workflow crons)

Auto-refreshes every 30s via HTMX so the user can leave the page open
during the 9:30-10:30 ET window and see the strategy unfold.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from services.settings_service import TEMPLATES_DIR, Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/today", response_class=HTMLResponse)
async def today_page(request: Request, s: Settings = Depends(get_settings)):
    ctx = await _today_context()
    ctx.update({
        "settings": s,
        "app_version": "0.1.0",
        "active_page": "today",
    })
    return templates.TemplateResponse(request=request, name="today.html", context=ctx)


@router.get("/api/today/data", response_class=HTMLResponse)
async def today_data(request: Request, s: Settings = Depends(get_settings)):
    """HTMX-polled partial — returns just the cockpit panels (no shell)."""
    ctx = await _today_context()
    ctx.update({"settings": s})
    return templates.TemplateResponse(
        request=request, name="today/_panels.html", context=ctx,
    )


# --------------------------------------------------------------------------- #
# Composition
# --------------------------------------------------------------------------- #


async def _today_context() -> dict:
    """Compose every data source the page needs. Each branch wrapped in
    try/except so a single broken service doesn't dark the whole cockpit."""
    today_et = datetime.now().astimezone().date()

    return {
        "today_iso":       today_et.isoformat(),
        "now_utc":         datetime.now(timezone.utc).isoformat(),
        "macro":           await _macro_block(),
        "regime_gate":     await _regime_gate_block(),
        "pending":         await _pending_block(),
        "alerts":          await _alerts_block(),
        "positions":       await _positions_block(),
        "fills_today":     await _fills_block(today_et),
        "jobs_today":      await _jobs_block(today_et),
        "broker_status":   await _broker_status_block(),
    }


async def _macro_block() -> dict:
    try:
        from agents.macro import compute_macro_context
        as_of = pd.Timestamp.now(tz="UTC")
        m = await compute_macro_context(as_of_ts=as_of)
        return {
            "vix_level":    m.get("vix_level"),
            "vix_regime":   m.get("vix_regime"),
            "spy_trend_20d": m.get("spy_trend_20d"),
            "spy_above_sma200": m.get("spy_above_sma200"),
            "ok": True,
        }
    except Exception as e:                                            # noqa: BLE001
        return {"ok": False, "error": str(e)}


async def _regime_gate_block() -> dict:
    """Evaluate the DL strategy's regime gate against current macro.

    Returns whether DL would fire today regardless of candle conditions —
    this is the most operationally useful number ('would the strategy try
    to trade today?')."""
    try:
        import yaml
        from services.settings_service import STRATEGY_CONFIG_DIR
        cfg = yaml.safe_load((STRATEGY_CONFIG_DIR / "double_lock.yaml").read_text(encoding="utf-8"))
        thr = cfg.get("thresholds") or {}
        vix_min = float(thr.get("vix_min", 20.0))

        macro = await _macro_block()
        if not macro.get("ok"):
            return {"ok": False, "reason": "macro unavailable"}

        vix = macro.get("vix_level") or 0
        passes = vix >= vix_min
        return {
            "ok": True,
            "passes": passes,
            "strategy": "double_lock",
            "vix_now": vix,
            "vix_min": vix_min,
            "verdict": "PASS" if passes else "BLOCKED",
            "reason": (
                "VIX clears the regime floor — DL is eligible to fire if candles align"
                if passes else
                f"VIX {vix:.2f} below floor {vix_min:.0f} — DL will not fire today"
            ),
        }
    except Exception as e:                                            # noqa: BLE001
        return {"ok": False, "error": str(e)}


async def _pending_block() -> list[dict]:
    try:
        from services import db_service
        rows = await db_service.list_pending_approvals(status="pending", limit=10)
        return [{
            "plan_id":     r.get("plan_id"),
            "symbol":      r.get("symbol"),
            "direction":   r.get("direction"),
            "strategy":    r.get("strategy_name") or r.get("strategy"),
            "entry_price": r.get("entry_price"),
            "ts_created":  r.get("ts_created"),
        } for r in rows]
    except Exception as e:                                            # noqa: BLE001
        logger.warning("today: pending fetch failed: %s", e)
        return []


async def _alerts_block() -> list[dict]:
    try:
        from services import alert_service
        return await alert_service.list_alerts(only_unread=False, limit=15)
    except Exception as e:                                            # noqa: BLE001
        logger.warning("today: alerts fetch failed: %s", e)
        return []


async def _positions_block() -> list[dict]:
    try:
        from services.broker_service import get_adapter
        adapter = get_adapter()
        if not adapter.connected:
            await adapter.connect()
        st = await adapter.get_account_state()
        return [{
            "symbol":          p.symbol,
            "shares":          p.shares,
            "avg_entry_price": p.avg_entry_price,
            "market_price":    p.market_price,
            "unrealized_pnl":  p.unrealized_pnl_usd,
        } for p in st.open_positions]
    except Exception as e:                                            # noqa: BLE001
        logger.warning("today: positions fetch failed: %s", e)
        return []


async def _fills_block(today_et: date) -> list[dict]:
    try:
        from services.broker_service import get_adapter
        adapter = get_adapter()
        if not adapter.connected:
            await adapter.connect()
        # Filter to today's fills (broker returns ISO timestamps)
        cutoff_iso = datetime(today_et.year, today_et.month, today_et.day).isoformat()
        all_fills = await adapter.get_fills(since_ts=cutoff_iso)
        return [{
            "symbol":   f.symbol,
            "side":     f.side,
            "shares":   f.shares,
            "price":    f.price,
            "ts_filled": f.ts_filled,
        } for f in all_fills]
    except Exception as e:                                            # noqa: BLE001
        logger.warning("today: fills fetch failed: %s", e)
        return []


async def _jobs_block(today_et: date) -> list[dict]:
    """Today's scheduled job fire times (only the ones already registered)."""
    try:
        from services.scheduler import get_scheduler
        sched = get_scheduler()
        if not sched:
            return []
        out = []
        for j in sched.get_jobs():
            nrt = j.next_run_time
            if nrt is None:
                continue
            # Only include jobs firing today
            if nrt.astimezone().date() != today_et:
                continue
            out.append({
                "id":       j.id,
                "name":     j.name or j.id,
                "next_run": nrt.isoformat(),
            })
        out.sort(key=lambda d: d["next_run"])
        return out
    except Exception as e:                                            # noqa: BLE001
        logger.warning("today: jobs fetch failed: %s", e)
        return []


async def _broker_status_block() -> dict:
    try:
        from services.broker_service import get_adapter
        adapter = get_adapter()
        return {
            "broker_name": adapter.broker_name,
            "connected":   adapter.connected,
        }
    except Exception as e:                                            # noqa: BLE001
        return {"broker_name": "unknown", "connected": False, "error": str(e)}
