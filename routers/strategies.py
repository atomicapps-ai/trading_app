"""strategies router — list, toggle, and run trading strategies.

Each ``strategy_configs/*.yaml`` file is one strategy (swing_momentum,
double_lock, ...). The page surfaces:
  * description, holding period, mode, active flag
  * which scheduled workflow uses it (and when it next fires)
  * backtest_summary — point WR, CI, profit factor, sample size
  * a Run-now button that triggers the linked workflow ad-hoc

Active toggle persistence
-------------------------
Writing ``active: true/false`` back to the YAML would kill its inline
comments. Instead the user's override is stored under the synthetic
``__strategies__`` widget-id in the existing ``user_widget_settings``
table (same pattern used for dashboard layout). The merged "effective"
active flag = override if set, else YAML's value.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from services import db_service, widget_settings as ws
from services.pipeline_service import run_workflow_by_id
from services.settings_service import (
    STRATEGY_CONFIG_DIR, TEMPLATES_DIR, Settings, get_settings,
)
from services.workflow_engine import WorkflowEngine

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Synthetic widget-id used to store per-strategy overrides in the
# user_widget_settings table. Keys: "<strategy_name>.active" -> bool,
# "<strategy_name>.archived" -> bool (set when user manually archives).
_STRATEGY_OVERRIDES_KEY = "__strategies__"

# Validation thresholds for auto-promotion to the Validated bucket.
# WR is a legacy criterion (the double_lock era claimed 82% win rate). The
# current strategies are payoff-geometry edges that win 25-55% BY DESIGN and
# make money on profit factor / R-multiple — so profit factor, not win rate,
# is the correct validation metric. A high-WR strategy can still validate via
# the legacy WR bar; an explicit ``backtest_summary.validated: true`` always wins.
_VALIDATION_WR_THRESHOLD = 72.0
_VALIDATION_PF_THRESHOLD = 1.20

# Buckets shown as tabs on /strategies/{bucket}
_BUCKETS = ("validated", "in-progress", "archived")
_BUCKET_LABELS = {
    "validated":   "Validated",
    "in-progress": "In Progress",
    "archived":    "Archived",
}


def _classify(cfg: dict, archived_override: bool,
              validation: dict | None = None) -> str:
    """Decide which bucket a strategy belongs to.

    Priority:
      archived   — user explicitly archived
      validated  — the latest APP validation run (strategy_validations) PASSED;
                   this is the earned, data-backed source of truth
      else       — fall back to a config backtest_summary that clears the
                   profit-factor bar (or the legacy WR bar); otherwise in-progress
    """
    if archived_override:
        return "archived"
    # 1) Earned status from a real validation run in the app.
    if validation is not None:
        v = str(validation.get("verdict", "")).lower()
        if v == "validated":
            return "validated"
        if v == "failed":
            return "in-progress"
    # 2) Config backtest_summary fallback (PF is the right metric; WR is legacy).
    bs = cfg.get("backtest_summary") or {}
    pf = bs.get("oos_profit_factor") or bs.get("profit_factor")
    try:
        if pf is not None and float(pf) >= _VALIDATION_PF_THRESHOLD:
            return "validated"
    except (TypeError, ValueError):
        pass
    wr = bs.get("point_wr_pct")
    try:
        if wr is not None and float(wr) >= _VALIDATION_WR_THRESHOLD:
            return "validated"
    except (TypeError, ValueError):
        pass
    return "in-progress"


# --------------------------------------------------------------------------- #
# Loaders
# --------------------------------------------------------------------------- #


def _strategy_files() -> list[Path]:
    return sorted(STRATEGY_CONFIG_DIR.glob("*.yaml"))


def _load_strategy(path: Path) -> dict[str, Any]:
    """Read one strategy YAML. Returns a flattened dict tagged with file metadata.

    Keys outside the YAML payload:
      _name        — file stem (machine name)
      _path        — POSIX path string for diagnostics
    """
    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:                                    # noqa: BLE001
        logger.warning("strategies: bad yaml %s: %s", path.name, e)
        cfg = {"_load_error": str(e)}
    cfg.setdefault("strategy_name", path.stem)
    cfg["_name"] = path.stem
    cfg["_path"] = path.as_posix()
    return cfg


async def _load_workflows() -> list[dict[str, Any]]:
    """Return [{workflow_id, schedule, steps[*].params.strategy, ...}] dicts.

    We use the engine so the parsing matches what the scheduler sees
    at startup.
    """
    engine = WorkflowEngine(get_settings())
    workflows = await engine.list_workflows()
    out: list[dict[str, Any]] = []
    for wf in workflows:
        strategies_used: set[str] = set()
        for s in wf.steps:
            params = s.params or {}
            v = params.get("strategy")
            if v:
                strategies_used.add(str(v))
        out.append({
            "workflow_id": wf.workflow_id,
            "description": wf.description,
            "schedule": wf.schedule,
            "default_mode": wf.default_mode,
            "strategies_used": sorted(strategies_used),
        })
    return out


def _fmt_run(run: dict | None) -> dict | None:
    """Preformat a pipeline_run row for the card's 'Last run' line.

    Renders the timestamp in ET (the market timezone the operator thinks in
    and the timezone the scheduler fires on) and pulls out the result counts.
    """
    if not run:
        return None
    from datetime import datetime, timezone as _tz
    from zoneinfo import ZoneInfo
    import json as _json
    ts = run.get("ts_end") or run.get("ts_start") or ""
    when_et = "—"
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_tz.utc)
        # Pacific time, 12-hour clock (not military), DST-aware label (PST/PDT).
        pt = dt.astimezone(ZoneInfo("America/Los_Angeles"))
        when_et = pt.strftime("%b %d, %Y · %I:%M %p") + f" {pt.tzname() or 'PT'}"
    except (ValueError, TypeError):
        pass
    try:
        blocked = len(_json.loads(run.get("plans_blocked_json") or "[]"))
    except Exception:                                             # noqa: BLE001
        blocked = 0
    return {
        "run_id": run.get("run_id"),
        "workflow_id": run.get("workflow_id"),
        "when_et": when_et,
        "status": run.get("status") or "?",
        "error": run.get("error_message"),
        "symbols": run.get("symbols_analyzed") or 0,
        "signals": run.get("signals_generated") or 0,
        "plans": run.get("plans_proposed") or 0,
        "approved": run.get("plans_approved") or 0,
        "blocked": blocked,
    }


def _pt_date(ts: str | None) -> str:
    """A UTC/ISO timestamp → 'Jul 07, 2026' in Pacific time."""
    from datetime import datetime, timezone as _tz
    from zoneinfo import ZoneInfo
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_tz.utc)
        return dt.astimezone(ZoneInfo("America/Los_Angeles")).strftime("%b %d, %Y")
    except (ValueError, TypeError):
        return str(ts or "")[:10]


def _job_for_workflow(workflow_id: str) -> dict[str, Any] | None:
    """Look up the live APScheduler job for this workflow id, if any."""
    try:
        from services.scheduler import get_scheduler
        sched = get_scheduler()
        job = sched.get_job(f"wf_{workflow_id}")
        if job is None:
            return None
        return {
            "id": job.id,
            "name": job.name,
            "next_run_time": (
                job.next_run_time.isoformat() if job.next_run_time else None
            ),
            "trigger": str(job.trigger),
        }
    except Exception as e:                                    # noqa: BLE001
        logger.debug("scheduler unavailable: %s", e)
        return None


async def _resolve_active(name: str, yaml_default: bool) -> tuple[bool, bool]:
    """Return (effective_active, has_override) for one strategy."""
    saved = await ws.get("default", _STRATEGY_OVERRIDES_KEY, f"{name}.active")
    if saved is None:
        return bool(yaml_default), False
    return bool(saved), True


# --------------------------------------------------------------------------- #
# HTML page
# --------------------------------------------------------------------------- #


async def _bucket_counts() -> dict[str, int]:
    """Count strategies in each bucket — used to populate the page-tabs."""
    counts = {b: 0 for b in _BUCKETS}
    validations = await db_service.latest_validations_all()
    for p in _strategy_files():
        c = _load_strategy(p)
        archived = bool(await ws.get("default", _STRATEGY_OVERRIDES_KEY, f"{c['_name']}.archived"))
        v = validations.get(c.get("strategy_name", c["_name"])) or validations.get(c["_name"])
        counts[_classify(c, archived, v)] += 1
    return counts


@router.get("/strategies/validated", response_class=HTMLResponse)
async def strategies_validated_page(request: Request, s: Settings = Depends(get_settings)):
    # Combined "Strategies" view: verified + in-progress on one page (the ✓
    # Validated badge distinguishes them). Archived stays separate.
    return await _strategies_bucket_page(
        request, s, bucket="validated", include={"validated", "in-progress"},
    )


@router.get("/strategies/in-progress", response_class=HTMLResponse)
async def strategies_inprogress_page():
    # In-progress is now merged into the main Strategies page.
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/strategies/validated", status_code=307)


@router.get("/strategies/archived", response_class=HTMLResponse)
async def strategies_archived_page(request: Request, s: Settings = Depends(get_settings)):
    return await _strategies_bucket_page(request, s, bucket="archived")


async def _strategies_bucket_page(request: Request, s: Settings, bucket: str,
                                  include: set[str] | None = None):
    show = include or {bucket}
    if bucket not in _BUCKETS:
        raise HTTPException(404, f"unknown bucket: {bucket}")
    cfgs = [_load_strategy(p) for p in _strategy_files()]
    workflows = await _load_workflows()

    # Build {strategy_name -> [workflow_dict, ...]}
    by_strategy: dict[str, list[dict]] = {}
    for wf in workflows:
        for sname in wf["strategies_used"]:
            by_strategy.setdefault(sname, []).append(wf)

    # Latest pipeline runs from SQLite — anchored to workflow_id so we
    # can show "last run / status" per strategy.
    runs = await db_service.list_pipeline_runs(limit=120)
    latest_by_workflow: dict[str, dict] = {}
    for r in runs:
        wf = r.get("workflow_id")
        if wf and wf not in latest_by_workflow:
            latest_by_workflow[wf] = r

    # Latest earned validation per strategy — drives the bucket + the card.
    validations = await db_service.latest_validations_all()

    rows = []
    for c in cfgs:
        name = c["_name"]
        eff_active, has_override = await _resolve_active(
            name, bool(c.get("active", False)),
        )
        archived = bool(await ws.get("default", _STRATEGY_OVERRIDES_KEY, f"{name}.archived"))
        from services import auto_approve_service as _aas
        auto_approve = await _aas.is_enabled(name)
        validation = validations.get(c.get("strategy_name", name)) or validations.get(name)
        if validation and validation.get("ts"):
            validation = {**validation, "ts_pt": _pt_date(validation.get("ts"))}
        bucket_for_row = _classify(c, archived, validation)
        if bucket_for_row not in show:
            continue
        wfs = by_strategy.get(c.get("strategy_name", name)) or []
        strat_runs = []
        for wf in wfs:
            wf["job"] = _job_for_workflow(wf["workflow_id"])
            lr = latest_by_workflow.get(wf["workflow_id"])
            wf["latest_run"] = lr
            if lr:
                strat_runs.append(lr)
        # Most recent run across all workflows that use this strategy.
        last_run = _fmt_run(
            max(strat_runs, key=lambda r: r.get("ts_start") or "")
        ) if strat_runs else None
        rows.append({
            "name": name,
            "title": c.get("strategy_name", name),
            "description": (c.get("description") or "").strip(),
            "version": c.get("version"),
            "mode": c.get("mode", "research"),
            "holding_period": c.get("holding_period"),
            "style": c.get("style") or ("day_trade" if c.get("holding_period") == "intraday" else "swing"),
            "family": c.get("family"),
            "instrument": c.get("instrument"),
            "direction": c.get("direction"),
            "active": eff_active,
            "active_yaml": bool(c.get("active", False)),
            "active_overridden": has_override,
            "min_signal_strength": c.get("min_signal_strength"),
            "backtest_summary": c.get("backtest_summary") or {},
            "risk": c.get("risk") or {},
            "thresholds": c.get("thresholds") or {},
            "portfolio_rules": c.get("portfolio_rules") or {},
            "workflows": wfs,
            "load_error": c.get("_load_error"),
            "archived": archived,
            "auto_approve": auto_approve,
            "validation": validation,
            "last_run": last_run,
        })

    # Group by style (swing first, then day_trade), then family, then title — so the
    # template can render contiguous "Swing trades" / "Day trades" sections.
    _style_order = {"swing": 0, "day_trade": 1}
    rows.sort(key=lambda r: (_style_order.get(r.get("style"), 2),
                             (r.get("family") or "zz"), r.get("title") or ""))

    counts = await _bucket_counts()
    tabs = [
        {"key": "validated", "label": "Strategies", "href": "/strategies/validated",
         "count": counts.get("validated", 0) + counts.get("in-progress", 0)},
        {"key": "archived", "label": "Archived", "href": "/strategies/archived",
         "count": counts.get("archived", 0)},
    ]
    active_key = {
        "validated": "strategies_validated",
        "in-progress": "strategies_validated",
        "archived": "strategies_archived",
    }[bucket]
    return templates.TemplateResponse(
        request=request,
        name="strategies.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": active_key,
            "active_section": "strategies",
            "tabs": tabs,
            "active_tab": "archived" if bucket == "archived" else "validated",
            "bucket": bucket,
            "bucket_label": "Archived" if bucket == "archived" else "Strategies",
            "strategies": rows,
        },
    )


# --------------------------------------------------------------------------- #
# JSON API
# --------------------------------------------------------------------------- #


@router.get("/api/strategies")
async def list_strategies() -> dict:
    """JSON list of strategies — lightweight version of the page."""
    cfgs = [_load_strategy(p) for p in _strategy_files()]
    out = []
    for c in cfgs:
        eff, _ = await _resolve_active(c["_name"], bool(c.get("active", False)))
        out.append({
            "name": c["_name"],
            "title": c.get("strategy_name", c["_name"]),
            "active": eff,
            "mode": c.get("mode"),
            "holding_period": c.get("holding_period"),
            "description": c.get("description", "").strip(),
            "backtest_summary": c.get("backtest_summary") or {},
        })
    return {"strategies": out}


@router.post("/api/strategies/{name}/toggle", response_class=JSONResponse)
async def toggle_strategy(name: str) -> dict:
    """Flip the active flag. Persists as an override under
    ``user_widget_settings`` so the YAML isn't rewritten."""
    files = {p.stem: p for p in _strategy_files()}
    if name not in files:
        raise HTTPException(404, f"unknown strategy: {name}")
    cfg = _load_strategy(files[name])
    current_eff, _ = await _resolve_active(name, bool(cfg.get("active", False)))
    new_value = not current_eff
    await ws.set_("default", _STRATEGY_OVERRIDES_KEY, f"{name}.active", new_value)
    return {"name": name, "active": new_value}


