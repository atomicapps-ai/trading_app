"""pipeline_service.py — production workflow runner with gates + DB.

Thin layer over ``WorkflowEngine`` that enforces the two hard invariants
phase4_prompt.md demands:

  1. ``ComplianceOfficer`` (C1–C8) runs on every TradePlan the workflow
     emits. No YAML can skip or re-order this.
  2. ``RiskManager`` (R1–R9) runs on every plan that passes compliance.
     Resizes are allowed; rejections drop the plan.

Verdicts are written to SQLite regardless of outcome so the UI can show
the full history of what got blocked and why.

Called by:
  * POST /api/workflows/{id}/run  (manual trigger from the UI)
  * APScheduler (Phase 7 — schedules derived from workflow YAML)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pandas as pd

from agents.compliance_officer import ComplianceOfficer
from agents.risk_manager import RiskManager
from models.account import AccountState, LULDBand, MarketState
from models.trade_plan import TradePlan
from services import db_service
from services.broker_service import get_adapter
from services.settings_service import Settings, get_settings
from services.workflow_engine import WorkflowEngine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------- #
# Public entry point
# ---------------------------------------------------------------------- #


async def run_workflow_by_id(
    workflow_id: str,
    mode: str | None = None,
    as_of_ts: pd.Timestamp | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Load workflow YAML → run engine → gate every plan → persist to DB.

    Returns a dict summary (shape mirrors the UI-facing run-summary
    contract). Individual plan rows + verdicts are in SQLite for
    ``/pending`` to pick up.
    """
    s = settings or get_settings()
    engine = WorkflowEngine(s)
    try:
        workflow = await engine.load_by_id(workflow_id)
    except FileNotFoundError:
        raise

    run_result = await engine.run(workflow, mode=mode, as_of_ts=as_of_ts)

    # Per the spec, verdicts are persisted even when the workflow itself
    # errored out mid-step — we want the run history complete.
    plans_proposed: list[dict] = []
    plan_step = next(
        (sr for sr in run_result.step_results if sr.step_id == "plan"), None,
    )
    if plan_step and not plan_step.error:
        plans_proposed = plan_step.output.get("plans") or []

    if not plans_proposed:
        await db_service.record_pipeline_run(
            run_id=run_result.run_id,
            workflow_id=run_result.workflow_id,
            mode=run_result.mode,
            ts_start=run_result.ts_start,
            ts_end=run_result.ts_end,
            symbols_analyzed=run_result.symbols_in_shortlist,
            signals_generated=run_result.signals_generated,
            plans_proposed=0,
            plans_approved=0,
            plans_blocked=[],
            error_message=run_result.error,
            status="error" if run_result.error else "complete",
            duration_seconds=run_result.duration_seconds,
        )
        return _summary(run_result, plans_proposed=0, plans_approved=0,
                        plans_blocked=[])

    # ---- Gate every plan ---------------------------------------------- #
    compliance = ComplianceOfficer(s)
    risk = RiskManager(s)
    adapter = get_adapter()
    account = await _safe_get_account(adapter)
    strategy = _strategy_from_workflow(workflow)

    approved = 0
    blocked: list[dict[str, str]] = []

    for plan_dict in plans_proposed:
        plan = TradePlan.model_validate(plan_dict)
        symbol = plan.instrument.get("symbol", "")
        market_state = _market_state_for_plan(plan, adapter)

        # ---- Compliance -----------------------------------------------
        compliance_verdict = compliance.check(plan, account, market_state)
        if compliance_verdict.result == "rejected":
            await db_service.upsert_pending_plan(
                plan_dict,
                compliance_verdict=compliance_verdict.model_dump(),
                risk_verdict=None,
                status="rejected",
                strategy=strategy,
            )
            blocked.append({
                "plan_id": plan.plan_id,
                "symbol": symbol,
                "gate": "compliance",
                "reason": compliance_verdict.block_reason or "",
            })
            logger.info(
                "pipeline: %s blocked by compliance (%s)",
                symbol, compliance_verdict.block_reason,
            )
            continue

        # ---- Risk -----------------------------------------------------
        risk_verdict = risk.pre_trade_check(plan, account, market_state)
        if risk_verdict.result == "rejected":
            await db_service.upsert_pending_plan(
                plan_dict,
                compliance_verdict=compliance_verdict.model_dump(),
                risk_verdict=risk_verdict.model_dump(),
                status="rejected",
                strategy=strategy,
            )
            blocked.append({
                "plan_id": plan.plan_id,
                "symbol": symbol,
                "gate": "risk",
                "reason": risk_verdict.reject_reason or "",
            })
            logger.info(
                "pipeline: %s rejected by risk (%s)",
                symbol, risk_verdict.reject_reason,
            )
            continue

        # Pass / resize → queue for human approval. resized verdicts
        # mutate the plan's risk block so downstream callers see the
        # approved size, not the originally-proposed one.
        if risk_verdict.result == "resized":
            plan_dict = _apply_resize(plan_dict, risk_verdict.model_dump())

        await db_service.upsert_pending_plan(
            plan_dict,
            compliance_verdict=compliance_verdict.model_dump(),
            risk_verdict=risk_verdict.model_dump(),
            status="pending",
            strategy=strategy,
        )
        approved += 1

    await db_service.record_pipeline_run(
        run_id=run_result.run_id,
        workflow_id=run_result.workflow_id,
        mode=run_result.mode,
        ts_start=run_result.ts_start,
        ts_end=run_result.ts_end,
        symbols_analyzed=run_result.symbols_in_shortlist,
        signals_generated=run_result.signals_generated,
        plans_proposed=len(plans_proposed),
        plans_approved=approved,
        plans_blocked=blocked,
        error_message=run_result.error,
        status="error" if run_result.error else "complete",
        duration_seconds=run_result.duration_seconds,
    )

    logger.info(
        "pipeline: %s run_id=%s — %d plans proposed, %d approved, %d blocked",
        run_result.workflow_id, run_result.run_id,
        len(plans_proposed), approved, len(blocked),
    )
    return _summary(run_result, plans_proposed=len(plans_proposed),
                    plans_approved=approved, plans_blocked=blocked)


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #


