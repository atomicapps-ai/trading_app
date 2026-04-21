"""workflow_engine.py — composable agent workflow runner.

Loads ``workflows/*.yaml`` and executes the declared step DAG. Each step
names an agent kind (``filter_universe``, ``analyze``, etc.) plus its
params. Steps with identical ``depends_on`` sets run in parallel via
``asyncio.gather``.

Hard invariants (NOT expressible in YAML)
-----------------------------------------
1. ``compliance_officer`` runs on every TradePlan any step emits. It is
   injected automatically — the workflow cannot declare it.
2. ``risk_manager`` runs after compliance on pass verdicts only.
3. Workflow YAML that names a step with ``kind: compliance_officer`` or
   ``kind: risk_manager`` is rejected at ``load()``.

Phase 4 scope
-------------
Only ``filter_universe`` is wired to a real agent today. The other step
kinds are stubs that log "not yet implemented" and return an empty
output. Wiring them is the remaining Phase 4 work (analyst, news, macro,
portfolio_manager). The engine itself is complete — future steps plug in
via ``_step_registry``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal
from uuid import uuid4

import pandas as pd
import yaml
from pydantic import BaseModel, Field, field_validator

from agents.analyst import run_analyst_on_shortlist
from agents.macro import compute_macro_context
from agents.universe_filter import UniverseFilter
from services.settings_service import DATA_DIR, PROJECT_ROOT, Settings

logger = logging.getLogger(__name__)

WORKFLOWS_DIR: Path = PROJECT_ROOT / "workflows"
UNIVERSE_LATEST_FILE: Path = DATA_DIR / "universe_latest.json"
PIPELINE_STATUS_FILE: Path = DATA_DIR / "pipeline_status.json"

StepKind = Literal[
    "fetch_news",
    "fetch_filings",
    "filter_universe",
    "compute_macro",
    "analyze",
    "plan",
]
_FORBIDDEN_KINDS = {"compliance_officer", "risk_manager"}


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #


class WorkflowStep(BaseModel):
    id: str
    kind: StepKind
    params: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)


class Workflow(BaseModel):
    workflow_id: str
    description: str = ""
    schedule: str | None = None  # optional cron string
    default_mode: Literal["research", "paper", "live"] = "paper"
    steps: list[WorkflowStep]

    @field_validator("steps")
    @classmethod
    def _no_gate_steps(cls, v: list[WorkflowStep]) -> list[WorkflowStep]:
        for s in v:
            if s.kind in _FORBIDDEN_KINDS:
                raise ValueError(
                    f"step {s.id!r}: compliance_officer and risk_manager "
                    f"are injected automatically — they cannot appear in a workflow YAML"
                )
        return v


class StepResult(BaseModel):
    step_id: str
    kind: StepKind
    output: dict[str, Any] = Field(default_factory=dict)
    duration_seconds: float = 0.0
    error: str | None = None


class WorkflowRunResult(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    workflow_id: str
    mode: Literal["research", "paper", "live"]
    as_of_ts: str | None = None
    ts_start: str
    ts_end: str
    duration_seconds: float
    step_results: list[StepResult] = Field(default_factory=list)
    # Aggregate counts for the UI
    symbols_in_shortlist: int = 0
    signals_generated: int = 0
    plans_proposed: int = 0
    error: str | None = None


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #


class WorkflowEngine:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._universe_filter = UniverseFilter(settings)
        self._step_registry: dict[
            str, Callable[[WorkflowStep, "WorkflowContext"], Awaitable[dict[str, Any]]]
        ] = {
            "filter_universe": self._run_filter_universe,
            "compute_macro": self._run_compute_macro,
            "fetch_news": self._stub_fetch_news,
            "fetch_filings": self._stub_fetch_filings,
            "analyze": self._run_analyze,
            "plan": self._stub_plan,
        }

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def load(self, path: Path) -> Workflow:
        """Parse + validate a workflow YAML. Raises on forbidden step kinds
        or unresolved ``depends_on`` references."""
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        wf = Workflow.model_validate(raw)
        self._validate_dag(wf)
        return wf

    async def list_workflows(self) -> list[Workflow]:
        """Return every workflow found in WORKFLOWS_DIR."""
        out: list[Workflow] = []
        if not WORKFLOWS_DIR.exists():
            return out
        for p in sorted(WORKFLOWS_DIR.glob("*.yaml")):
            try:
                out.append(await self.load(p))
            except Exception as e:  # noqa: BLE001
                logger.error("Failed to load workflow %s: %s", p.name, e)
        return out

    async def load_by_id(self, workflow_id: str) -> Workflow:
        path = WORKFLOWS_DIR / f"{workflow_id}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"workflow not found: {workflow_id}")
        return await self.load(path)

    async def run(
        self,
        workflow: Workflow,
        mode: str | None = None,
        as_of_ts: pd.Timestamp | None = None,
    ) -> WorkflowRunResult:
        """Execute the DAG. Siblings run in parallel; dependent steps wait."""
        effective_mode = mode or workflow.default_mode
        ctx = WorkflowContext(
            workflow_id=workflow.workflow_id,
            run_id=str(uuid4()),
            mode=effective_mode,  # type: ignore[arg-type]
            as_of_ts=as_of_ts,
        )
        ts_start = datetime.now(timezone.utc)
        t0 = time.perf_counter()

        self._write_status({
            "status": "running",
            "workflow_id": workflow.workflow_id,
            "ts_start": ts_start.isoformat(),
        })

        step_results: list[StepResult] = []
        step_by_id = {s.id: s for s in workflow.steps}
        levels = self._topological_levels(workflow)
        error: str | None = None

        try:
            for level in levels:
                # siblings in a level run in parallel
                coros = [self._run_step(step_by_id[sid], ctx) for sid in level]
                results = await asyncio.gather(*coros, return_exceptions=False)
                step_results.extend(results)
                for r in results:
                    ctx.outputs[r.step_id] = r.output
                    if r.error:
                        error = f"step {r.step_id} failed: {r.error}"
                        raise RuntimeError(error)
        except RuntimeError as e:
            # Already logged by the step runner; just fall through
            logger.error("Workflow %s aborted: %s", workflow.workflow_id, e)

        ts_end = datetime.now(timezone.utc)
        duration = time.perf_counter() - t0

        # Collect aggregate counts for the UI
        shortlist_size = 0
        for r in step_results:
            if r.kind == "filter_universe":
                shortlist_size = int(r.output.get("shortlist_size", 0))
        signals = sum(
            int(r.output.get("signals_generated", 0)) for r in step_results
        )
        plans = sum(
            int(r.output.get("plans_proposed", 0)) for r in step_results
        )

        result = WorkflowRunResult(
            workflow_id=workflow.workflow_id,
            mode=effective_mode,  # type: ignore[arg-type]
            as_of_ts=as_of_ts.isoformat() if as_of_ts is not None else None,
            ts_start=ts_start.isoformat(),
            ts_end=ts_end.isoformat(),
            duration_seconds=round(duration, 3),
            step_results=step_results,
            symbols_in_shortlist=shortlist_size,
            signals_generated=signals,
            plans_proposed=plans,
            error=error,
        )

        self._write_status({
            "status": "error" if error else "idle",
            "workflow_id": workflow.workflow_id,
            "ts_start": ts_start.isoformat(),
            "ts_end": ts_end.isoformat(),
            "duration_seconds": result.duration_seconds,
            "symbols_in_shortlist": shortlist_size,
            "signals_generated": signals,
            "plans_proposed": plans,
            "error": error,
        })

        logger.info(
            "Workflow %s %s: duration=%.2fs shortlist=%d signals=%d plans=%d",
            workflow.workflow_id,
            "FAILED" if error else "complete",
            duration, shortlist_size, signals, plans,
        )
        return result

    # ------------------------------------------------------------------ #
    # Step runner
    # ------------------------------------------------------------------ #

    async def _run_step(
        self, step: WorkflowStep, ctx: "WorkflowContext",
    ) -> StepResult:
        handler = self._step_registry.get(step.kind)
        if handler is None:
            return StepResult(
                step_id=step.id, kind=step.kind,
                error=f"no handler registered for kind={step.kind!r}",
            )
        t0 = time.perf_counter()
        try:
            output = await handler(step, ctx)
            return StepResult(
                step_id=step.id, kind=step.kind,
                output=output,
                duration_seconds=round(time.perf_counter() - t0, 3),
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("Step %s (%s) failed", step.id, step.kind)
            return StepResult(
                step_id=step.id, kind=step.kind,
                duration_seconds=round(time.perf_counter() - t0, 3),
                error=str(e),
            )

    # ------------------------------------------------------------------ #
    # Real step handlers
    # ------------------------------------------------------------------ #

    async def _run_filter_universe(
        self, step: WorkflowStep, ctx: "WorkflowContext",
    ) -> dict[str, Any]:
        preset_name = step.params.get("preset", "liquid_momentum_core")
        shortlist_size = int(step.params.get("shortlist_size", 50))
        result = await self._universe_filter.run(
            preset_name,
            as_of_ts=ctx.as_of_ts,
            shortlist_size=shortlist_size,
        )
        # Persist latest snapshot for the UI + Phase 5 backtest replay
        try:
            UNIVERSE_LATEST_FILE.parent.mkdir(parents=True, exist_ok=True)
            UNIVERSE_LATEST_FILE.write_text(
                result.model_dump_json(indent=2), encoding="utf-8",
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to write %s: %s", UNIVERSE_LATEST_FILE, e)

        return {
            "preset_name": result.preset_name,
            "universe": result.universe,
            "universe_size": result.universe_size,
            "shortlist": result.shortlist,
            "shortlist_size": result.shortlist_size,
            "total_screened": result.total_screened,
            "rejection_reasons": result.rejection_reasons,
            "duration_seconds": result.run_duration_seconds,
        }

    # ------------------------------------------------------------------ #
    # Stub handlers (Phase 4 remainder will replace each)
    # ------------------------------------------------------------------ #

    async def _run_compute_macro(
        self, step: WorkflowStep, ctx: "WorkflowContext",
    ) -> dict[str, Any]:
        macro = await compute_macro_context(as_of_ts=ctx.as_of_ts)
        return {"macro_context": macro}

    async def _run_analyze(
        self, step: WorkflowStep, ctx: "WorkflowContext",
    ) -> dict[str, Any]:
        # Pull the upstream shortlist out of filter_universe's output
        universe_out = ctx.outputs.get("filter_universe", {})
        shortlist: list[str] = list(universe_out.get("shortlist") or [])
        if not shortlist:
            logger.info("analyze: empty shortlist — nothing to do")
            return {"signals": {}, "signals_generated": 0}

        macro_out = ctx.outputs.get("compute_macro", {})
        macro_context = macro_out.get("macro_context", {})

        strategy = step.params.get("strategy", "swing_momentum")
        signals_by_symbol = await run_analyst_on_shortlist(
            shortlist,
            settings=self._settings,
            macro_context=macro_context,
            as_of_ts=ctx.as_of_ts,
            strategy_name=strategy,
        )
        total = sum(len(s) for s in signals_by_symbol.values())
        logger.info(
            "analyze: %d symbols scanned, %d symbols emitted signals (%d total)",
            len(shortlist), len(signals_by_symbol), total,
        )
        return {
            "signals": {
                sym: [s.model_dump() for s in sigs]
                for sym, sigs in signals_by_symbol.items()
            },
            "signals_generated": total,
            "symbols_with_signals": len(signals_by_symbol),
        }

    async def _stub_fetch_news(
        self, step: WorkflowStep, ctx: "WorkflowContext",
    ) -> dict[str, Any]:
        logger.info("[stub] fetch_news — returning empty news map")
        return {"news_by_symbol": {}, "stub": True}

    async def _stub_fetch_filings(
        self, step: WorkflowStep, ctx: "WorkflowContext",
    ) -> dict[str, Any]:
        logger.info("[stub] fetch_filings — returning empty filings map")
        return {"filings_by_symbol": {}, "stub": True}

    async def _stub_plan(
        self, step: WorkflowStep, ctx: "WorkflowContext",
    ) -> dict[str, Any]:
        logger.info("[stub] plan — portfolio_manager not yet built")
        return {"plans": [], "plans_proposed": 0, "stub": True}

    # ------------------------------------------------------------------ #
    # DAG / validation
    # ------------------------------------------------------------------ #

    def _validate_dag(self, wf: Workflow) -> None:
        ids = {s.id for s in wf.steps}
        for s in wf.steps:
            for dep in s.depends_on:
                if dep not in ids:
                    raise ValueError(
                        f"step {s.id!r} depends_on unknown step {dep!r}"
                    )
        # Cycle detection via topological sort (raises on cycle)
        self._topological_levels(wf)

    def _topological_levels(self, wf: Workflow) -> list[list[str]]:
        """Return steps grouped into levels; each level can run in parallel."""
        deps: dict[str, set[str]] = {s.id: set(s.depends_on) for s in wf.steps}
        resolved: set[str] = set()
        levels: list[list[str]] = []
        remaining = dict(deps)
        while remaining:
            ready = [sid for sid, d in remaining.items() if d <= resolved]
            if not ready:
                raise ValueError(
                    f"cycle or unresolved dependency in workflow: {list(remaining)}"
                )
            levels.append(sorted(ready))
            resolved.update(ready)
            for sid in ready:
                remaining.pop(sid)
        return levels

    # ------------------------------------------------------------------ #
    # Status persistence
    # ------------------------------------------------------------------ #

    def _write_status(self, payload: dict[str, Any]) -> None:
        try:
            PIPELINE_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
            PIPELINE_STATUS_FILE.write_text(
                json.dumps(payload, indent=2), encoding="utf-8",
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to write pipeline_status.json: %s", e)


# --------------------------------------------------------------------------- #
# Context (mutable bag of step outputs passed down the DAG)
# --------------------------------------------------------------------------- #


class WorkflowContext(BaseModel):
    workflow_id: str
    run_id: str
    mode: Literal["research", "paper", "live"]
    as_of_ts: pd.Timestamp | None = None
    outputs: dict[str, dict[str, Any]] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}