@router.post("/api/strategies/{name}/clear-override", response_class=JSONResponse)
async def clear_strategy_override(name: str) -> dict:
    """Drop the active-override; falls back to the YAML default."""
    await ws.delete("default", _STRATEGY_OVERRIDES_KEY, f"{name}.active")
    return {"name": name, "cleared": True}


@router.post("/api/strategies/{name}/archive", response_class=JSONResponse)
async def archive_strategy(name: str) -> dict:
    """Manually move a strategy to the Archived bucket.

    Stored as an override (not in YAML) so backtested strategies can be
    archived without rewriting their config files.
    """
    files = {p.stem: p for p in _strategy_files()}
    if name not in files:
        raise HTTPException(404, f"unknown strategy: {name}")
    await ws.set_("default", _STRATEGY_OVERRIDES_KEY, f"{name}.archived", True)
    return {"name": name, "archived": True}


@router.post("/api/strategies/{name}/unarchive", response_class=JSONResponse)
async def unarchive_strategy(name: str) -> dict:
    """Move a strategy out of Archived. Falls back to validated/in-progress
    based on its backtest_summary."""
    await ws.delete("default", _STRATEGY_OVERRIDES_KEY, f"{name}.archived")
    return {"name": name, "archived": False}


@router.get("/strategies/{name}/history", response_class=HTMLResponse)
async def strategy_history(
    request: Request,
    name: str,
    since: str | None = None,
    until: str | None = None,
    symbols: str | None = None,
    s: Settings = Depends(get_settings),
):
    """Per-strategy History tab — merges actual closed trades from JSONL
    with simulated trades from the replay engine over the same window.

    Lets the operator answer: "If I'd taken every signal this strategy
    proposed since date X, what would the trades have looked like?"
    Each row is tagged actual/simulated so the operator can see at a
    glance whether a date range had real fills or only counterfactuals.

    Query params:
        since/until: YYYY-MM-DD. Default since = 14 days ago, until = today.
        symbols:     CSV. Default = the 16-symbol DL bellwether universe.
    """
    files = {p.stem: p for p in _strategy_files()}
    if name not in files:
        raise HTTPException(404, f"unknown strategy: {name}")

    from datetime import date, timedelta
    today = date.today()
    if since:
        try:
            since_d = date.fromisoformat(since)
        except ValueError:
            since_d = today - timedelta(days=14)
    else:
        since_d = today - timedelta(days=14)
    if until:
        try:
            until_d = date.fromisoformat(until)
        except ValueError:
            until_d = today
    else:
        until_d = today

    # Default symbol set:
    #   - explicit ?symbols= param takes precedence
    #   - else use the active screener's saved tickers (matches what
    #     the live cron + strategy-live use day-to-day)
    #   - else fall back to the 16-symbol bellwether seed
    BELLWETHER = [
        "AMD", "AMZN", "BA", "COST", "GS", "HD", "INTC", "IWM",
        "META", "ORCL", "SPY", "TSLA", "XLF", "AAPL", "MSFT", "NVDA",
    ]
    if symbols:
        sym_list = [x.strip().upper() for x in symbols.split(",") if x.strip()]
        sym_source = "url"
    else:
        sym_list = []
        try:
            active = await db_service.get_active_universe_preset()
            if active and active.get("tickers"):
                sym_list = list(active["tickers"])
                sym_source = f"active screener ({active.get('name')})"
        except Exception:                                             # noqa: BLE001
            pass
        if not sym_list:
            sym_list = BELLWETHER
            sym_source = "bellwether fallback (no active screener)"

    cfg = _load_strategy(files[name])
    return templates.TemplateResponse(
        request=request,
        name="strategies/history.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "strategies",
            "strategy_name": name,
            "strategy_title": cfg.get("strategy_name", name),
            "since": since_d.isoformat(),
            "until": until_d.isoformat(),
            "symbols_param": ",".join(sym_list),
            "default_symbols": ", ".join(BELLWETHER),
            "symbols_source": sym_source,
            "symbols_count": len(sym_list),
        },
    )