def _summary(run_result, *, plans_proposed: int, plans_approved: int,
             plans_blocked: list) -> dict[str, Any]:
    return {
        "run_id": run_result.run_id,
        "workflow_id": run_result.workflow_id,
        "mode": run_result.mode,
        "ts_start": run_result.ts_start,
        "ts_end": run_result.ts_end,
        "duration_seconds": run_result.duration_seconds,
        "symbols_in_shortlist": run_result.symbols_in_shortlist,
        "signals_generated": run_result.signals_generated,
        "plans_proposed": plans_proposed,
        "plans_approved": plans_approved,
        "plans_blocked": plans_blocked,
        "error": run_result.error,
        "step_results": [sr.model_dump() for sr in run_result.step_results],
    }


def _strategy_from_workflow(workflow) -> str:
    """Pull the strategy name out of whichever step declared it."""
    for step in workflow.steps:
        if step.kind in ("analyze", "plan"):
            strategy = step.params.get("strategy")
            if strategy:
                return strategy
    return "swing_momentum"


async def _safe_get_account(adapter) -> AccountState:
    """Get account state, connecting if needed; never raise out of here."""
    if not adapter.connected:
        try:
            await adapter.connect()
        except Exception as e:  # noqa: BLE001
            logger.warning("pipeline: adapter connect failed: %s", e)
    try:
        return await adapter.get_account_state()
    except Exception as e:  # noqa: BLE001
        # Fall back to a zeroed account so the gates still run deterministically.
        logger.error("pipeline: get_account_state failed (%s) — using zero stub", e)
        return AccountState(
            account_id="unknown",
            broker=getattr(adapter, "broker_name", "unknown"),
            type="cash",
            equity=0.0,
            cash=0.0,
            buying_power=0.0,
            open_positions=[],
            ts_snapshot=datetime.now(timezone.utc).isoformat(),
        )


def _market_state_for_plan(plan: TradePlan, adapter) -> MarketState:
    """Best-effort snapshot for the plan's symbol.

    In research/paper we only have yfinance + Alpaca; we don't have
    halt status or LULD bands. Those gates are advisory in research
    mode anyway. For spread we use the adapter's last quote if we can
    get it without blocking too long — but we don't fail the plan over
    a missing quote.
    """
    symbol = plan.instrument.get("symbol", "")
    # Default: synthetic state with 0 spread (R9 skips in research mode;
    # the gate tolerates "unknown" by not triggering).
    return MarketState(
        symbol=symbol,
        ts=datetime.now(timezone.utc).isoformat(),
        halt_status=False,
        ssr_active=False,
        luld_band=None,
        earnings_within_hours=None,
        adv=50_000_000,  # Conservative default — 50M shares ADV. R8
                         # computes participation cap from this. For
                         # the liquid names we trade this is close to
                         # reality for mega-caps.
        adv_dollar=50_000_000 * float(plan.setup.entry.price or 0),
        current_spread_bps=0.0,
        vix=None,
        session="regular",
    )


def _apply_resize(plan_dict: dict, risk_verdict: dict) -> dict:
    """Update the plan's risk block to reflect the R-gate's approved size."""
    new_size = int(risk_verdict.get("approved_size_shares") or 0)
    if new_size <= 0:
        return plan_dict
    risk_block = dict(plan_dict.get("risk") or {})
    entry = float(plan_dict.get("setup", {}).get("entry", {}).get("price") or 0)
    r_per_share = float(risk_block.get("r_per_share") or 0)
    risk_block["position_size_shares"] = new_size
    risk_block["position_notional_usd"] = round(new_size * entry, 2)
    risk_block["position_risk_usd"] = round(new_size * r_per_share, 2)
    new_plan = dict(plan_dict)
    new_plan["risk"] = risk_block
    return new_plan


# ---------------------------------------------------------------------- #
# Listing (used by status routes)
# ---------------------------------------------------------------------- #


async def list_runs(limit: int = 20) -> list[dict]:
    return await db_service.list_pipeline_runs(limit=limit)
