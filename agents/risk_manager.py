"""risk_manager.py — pre-trade hard gate R1–R9.

Post-trade postmortem (MFE / MAE / R-multiple / learning tags) is wired
in Phase 6 alongside the executioner. Phase 4 only needs pre-trade sizing
+ rejection.

Gate behavior
-------------
* **R1 (per-trade risk cap)** and **R2 (notional cap)** may *resize*
  the proposed position. Both run; the effective approved size is the
  minimum of the two resizes and the original size.
* **R8 (participation cap)** may further resize against ADV.
* **R3, R4, R5, R6, R7, R9** reject outright — no resize.
* If any resize drives approved shares to 0, the plan is rejected
  (``result="reject"``, reason ``sizing_reduced_to_zero``).

Mode sensitivity
----------------
R9 requires a live quote spread. In research mode we do not synthesize
one; if ``market_state.current_spread_bps`` is 0 (the historical-adapter
default) or negative, R9 is skipped. Paper and live enforce R9 normally.

Signature note
--------------
The phase4 scaffold listed ``pre_trade_check(plan, account)`` without a
``MarketState`` argument, but R8 needs ADV and R9 needs the current
spread. Both are per-symbol microstructure, so we accept ``MarketState``
as a third parameter here — consistent with ``ComplianceOfficer.check``.
"""
from __future__ import annotations

import logging
import math

from models.account import AccountState, MarketState
from models.trade_plan import TradePlan
from models.verdicts import RiskGate, RiskVerdict
from services.settings_service import RiskDefaults, Settings

logger = logging.getLogger(__name__)


