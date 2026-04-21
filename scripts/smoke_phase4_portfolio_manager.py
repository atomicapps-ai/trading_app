"""Phase 4 C1 — portfolio_manager smoke test.

Two passes:
  1. Direct unit exercise — hand-built signals + account -> portfolio_manager
     emits a TradePlan with correct R math, position sizing, and shape.
  2. End-to-end — run research_run workflow and check the plan step now
     emits REAL TradePlan dicts (not stubs).

Run:
  .venv\\Scripts\\python -m scripts.smoke_phase4_portfolio_manager
"""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

from services.settings_service import ENV_FILE

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


async def direct_test() -> int:
    from agents.portfolio_manager import PortfolioManager
    from models.account import AccountState
    from models.signal import Evidence, KeyLevels, Signal
    from services.settings_service import Settings

    print("=" * 78)
    print("[1/2] Direct portfolio_manager exercise")
    print("=" * 78)

    settings = Settings()
    pm = PortfolioManager(settings)

    # Hand-crafted signals: two technical patterns agreeing long on NVDA.
    # Entry $100, stop $95 -> R=$5/share. TP1 $110 (2R), TP2 $120 (4R).
    def mksig(
        pattern: str, strength: float,
        entry=100.0, stop=95.0, tp1=110.0, tp2=120.0,
    ) -> Signal:
        return Signal(
            symbol="NVDA",
            lens="technical",
            direction="long",
            strength=strength,
            timeframe="swing_days",
            key_levels=KeyLevels(invalidation=stop),
            evidence=[Evidence(type="pattern", ref=f"{pattern} confirmed")],
            invalidation_condition="daily_close_below_stop",
            pattern_name=pattern,
            entry_price=entry,
            stop_price=stop,
            tp1_price=tp1,
            tp2_price=tp2,
        )

    signals = [
        mksig("bull_flag", 0.78),
        mksig("volatility_squeeze", 0.64),
    ]

    account = AccountState(
        account_id="TEST",
        broker="alpaca_paper",
        type="margin",
        equity=100_000.0,
        cash=100_000.0,
        buying_power=200_000.0,
        open_positions=[],
        ts_snapshot=datetime.now(timezone.utc).isoformat(),
    )

    plan = await pm.process_signals(
        symbol="NVDA", signals=signals, account=account, mode="paper",
    )
    expect(plan is not None, "expected a TradePlan, got None")
    print(f"  plan_id={plan.plan_id}")
    print(f"  direction={plan.setup.direction}, mode={plan.mode}")
    print(f"  entry=${plan.setup.entry.price}, stop=${plan.setup.stop_loss.initial.price}")
    print(f"  tp1=${plan.setup.take_profit[0].price} tp2=${plan.setup.take_profit[1].price}")
    print(f"  shares={plan.risk['position_size_shares']}, "
          f"notional=${plan.risk['position_notional_usd']:,.2f}, "
          f"risk=${plan.risk['position_risk_usd']:,.2f}")
    print(f"  R_tp1={plan.risk['r_multiple_to_tp1']}, R_tp2={plan.risk['r_multiple_to_tp2']}")
    print(f"  conviction={plan.thesis['conviction']}, "
          f"lenses={plan.thesis['lenses_contributing']}, "
          f"patterns={sorted({s.pattern_name for s in signals})}")

    # Position sizing check: 0.50% of $100k = $500 max risk; R=$5 -> 100 shares
    expect(plan.risk["position_size_shares"] == 100,
           f"expected 100 shares @ 0.5% risk on $5 R, got {plan.risk['position_size_shares']}")
    expect(abs(plan.risk["position_risk_usd"] - 500.0) < 1e-6,
           f"expected $500 risk, got {plan.risk['position_risk_usd']}")
    expect(abs(plan.risk["r_multiple_to_tp1"] - 2.0) < 1e-6,
           f"expected R_tp1=2.0, got {plan.risk['r_multiple_to_tp1']}")
    expect(abs(plan.risk["r_multiple_to_tp2"] - 4.0) < 1e-6,
           f"expected R_tp2=4.0, got {plan.risk['r_multiple_to_tp2']}")
    expect(len(plan.setup.take_profit) == 2 and
           plan.setup.take_profit[0].size_pct + plan.setup.take_profit[1].size_pct == 100,
           "TP legs must sum to 100% size")

    # Negative cases
    # a) signals disagree -> no plan
    mixed = [mksig("bull_flag", 0.7), Signal(
        symbol="NVDA", lens="technical", direction="short", strength=0.6,
        timeframe="swing_days",
        key_levels=KeyLevels(invalidation=105.0),
        invalidation_condition="below_support",
        pattern_name="bear_flag",
        entry_price=100.0, stop_price=105.0, tp1_price=92.0, tp2_price=85.0,
    )]
    # Long strength 0.7, short strength 0.6 -> long wins, only 1 pattern (bull_flag)
    # strength 0.7 < override 0.75, 1 lens < 2, 1 pattern < 2 -> no consensus
    result = await pm.process_signals(
        symbol="NVDA", signals=mixed, account=account, mode="paper",
    )
    expect(result is None, "mixed signals without consensus should yield no plan")
    print("  [neg] mixed low-conviction signals -> no plan (correct)")

    # b) existing position -> skip
    result = await pm.process_signals(
        symbol="NVDA", signals=signals, account=account,
        existing_positions=["NVDA"], mode="paper",
    )
    expect(result is None, "existing position should skip new plan in Phase 4")
    print("  [neg] already in NVDA -> skip (correct)")

    # c) pending queue full
    result = await pm.process_signals(
        symbol="NVDA", signals=signals, account=account,
        mode="paper", pending_count=5,
    )
    expect(result is None, "pending=5 should block further plans")
    print("  [neg] pending queue full (5) -> skip (correct)")

    print("  OK — direct portfolio_manager tests pass")
    return 0


