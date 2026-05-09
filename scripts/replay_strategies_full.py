"""scripts/replay_strategies_full.py — DL/ORB/VWAP-Reclaim over the 4-year window.

Same multi-strategy replay as `replay_strategies.py` but with the SINCE
hard-coded to the start of the new Alpaca 30m cache (2022-01-03), to
exploit the deeper history we just back-filled. This is the right script
to run for "does the algorithm hold up out-of-sample?" analysis.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path

# Force UTF-8 stdout (Windows cp1252 chokes on the arrow / R-multiple chars).
try:
    sys.stdout.reconfigure(encoding="utf-8")                            # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv                                          # noqa: E402
load_dotenv(ROOT / ".env")

from scripts.replay_strategies import (                                 # noqa: E402
    _detect_orb,
    _detect_vwap_reclaim,
    _print_summaries,
    _summarize,
    replay_one_strategy,
)
from scripts.replay_dl import _load_cat_stop_pct, replay as dl_replay   # noqa: E402

BELLWETHER_16 = ["AAPL", "AMD", "AMZN", "BA", "COST", "GS", "HD", "INTC",
                 "IWM", "META", "MSFT", "NVDA", "ORCL", "SPY", "TSLA", "XLF"]

# Start of the new Alpaca 30m cache (smoke test verified all 16 have data
# back to at least 2022-01-03).
SINCE = date(2022, 1, 3)
UNTIL = date(2026, 5, 8)
CAPITAL = 10_000.0


async def main() -> int:
    cat_stop = _load_cat_stop_pct("double_lock")
    print(f"Window: {SINCE} -> {UNTIL}  ({len(BELLWETHER_16)} symbols)")
    print(f"Capital: ${CAPITAL:,.0f}/trade  Stop: {cat_stop}% catastrophic")
    print()

    print("[1/3] running Double-Lock ...")
    dl_trades = await dl_replay(
        BELLWETHER_16, since=SINCE, until=UNTIL, strategy="double_lock",
    )

    print(f"[2/3] running ORB-30m ... (will take longer — every day evaluated)")
    orb_result = await replay_one_strategy(
        "ORB-30m",
        lambda today_bars, sym, daily_ind, vix_prev, as_of:
            _detect_orb(today_bars, cat_stop_pct=cat_stop),
        symbols=BELLWETHER_16, since=SINCE, until=UNTIL, cat_stop_pct=cat_stop,
    )

    print("[3/3] running VWAP-Reclaim-1030 ...")
    vwap_result = await replay_one_strategy(
        "VWAP-Reclaim-1030",
        lambda today_bars, sym, daily_ind, vix_prev, as_of:
            _detect_vwap_reclaim(today_bars, cat_stop_pct=cat_stop),
        symbols=BELLWETHER_16, since=SINCE, until=UNTIL, cat_stop_pct=cat_stop,
    )

    summaries = [
        _summarize("Double-Lock (DL)",     dl_trades,         CAPITAL),
        _summarize("ORB-30m",              orb_result.trades, CAPITAL),
        _summarize("VWAP-Reclaim-1030",    vwap_result.trades, CAPITAL),
    ]
    _print_summaries(summaries, CAPITAL)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
