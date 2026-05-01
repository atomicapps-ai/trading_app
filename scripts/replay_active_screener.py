"""scripts/replay_active_screener.py — replay against the active screener.

Pulls the saved tickers from whichever screener is currently active in
the DB, runs the replay engine over a date window, prints summary +
top trades.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

    from services import db_service
    from scripts.replay_dl import replay

    # Pull the active screener's tickers
    presets = await db_service.list_universe_presets()
    active = next((p for p in presets if p.get("is_active")), None)
    if active is None:
        print("No active screener.")
        return
    tickers = active.get("tickers") or []
    if not tickers:
        print(f"Active screener {active['name']!r} has 0 tickers — populate it first.")
        return

    print(f"Active screener: {active['name']}  ({len(tickers)} tickers)")
    print()

    # Run replay over the known-active period
    since = date(2026, 3, 1)
    until = date(2026, 4, 30)
    strategy = "double_lock"
    print(f"Strategy: {strategy}")
    print(f"Window:   {since} -> {until}")
    print(f"This will take 30s-2min depending on cache state.")
    print()

    trades = await replay(tickers, since=since, until=until, strategy=strategy)

    if not trades:
        print(">>> 0 trades fired in this window. <<<")
        return

    wins = sum(1 for t in trades if t.win)
    losses = len(trades) - wins
    wr = wins / len(trades) * 100
    total = sum(t.pnl_pct for t in trades)
    longs = sum(1 for t in trades if t.direction.lower() == "long")
    shorts = len(trades) - longs

    print("=" * 60)
    print(f"SUMMARY")
    print("=" * 60)
    print(f"Trades:        {len(trades)}  ({wins} wins, {losses} losses)")
    print(f"Win rate:      {wr:.1f}%")
    print(f"Total P&L:     {total:+.2f}%")
    print(f"Avg per trade: {total/len(trades):+.2f}%")
    print(f"Best:          {max(t.pnl_pct for t in trades):+.2f}%")
    print(f"Worst:         {min(t.pnl_pct for t in trades):+.2f}%")
    print(f"Longs/Shorts:  {longs} / {shorts}")
    print()
    print("=" * 60)
    print(f"TRADES (sorted by date)")
    print("=" * 60)
    print(f"{'Date':12s} {'Symbol':6s} {'Dir':5s} {'Entry':>8s} {'Stop':>8s} {'Exit':>8s} "
          f"{'Reason':6s} {'P&L%':>7s}  W/L")
    for t in sorted(trades, key=lambda x: x.date_str):
        wl = 'W' if t.win else 'L'
        print(f"{t.date_str:12s} {t.symbol:6s} {t.direction:5s} "
              f"{t.entry:>8.2f} {t.stop:>8.2f} {t.exit_px:>8.2f} "
              f"{t.exit_reason:6s} {t.pnl_pct:>+7.2f}  {wl}")


if __name__ == "__main__":
    asyncio.run(main())
