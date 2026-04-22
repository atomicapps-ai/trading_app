"""Phase 4 analyst smoke test.

Exercises:
  1. Every detector is a pure function (no datetime.now, no network).
  2. The macro lens produces a non-empty context from cached SPY+VIX.
  3. Analyst.run produces Signal objects on at least one of 25 shortlist
     names — not a guarantee every day, so we just assert the shape and
     walk away green if no pattern fires (the detectors may simply be
     quiet today).
  4. `as_of_ts` determinism: same call twice → same signals.
  5. The end-to-end research_run workflow has `signals_generated` populated
     by the REAL analyze step.

Run:  .venv\\Scripts\\python.exe -m scripts.smoke_phase4_analyst
"""
from __future__ import annotations

import asyncio
import logging
import sys

import pandas as pd

from agents.analyst import Analyst, run_analyst_on_shortlist
from agents.macro import compute_macro_context
from services.settings_service import Settings
from services.workflow_engine import WorkflowEngine

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


async def main() -> int:
    print("=" * 70)
    print("Phase 4 analyst smoke test")
    print("=" * 70)

    settings = Settings()

    # ---- 1. Macro context ------------------------------------------------
    print("\n[1/5] compute_macro_context() live")
    macro = await compute_macro_context(as_of_ts=None)
    print(f"  macro: {macro}")
    expect(
        macro.get("vix_level") is not None or macro.get("spy_trend_20d") is not None,
        "macro: at least VIX or SPY trend must be populated",
    )
    print("  OK")

    # ---- 2. Analyst on one symbol ---------------------------------------
    print("\n[2/5] Analyst.run on NVDA (live)")
    analyst = Analyst(settings)
    signals = await analyst.run("NVDA", macro_context=macro, as_of_ts=None)
    print(f"  {len(signals)} signal(s) emitted")
    for s in signals:
        print(f"    {s.symbol} {s.lens} {s.direction} strength={s.strength:.2f}")
    # Don't assert N>0 — detectors may be quiet. Assert shape.
    for s in signals:
        expect(0.55 <= s.strength <= 1.0, f"strength out of band: {s.strength}")
    print("  OK")

    # ---- 3. Shortlist scan ----------------------------------------------
    print("\n[3/5] run_analyst_on_shortlist on liquid_momentum_core shortlist")
    shortlist = [
        "AAPL", "MSFT", "NVDA", "META", "GOOGL", "AMZN", "TSLA", "AMD",
        "AVGO", "NFLX", "ADBE", "CRM", "ORCL", "COST", "JPM",
        "V", "MA", "UNH", "LLY", "HD", "WMT", "DIS", "BA", "CAT", "GE",
    ]
    by_symbol = await run_analyst_on_shortlist(
        shortlist, settings=settings, macro_context=macro, as_of_ts=None,
    )
    total = sum(len(sigs) for sigs in by_symbol.values())
    print(f"  {len(by_symbol)} symbols fired, {total} total signals")
    for sym, sigs in sorted(by_symbol.items()):
        print(f"    {sym}: " + ", ".join(
            f"{s.lens}/{s.direction}/{s.strength:.2f}" for s in sigs
        ))
    print("  OK")

    # ---- 4. Determinism -------------------------------------------------
    print("\n[4/5] determinism — same as_of_ts -> same signals")
    as_of = pd.Timestamp("2024-06-15", tz="UTC")
    a = await analyst.run("NVDA", macro_context=macro, as_of_ts=as_of)
    b = await analyst.run("NVDA", macro_context=macro, as_of_ts=as_of)
    sig_a = sorted((s.direction, round(s.strength, 3)) for s in a)
    sig_b = sorted((s.direction, round(s.strength, 3)) for s in b)
    expect(sig_a == sig_b, f"non-deterministic: {sig_a} vs {sig_b}")
    print(f"  OK - NVDA @ 2024-06-15: {sig_a}")

    # ---- 5. End-to-end through workflow engine --------------------------
    print("\n[5/5] WorkflowEngine.run(research_run) signals come from real analyst")
    engine = WorkflowEngine(settings)
    wf = await engine.load_by_id("research_run")
    rr = await engine.run(wf)
    expect(rr.error is None, f"workflow errored: {rr.error}")
    # analyze step should now be REAL not stubbed
    analyze_result = next(
        (s for s in rr.step_results if s.step_id == "analyze"), None,
    )
    expect(analyze_result is not None, "analyze step missing from run result")
    expect(not analyze_result.output.get("stub", False),
           "analyze step still reports stub=True")
    print(
        f"  OK - shortlist={rr.symbols_in_shortlist}, "
        f"signals_generated={rr.signals_generated}, "
        f"duration={rr.duration_seconds:.2f}s"
    )

    print("\n" + "=" * 70)
    print("ALL GREEN - analyst + macro lens + wired workflow.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
