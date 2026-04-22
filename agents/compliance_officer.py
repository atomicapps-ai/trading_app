"""compliance_officer.py — hard gate, veto authority.

Implements gates C1–C8 from SKILL.md §3 Agent 4. Each gate is a method
that returns ``ComplianceVerdict | None``. ``None`` means PASS; a non-None
return blocks immediately — the remaining gates are NOT evaluated.

Mode sensitivity
----------------
C1 (halt), C2 (LULD), C3 (SSR) require real-time market microstructure
data that we do not synthesize in research mode. Per the Phase 4 spec,
these three gates are **advisory** in research mode — the check runs but
a violation is logged at WARNING and downgraded to a pass. Paper and
live modes enforce them normally.

C4–C8 are enforced in every mode.

Invariants
----------
* This class is pure: no I/O, no clock reads, no module-level mutation.
* The caller (pipeline_service) is responsible for constructing a fresh
  ``MarketState`` for each plan before invoking ``check()``.
* The returned verdict's ``gates_evaluated`` list is cumulative up to and
  including the gate that blocked (if any).
"""
from __future__ import annotations

import logging
from typing import Callable

from models.account import AccountState, MarketState
from models.trade_plan import TradePlan
from models.verdicts import ComplianceGate, ComplianceVerdict
from services.settings_service import Settings

logger = logging.getLogger(__name__)


_ALL_GATES: tuple[ComplianceGate, ...] = (
    "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8",
)


