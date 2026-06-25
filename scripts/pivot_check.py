"""pivot_check — see the support/resistance context for symbols (no Kronos needed).

Deterministic floor-trader pivots (weekly + monthly) + recent swing highs/lows, with
the nearest support/resistance to current price. Lets you eyeball the levels that the
Kronos candidates now carry as displayed context.

USAGE:
  python scripts/pivot_check.py --symbols AAPL NVDA SPY XOM
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger("pivot_check")


def main() -> None:
    ap = argparse.ArgumentParser(description="Show pivot S/R context for symbols")
    ap.add_argument("--symbols", nargs="+", default=["AAPL", "NVDA", "SPY", "XOM"])
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from scripts.kronos_poc import fetch_daily_bars
    from services import pivot_service

    for sym in args.symbols:
        try:
            bars = fetch_daily_bars(sym)
            pv = pivot_service.pivot_context(bars)
            res = pv["nearest_resistance"]
            sup = pv["nearest_support"]
            logger.info("\n=== %s  (price %.2f) ===", sym, pv["price"])
            if res:
                logger.info("  nearest resistance: %.2f (%+.2f%%)", res["level"], res["dist_pct"])
            if sup:
                logger.info("  nearest support:    %.2f (%+.2f%%)", sup["level"], sup["dist_pct"])
            if pv["weekly"]:
                w = pv["weekly"]
                logger.info("  weekly pivots: P %.2f  R1 %.2f  S1 %.2f", w["P"], w["R1"], w["S1"])
            if pv["monthly"]:
                m = pv["monthly"]
                logger.info("  monthly pivots: P %.2f  R1 %.2f  S1 %.2f", m["P"], m["R1"], m["S1"])
            logger.info("  recent swing highs: %s", pv["swing_highs"])
            logger.info("  recent swing lows:  %s", pv["swing_lows"])
        except Exception as exc:  # noqa: BLE001
            logger.error("%s failed: %s", sym, exc)


if __name__ == "__main__":
    main()
