"""build_strategy_universe.py — derive each strategy's universe ("local galaxy")
from its own 10-year backtest.

Model (see CLAUDE.md / HANDOFF):
  master  = a broad pool of tradeable symbols (here: everything cached with
            enough history to compute indicators).
  Subset A = symbols that fired the strategy AT LEAST ONCE over the backtest
             window — proven CAPABLE of producing the setup.
  Subset B = eligible-but-unproven symbols (in master, not in A) — the pool that
             can still produce a first-time (newcomer) signal. Only true
             never-matchers / illiquid / wrong-asset symbols are excluded.
  universe = A ∪ B, saved as a screener and linked to the strategy.

This is a ONE-TIME step per strategy (re-run on strategy change or when enough
new candles accumulate) — NOT a daily job.

Usage:
    python scripts/build_strategy_universe.py [--since 2015-01-01] [--min-signals 1]
                                              [--save] [--strategies a,b,c]
"""
import argparse
import asyncio
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from scripts.replay_swing import replay as replay_daily

HIST = Path("data/historical")
DAILY_STRATEGIES = ["momentum_breakout", "fear_dip_reversion", "macd_run", "coil_breakout"]
MIN_BARS = 210


def eligible_master() -> list[str]:
    """Broad pool: every symbol with a daily CSV of >= MIN_BARS bars.
    (On a real run this is the 2000+ master; here it's whatever's cached.)"""
    out = []
    for p in sorted(HIST.glob("*_1d.csv")):
        sym = p.name.replace("_1d.csv", "")
        try:
            n = sum(1 for _ in open(p)) - 1
        except OSError:
            continue
        if n >= MIN_BARS:
            out.append(sym)
    return out


async def subset_a(strategy: str, master: list[str], since: str, until: str,
                   min_signals: int) -> dict[str, int]:
    """{symbol: signal_count} for symbols that fired >= min_signals in the window."""
    trades = await replay_daily(master, since, until, strategy=strategy)
    counts: dict[str, int] = {}
    for t in trades:
        counts[t.symbol] = counts.get(t.symbol, 0) + 1
    return {s: c for s, c in counts.items() if c >= min_signals}


async def build_one(strategy: str, master: list[str], since: str, until: str,
                    min_signals: int, save: bool) -> dict:
    a_counts = await subset_a(strategy, master, since, until, min_signals)
    a = set(a_counts)
    b = [s for s in master if s not in a]          # eligible newcomers
    universe = sorted(a) + sorted(b)               # A ∪ B (A first)
    top = sorted(a_counts.items(), key=lambda kv: -kv[1])[:12]
    result = {
        "strategy": strategy, "master": len(master),
        "A": len(a), "B": len(b), "universe": len(universe),
        "top_A": top,
    }
    if save:
        from services import db_service
        name = f"{strategy}_universe"
        try:
            await db_service.create_universe_preset(
                name=name, title=f"{strategy} universe (A∪B)",
                description=(f"Auto-built from {strategy}'s 10y backtest. "
                            f"A={len(a)} proven (fired ≥{min_signals}), "
                            f"B={len(b)} eligible newcomers."),
            )
        except Exception:
            pass  # already exists → just refresh tickers
        await db_service.save_universe_preset_tickers(name, universe, source="backtest_universe")
        result["saved_as"] = name
    return result


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=(date.today() - timedelta(days=3650)).isoformat())
    ap.add_argument("--until", default=date.today().isoformat())
    ap.add_argument("--min-signals", type=int, default=1)
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--strategies", default=",".join(DAILY_STRATEGIES))
    args = ap.parse_args()

    from services import db_service
    await db_service.ensure_tables()

    master = eligible_master()
    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    print(f"Master pool: {len(master)} symbols (≥{MIN_BARS} daily bars) | "
          f"window {args.since} → {args.until} | min_signals={args.min_signals}\n")

    rows = []
    for strat in strategies:
        r = await build_one(strat, master, args.since, args.until,
                            args.min_signals, args.save)
        rows.append(r)
        saved = f" → saved '{r.get('saved_as')}'" if args.save else ""
        print(f"### {strat}: A(proven)={r['A']}  B(eligible)={r['B']}  "
              f"universe={r['universe']}{saved}")
        if r["top_A"]:
            print("    top A by fire-count: " +
                  ", ".join(f"{s}×{c}" for s, c in r["top_A"]))
        print()

    # Show differentiation: how much do the proven sets overlap?
    print("=== per-strategy proven-set differentiation (Subset A) ===")
    print(f"  {'strategy':<22}{'A size':>7}")
    for r in rows:
        print(f"  {r['strategy']:<22}{r['A']:>7}")


if __name__ == "__main__":
    asyncio.run(main())