class ComplianceOfficer:
    """Runs C1–C8 against a TradePlan. Veto authority, no override."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Public entry point
    # ------------------------------------------------------------------ #

    def check(
        self,
        plan: TradePlan,
        account: AccountState,
        market_state: MarketState,
    ) -> ComplianceVerdict:
        """Evaluate all gates in sequence. Return on the first block."""
        gates: list[tuple[ComplianceGate, Callable[..., ComplianceVerdict | None]]] = [
            ("C1", self._c1_halt_check),
            ("C2", self._c2_luld_check),
            ("C3", self._c3_ssr_check),
            ("C4", self._c4_wash_sale_check),
            ("C5", self._c5_pdt_check),
            ("C6", self._c6_restricted_list_check),
            ("C7", self._c7_earnings_blackout_check),
            ("C8", self._c8_plan_completeness_check),
        ]
        evaluated: list[ComplianceGate] = []
        for gate_id, gate in gates:
            evaluated.append(gate_id)
            verdict = gate(plan, account, market_state)
            if verdict is not None:
                verdict.gates_evaluated = list(evaluated)
                logger.warning(
                    "Compliance BLOCK plan=%s gate=%s reason=%s",
                    plan.plan_id, gate_id, verdict.block_reason,
                )
                return verdict
        return ComplianceVerdict(
            plan_id=plan.plan_id,
            result="approved",
            gates_evaluated=list(evaluated),
        )

    # ------------------------------------------------------------------ #
    # Gate implementations
    # ------------------------------------------------------------------ #

    def _c1_halt_check(
        self, plan: TradePlan, account: AccountState, ms: MarketState,
    ) -> ComplianceVerdict | None:
        """Gate C1: Trading halt check.

        SKILL.md §3 Agent 4 C1. Advisory in research mode (no live halt
        feed); enforced in paper/live.
        """
        if not ms.halt_status:
            return None
        if plan.mode == "research":
            logger.info(
                "C1 advisory (research mode): %s is halted per market_state",
                ms.symbol,
            )
            return None
        return ComplianceVerdict(
            plan_id=plan.plan_id,
            result="rejected",
            gates_evaluated=[],
            gates_failed=["C1"],
            block_reason="symbol_halted",
            cited_rule="SKILL.md §3 C1 — Trading halt",
        )

    def _c2_luld_check(
        self, plan: TradePlan, account: AccountState, ms: MarketState,
    ) -> ComplianceVerdict | None:
        """Gate C2: Limit-Up / Limit-Down band.

        SKILL.md §3 Agent 4 C2. Advisory in research mode.
        """
        band = ms.luld_band
        if band is None:
            return None  # no band data → cannot evaluate, pass
        entry = plan.setup.entry.price
        if band.lower <= entry <= band.upper:
            return None
        if plan.mode == "research":
            logger.info(
                "C2 advisory (research mode): entry %.2f outside LULD [%.2f, %.2f]",
                entry, band.lower, band.upper,
            )
            return None
        return ComplianceVerdict(
            plan_id=plan.plan_id,
            result="rejected",
            gates_evaluated=[],
            gates_failed=["C2"],
            block_reason="price_outside_luld_band",
            cited_rule="SKILL.md §3 C2 — LULD",
        )

    def _c3_ssr_check(
        self, plan: TradePlan, account: AccountState, ms: MarketState,
    ) -> ComplianceVerdict | None:
        """Gate C3: Short Sale Restriction (Reg SHO Rule 201).

        Only applies to short trades. Advisory in research mode.
        """
        if plan.setup.direction != "short":
            return None
        if not ms.ssr_active:
            return None
        if plan.mode == "research":
            logger.info("C3 advisory (research mode): SSR active on %s", ms.symbol)
            return None
        return ComplianceVerdict(
            plan_id=plan.plan_id,
            result="rejected",
            gates_evaluated=[],
            gates_failed=["C3"],
            block_reason="ssr_active_no_short_on_downtick",
            cited_rule="SKILL.md §3 C3 — Reg SHO Rule 201",
        )

    def _c4_wash_sale_check(
        self, plan: TradePlan, account: AccountState, ms: MarketState,
    ) -> ComplianceVerdict | None:
        """Gate C4: Wash Sale Rule — IRC §1091.

        Blocks a long open if the symbol was closed at a loss within the
        prior 30 days (tracked in ``account.wash_sale_window``). Short
        trades are not affected. Enforced in all modes.
        """
        if not self._settings.compliance.wash_sale_tracking_enabled:
            return None
        if plan.setup.direction != "long":
            return None
        symbol = plan.instrument.get("symbol", "")
        if symbol and symbol in account.wash_sale_window:
            return ComplianceVerdict(
                plan_id=plan.plan_id,
                result="rejected",
                gates_evaluated=[],
                gates_failed=["C4"],
                block_reason="wash_sale_window_active",
                cited_rule="IRC §1091 — Wash Sale Rule",
            )
        return None

    def _c5_pdt_check(
        self, plan: TradePlan, account: AccountState, ms: MarketState,
    ) -> ComplianceVerdict | None:
        """Gate C5: Pattern Day Trader rule (FINRA 4210).

        Applies only to margin accounts with equity < $25,000 and only to
        intraday holds. Swing plans (or plans without an explicit
        ``expected_holding_period``) skip this gate.
        """
        if account.type != "margin":
            return None
        if account.equity >= 25_000:
            return None
        holding_period = plan.thesis.get("expected_holding_period")
        if holding_period != "intraday":
            return None
        if account.day_trade_count_rolling_5d < 3:
            return None
        return ComplianceVerdict(
            plan_id=plan.plan_id,
            result="rejected",
            gates_evaluated=[],
            gates_failed=["C5"],
            block_reason="pdt_rule_day_trade_limit_reached",
            cited_rule="FINRA Rule 4210 — Pattern Day Trader",
        )

    def _c6_restricted_list_check(
        self, plan: TradePlan, account: AccountState, ms: MarketState,
    ) -> ComplianceVerdict | None:
        """Gate C6: Restricted symbols list (operator-curated).

        Source: ``settings.compliance.restricted_symbols``. Enforced in
        every mode — the list is the human's standing veto.
        """
        symbol = plan.instrument.get("symbol", "")
        restricted = {s.upper() for s in self._settings.compliance.restricted_symbols}
        if symbol.upper() in restricted:
            return ComplianceVerdict(
                plan_id=plan.plan_id,
                result="rejected",
                gates_evaluated=[],
                gates_failed=["C6"],
                block_reason="on_restricted_list",
                cited_rule="settings.compliance.restricted_symbols",
            )
        return None

    def _c7_earnings_blackout_check(
        self, plan: TradePlan, account: AccountState, ms: MarketState,
    ) -> ComplianceVerdict | None:
        """Gate C7: Earnings blackout window.

        Block if the next earnings event is within
        ``settings.compliance.earnings_blackout_hours``. Skipped entirely
        when ``earnings_blackout_enabled == False``.
        """
        comp = self._settings.compliance
        if not comp.earnings_blackout_enabled:
            return None
        hours_to_earnings = ms.earnings_within_hours
        if hours_to_earnings is None:
            return None
        if hours_to_earnings >= comp.earnings_blackout_hours:
            return None
        return ComplianceVerdict(
            plan_id=plan.plan_id,
            result="rejected",
            gates_evaluated=[],
            gates_failed=["C7"],
            block_reason="earnings_blackout_window",
            cited_rule="SKILL.md §3 C7 — Earnings blackout",
        )

    def _c8_plan_completeness_check(
        self, plan: TradePlan, account: AccountState, ms: MarketState,
    ) -> ComplianceVerdict | None:
        """Gate C8: TradePlan completeness.

        Pydantic has already enforced presence of instrument/thesis/setup/
        risk/execution at construction. This gate verifies the *dict*
        fields that Pydantic can't type-check: risk sizing and instrument
        identity. The TP-sums-to-100 and take_profit non-empty rules are
        enforced by the ``Setup`` validator, so reaching C8 means those
        are already valid.
        """
        missing: list[str] = []

        if not plan.instrument.get("symbol"):
            missing.append("instrument.symbol")

        if plan.setup.entry.price <= 0:
            missing.append("setup.entry.price")
        if plan.setup.stop_loss.initial.price <= 0:
            missing.append("setup.stop_loss.initial.price")
        if not plan.setup.take_profit:
            missing.append("setup.take_profit")

        risk = plan.risk or {}
        if not _positive(risk.get("r_per_share")):
            missing.append("risk.r_per_share")
        if not _positive_int(risk.get("position_size_shares")):
            missing.append("risk.position_size_shares")

        if not missing:
            return None
        return ComplianceVerdict(
            plan_id=plan.plan_id,
            result="rejected",
            gates_evaluated=[],
            gates_failed=["C8"],
            block_reason=f"incomplete_trade_plan: {', '.join(missing)}",
            cited_rule="SKILL.md §3 C8 — Plan completeness",
        )


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #


def _positive(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0


def _positive_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v > 0
