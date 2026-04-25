"""Smoke test: executioner.close_at_time() schedules a market-close
at the plan's TimeStop deadline.

Covers:
  1. Intraday TradePlan deadline computation in portfolio_manager
     (today/tomorrow 15:00 ET, depending on now()).
  2. close_at_time happy path — APScheduler job registered with the
     expected id and run_date.
  3. close_at_time refuses research mode, missing symbol, past
     deadline, malformed deadline.
  4. Idempotency — second call replaces, doesn't double-register.

Does NOT actually fire the close — APScheduler is started but the
deadline is far enough in the future that the job stays pending
during the test. The job is unscheduled before exit.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from agents.executioner import Executioner
from models.trade_plan import (
    EntryOrder,
    Setup,
    StopLoss,
    StopLossInitial,
    TakeProfitLeg,
    ThesisInvalidation,
    TimeStop,
    TradePlan,
    TrailingStop,
)
from services.scheduler import get_scheduler, stop_scheduler
from services.settings_service import get_settings


def _make_plan(
    *,
    mode: str = "paper",
    direction: str = "long",
    deadline: str | None = None,
    active: bool = True,
    symbol: str = "AAPL",
) -> TradePlan:
    if deadline is None:
        deadline = (
            datetime.now(timezone.utc) + timedelta(hours=1)
        ).isoformat()
    return TradePlan(
        mode=mode,  # type: ignore[arg-type]
        instrument={"symbol": symbol, "asset_class": "equity",
                    "exchange": "NASDAQ", "sector": None, "industry": None},
        thesis={"summary": "smoke", "lenses_contributing": ["technical"],
                "signal_ids": [], "conviction": 0.8,
                "expected_holding_period": "intraday",
                "similar_past_setups": [],
                "memory_win_rate": None, "memory_avg_r": None},
        setup=Setup(
            direction=direction,  # type: ignore[arg-type]
            entry=EntryOrder(type="limit", price=100.0, valid_until="day"),
            take_profit=[
                TakeProfitLeg(leg=1, price=101.0, size_pct=50, reason="tp1"),
                TakeProfitLeg(leg=2, price=102.0, size_pct=50, reason="tp2"),
            ],
            stop_loss=StopLoss(
                initial=StopLossInitial(type="hard", price=99.0, reason="cat"),
                trail=TrailingStop(active=False, activate_after="",
                                    mode="percent", percent=1.0),
                time_stop=TimeStop(active=active, condition="EOD",
                                    deadline=deadline),
                thesis_invalidation=ThesisInvalidation(active=False,
                                                       condition=""),
            ),
        ),
        risk={"r_per_share": 1.0, "position_size_shares": 10,
              "position_notional_usd": 1000.0, "position_risk_usd": 10.0,
              "position_risk_pct_of_equity": 0.1,
              "position_notional_pct_of_equity": 1.0,
              "r_multiple_to_tp1": 1.0, "r_multiple_to_tp2": 2.0},
        execution={"preferred_algo": "vwap", "broker": "alpaca",
                   "account_type": mode},
        evidence=[],
        tradingview_chart_url="",
    )


def _section(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


async def _run() -> None:
    settings = get_settings()
    exe = Executioner(settings)
    sched = get_scheduler()
    if not sched.running:
        sched.start()

    # ── 1. Happy path ───────────────────────────────────────────
    _section("1. happy path — schedules a job")
    deadline = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
    plan = _make_plan(deadline=deadline)
    ok = exe.close_at_time(plan, deadline, qty=10)
    assert ok, "close_at_time returned False on happy path"
    job = sched.get_job(f"close_{plan.plan_id}")
    assert job is not None, "scheduler has no job for the plan"
    print(f"  job id      : {job.id}")
    print(f"  next run    : {job.next_run_time}")
    print(f"  args        : {job.args}")
    sched.remove_job(job.id)

    # ── 2. Research mode refused ────────────────────────────────
    _section("2. research mode -> refused")
    plan = _make_plan(mode="research")
    ok = exe.close_at_time(plan, deadline, qty=10)
    assert not ok, "research mode should refuse"
    print("  refused as expected")

    # ── 3. Past deadline refused ────────────────────────────────
    _section("3. past deadline -> refused")
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    plan = _make_plan(deadline=past)
    ok = exe.close_at_time(plan, past, qty=10)
    assert not ok, "past deadline should refuse"
    print("  refused as expected")

    # ── 4. Malformed deadline refused ───────────────────────────
    _section("4. malformed deadline -> refused")
    plan = _make_plan()
    ok = exe.close_at_time(plan, "not-a-date", qty=10)
    assert not ok, "malformed deadline should refuse"
    print("  refused as expected")

    # ── 5. Missing symbol refused ───────────────────────────────
    _section("5. missing symbol -> refused")
    plan = _make_plan(symbol="")
    ok = exe.close_at_time(plan, deadline, qty=10)
    assert not ok, "missing symbol should refuse"
    print("  refused as expected")

    # ── 6. Idempotency (second call replaces) ───────────────────
    _section("6. idempotency — second call replaces, doesn't dup")
    deadline_a = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
    deadline_b = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    plan = _make_plan(deadline=deadline_a)
    exe.close_at_time(plan, deadline_a, qty=10)
    exe.close_at_time(plan, deadline_b, qty=20)
    matching = [
        j for j in sched.get_jobs() if j.id == f"close_{plan.plan_id}"
    ]
    assert len(matching) == 1, f"expected exactly 1 job, got {len(matching)}"
    job = matching[0]
    assert job.args[3] == 20, f"qty not updated: {job.args}"
    print(f"  job count   : 1 (qty updated to {job.args[3]})")
    sched.remove_job(job.id)

    # ── 7. portfolio_manager intraday deadline = today 15:00 ET ─
    _section("7. portfolio_manager intraday deadline = today 15:00 ET")
    from agents.portfolio_manager import PortfolioManager
    from models.account import AccountState
    from models.signal import Evidence, KeyLevels, Signal

    pm = PortfolioManager(
        settings,
        strategy_config={
            "holding_period": "intraday",
            "min_signal_strength": 0.5,
            "portfolio_rules": {
                "single_signal_override": 0.55,
                "min_lenses_agreeing": 1,
                "min_patterns_agreeing": 1,
                "trail_mode": "percent",
                "trail_percent": 1.0,
                "trail_activate_after": "price >= entry + 1.0R",
                "time_stop_close_et_hour": 15,
                "time_stop_close_et_minute": 0,
                "time_stop_condition": "exit at 15:00 ET bar close",
            },
        },
    )
    sig = Signal(
        signal_id="s1", symbol="AAPL", lens="technical", direction="long",
        strength=0.85, timeframe="intraday",
        key_levels=KeyLevels(support=97.0, resistance=102.0,
                              invalidation=97.0),
        pattern_name="double_lock_filtered",
        invalidation_condition="cat_stop",
        entry_price=100.0, stop_price=97.0, tp1_price=101.0, tp2_price=102.0,
        evidence=[Evidence(type="bar", ref="aapl-30m")],
    )
    account = AccountState(
        account_id="X", broker="alpaca", type="margin",
        equity=100_000.0, cash=100_000.0, buying_power=200_000.0,
        ts_snapshot=datetime.now(timezone.utc).isoformat(),
    )
    plan = await pm.process_signals(
        symbol="AAPL", signals=[sig], account=account, mode="paper",
    )
    assert plan is not None, "portfolio_manager returned None"
    deadline_iso = plan.setup.stop_loss.time_stop.deadline
    deadline_dt = datetime.fromisoformat(deadline_iso.replace("Z", "+00:00"))
    deadline_et = deadline_dt.astimezone(ZoneInfo("America/New_York"))
    print(f"  deadline UTC: {deadline_iso}")
    print(f"  deadline ET : {deadline_et.isoformat()}")
    print(f"  holding_period: {plan.thesis['expected_holding_period']}")
    assert deadline_et.hour == 15 and deadline_et.minute == 0, \
        f"expected 15:00 ET, got {deadline_et.hour:02d}:{deadline_et.minute:02d}"
    assert plan.thesis["expected_holding_period"] == "intraday"
    print("  OK deadline anchored to 15:00 ET, holding_period propagated")

    stop_scheduler()
    print("\n[smoke_close_at_time] ALL CHECKS PASSED")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