async def end_to_end_test() -> int:
    from services.settings_service import Settings
    from services.workflow_engine import WorkflowEngine

    print("\n" + "=" * 78)
    print("[2/2] End-to-end research_run via workflow engine")
    print("=" * 78)

    settings = Settings()
    engine = WorkflowEngine(settings)
    wf = await engine.load_by_id("research_run")
    result = await engine.run(wf)

    expect(result.error is None, f"workflow errored: {result.error}")
    plan_step = next((s for s in result.step_results if s.step_id == "plan"), None)
    expect(plan_step is not None, "plan step missing")
    expect(not plan_step.output.get("stub", False),
           f"plan step still stubbed: {plan_step.output}")

    plans = plan_step.output.get("plans", []) or []
    signals = (
        next((s for s in result.step_results if s.step_id == "analyze"), None)
        .output.get("signals") or {}
    )
    total_signals = sum(len(v) for v in signals.values())

    print(f"  shortlist_size = {result.symbols_in_shortlist}")
    print(f"  signals_generated = {total_signals}")
    print(f"  plans_proposed = {len(plans)}")
    for p in plans:
        sym = p["instrument"]["symbol"]
        direction = p["setup"]["direction"]
        shares = p["risk"]["position_size_shares"]
        entry = p["setup"]["entry"]["price"]
        stop = p["setup"]["stop_loss"]["initial"]["price"]
        tp1 = p["setup"]["take_profit"][0]["price"]
        print(f"    {sym} {direction} {shares}sh entry=${entry} stop=${stop} tp1=${tp1} "
              f"R_tp1={p['risk']['r_multiple_to_tp1']}")

    # We don't assert plans > 0 — real market data may not trigger a
    # consensus on a given day. What we DO assert is that plan_step is
    # no longer stubbed, and that any plans produced have a sane shape.
    for p in plans:
        expect("plan_id" in p, "plan missing plan_id")
        expect(p["mode"] == "research", f"wrong mode: {p['mode']}")
        expect(p["risk"]["position_size_shares"] >= 0, "negative share count")

    print("  OK — plan step is live, no stubs")
    return 0


async def main() -> int:
    load_dotenv(ENV_FILE, override=False)
    try:
        rc = await direct_test()
        if rc != 0:
            return rc
        rc = await end_to_end_test()
        if rc != 0:
            return rc
    except AssertionError as e:
        print(f"\nFAIL — {e}")
        return 1

    print("\n" + "=" * 78)
    print("ALL GREEN — portfolio_manager wired end-to-end.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