class RiskManager:
    """Runs R1–R9 pre-trade. Hard gate; resizes or rejects."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Public entry point
    # ------------------------------------------------------------------ #

    def pre_trade_check(
        self,
        plan: TradePlan,
        account: AccountState,
        market_state: MarketState,
    ) -> RiskVerdict:
        """Evaluate R1–R9. Returns approve / resize / reject."""
        rd = self._settings.risk_defaults
        original_size = int(plan.risk.get("position_size_shares") or 0)
        r_per_share = float(plan.risk.get("r_per_share") or 0.0)
        entry_price = float(plan.setup.entry.price)
        evaluated: list[RiskGate] = []
        triggered: list[RiskGate] = []
        reasons: list[str] = []

        if original_size <= 0 or r_per_share <= 0 or entry_price <= 0:
            # Defensive: C8 should have caught this, but we can't divide
            # by zero in the cap math below. Kick it back as reject.
            return RiskVerdict(
                plan_id=plan.plan_id,
                result="reject",
                original_size_shares=original_size,
                approved_size_shares=0,
                gates_evaluated=evaluated,
                gates_triggered=triggered,
                reject_reason="invalid_sizing_inputs",
            )

        approved = original_size

        # ---- R1: per-trade risk cap ---------------------------------------
        evaluated.append("R1")
        r1_cap = self._r1_per_trade_risk_cap(account.equity, r_per_share, rd)
        if r1_cap < approved:
            triggered.append("R1")
            reasons.append(
                f"R1 per_trade_risk_cap: reduced from {approved} to {r1_cap} shares"
            )
            approved = r1_cap

        # ---- R2: notional cap ---------------------------------------------
        evaluated.append("R2")
        r2_cap = self._r2_notional_cap(account.equity, entry_price, rd)
        if r2_cap < approved:
            triggered.append("R2")
            reasons.append(
                f"R2 notional_cap: reduced from {approved} to {r2_cap} shares"
            )
            approved = r2_cap

        # ---- R3: daily loss cap -------------------------------------------
        evaluated.append("R3")
        if self._r3_daily_loss_cap_hit(account, rd):
            triggered.append("R3")
            return _reject(
                plan, original_size, evaluated, triggered,
                reason="daily_loss_cap_reached",
            )

        # ---- R4: max open positions ---------------------------------------
        evaluated.append("R4")
        if len(account.open_positions) >= rd.max_open_positions:
            triggered.append("R4")
            return _reject(
                plan, original_size, evaluated, triggered,
                reason=f"max_open_positions_reached ({rd.max_open_positions})",
            )

        # ---- R5: max daily trades -----------------------------------------
        evaluated.append("R5")
        if account.trades_today >= rd.max_daily_trades:
            triggered.append("R5")
            return _reject(
                plan, original_size, evaluated, triggered,
                reason=f"max_daily_trades_reached ({rd.max_daily_trades})",
            )

        # ---- R6: sector concentration -------------------------------------
        evaluated.append("R6")
        sector = plan.instrument.get("sector") or ""
        if sector and self._r6_sector_concentration_exceeded(
            sector, approved, entry_price, account, rd,
        ):
            triggered.append("R6")
            return _reject(
                plan, original_size, evaluated, triggered,
                reason=(
                    f"sector_concentration_exceeded "
                    f"(>{rd.max_sector_concentration_pct:.1f}% in {sector})"
                ),
            )

        # ---- R7: minimum R:R ratio ----------------------------------------
        evaluated.append("R7")
        r_multiple_tp1 = float(plan.risk.get("r_multiple_to_tp1") or 0.0)
        if r_multiple_tp1 < rd.min_rr_ratio:
            triggered.append("R7")
            return _reject(
                plan, original_size, evaluated, triggered,
                reason=(
                    f"insufficient_risk_reward "
                    f"(tp1 R={r_multiple_tp1:.2f} < {rd.min_rr_ratio:.2f})"
                ),
            )

        # ---- R8: liquidity / participation cap ----------------------------
        evaluated.append("R8")
        r8_cap = self._r8_participation_cap(market_state.adv, rd)
        if r8_cap < approved:
            triggered.append("R8")
            reasons.append(
                f"R8 participation_cap: reduced from {approved} to {r8_cap} shares"
            )
            approved = r8_cap

        # ---- R9: spread check ---------------------------------------------
        evaluated.append("R9")
        spread_bps = market_state.current_spread_bps
        if plan.mode != "research" and spread_bps > 0:
            if spread_bps > rd.max_spread_bps_to_cross:
                triggered.append("R9")
                return _reject(
                    plan, original_size, evaluated, triggered,
                    reason=(
                        f"spread_too_wide "
                        f"({spread_bps:.1f}bps > {rd.max_spread_bps_to_cross:.1f})"
                    ),
                )

        # ---- Zero-size guard after all resizes ----------------------------
        if approved <= 0:
            return _reject(
                plan, original_size, evaluated, triggered,
                reason="sizing_reduced_to_zero",
            )

        approved_risk = approved * r_per_share
        approved_notional = approved * entry_price
        if approved == original_size and not triggered:
            result = "approve"
            resize_reason = None
        else:
            result = "resize"
            resize_reason = "; ".join(reasons) if reasons else None

        logger.info(
            "Risk %s plan=%s size %d -> %d triggered=%s",
            result.upper(), plan.plan_id, original_size, approved, triggered,
        )

        return RiskVerdict(
            plan_id=plan.plan_id,
            result=result,
            original_size_shares=original_size,
            approved_size_shares=approved,
            gates_evaluated=evaluated,
            gates_triggered=triggered,
            resize_reason=resize_reason,
            approved_risk_usd=round(approved_risk, 2),
            approved_notional_usd=round(approved_notional, 2),
        )

    # ------------------------------------------------------------------ #
    # Individual gate math (pure helpers)
    # ------------------------------------------------------------------ #

    def _r1_per_trade_risk_cap(
        self, equity: float, r_per_share: float, rd: RiskDefaults,
    ) -> int:
        """Gate R1: per-trade risk cap.

        ``max_risk_pct_per_trade`` is a percentage of equity (0.50 = 0.5%).
        Returns the maximum allowable share count under the cap.
        """
        cap_usd = equity * rd.max_risk_pct_per_trade / 100.0
        return max(0, math.floor(cap_usd / r_per_share))

    def _r2_notional_cap(
        self, equity: float, entry_price: float, rd: RiskDefaults,
    ) -> int:
        """Gate R2: position notional cap.

        ``max_position_pct_of_equity`` is a percentage (10.0 = 10%).
        """
        cap_usd = equity * rd.max_position_pct_of_equity / 100.0
        return max(0, math.floor(cap_usd / entry_price))

    def _r3_daily_loss_cap_hit(
        self, account: AccountState, rd: RiskDefaults,
    ) -> bool:
        """Gate R3: daily loss cap.

        Reject if realized+unrealized intraday P&L breaches
        ``-(equity × max_daily_loss_pct / 100)``.
        """
        daily_pnl = account.realized_pnl_today + account.unrealized_pnl_today
        loss_cap_usd = account.equity * rd.max_daily_loss_pct / 100.0
        return daily_pnl <= -loss_cap_usd

    def _r6_sector_concentration_exceeded(
        self,
        sector: str,
        shares_after_resize: int,
        entry_price: float,
        account: AccountState,
        rd: RiskDefaults,
    ) -> bool:
        """Gate R6: correlated exposure (sector concentration).

        Summed notional of existing positions in the same sector plus the
        new proposal cannot exceed ``max_sector_concentration_pct`` of
        equity.
        """
        if account.equity <= 0:
            return True  # defensive — no equity → every trade concentrates
        same_sector_notional = sum(
            abs(p.shares) * p.market_price
            for p in account.open_positions
            if (p.sector or "") == sector
        )
        total_after = same_sector_notional + shares_after_resize * entry_price
        pct_after = (total_after / account.equity) * 100.0
        return pct_after > rd.max_sector_concentration_pct

    def _r8_participation_cap(self, adv: int, rd: RiskDefaults) -> int:
        """Gate R8: liquidity / participation cap.

        Cap order size at ``participation_cap_pct_adv`` of 30-day ADV.
        If ADV is unknown (0), no cap is applied (return a very large
        number).
        """
        if adv <= 0:
            return 10**12  # effectively no cap
        return max(0, math.floor(adv * rd.participation_cap_pct_adv / 100.0))


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #


def _reject(
    plan: TradePlan,
    original_size: int,
    evaluated: list[RiskGate],
    triggered: list[RiskGate],
    reason: str,
) -> RiskVerdict:
    logger.warning(
        "Risk REJECT plan=%s reason=%s triggered=%s",
        plan.plan_id, reason, triggered,
    )
    return RiskVerdict(
        plan_id=plan.plan_id,
        result="reject",
        original_size_shares=original_size,
        approved_size_shares=0,
        gates_evaluated=evaluated,
        gates_triggered=triggered,
        reject_reason=reason,
    )
