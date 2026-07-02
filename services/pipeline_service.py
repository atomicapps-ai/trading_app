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

    # Per-symbol drill-down: what happened to every symbol on the shortlist.
    # Built regardless of plan count — a 0-plan run is exactly when the
    # operator most needs to see WHY (no setup vs. blocked vs. no fear
    # regime, etc.). Gate outcomes get merged in during the plan loop below.
    outcomes = _build_symbol_outcomes(run_result)

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
            symbol_outcomes=outcomes,
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
        market_state = await _market_state_for_plan(plan, adapter)

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
            _mark_outcome(outcomes, symbol, "blocked_compliance",
                          compliance_verdict.block_reason or "compliance gate",
                          plan_id=plan.plan_id)
            logger.info(
                "pipeline: %s blocked by compliance (%s)",
                symbol, compliance_verdict.block_reason,
            )
            # Dashboard-only alert (no phone push) — gives the operator
            # visibility into rejected plans without spamming notifications.
            try:
                from services import alert_service
                await alert_service.record_alert(
                    kind="rejected", strategy=strategy, symbol=symbol,
                    direction=plan.setup.direction, plan_id=plan.plan_id,
                    title=f"{symbol} {plan.setup.direction.upper()} rejected by compliance",
                    body=f"Reason: {compliance_verdict.block_reason or '(no reason)'}",
                    payload={"gate": "compliance", "reason": compliance_verdict.block_reason},
                )
            except Exception as e:                                # noqa: BLE001
                logger.debug("rejected-alert (compliance) failed: %s", e)
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
            _mark_outcome(outcomes, symbol, "blocked_risk",
                          risk_verdict.reject_reason or "risk gate",
                          plan_id=plan.plan_id)
            logger.info(
                "pipeline: %s rejected by risk (%s)",
                symbol, risk_verdict.reject_reason,
            )
            # Dashboard-only alert (no phone push) — same rationale as
            # the compliance hook above. Use plain "rejected" kind so
            # both gate types share one alert stream.
            try:
                from services import alert_service
                await alert_service.record_alert(
                    kind="rejected", strategy=strategy, symbol=symbol,
                    direction=plan.setup.direction, plan_id=plan.plan_id,
                    title=f"{symbol} {plan.setup.direction.upper()} rejected by risk",
                    body=f"Reason: {risk_verdict.reject_reason or '(no reason)'}",
                    payload={"gate": "risk", "reason": risk_verdict.reject_reason,
                             "blocked_gate": getattr(risk_verdict, "blocked_gate", None)},
                )
            except Exception as e:                                # noqa: BLE001
                logger.debug("rejected-alert (risk) failed: %s", e)
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
        _mark_outcome(
            outcomes, symbol, "queued",
            f"passed gates ({risk_verdict.result})", plan_id=plan.plan_id,
        )

        # ── ARMED alert ─────────────────────────────────────────────
        # The plan cleared compliance + risk and is awaiting human ack.
        # Fire a dashboard banner notification so the operator doesn't
        # miss the 10:30 fire while looking at another tab.
        try:
            from services import alert_service
            entry_dict = (plan_dict.get("setup") or {}).get("entry") or {}
            entry_price = entry_dict.get("price")
            await alert_service.record_alert(
                kind="armed",
                strategy=strategy,
                symbol=symbol,
                direction=plan.setup.direction,
                plan_id=plan.plan_id,
                title=(
                    f"{symbol} {plan.setup.direction.upper()} — "
                    f"{strategy} ARMED"
                ),
                body=(
                    f"Entry @ {entry_price} · "
                    f"conviction {plan.thesis.get('conviction', 0):.0%} · "
                    f"awaiting approval"
                ),
                payload={
                    "entry_price": entry_price,
                    "valid_until": entry_dict.get("valid_until"),
                    "risk_usd": (plan_dict.get("risk") or {}).get(
                        "position_risk_usd"),
                    "shares": (plan_dict.get("risk") or {}).get(
                        "position_size_shares"),
                    "ts_created": plan.ts_created,
                },
            )
        except Exception as e:                                    # noqa: BLE001
            logger.warning("armed-alert recording failed: %s", e)

        # ── AUTO-APPROVE (paper-only) ───────────────────────────────
        # If the strategy has auto_approve enabled AND every safety
        # guardrail passes (paper account, paper mode, not halted),
        # immediately dispatch the executioner with a synthetic ack.
        # Live accounts and live mode always require manual ack —
        # enforced inside auto_approve_service.safe_to_auto_approve().
        try:
            from datetime import datetime, timezone
            from agents.executioner import Executioner
            from models.verdicts import HumanAckRecord
            from services import auto_approve_service

            allowed, reason = await auto_approve_service.safe_to_auto_approve(strategy)
            if allowed:
                logger.warning(
                    "AUTO-APPROVE firing for plan_id=%s symbol=%s strategy=%s",
                    plan.plan_id, symbol, strategy,
                )
                ack = HumanAckRecord(
                    plan_id=plan.plan_id,
                    ts=datetime.now(timezone.utc).isoformat(),
                    action="approve",
                    ack_by="auto_approve",
                )
                await db_service.ack_plan(
                    plan.plan_id, "approve", ack_record=ack.model_dump(),
                )
                # Reuse the function-scope `s` (Settings) — don't re-import
                # get_settings here, that creates a function-local binding
                # that shadows the module-level import at line 56 and
                # raises UnboundLocalError on the first reference.
                exe = Executioner(s)
                exec_result = await exe.execute_plan(
                    plan=plan,
                    compliance_verdict=compliance_verdict,
                    risk_verdict=risk_verdict,
                    ack=ack,
                )
                await db_service.record_execution(
                    plan.plan_id, exec_result.model_dump(),
                )
                logger.warning(
                    "AUTO-APPROVE result: plan_id=%s placed=%s reason=%s",
                    plan.plan_id, exec_result.placed,
                    exec_result.reject_reason or "",
                )
            else:
                logger.info(
                    "auto_approve declined plan_id=%s reason=%s",
                    plan.plan_id, reason,
                )
        except Exception as e:                                    # noqa: BLE001
            logger.error("auto_approve hook raised: %s", e, exc_info=True)

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
        symbol_outcomes=outcomes,
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


