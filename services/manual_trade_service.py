"""manual_trade_service — build, gate, queue, and optionally execute an
operator-entered ("manual") trade.

Reuses the same machinery the strategy pipeline uses so a manual trade is a
first-class citizen:
  * PortfolioManager._build_plan assembles the full TradePlan (stop / TP legs /
    trail / risk block) from operator-supplied levels.
  * ComplianceOfficer + RiskManager gate it (same hard gates as the pipeline).
  * db_service.upsert_pending_plan persists it to /pending.
  * Executioner places the order (immediately, for "Execute now").

Sizing is operator-driven: a dollar amount and/or an explicit share count
(share count wins if both supplied), overriding the %-risk sizing.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Literal

from agents.compliance_officer import ComplianceOfficer
from agents.portfolio_manager import PortfolioManager, _DEFAULT_RULES
from agents.risk_manager import RiskManager
from models.signal import Evidence, KeyLevels, Signal
from services import db_service, pipeline_service
from services.broker_service import get_adapter
from services.settings_service import Settings

logger = logging.getLogger(__name__)

MANUAL_STRATEGY = "manual"


async def build_plan(
    *,
    symbol: str,
    direction: Literal["long", "short"],
    entry_type: Literal["market", "limit"],
    entry_price: float,
    stop_price: float,
    tp1_price: float | None,
    tp2_price: float | None,
    dollars: float | None,
    shares: int | None,
    settings: Settings,
) -> dict:
    """Assemble a TradePlan dict from operator input. Pure-ish: only touches
    the broker for account equity (needed by the planner's sizing)."""
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("symbol required")
    if entry_price <= 0 or stop_price <= 0:
        raise ValueError("entry and stop must be positive")
    if direction == "long" and stop_price >= entry_price:
        raise ValueError("for a long, stop must be below entry")
    if direction == "short" and stop_price <= entry_price:
        raise ValueError("for a short, stop must be above entry")

    # Default TP legs if none supplied: a single 2R target. The Setup model
    # requires take_profit size_pct to sum to 100.
    r = abs(entry_price - stop_price)
    if tp1_price is None:
        tp1_price = entry_price + (2.0 * r if direction == "long" else -2.0 * r)
    if tp2_price is None:
        tp2_price = entry_price + (4.0 * r if direction == "long" else -4.0 * r)

    sig = Signal(
        symbol=symbol,
        lens="technical",
        direction=direction,
        strength=1.0,
        timeframe="swing_days",
        key_levels=KeyLevels(
            support=stop_price if direction == "long" else None,
            resistance=stop_price if direction == "short" else None,
            invalidation=stop_price,
        ),
        evidence=[Evidence(type="manual", ref="operator-entered trade")],
        invalidation_condition="manual_stop",
        pattern_name="manual",
        entry_price=round(entry_price, 2),
        stop_price=round(stop_price, 2),
        tp1_price=round(tp1_price, 2),
        tp2_price=round(tp2_price, 2),
    )

    adapter = get_adapter()
    account = await pipeline_service._safe_get_account(adapter)
    mode = settings.app.mode
    pm = PortfolioManager(settings, strategy_config={})
    plan = pm._build_plan(
        symbol=symbol, direction=direction, anchor=sig, all_signals=[sig],
        account=account, mode=mode, rules=dict(_DEFAULT_RULES),
    )

    # Entry type override. The EntryOrder model's market type is
    # "market_on_trigger" (the executioner maps it to a broker market order).
    plan.setup.entry.type = (  # type: ignore[assignment]
        "market_on_trigger" if entry_type == "market" else "limit"
    )

    # Operator sizing override (shares wins; else dollars; else keep %-risk calc).
    override_shares: int | None = None
    if shares and shares > 0:
        override_shares = int(shares)
    elif dollars and dollars > 0 and entry_price > 0:
        override_shares = max(1, math.floor(dollars / entry_price))
    if override_shares is not None:
        r_per_share = abs(entry_price - stop_price)
        plan.risk["position_size_shares"] = override_shares
        plan.risk["position_notional_usd"] = round(override_shares * entry_price, 2)
        plan.risk["position_risk_usd"] = round(override_shares * r_per_share, 2)
        if account.equity > 0:
            plan.risk["position_risk_pct_of_equity"] = round(
                override_shares * r_per_share / account.equity * 100, 3)
            plan.risk["position_notional_pct_of_equity"] = round(
                override_shares * entry_price / account.equity * 100, 2)

    plan.thesis["summary"] = f"MANUAL {direction.upper()} {symbol} (operator-entered)"
    plan.thesis["conviction"] = 1.0
    return plan.model_dump()


async def gate_and_queue(
    plan_dict: dict, settings: Settings, *, execute_now: bool = False,
) -> dict[str, Any]:
    """Run compliance + risk on the plan, persist to /pending, and (if
    execute_now and it passed) fire the executioner with a synthetic ack."""
    from models.trade_plan import TradePlan
    plan = TradePlan.model_validate(plan_dict)
    symbol = plan.instrument.get("symbol", "")

    adapter = get_adapter()
    account = await pipeline_service._safe_get_account(adapter)
    market_state = await pipeline_service._market_state_for_plan(plan, adapter)

    compliance = ComplianceOfficer(settings)
    risk = RiskManager(settings)

    cv = compliance.check(plan, account, market_state)
    if cv.result == "rejected":
        await db_service.upsert_pending_plan(
            plan_dict, compliance_verdict=cv.model_dump(), risk_verdict=None,
            status="rejected", strategy=MANUAL_STRATEGY)
        return {"status": "rejected", "gate": "compliance",
                "reason": cv.block_reason, "plan_id": plan.plan_id}

    rv = risk.pre_trade_check(plan, account, market_state)
    if rv.result == "rejected":
        await db_service.upsert_pending_plan(
            plan_dict, compliance_verdict=cv.model_dump(),
            risk_verdict=rv.model_dump(), status="rejected",
            strategy=MANUAL_STRATEGY)
        return {"status": "rejected", "gate": "risk",
                "reason": rv.reject_reason, "plan_id": plan.plan_id}

    if rv.result == "resized":
        new_size = int(getattr(rv, "approved_size_shares", 0) or 0)
        if new_size > 0:
            entry = float(plan_dict["setup"]["entry"]["price"] or 0)
            rps = float(plan_dict["risk"].get("r_per_share") or 0)
            plan_dict["risk"]["position_size_shares"] = new_size
            plan_dict["risk"]["position_notional_usd"] = round(new_size * entry, 2)
            plan_dict["risk"]["position_risk_usd"] = round(new_size * rps, 2)
            plan = TradePlan.model_validate(plan_dict)

    await db_service.upsert_pending_plan(
        plan_dict, compliance_verdict=cv.model_dump(),
        risk_verdict=rv.model_dump(), status="pending", strategy=MANUAL_STRATEGY)

    result = {"status": "pending", "plan_id": plan.plan_id, "symbol": symbol,
              "shares": plan_dict["risk"].get("position_size_shares")}

    if execute_now:
        from agents.executioner import Executioner
        from models.verdicts import HumanAckRecord
        ack = HumanAckRecord(
            plan_id=plan.plan_id, ts=datetime.now(timezone.utc).isoformat(),
            action="approve", ack_by="manual_execute_now")
        await db_service.ack_plan(plan.plan_id, "approve", ack_record=ack.model_dump())
        exe = Executioner(settings)
        exec_result = await exe.execute_plan(
            plan=plan, compliance_verdict=cv, risk_verdict=rv, ack=ack)
        await db_service.record_execution(plan.plan_id, exec_result.model_dump())
        result["status"] = "executed" if exec_result.placed else "execute_failed"
        result["placed"] = exec_result.placed
        result["reject_reason"] = exec_result.reject_reason
        result["broker_order_id"] = getattr(exec_result, "broker_order_id", None)

    return result