@router.get("/api/strategies/{name}/history", response_class=JSONResponse)
async def strategy_history_data(
    name: str,
    since: str,
    until: str,
    symbols: str,
    refresh: bool = False,
    ignore_regime: bool = False,
) -> dict:
    """JSON: merged history of actual + simulated trades for a strategy
    over the given date window. Called by the History page on Run."""
    from datetime import date, datetime, timezone
    files = {p.stem: p for p in _strategy_files()}
    if name not in files:
        raise HTTPException(404, f"unknown strategy: {name}")

    try:
        since_d = date.fromisoformat(since)
        until_d = date.fromisoformat(until)
    except ValueError as e:
        raise HTTPException(400, f"bad date format: {e}")

    sym_list = [x.strip().upper() for x in symbols.split(",") if x.strip()]
    # fvg_continuation supplies its own FX pairs in replay_fvg, so it doesn't
    # require the equity symbol list the daily strategies use.
    if not sym_list and name != "fvg_continuation":
        raise HTTPException(400, "no symbols supplied")

    # ---- Simulated trades via the replay engine ----
    # Engine dispatch by timeframe: intraday strategies (double_lock) use the
    # 10:30 ET replay; daily swing strategies (momentum_breakout, fear_dip_
    # reversion, swing_momentum) use replay_swing.
    cfg_for_engine = _load_strategy(files[name])
    is_intraday = str(cfg_for_engine.get("holding_period", "swing_days")) == "intraday"
    simulated: list[dict] = []
    sim_error: str | None = None
    try:
        if name == "fvg_continuation":
            # FX intraday FVG-continuation has its own session-aware replay (FX 30m).
            from scripts.replay_fvg import replay as _replay
            trig = "NY"
        elif is_intraday:
            from scripts.replay_dl import replay as _replay
            trig = "10:30"
        else:
            from scripts.replay_swing import replay as _replay
            trig = "EOD"
        sim_trades = await _replay(
            symbols=sym_list, since=since_d, until=until_d,
            strategy=name, refresh=refresh, ignore_regime=ignore_regime,
        )
        for t in sim_trades:
            simulated.append({
                "source":      "simulated",
                "date":        t.date_str,
                "trigger_et":  trig,
                "symbol":      t.symbol,
                "direction":   t.direction.lower(),
                "entry":       t.entry,
                "stop":        t.stop,
                "exit":        t.exit_px,
                "tp":          getattr(t, "tp", None),
                "exit_reason": t.exit_reason,
                "pnl_pct":     t.pnl_pct,
                "pnl_per_100": t.pnl_dollars_per_100shr,
                "win":         t.win,
                "pqs":         t.pqs,
                "notes":       t.notes,
            })
    except Exception as e:                                            # noqa: BLE001
        logger.exception("strategy_history: replay failed")
        sim_error = f"{type(e).__name__}: {e}"

    # ---- Actual closed trades from the JSONL pool, filtered by strategy + window ----
    actual: list[dict] = []
    try:
        from services import log_service
        records = await log_service.read_records()
        for r in records:
            setup = r.setup_snapshot or {}
            instr = r.instrument or {}
            lc = r.lifecycle or {}
            execn = r.execution or {}
            outc = r.outcome or {}

            if (setup.get("strategy_name") or "") != name:
                continue
            ts_entered = lc.get("ts_entered") or lc.get("ts_planned") or ""
            try:
                d = datetime.fromisoformat(ts_entered.replace("Z", "+00:00")).date()
            except (ValueError, TypeError):
                continue
            if not (since_d <= d <= until_d):
                continue

            # Render trigger time in ET
            try:
                dt_et = (
                    datetime.fromisoformat(ts_entered.replace("Z", "+00:00"))
                    .astimezone(__import__("zoneinfo").ZoneInfo("America/New_York"))
                )
                trigger_et = dt_et.strftime("%H:%M")
            except Exception:                                         # noqa: BLE001
                trigger_et = "—"

            actual.append({
                "source":      "actual",
                "trade_id":    r.trade_id,
                "plan_id":     r.plan_id,
                "date":        d.isoformat(),
                "trigger_et":  trigger_et,
                "symbol":      instr.get("symbol", ""),
                "direction":   setup.get("direction", "long"),
                "entry":       execn.get("avg_entry_price") or execn.get("planned_entry"),
                "stop":        setup.get("stop_loss_price"),
                "exit":        execn.get("avg_exit_price"),
                "tp":          setup.get("take_profit_price"),
                "exit_reason": outc.get("exit_reason", ""),
                "pnl_pct":     outc.get("pnl_pct"),
                "pnl_usd":     outc.get("pnl_usd"),
                "win":         (outc.get("pnl_usd") or 0) > 0,
                "notes":       "",
            })
    except Exception as e:                                            # noqa: BLE001
        logger.warning("strategy_history: actual-read failed: %s", e)

    # Merge + sort by date desc, then trigger time desc
    merged = sorted(
        simulated + actual,
        key=lambda x: (x.get("date", ""), x.get("trigger_et", "")),
        reverse=True,
    )

    # Stable per-row image key so a rendered chart can be stored + shown as a
    # thumbnail. Actual trades key on trade_id; simulated (backtest) trades key
    # deterministically on strategy+symbol+date+direction. Attach image_url when
    # a PNG already exists (data/trade_images/<key>.png, served at /trade-images).
    import re as _re

    from services import trade_image_index
    for row in merged:
        if row.get("source") == "actual" and row.get("trade_id"):
            key = str(row["trade_id"])
        else:
            raw = f"bt_{name}_{row.get('symbol','')}_{row.get('date','')}_{row.get('direction','')}"
            key = _re.sub(r"[^A-Za-z0-9._-]", "-", raw)[:120]
        st = trade_image_index.status(key)
        row["image_key"] = key
        row["image_url"] = st["url"]
        row["image_stale"] = st["stale"]

    # Aggregate stats
    n_actual = sum(1 for r in merged if r["source"] == "actual")
    n_sim = sum(1 for r in merged if r["source"] == "simulated")
    wins = sum(1 for r in merged if r.get("win"))
    losses = len(merged) - wins
    wr = (wins / len(merged) * 100.0) if merged else 0.0
    total_pct = sum((r.get("pnl_pct") or 0.0) for r in merged)

    return {
        "strategy": name,
        "since": since_d.isoformat(),
        "until": until_d.isoformat(),
        "symbols_count": len(sym_list),
        "ignore_regime": ignore_regime,
        "trades": merged,
        "summary": {
            "total":   len(merged),
            "actual":  n_actual,
            "sim":     n_sim,
            "wins":    wins,
            "losses":  losses,
            "win_rate": round(wr, 1),
            "total_pnl_pct": round(total_pct, 2),
        },
        "sim_error": sim_error,
    }


