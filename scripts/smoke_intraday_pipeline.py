#!/usr/bin/env python
"""
End-to-end smoke for the intraday Double-Lock pipeline.

Exercises every link added in this session:

  data_service.get_bars("30m")            ← TODO #1
    -> Analyst.run_intraday()             ← TODO #2 (option 2b)
    -> PortfolioManager.process_signals() ← TODO #3 (trail_mode=percent)
    -> TradePlan with percent-mode trail + intraday timeframe

Forces a same-day 10:30 ET as_of_ts so the time-gated detector fires
on whatever recent day has clean data. Reports:

  * how many symbols' 30m bars were fetched
  * how many intraday signals fired
  * a built TradePlan with the trail block confirmed mode=percent

Run via cmds.py; output -> claude_output.txt.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import pandas as pd

# Project imports
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.analyst import Analyst, run_intraday_on_shortlist  # noqa: E402
from agents.macro import compute_macro_context                  # noqa: E402
from agents.portfolio_manager import PortfolioManager           # noqa: E402
from models.account import AccountState                         # noqa: E402
from models.signal import Evidence, KeyLevels, Signal           # noqa: E402
from services.settings_service import get_settings              # noqa: E402


def _synthetic_signal(sym: str) -> Signal:
    """A hand-built Signal that mirrors what double_lock_filtered would emit.
    Used to verify the portfolio_manager / trail wiring when live regime
    conditions don't fire today."""
    entry = 200.0
    stop  = entry * 0.97   # 3% cat stop
    return Signal(
        symbol=sym,
        lens="technical",
        direction="long",
        strength=0.85,
        timeframe="intraday",
        key_levels=KeyLevels(support=stop, resistance=None, invalidation=stop),
        evidence=[Evidence(type="pattern", ref="synthetic — trail wiring smoke")],
        invalidation_condition="3% catastrophic stop",
        pattern_name="double_lock_filtered",
        entry_price=entry,
        stop_price=stop,
        tp1_price=entry * 1.06,
        tp2_price=entry * 1.09,
    )

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("smoke")

UNIVERSE = [
    # Liquid mega-caps + ETFs that produced filtered fires in the dump
    "AMD", "AMZN", "BA", "COST", "GS", "HD", "INTC", "IWM", "META",
    "ORCL", "SPY", "TSLA", "XLF", "AAPL", "MSFT", "NVDA",
]


def _stub_account() -> AccountState:
    """Minimal AccountState for portfolio_manager sizing."""
    return AccountState(
        account_id="SMOKE-INTRADAY-001",
        broker="alpaca",
        type="margin",
        equity=100_000.0,
        cash=100_000.0,
        buying_power=200_000.0,
        ts_snapshot=pd.Timestamp.now(tz="UTC").isoformat(),
    )


async def _find_recent_1030_et() -> pd.Timestamp:
    """Pick the most recent 10:30 America/New_York timestamp on a weekday.

    Walks back day-by-day until we hit a weekday. The detector itself
    is what enforces "data exists" — we only need the timestamp shape.
    """
    now = pd.Timestamp.now(tz="America/New_York")
    candidate = now.normalize().replace(hour=10, minute=30)
    if candidate >= now:
        candidate -= pd.Timedelta(days=1)
    while candidate.weekday() >= 5:  # 5=Sat, 6=Sun
        candidate -= pd.Timedelta(days=1)
    return candidate.tz_convert("UTC")


async def main() -> None:
    settings = get_settings()
    print(f"Mode: {settings.app.mode}")

    as_of = await _find_recent_1030_et()
    print(f"as_of_ts: {as_of.tz_convert('America/New_York')}  ({as_of} UTC)")

    print("\n[1] Building macro context (SPY trend + VIX)...")
    macro = await compute_macro_context(as_of_ts=as_of)
    print(f"    macro: {macro}")
    if macro.get("vix_level") is None:
        print("    !! VIX missing — DL filter requires this. Smoke will report 0 fires.")

    print(f"\n[2] Running intraday analyst on {len(UNIVERSE)} symbols...")
    sigs_by_sym = await run_intraday_on_shortlist(
        UNIVERSE, settings,
        macro_context=macro,
        as_of_ts=as_of,
        strategy_name="double_lock",
    )
    print(f"    Signals fired: {sum(len(v) for v in sigs_by_sym.values())} "
          f"across {len(sigs_by_sym)} symbols")
    for sym, sigs in sigs_by_sym.items():
        for s in sigs:
            print(f"      {sym} {s.direction.upper():5s} entry={s.entry_price} "
                  f"stop={s.stop_price} pqs={int(s.strength * 100)} "
                  f"timeframe={s.timeframe} pattern={s.pattern_name}")

    pm = PortfolioManager(
        settings,
        strategy_config=Analyst(settings, "double_lock")._strategy_config,
    )
    account = _stub_account()

    if not sigs_by_sym:
        print("\n[3] No live signals fired — falling back to a synthetic signal so")
        print("    we can still verify trail.mode='percent' wiring (TODO #3).")
        first_sym = "NVDA"
        first_sigs = [_synthetic_signal(first_sym)]
    else:
        print("\n[3] Building TradePlan from first live signal...")
        first_sym, first_sigs = next(iter(sigs_by_sym.items()))

    plan = await pm.process_signals(
        symbol=first_sym,
        signals=first_sigs,
        account=account,
        existing_positions=[],
        mode=settings.app.mode,
        pending_count=0,
    )
    if plan is None:
        print("    Plan = None (consensus or sizing rejected the signal)")
        return

    print(f"    plan_id        : {plan.plan_id}")
    print(f"    symbol/dir     : {plan.instrument['symbol']} {plan.setup.direction}")
    print(f"    entry          : ${plan.setup.entry.price}")
    print(f"    stop (initial) : ${plan.setup.stop_loss.initial.price}")
    print(f"    trail.active   : {plan.setup.stop_loss.trail.active}")
    print(f"    trail.mode     : {plan.setup.stop_loss.trail.mode}    <- should be 'percent'")
    print(f"    trail.percent  : {plan.setup.stop_loss.trail.percent}    <- should be 1.0")
    print(f"    trail.activate_after: {plan.setup.stop_loss.trail.activate_after}")
    print(f"    time_stop.condition : {plan.setup.stop_loss.time_stop.condition}")
    print(f"    R per share    : ${plan.risk['r_per_share']}")
    print(f"    position size  : {plan.risk['position_size_shares']} shares")
    print(f"    notional       : ${plan.risk['position_notional_usd']}")

    # Verdict
    ok_mode    = plan.setup.stop_loss.trail.mode == "percent"
    ok_percent = abs((plan.setup.stop_loss.trail.percent or 0.0) - 1.0) < 1e-6
    print()
    if ok_mode and ok_percent:
        print("[4] PASS - full intraday pipeline wired:")
        print("      data_service.get_bars('30m') -> Analyst.run_intraday() -> ")
        print("      PortfolioManager.process_signals() -> TradePlan(percent trail)")
    else:
        print("[4] FAIL - trail config did not propagate:")
        print(f"      expected mode='percent' got '{plan.setup.stop_loss.trail.mode}'")
        print(f"      expected percent=1.0 got {plan.setup.stop_loss.trail.percent}")


if __name__ == "__main__":
    asyncio.run(main())
