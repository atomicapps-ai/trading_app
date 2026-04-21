"""executioner.py — the only agent that talks to the broker adapter.

Receives an approved TradePlan + the human's ack, re-verifies every
safety gate, translates the plan's entry into an Order, and places it
through the injected BrokerAdapter.

SKILL.md §9 + phase4 prompt set the invariants this file enforces:

  * mode must be ``paper`` or ``live`` (research never trades)
  * compliance_verdict.result must be ``pass``
  * risk_verdict.result must be ``approve`` or ``resize``
  * services.broker_service.TRADING_HALTED must be False
  * HumanAckRecord must be fresh (within settings.execution.human_ack_timeout_minutes)
  * HumanAckRecord.action must be ``approve``

Any violation returns a populated ExecutionResult with ``placed=False``
and the specific reason — the caller persists it, the UI surfaces it,
and no order leaves this machine.

Phase 4 scope
-------------
The entry order is the only side placed here. Stop / take-profit
brackets, time stops, and thesis invalidation are recorded on the
TradePlan for Phase 7's position manager, which will poll positions
and trigger exits.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from brokers.base import BrokerAdapter
from models.account import Order, OrderAck
from models.execution import ExecutionResult
from models.trade_plan import TradePlan
from models.verdicts import ComplianceVerdict, HumanAckRecord, RiskVerdict
from services import broker_service
from services.settings_service import Settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------- #
# Enum translation
# ---------------------------------------------------------------------- #


def _side_for_direction(direction: str) -> str:
    if direction == "long":
        return "buy"
    if direction == "short":
        return "sell_short"
    raise ValueError(f"unexpected direction: {direction!r}")


def _order_type_for_entry(entry_type: str) -> str:
    # TradePlan.setup.entry.type -> Order.order_type
    return {
        "limit": "limit",
        "stop": "stop",
        "market_on_trigger": "market",
    }.get(entry_type, "limit")


def _tif_for_valid_until(valid_until: str) -> str:
    # TradePlan.setup.entry.valid_until -> Order.time_in_force
    if valid_until == "gtc":
        return "gtc"
    if valid_until == "session_close":
        return "day"
    # iso8601 — closest approximation the adapters all support
    return "day"


# ---------------------------------------------------------------------- #
# Executioner
# ---------------------------------------------------------------------- #


class Executioner:
    def __init__(
        self,
        settings: Settings,
        adapter: BrokerAdapter | None = None,
    ) -> None:
        self._settings = settings
        self._adapter = adapter  # None → resolved via broker_service.get_adapter()

    async def execute_plan(
        self,
        plan: TradePlan,
        compliance_verdict: ComplianceVerdict | None,
        risk_verdict: RiskVerdict | None,
        ack: HumanAckRecord,
    ) -> ExecutionResult:
        """Re-check every gate, translate plan→Order, place via adapter."""
        # ---- Mode gate -------------------------------------------------
        if plan.mode == "research":
            return self._reject(plan, "research_mode_no_orders", ack)

        # ---- Halt gate -------------------------------------------------
        if broker_service.TRADING_HALTED:
            return self._reject(plan, "trading_halted", ack)

        # ---- Ack gate --------------------------------------------------
        if ack.action != "approve":
            return self._reject(plan, f"ack_action_not_approve ({ack.action})", ack)
        if not self._ack_is_fresh(ack):
            return self._reject(plan, "ack_stale", ack)

        # ---- Verdict gates --------------------------------------------
        if compliance_verdict is None or compliance_verdict.result != "pass":
            reason = (
                f"compliance_not_pass (result={getattr(compliance_verdict, 'result', None)!r})"
            )
            return self._reject(plan, reason, ack)
        if risk_verdict is None or risk_verdict.result not in ("approve", "resize"):
            reason = (
                f"risk_not_approved (result={getattr(risk_verdict, 'result', None)!r})"
            )
            return self._reject(plan, reason, ack)

        # Sizing: risk verdict is the source of truth (it may have resized)
        qty = int(risk_verdict.approved_size_shares or 0)
        if qty <= 0:
            return self._reject(plan, "approved_size_zero", ack)

        # ---- Live mode additional guardrail ----------------------------
        # SKILL.md: live orders must require human ack. The ack check above
        # already covers this, but we also require execution to be enabled.
        if plan.mode == "live" and not self._settings.execution.human_ack_required:
            return self._reject(
                plan, "live_mode_requires_execution.human_ack_required=true", ack,
            )

        # ---- Translate -------------------------------------------------
        try:
            order = self._plan_to_order(plan, qty)
        except ValueError as e:
            return self._reject(plan, f"order_translation_failed: {e}", ack)

        # ---- Place -----------------------------------------------------
        adapter = self._adapter or broker_service.get_adapter()
        if not adapter.connected:
            try:
                ok = await adapter.connect()
                if not ok:
                    return self._reject(plan, "broker_disconnected", ack)
            except Exception as e:  # noqa: BLE001
                return self._reject(plan, f"broker_connect_raised: {e}", ack)

        logger.info(
            "Executioner: placing %s %s %s qty=%d (plan=%s)",
            order.side, order.order_type, order.symbol, order.quantity,
            plan.plan_id,
        )
        try:
            order_ack = await adapter.place_order(order)
        except Exception as e:  # noqa: BLE001
            logger.exception("place_order raised")
            return self._reject(plan, f"place_order_raised: {e}", ack)

        result = ExecutionResult(
            plan_id=plan.plan_id,
            ack_id=ack.ack_id,
            placed=order_ack.accepted,
            client_order_id=order_ack.client_order_id,
            broker_order_id=order_ack.broker_order_id,
            broker_name=adapter.broker_name,
            order_json=order.model_dump(),
            order_ack_json=order_ack.model_dump(),
            ts=datetime.now(timezone.utc).isoformat(),
            reject_reason=order_ack.reject_reason if not order_ack.accepted else None,
        )
        if result.placed:
            logger.info(
                "Executioner: placed plan=%s broker_order_id=%s",
                plan.plan_id, result.broker_order_id,
            )
        else:
            logger.warning(
                "Executioner: broker rejected plan=%s reason=%s",
                plan.plan_id, result.reject_reason,
            )
        return result

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _ack_is_fresh(self, ack: HumanAckRecord) -> bool:
        try:
            ack_ts = datetime.fromisoformat(ack.ts.replace("Z", "+00:00"))
        except Exception:  # noqa: BLE001
            return False
        max_age = timedelta(
            minutes=self._settings.execution.human_ack_timeout_minutes,
        )
        return (datetime.now(timezone.utc) - ack_ts) <= max_age

    def _plan_to_order(self, plan: TradePlan, qty: int) -> Order:
        symbol = plan.instrument.get("symbol")
        if not symbol:
            raise ValueError("plan.instrument.symbol missing")
        side = _side_for_direction(plan.setup.direction)
        entry = plan.setup.entry
        order_type = _order_type_for_entry(entry.type)
        tif = _tif_for_valid_until(entry.valid_until)

        client_order_id = f"exec-{plan.plan_id[:8]}-{uuid4().hex[:6]}"

        limit_price: float | None = None
        stop_price: float | None = None
        if order_type == "limit":
            limit_price = float(entry.price)
        elif order_type == "stop":
            stop_price = float(entry.price)
        # market → no price

        return Order(
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,  # type: ignore[arg-type]
            order_type=order_type,  # type: ignore[arg-type]
            quantity=qty,
            limit_price=limit_price,
            stop_price=stop_price,
            time_in_force=tif,  # type: ignore[arg-type]
            algo=None,
            extended_hours=False,
        )

    def _reject(
        self,
        plan: TradePlan,
        reason: str,
        ack: HumanAckRecord,
    ) -> ExecutionResult:
        logger.warning(
            "Executioner: refused to place plan=%s reason=%s",
            plan.plan_id, reason,
        )
        return ExecutionResult(
            plan_id=plan.plan_id,
            ack_id=ack.ack_id,
            placed=False,
            client_order_id=None,
            broker_order_id=None,
            broker_name=None,
            order_json=None,
            order_ack_json=None,
            ts=datetime.now(timezone.utc).isoformat(),
            reject_reason=reason,
        )