@router.post("/api/strategies/{name}/auto-approve", response_class=JSONResponse)
async def toggle_auto_approve(name: str) -> dict:
    """Flip the per-strategy auto-approve flag.

    When enabled (and the active broker account is paper), TradePlans
    from this strategy auto-fire the executioner without waiting for
    human approval. Live accounts and live mode always require manual
    ack — that's a hard guardrail in auto_approve_service.
    """
    files = {p.stem: p for p in _strategy_files()}
    if name not in files:
        raise HTTPException(404, f"unknown strategy: {name}")
    from services import auto_approve_service
    current = await auto_approve_service.is_enabled(name)
    new_value = not current
    await auto_approve_service.set_enabled(name, new_value)
    return {"name": name, "auto_approve": new_value}


@router.post("/api/strategies/{name}/run", response_class=JSONResponse)
async def run_strategy(name: str, mode: str | None = None,
                       as_of: str | None = None,
                       refresh: bool | None = None,
                       wait: bool = False,
                       s: Settings = Depends(get_settings)) -> dict:
    """Kick off a strategy scan. ASYNC by default: returns a job id
    immediately and runs the scan in the background, so a long scan can't hit
    Cloudflare's ~100s request timeout (524) through the tunnel. Poll
    ``GET /api/strategies/runs/{job_id}`` for the result.

    ``?wait=1`` runs synchronously and returns the full result (for scripts /
    local curl where there's no proxy timeout)."""
    # Validate as_of up front so bad input returns 400 to the client now,
    # rather than failing inside a background job.
    if as_of:
        try:
            date.fromisoformat(as_of)
        except ValueError:
            raise HTTPException(400, f"bad as_of date: {as_of!r} (want YYYY-MM-DD)")

    if wait:
        return await _do_strategy_run(name, mode, as_of, refresh, s)

    from services import run_jobs
    job_id = run_jobs.create(name)

    async def _bg() -> None:
        try:
            run_jobs.mark_done(job_id, await _do_strategy_run(name, mode, as_of, refresh, s))
        except HTTPException as e:
            run_jobs.mark_error(job_id, f"{e.status_code}: {e.detail}")
        except Exception as e:  # noqa: BLE001
            logger.exception("async strategy run failed")
            run_jobs.mark_error(job_id, str(e))

    asyncio.create_task(_bg())
    return {"job_id": job_id, "status": "running", "strategy": name}


