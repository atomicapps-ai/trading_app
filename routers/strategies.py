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

import logging
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

# Validation threshold for auto-promotion to the Validated bucket.
_VALIDATION_WR_THRESHOLD = 72.0

# Buckets shown as tabs on /strategies/{bucket}
_BUCKETS = ("validated", "in-progress", "archived")
_BUCKET_LABELS = {
    "validated":   "Validated",
    "in-progress": "In Progress",
    "archived":    "Archived",
}


def _classify(cfg: dict, archived_override: bool) -> str:
    """Decide which bucket a strategy belongs to.

    archived: user explicitly archived (manual override, future UI)
    validated: backtest_summary clears the WR threshold
    in_progress: everything else (default for new strategies)
    """
    if archived_override:
        return "archived"
    bs = cfg.get("backtest_summary") or {}
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
    for p in _strategy_files():
        c = _load_strategy(p)
        archived = bool(await ws.get("default", _STRATEGY_OVERRIDES_KEY, f"{c['_name']}.archived"))
        counts[_classify(c, archived)] += 1
    return counts


@router.get("/strategies/validated", response_class=HTMLResponse)
async def strategies_validated_page(request: Request, s: Settings = Depends(get_settings)):
    return await _strategies_bucket_page(request, s, bucket="validated")


@router.get("/strategies/in-progress", response_class=HTMLResponse)
async def strategies_inprogress_page(request: Request, s: Settings = Depends(get_settings)):
    return await _strategies_bucket_page(request, s, bucket="in-progress")


@router.get("/strategies/archived", response_class=HTMLResponse)
async def strategies_archived_page(request: Request, s: Settings = Depends(get_settings)):
    return await _strategies_bucket_page(request, s, bucket="archived")


async def _strategies_bucket_page(request: Request, s: Settings, bucket: str):
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
    runs = await db_service.list_pipeline_runs(limit=50)
    latest_by_workflow: dict[str, dict] = {}
    for r in runs:
        wf = r.get("workflow_id")
        if wf and wf not in latest_by_workflow:
            latest_by_workflow[wf] = r

    rows = []
    for c in cfgs:
        name = c["_name"]
        eff_active, has_override = await _resolve_active(
            name, bool(c.get("active", False)),
        )
        archived = bool(await ws.get("default", _STRATEGY_OVERRIDES_KEY, f"{name}.archived"))
        bucket_for_row = _classify(c, archived)
        if bucket_for_row != bucket:
            continue
        wfs = by_strategy.get(c.get("strategy_name", name)) or []
        for wf in wfs:
            wf["job"] = _job_for_workflow(wf["workflow_id"])
            wf["latest_run"] = latest_by_workflow.get(wf["workflow_id"])
        rows.append({
            "name": name,
            "title": c.get("strategy_name", name),
            "description": (c.get("description") or "").strip(),
            "version": c.get("version"),
            "mode": c.get("mode", "research"),
            "holding_period": c.get("holding_period"),
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
        })

    counts = await _bucket_counts()
    tabs = [
        {"key": b, "label": _BUCKET_LABELS[b], "href": f"/strategies/{b}",
         "count": counts.get(b, 0)}
        for b in _BUCKETS
    ]
    active_key = {
        "validated": "strategies_validated",
        "in-progress": "strategies_in_progress",
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
            "active_tab": bucket,
            "bucket": bucket,
            "bucket_label": _BUCKET_LABELS[bucket],
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


@router.post("/api/strategies/{name}/run", response_class=JSONResponse)
async def run_strategy(name: str, mode: str | None = None,
                       s: Settings = Depends(get_settings)) -> dict:
    """Run every workflow that mentions this strategy, ad-hoc.

    For multi-workflow strategies (rare today) we run them sequentially
    and return the per-workflow result. The scheduled cron run is
    untouched — this is just a manual fire-now.
    """
    workflows = await _load_workflows()
    matching = [
        wf for wf in workflows
        if name in wf["strategies_used"] or wf["workflow_id"] == name
    ]
    if not matching:
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
