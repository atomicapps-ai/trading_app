"""Dashboard router — stat cards, agent status, today's activity, open positions.

Plus the new modular widget system (services.dashboard_widgets):
  GET /api/dashboard/widgets/{id} dispatches to the matching Widget
  subclass; the dashboard template iterates ``WIDGETS`` and renders an
  HTMX-driven placeholder for each. New monitoring tiles (sector heatmap,
  Fear/Greed, SPY trend, etc.) ship as Widget subclasses without
  touching this router.

Stub-backed sections (Pending, Open positions, Agent status, Activity)
will migrate to widgets as they're touched. v1 keeps both side-by-side
to minimize blast radius.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from services import widget_settings as ws
from services.dashboard_widgets import (
    LAYOUT_WIDGET_ID,
    TAB_ORDER,
    get_widget,
    widgets_by_tab_for_user,
)
from services.indicator_registry import INDICATORS, indicators_by_category
from services.settings_service import TEMPLATES_DIR, Settings, get_settings
from services.stub_data import (
    STUB_ACCOUNT,
    STUB_OPEN_POSITIONS,
    STUB_PENDING,
)

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, s: Settings = Depends(get_settings)):
    account = await _real_account_or_stub()
    pending = await _real_pending_or_stub()
    positions = await _real_positions_or_stub()
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "dashboard",
            "account": account,
            "pending": pending,
            "open_positions": positions,
            # Widgets organized by tab. Returned as descriptor dicts that
            # already carry user-applied size overrides + saved order.
            "tabs": TAB_ORDER,
            "widgets_by_tab": await widgets_by_tab_for_user(),
        },
    )


async def _real_account_state():
    """Helper — returns (AccountState, error_string_or_None). Errors are
    captured so the caller can decide between real-with-positions, account-only,
    or full stub fallback."""
    try:
        from services.broker_service import get_adapter
        adapter = get_adapter()
        if not adapter.connected:
            await adapter.connect()
        return await adapter.get_account_state(), None
    except Exception as e:                                            # noqa: BLE001
        return None, str(e)


async def _real_account_or_stub() -> dict:
    """Return the dict shape ``templates/dashboard/_stats.html`` expects,
    populated from live broker state when available. Field names mirror
    the legacy STUB_ACCOUNT so the template never has to know which path
    produced the values."""
    st, err = await _real_account_state()
    if st is None:
        logger.warning("dashboard: real account fetch failed (%s); using stub", err)
        return {**STUB_ACCOUNT, "is_real": False}

    # Pull the operator's max-position cap out of risk_defaults so the
    # "open / max" widget shows a meaningful denominator.
    try:
        from services.settings_service import get_settings
        max_positions = get_settings().risk_defaults.max_open_positions
    except Exception:                                                 # noqa: BLE001
        max_positions = 8

    equity = st.equity or 0.0
    unreal = st.unrealized_pnl_today or 0.0
    return {
        # Real fields (used directly by the template)
        "account_id":     st.account_id,
        "broker":         st.broker,
        "type":           st.type,
        "equity":         equity,
        "cash":           st.cash,
        "buying_power":   st.buying_power,
        "open_positions": len(st.open_positions),
        "max_positions":  max_positions,
        "trades_today":   st.trades_today,
        "unrealized_pnl": unreal,
        # TRUE day P&L = equity − prior-close equity (AccountState.day_pnl_usd),
        # matching the live status bar. Falls back to unrealized for brokers
        # that don't report last_equity.
        "day_pnl_usd":    st.day_pnl_usd,
        "day_pnl_pct":    st.day_pnl_pct,
        "mode":           st.mode if hasattr(st, "mode") else "paper",
        "connected":      True,
        "is_real":        True,
    }


async def _real_pending_or_stub() -> list[dict]:
    """Live pending approvals from SQLite (pending_approvals table).

    Returns an empty list when there are no real pending plans — never
    falls back to STUB_PENDING. The previous fallback was a bug: it
    silently displayed fake NVDA + SPY rows whenever the DB read raised
    AttributeError on a misspelled function name.

    Shape mirrors the keys ``templates/dashboard/_pending.html`` reads.
    """
    try:
        from services import db_service
        rows = await db_service.get_pending_plans(status_filter="pending", limit=20)
    except Exception as e:                                            # noqa: BLE001
        logger.warning("dashboard: real pending fetch failed (%s)", e)
        return []
    out: list[dict] = []
    for r in rows:
        out.append({
            "plan_id":      r.get("plan_id"),
            "symbol":       r.get("symbol"),
            "direction":    r.get("direction"),
            "strategy":     r.get("strategy"),
            "conviction":   r.get("conviction") or 0.0,
            "entry":        r.get("entry"),
            "stop":         r.get("stop"),
            "tp1":          r.get("tp1"),
            "tp2":          r.get("tp2"),
            "risk_usd":     r.get("risk_usd") or 0.0,
            "rr_tp1":       r.get("rr_tp1") or 0.0,
            "position_size": r.get("position_size") or 0,
            "ts_created":   r.get("ts_created"),
            "compliance":   r.get("compliance"),
            "risk_result":  r.get("risk_result"),
        })
    return out


async def _real_positions_or_stub() -> list[dict]:
    """Live open positions — pulled out of AccountState which the broker
    adapter populates with the live position list (not just a count).

    Shape mirrors STUB_OPEN_POSITIONS so ``dashboard.html`` doesn't have
    to know whether the source was live or stub. Fields the broker
    doesn't carry (stop, strategy, pnl_r) get sensible defaults —
    enrichment from pending_approvals + plan_json is a follow-up.
    """
    st, err = await _real_account_state()
    if st is None:
        logger.warning("dashboard: real positions fetch failed (%s); using stub", err)
        return STUB_OPEN_POSITIONS
    if not st.open_positions:
        return []                                                     # genuinely 0 positions

    # Enrichment index: every broker position carries only symbol / qty /
    # entry / market price. The stop, strategy, TP and originating plan_id
    # live in the TradePlan that opened it. Build a symbol -> plan map from
    # pending_approvals so we can back-fill those fields and make each row
    # openable. Positions with NO matching plan (manual buys, smoke-script
    # leftovers, broker-side fills) are flagged origin="manual" so the UI
    # can still open a detail view instead of a dead end.
    plan_by_symbol = await _plan_index_by_symbol()

    rows: list[dict] = []
    for p in st.open_positions:
        entry = float(p.avg_entry_price or 0.0)
        current = float(p.market_price or 0.0)
        shares = int(p.shares or 0)
        direction = "long" if shares >= 0 else "short"
        pnl_pct = ((current - entry) / entry * 100.0) if entry else 0.0
        if direction == "short":
            pnl_pct = -pnl_pct

        plan = plan_by_symbol.get(p.symbol.upper())
        stop = float(plan.get("stop") or 0.0) if plan else 0.0
        strategy = (plan.get("strategy") if plan else "") or ""
        plan_id = plan.get("plan_id") if plan else None
        # R-multiple only meaningful once we know the planned stop.
        pnl_r = 0.0
        if stop and entry and abs(entry - stop) > 1e-9:
            r_per_share = abs(entry - stop)
            pnl_r = (current - entry) / r_per_share
            if direction == "short":
                pnl_r = -pnl_r

        rows.append({
            "symbol":     p.symbol,
            "direction":  direction,
            "shares":     abs(shares),
            "entry":      entry,
            "current":    current,
            "pnl_usd":    float(p.unrealized_pnl_usd or 0.0),
            "pnl_pct":    pnl_pct,
            "pnl_r":      round(pnl_r, 2),
            "stop":       stop,
            "strategy":   strategy,
            "sector":     p.sector or "",
            # Openability / provenance
            "plan_id":    plan_id,
            "tp1":        float(plan.get("tp1") or 0.0) if plan else 0.0,
            "origin":     "strategy" if plan_id else "manual",
            # Where the row links: the trade detail page when a plan exists,
            # else the orphan position detail page (symbol-keyed).
            "detail_url": f"/trades/{plan_id}" if plan_id
                          else f"/positions/{p.symbol.upper()}",
        })
    return rows


async def _plan_index_by_symbol() -> dict[str, dict]:
    """Map SYMBOL -> {plan_id, strategy, stop, tp1} for open/approved/pending
    plans, so dashboard positions can be back-filled from the TradePlan that
    opened them. Most-recent plan per symbol wins.

    Matching is by symbol (a position is one net line per symbol at the
    broker; we don't get a plan_id back on the fill). Good enough for the
    single-user tool — a symbol rarely has two live strategy plans at once.
    """
    from services import db_service
    index: dict[str, dict] = {}
    try:
        # Newest first across the stages a live position could map to.
        for status in ("open", "filled", "approved", "pending"):
            for row in await db_service.get_pending_plans(status_filter=status, limit=200):
                sym = (row.get("symbol") or "").upper()
                if not sym or sym in index:
                    continue
                index[sym] = {
                    "plan_id":  row.get("plan_id"),
                    "strategy": row.get("strategy"),
                    "stop":     row.get("stop"),
                    "tp1":      row.get("tp1"),
                }
    except Exception as e:                                             # noqa: BLE001
        logger.warning("dashboard: plan index build failed: %s", e)
    return index


@router.get("/api/dashboard/widgets/{widget_id}", response_class=HTMLResponse)
async def dashboard_widget(widget_id: str, request: Request):
    """Dispatch to the registered Widget — render its partial with its data.

    Failures inside a single widget are isolated: the widget renders an
    error card, the rest of the dashboard is unaffected.
    """
    widget = get_widget(widget_id)
    if widget is None:
        raise HTTPException(status_code=404, detail=f"unknown widget: {widget_id}")
    try:
        ctx = await widget.get_data()
    except Exception as exc:                              # noqa: BLE001
        logger.exception("widget %s get_data raised", widget_id)
        return templates.TemplateResponse(
            request=request,
            name="dashboard/widgets/_error.html",
            context={"widget_id": widget_id, "error": str(exc)},
        )
    return templates.TemplateResponse(
        request=request, name=widget.template, context=ctx,
    )


# --------------------------------------------------------------------------- #
# Per-widget user settings (⚙ panel)
# --------------------------------------------------------------------------- #


@router.get("/api/dashboard/widgets/{widget_id}/settings", response_class=HTMLResponse)
async def widget_settings_panel(widget_id: str, request: Request):
    """Render the settings modal body for any widget.

    All widgets get a panel: configurable widgets see their schema-driven
    form on top of the universal section (size cycle, refresh interval,
    reset). Non-configurable widgets just see the universal section.
    """
    widget = get_widget(widget_id)
    if widget is None:
        raise HTTPException(404, f"unknown widget: {widget_id}")
    current = await widget.resolve_settings() if widget.settings_schema else {}
    saved_layout = await ws.get_all("default", LAYOUT_WIDGET_ID)
    current_size = saved_layout.get(f"{widget_id}.size") or widget.size
    return templates.TemplateResponse(
        request=request,
        name="dashboard/_widget_settings.html",
        context={
            "widget": widget,
            "current": current,
            "current_size": current_size,
            "indicators_by_category": indicators_by_category(),
            "all_indicators": list(INDICATORS.values()),
        },
    )


@router.post("/api/dashboard/widgets/{widget_id}/settings", response_class=JSONResponse)
async def widget_settings_save(widget_id: str, request: Request):
    """Persist user settings for a widget. Body: JSON dict of key->value.

    Only keys declared in the widget's ``settings_schema`` are accepted —
    extra keys are silently dropped (defensive).
    """
    widget = get_widget(widget_id)
    if widget is None:
        raise HTTPException(404, f"unknown widget: {widget_id}")
    if not widget.user_configurable:
        # Non-configurable widgets accept no per-widget keys; their size
        # override goes through the layout endpoint.
        return {"saved": [], "ignored": list((await request.json()).keys())
                if request else []}
    try:
        payload: dict[str, Any] = await request.json()
    except Exception:                                          # noqa: BLE001
        raise HTTPException(400, "invalid JSON body")

    allowed = set(widget.settings_schema.keys())
    accepted = {k: v for k, v in payload.items() if k in allowed}
    if accepted:
        await ws.set_many("default", widget_id, accepted)
    return {"saved": list(accepted.keys()), "ignored":
            [k for k in payload if k not in allowed]}


@router.delete("/api/dashboard/widgets/{widget_id}/settings",
               response_class=JSONResponse)
async def widget_settings_reset(widget_id: str):
    """Drop every saved override for this widget plus its layout state."""
    widget = get_widget(widget_id)
    if widget is None:
        raise HTTPException(404, f"unknown widget: {widget_id}")
    await ws.reset_widget("default", widget_id)
    # Also drop the per-widget size override stored under __layout__.
    await ws.delete("default", LAYOUT_WIDGET_ID, f"{widget_id}.size")
    return {"reset": True}


# --------------------------------------------------------------------------- #
# Layout — drag-to-reorder + per-widget size cycle
# --------------------------------------------------------------------------- #


@router.post("/api/dashboard/layout", response_class=JSONResponse)
async def dashboard_layout_save(request: Request):
    """Persist layout changes. Body shape:

        {
          "tab": "market",                         # optional, with "order"
          "order": ["sector_heatmap", "fear_greed", ...],   # new order
          "size": {"widget_id": "sm" | "md" | "lg" | "wide"} # optional
        }

    Either or both keys are accepted. Unknown widget ids and bad sizes
    are silently dropped — defensive against stale frontend caches.
    """
    try:
        payload: dict[str, Any] = await request.json()
    except Exception:                                          # noqa: BLE001
        raise HTTPException(400, "invalid JSON body")

    tab = payload.get("tab")
    order = payload.get("order")
    size = payload.get("size") or {}

    valid_widget_ids = {w.id for w in
                        __import__("services.dashboard_widgets",
                                    fromlist=["WIDGETS"]).WIDGETS}
    valid_sizes = {"sm", "md", "lg", "wide"}
    valid_tabs = {t for t, _ in TAB_ORDER}

    updates: dict[str, Any] = {}
    if tab in valid_tabs and isinstance(order, list):
        clean_order = [w for w in order
                       if isinstance(w, str) and w in valid_widget_ids]
        updates[f"{tab}.order"] = clean_order
    if isinstance(size, dict):
        for wid, val in size.items():
            if wid in valid_widget_ids and val in valid_sizes:
                updates[f"{wid}.size"] = val

    if updates:
        await ws.set_many("default", LAYOUT_WIDGET_ID, updates)
    return {"saved": list(updates.keys())}


@router.delete("/api/dashboard/layout", response_class=JSONResponse)
async def dashboard_layout_reset():
    """Drop every layout override (order + size) — back to defaults."""
    await ws.reset_widget("default", LAYOUT_WIDGET_ID)
    return {"reset": True}


@router.get("/api/dashboard/stats", response_class=HTMLResponse)
async def dashboard_stats(request: Request):
    """HTMX-polled stats card. Pulls live account state on every poll."""
    return templates.TemplateResponse(
        request=request,
        name="dashboard/_stats.html",
        context={"account": await _real_account_or_stub()},
    )


@router.get("/api/dashboard/agents", response_class=HTMLResponse)
async def dashboard_agents(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="dashboard/_agents.html",
        context={"agents": await _real_agents()},
    )


@router.get("/api/dashboard/activity", response_class=HTMLResponse)
async def dashboard_activity(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="dashboard/_activity.html",
        context={"activity": await _real_activity(limit=10)},
    )


# --------------------------------------------------------------------------- #
# Real-data helpers for the agents + activity cards
# --------------------------------------------------------------------------- #


async def _real_agents() -> list[dict]:
    """Build the agents card from registered scheduler jobs + last
    pipeline_runs status. Each scheduler workflow job appears as one row;
    status is green / amber / red depending on whether its last run
    succeeded, hasn't run yet, or errored.

    Falls back to a static "agents not yet started" list on any error.
    """
    try:
        from services import db_service
        from services.scheduler import get_scheduler

        sched = get_scheduler()
        jobs = sched.get_jobs() if sched.running else []
        runs = await db_service.list_pipeline_runs(limit=200)
        runs_by_workflow: dict[str, dict] = {}
        for r in runs:
            wf = r.get("workflow_id")
            if wf and wf not in runs_by_workflow:
                runs_by_workflow[wf] = r

        # Workflow scheduler jobs are id-prefixed `wf_` per scheduler.py
        rows: list[dict] = []
        for j in jobs:
            jid = getattr(j, "id", "")
            if not jid.startswith("wf_"):
                continue
            workflow_id = jid[len("wf_"):]
            last = runs_by_workflow.get(workflow_id)
            if last is None:
                status = "amber"
                detail = f"next: {_fmt_next_run(j.next_run_time)}"
            elif (last.get("status") or "").lower() in ("error", "failed"):
                status = "red"
                detail = f"last err: {(last.get('error_message') or '').splitlines()[0][:60]}"
            else:
                ts = last.get("ts_end") or last.get("ts_start") or ""
                status = "green"
                from services.stub_data import time_ago
                detail = (
                    f"{last.get('signals_generated', 0)} sig · "
                    f"{last.get('plans_proposed', 0)} plans · "
                    f"{time_ago(ts) if ts else 'recent'}"
                )
            rows.append({
                "name": workflow_id.replace("_", " "),
                "status": status,
                "detail": detail,
            })

        # If no workflow jobs are registered (research mode, fresh boot)
        # show the broker connection as a single "agent" so the card
        # isn't empty.
        if not rows:
            from services.broker_service import get_adapter
            adapter = get_adapter()
            rows.append({
                "name": adapter.broker_name,
                "status": "green" if adapter.connected else "amber",
                "detail": "connected" if adapter.connected else "not connected",
            })
        return rows
    except Exception as e:                                            # noqa: BLE001
        logger.warning("dashboard: agents fetch failed (%s)", e)
        return [{"name": "agents", "status": "amber",
                 "detail": "no recent runs"}]


def _fmt_next_run(dt) -> str:
    if dt is None:
        return "—"
    try:
        from datetime import datetime, timezone
        delta = dt - datetime.now(dt.tzinfo or timezone.utc)
        secs = int(delta.total_seconds())
        if secs < 0:
            return "due"
        if secs < 60:
            return f"in {secs}s"
        if secs < 3600:
            return f"in {secs // 60}m"
        if secs < 86400:
            return f"in {secs // 3600}h"
        return f"in {secs // 86400}d"
    except Exception:                                                 # noqa: BLE001
        return "—"


async def _real_activity(limit: int = 10) -> list[dict]:
    """Build a unified activity feed from three real sources:

      1. dl_alerts (armed / filled / closed / lock1_scouted)
      2. pipeline_runs (workflow completes)
      3. broker fills since midnight ET today

    Sorts newest-first by ISO timestamp, returns top N as the dict shape
    ``templates/dashboard/_activity.html`` expects: ``{ts, kind, text}``.
    """
    from datetime import datetime, time, timezone

    items: list[dict] = []

    # --- Alerts -----------------------------------------------------------
    try:
        from services import alert_service
        alerts = await alert_service.list_alerts(limit=limit * 2)
        for a in alerts:
            kind_map = {
                "armed":          "plan",
                "lock1_scouted":  "signal",
                "filled":         "fill",
                "closed":         "fill",
                "test":           "signal",
            }
            items.append({
                "_ts_iso": a.get("ts", ""),
                "ts":      _hhmm(a.get("ts", "")),
                "kind":    kind_map.get(a.get("kind", ""), "signal"),
                "text":    a.get("title") or f"{a.get('kind')} {a.get('symbol') or ''}",
            })
    except Exception as e:                                            # noqa: BLE001
        logger.debug("activity: alerts source failed (%s)", e)

    # --- Pipeline runs ----------------------------------------------------
    try:
        from services import db_service
        runs = await db_service.list_pipeline_runs(limit=limit)
        for r in runs:
            ts_iso = r.get("ts_end") or r.get("ts_start") or ""
            wf = r.get("workflow_id") or "workflow"
            sig = r.get("signals_generated") or 0
            plans = r.get("plans_proposed") or 0
            text = f"{wf}: {sig} signals, {plans} plans"
            items.append({
                "_ts_iso": ts_iso,
                "ts":      _hhmm(ts_iso),
                "kind":    "universe" if r.get("status") == "complete" else "block",
                "text":    text,
            })
    except Exception as e:                                            # noqa: BLE001
        logger.debug("activity: pipeline_runs source failed (%s)", e)

    # --- Broker fills (today) ---------------------------------------------
    try:
        from services.broker_service import get_adapter
        adapter = get_adapter()
        if adapter.connected:
            midnight = datetime.combine(
                datetime.now(timezone.utc).date(), time(0, 0),
                tzinfo=timezone.utc,
            ).isoformat()
            fills = await adapter.get_fills(since_ts=midnight)
            for f in fills[:limit]:
                items.append({
                    "_ts_iso": f.ts,
                    "ts":      _hhmm(f.ts),
                    "kind":    "fill",
                    "text":    f"{f.symbol} {f.side} {f.shares} @ {f.price:.2f}",
                })
    except Exception as e:                                            # noqa: BLE001
        logger.debug("activity: fills source failed (%s)", e)

    # Sort newest-first, drop the _ts_iso scratch field.
    items.sort(key=lambda x: x.get("_ts_iso", ""), reverse=True)
    out: list[dict] = []
    for it in items[:limit]:
        out.append({"ts": it["ts"], "kind": it["kind"], "text": it["text"]})
    return out


def _hhmm(iso_ts: str) -> str:
    """Render an ISO timestamp as HH:MM in local time (best-effort)."""
    if not iso_ts:
        return ""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%H:%M")
    except Exception:                                                 # noqa: BLE001
        return ""