@router.get("/api/strategies/runs/{job_id}", response_class=JSONResponse)
async def strategy_run_status(job_id: str) -> dict:
    """Poll a background strategy-run job started by POST /run."""
    from services import run_jobs
    j = run_jobs.get(job_id)
    if j is None:
        raise HTTPException(404, "unknown or expired run job")
    out: dict = {"job_id": job_id, "strategy": j["strategy"], "status": j["status"]}
    if j["status"] == "done":
        out["result"] = j["result"]
    elif j["status"] == "error":
        out["error"] = j["error"]
    return out


async def _do_strategy_run(name: str, mode: str | None, as_of: str | None,
                           refresh: bool | None, s: Settings) -> dict:
    """The actual scan — runs every workflow that mentions this strategy (or
    the FVG session scan). Returns the summary dict the UI renders."""
    workflows = await _load_workflows()
    matching = [
        wf for wf in workflows
        if name in wf["strategies_used"] or wf["workflow_id"] == name
    ]
    if not matching:
        # Replay-only strategies (e.g. fvg_continuation — FX, no live broker yet)
        # have no scheduled workflow. Return a clear status instead of a 404 so the
        # ▶ Run button explains itself rather than "failing".
        from services.settings_service import STRATEGY_CONFIG_DIR
        import yaml as _yaml
        cfg_path = STRATEGY_CONFIG_DIR / f"{name}.yaml"
        cfg = {}
        if cfg_path.exists():
            try:
                cfg = _yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            except Exception:  # noqa: BLE001
                cfg = {}
        # FVG-continuation (FX/gold intraday) has no daily workflow — it runs
        # through its own session-based scan service, which evaluates the
        # latest NY session per symbol and queues gated plans to /pending.
        if name == "fvg_continuation" or cfg.get("strategy_name") == "fvg_continuation":
            from services.fvg_scan_service import run_fvg_scan
            from datetime import date as _date
            as_of_d = None
            if as_of:
                try:
                    as_of_d = _date.fromisoformat(as_of)
                except ValueError:
                    raise HTTPException(400, f"bad as_of date: {as_of!r} (want YYYY-MM-DD)")
            try:
                summary = await run_fvg_scan(settings=s, mode=mode, as_of=as_of_d,
                                             refresh=refresh)
            except Exception as e:                            # noqa: BLE001
                logger.exception("fvg scan run failed")
                raise HTTPException(422, f"FVG scan failed: {e}")
            return {"strategy": name, "runs": [{"workflow_id": "fvg_continuation_scan",
                                                "result": summary}], "fvg": True}
        if cfg.get("live_wired") is False or cfg.get("asset_class") == "forex":
            broker = cfg.get("broker_required", "an FX broker")
            return {
                "strategy": name, "runs": [],
                "note": (f"{name} is replay-only — it needs {broker} + an intraday "
                         f"workflow before it can run live. Use the History view to "
                         f"review its signals."),
                "replay_only": True,
            }
        raise HTTPException(
            404,
            f"no workflow mentions strategy {name!r}. Add it to a step's "
            f"params.strategy in workflows/*.yaml.",
        )
    results = []
    for wf in matching:
        try:
            r = await run_workflow_by_id(wf["workflow_id"], mode=mode, settings=s)
            results.append({"workflow_id": wf["workflow_id"], "result": r})
        except Exception as e:                                # noqa: BLE001
            logger.exception("manual strategy run failed")
            results.append({
                "workflow_id": wf["workflow_id"], "error": str(e),
            })
    return {"strategy": name, "runs": results}