# ---------------------------------------------------------------------- #
# Per-symbol drill-down
# ---------------------------------------------------------------------- #
#
# Outcome codes (ranked most→least actionable in the UI):
#   queued              plan built + passed both gates → awaiting approval
#   blocked_compliance  plan built but compliance gate rejected
#   blocked_risk        plan built but risk gate rejected
#   signal_no_plan      detector fired but no plan built (consensus / already
#                       open / queue full / inverted stop)
#   no_setup            analyzed, detector didn't fire (the common "nothing
#                       here today" case — this is where a 0-trade day lives)
#
# Pre-shortlist rejections (symbols that never reached analysis) are kept as
# an aggregate ``filter_rejections`` count, since the universe filter reports
# reasons in aggregate, not per symbol.


def _build_symbol_outcomes(run_result) -> dict[str, Any]:
    """Assemble the per-symbol processing map from the workflow step outputs.

    Every symbol on the shortlist gets a row. Symbols that fired a detector
    start as ``signal_no_plan`` and get upgraded to ``queued`` / ``blocked_*``
    as the gate loop runs (via ``_mark_outcome``). Symbols with no signal are
    ``no_setup`` — that is the honest reason most scans return 0 on a calm day.
    """
    steps = {sr.step_id: sr for sr in run_result.step_results}
    fu = steps.get("filter_universe")
    an = steps.get("analyze")

    shortlist: list[str] = list((fu.output.get("shortlist") if fu else None) or [])
    filter_rejections: dict[str, int] = (
        (fu.output.get("rejection_reasons") if fu else None) or {}
    )
    signals_by_symbol: dict[str, list] = (
        (an.output.get("signals") if an else None) or {}
    )

    symbols: dict[str, dict[str, Any]] = {}
    for sym in shortlist:
        sigs = signals_by_symbol.get(sym) or []
        if sigs:
            # Strongest signal's direction/strength for context.
            top = max(sigs, key=lambda s: s.get("strength", 0) if isinstance(s, dict) else 0)
            symbols[sym] = {
                "symbol": sym,
                "outcome": "signal_no_plan",
                "detail": "signal fired; no plan built (consensus / already open / queue)",
                "direction": (top.get("direction") if isinstance(top, dict) else None),
                "strength": (round(top.get("strength", 0), 2) if isinstance(top, dict) else None),
                "pattern": (top.get("pattern_name") if isinstance(top, dict) else None),
                "plan_id": None,
            }
        else:
            symbols[sym] = {
                "symbol": sym,
                "outcome": "no_setup",
                "detail": "analyzed — detector did not fire",
                "direction": None,
                "strength": None,
                "pattern": None,
                "plan_id": None,
            }

    return {
        "shortlist_size": len(shortlist),
        "signals_generated": run_result.signals_generated,
        "filter_rejections": filter_rejections,
        "total_screened": int((fu.output.get("total_screened") if fu else 0) or 0),
        "symbols": symbols,
    }


def _mark_outcome(outcomes: dict, symbol: str, outcome: str, detail: str,
                  *, plan_id: str | None = None) -> None:
    """Upgrade a symbol's row to a terminal gate outcome, in place."""
    if not outcomes:
        return
    row = outcomes.setdefault("symbols", {}).get(symbol)
    if row is None:
        row = {"symbol": symbol, "direction": None, "strength": None, "pattern": None}
        outcomes["symbols"][symbol] = row
    row["outcome"] = outcome
    row["detail"] = detail
    if plan_id:
        row["plan_id"] = plan_id


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


async def _market_state_for_plan(plan: TradePlan, adapter) -> MarketState:
    """Best-effort snapshot for the plan's symbol.

    In research/paper we only have yfinance + Alpaca; we don't have
    halt status or LULD bands. Those gates are advisory in research
    mode anyway. For spread we use the adapter's last quote if we can
    get it without blocking too long — but we don't fail the plan over
    a missing quote.

    earnings_within_hours: looked up via earnings_service (yfinance
    Ticker.calendar, 4-hour TTL cache). Compliance gate C7 reads this
    to enforce the configured earnings blackout window. Best-effort:
    if the lookup fails the value stays None and C7 skips the check.
    """
    symbol = plan.instrument.get("symbol", "")

    earnings_hours: float | None = None
    if symbol:
        try:
            from services import earnings_service
            earnings_hours = await earnings_service.get_hours_to_next_earnings(symbol)
        except Exception as exc:                                      # noqa: BLE001
            logger.debug("earnings lookup for %s failed: %s", symbol, exc)

    return MarketState(
        symbol=symbol,
        ts=datetime.now(timezone.utc).isoformat(),
        halt_status=False,
        ssr_active=False,
        luld_band=None,
        earnings_within_hours=earnings_hours,
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