# ---------------------------------------------------------------------- #
# Validation — run a real backtest from the UI; status is EARNED + stored
# ---------------------------------------------------------------------- #

# Strategies currently validating (guards double-runs; drives the spinner).
_VALIDATION_INFLIGHT: set[str] = set()


def _run_validation_sync(name: str) -> None:
    """Run the (async) validation in a fresh event loop on a worker thread so
    the main FastAPI loop stays responsive during the minutes-long backtest."""
    import asyncio as _a
    from services.strategy_validation_service import validate_strategy
    loop = _a.new_event_loop()
    _a.set_event_loop(loop)
    try:
        loop.run_until_complete(validate_strategy(name))
    finally:
        loop.close()


async def _validate_bg(name: str) -> None:
    import asyncio as _a
    try:
        await _a.to_thread(_run_validation_sync, name)
    except Exception:                                             # noqa: BLE001
        logger.exception("background validation failed for %s", name)
    finally:
        _VALIDATION_INFLIGHT.discard(name)


@router.post("/api/strategies/{name}/validate", response_class=JSONResponse)
async def validate_strategy_endpoint(name: str) -> dict:
    """Kick off a backtest-validation for one strategy (runs in the
    background; poll GET /api/strategies/{name}/validation for the result)."""
    if not (STRATEGY_CONFIG_DIR / f"{name}.yaml").exists():
        raise HTTPException(404, f"unknown strategy {name!r}")
    if name in _VALIDATION_INFLIGHT:
        return {"strategy": name, "status": "already_running"}
    _VALIDATION_INFLIGHT.add(name)
    import asyncio as _a
    _a.create_task(_validate_bg(name))
    return {"strategy": name, "status": "started"}


@router.get("/api/strategies/{name}/validation", response_class=JSONResponse)
async def get_latest_validation(name: str) -> dict:
    v = await db_service.latest_validation(name)
    return {"strategy": name, "running": name in _VALIDATION_INFLIGHT,
            "validation": v}


@router.get("/strategies/{name}/validations", response_class=HTMLResponse)
async def validations_history_page(name: str, request: Request,
                                   s: Settings = Depends(get_settings)):
    if not (STRATEGY_CONFIG_DIR / f"{name}.yaml").exists():
        raise HTTPException(404, f"unknown strategy {name!r}")
    cfg = _load_strategy(STRATEGY_CONFIG_DIR / f"{name}.yaml")
    history = await db_service.list_validations(name, limit=50)
    return templates.TemplateResponse(
        request=request, name="strategy_validations.html",
        context={"settings": s, "app_version": "0.1.0",
                 "active_page": "strategies", "active_section": "strategies",
                 "strategy": name, "title": cfg.get("strategy_name", name),
                 "description": (cfg.get("description") or "").strip(),
                 "history": history, "running": name in _VALIDATION_INFLIGHT},
    )


# ---------------------------------------------------------------------- #
# Strategy configuration editor (filters/thresholds + stock list)
# ---------------------------------------------------------------------- #

import re as _re  # noqa: E402


def _yaml_replace_scalar(text: str, key: str, value, *, nth: int = 1) -> tuple[str, bool]:
    """Replace the value of ``key:`` in YAML text, preserving indentation and
    inline comments elsewhere. Only the nth matching line is changed. Returns
    (new_text, changed). Comment-preserving by design (we never re-dump)."""
    if isinstance(value, bool):
        v = "true" if value else "false"
    elif isinstance(value, float):
        v = repr(value)
    elif isinstance(value, int):
        v = str(value)
    else:
        v = str(value)
    pat = _re.compile(rf"^(?P<indent>[ \t]*){_re.escape(key)}:[ \t]*\S.*$", _re.M)
    matches = list(pat.finditer(text))
    if len(matches) < nth:
        return text, False
    m = matches[nth - 1]
    new_line = f"{m.group('indent')}{key}: {v}"
    return text[:m.start()] + new_line + text[m.end():], True


async def _workflows_for(name: str) -> list[str]:
    wfs = await _load_workflows()
    return [wf["workflow_id"] for wf in wfs if name in wf["strategies_used"]]


def _workflow_universe(wf_id: str, fallback: str | None) -> str | None:
    from services.workflow_engine import WORKFLOWS_DIR
    wp = WORKFLOWS_DIR / f"{wf_id}.yaml"
    if not wp.exists():
        return fallback
    doc = yaml.safe_load(wp.read_text(encoding="utf-8")) or {}
    for st in doc.get("steps", []):
        if st.get("kind") == "filter_universe":
            return (st.get("params") or {}).get("preset", fallback)
    return fallback


@router.get("/api/strategies/{name}/config", response_class=JSONResponse)
async def get_strategy_config(name: str) -> dict:
    """Return the editable config for one strategy: per-detector thresholds,
    the runtime universe (from its workflow), and the available screeners."""
    files = {p.stem: p for p in _strategy_files()}
    if name not in files:
        raise HTTPException(404, f"unknown strategy: {name}")
    cfg = _load_strategy(files[name])
    wf_ids = await _workflows_for(name)
    universe = cfg.get("universe_filter_preset")
    for wid in wf_ids:
        universe = _workflow_universe(wid, universe)
        break
    screeners: list[dict] = []
    try:
        from services import db_service
        for p in await db_service.list_universe_presets():
            screeners.append({"name": p.get("name"),
                              "tickers": len(p.get("tickers") or [])})
    except Exception as e:                                    # noqa: BLE001
        logger.debug("config: screener list failed: %s", e)
    return {
        "name": name,
        "title": cfg.get("strategy_name", name),
        "universe": universe,
        "screeners": screeners,
        "detectors": cfg.get("detectors") or [],
        "pattern_thresholds": cfg.get("pattern_thresholds") or {},
        "workflows": wf_ids,
    }


@router.post("/api/strategies/{name}/config", response_class=JSONResponse)
async def save_strategy_config(name: str, request: Request) -> dict:
    """Persist edited thresholds + stock list back to the YAML (comment-safe).
    Applies on the strategy's next run — no restart needed for params."""
    files = {p.stem: p for p in _strategy_files()}
    if name not in files:
        raise HTTPException(404, f"unknown strategy: {name}")
    body = await request.json()
    thresholds = body.get("pattern_thresholds") or {}
    universe = body.get("universe")

    path = files[name]
    text = path.read_text(encoding="utf-8")
    changed: list[str] = []

    for det, fields in thresholds.items():
        for k, raw in (fields or {}).items():
            v = raw
            if isinstance(v, str):
                if v.lower() in ("true", "false"):
                    v = v.lower() == "true"
                elif _re.fullmatch(r"-?\d+", v):
                    v = int(v)
                else:
                    try:
                        v = float(v)
                    except ValueError:
                        pass
            text, ok = _yaml_replace_scalar(text, k, v)
            if ok:
                changed.append(f"{det}.{k}={v}")

    try:
        yaml.safe_load(text)
    except Exception as e:                                    # noqa: BLE001
        raise HTTPException(400, f"edit produced invalid YAML: {e}")
    path.write_text(text, encoding="utf-8")

    if universe:
        t2, _ = _yaml_replace_scalar(
            path.read_text(encoding="utf-8"), "universe_filter_preset", universe)
        path.write_text(t2, encoding="utf-8")
        from services.workflow_engine import WORKFLOWS_DIR
        for wid in await _workflows_for(name):
            wp = WORKFLOWS_DIR / f"{wid}.yaml"
            if not wp.exists():
                continue
            wt, ok = _yaml_replace_scalar(wp.read_text(encoding="utf-8"), "preset", universe)
            if ok:
                try:
                    yaml.safe_load(wt)
                except Exception:                            # noqa: BLE001
                    continue
                wp.write_text(wt, encoding="utf-8")
                changed.append(f"{wid}.universe={universe}")
        changed.append(f"universe_filter_preset={universe}")

    logger.info("strategy %s config updated: %s", name, changed)
    return {"name": name, "changed": changed}
