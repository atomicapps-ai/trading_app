"""Diagnose which Finviz filter is excluding NVDA, MSFT, META, TSLA."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")                            # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services import universe_service


# Full Stage 1 filter set
ALL_FILTERS = {
    "sh_price": "o15",
    "sh_avgvol": "o2000",
    "cap": "midover",
    "geo": "usa",
    "fa_pe": "profitable",
    "fa_opermargin": "pos",
    "ta_sma50_pa": "pa",
    "ta_sma200_pa": "pa",
}

TARGETS = ["NVDA", "MSFT", "META", "TSLA"]


async def main() -> int:
    # First: run with all filters, see which targets are missing
    print(f"=== Full filter set: {ALL_FILTERS}")
    full_tickers, truncated = await asyncio.to_thread(
        lambda: universe_service.scrape_finviz_filters(ALL_FILTERS, max_pages=50),
    )
    full_set = set(full_tickers)
    print(f"  total: {len(full_tickers)} (truncated={truncated})")
    for t in TARGETS:
        print(f"  {t}: {'IN' if t in full_set else 'MISSING'}")

    # Then drop filters one at a time to find the culprit
    print(f"\n=== Dropping each filter one-by-one to find culprits")
    for filter_id in list(ALL_FILTERS.keys()):
        sub = {k: v for k, v in ALL_FILTERS.items() if k != filter_id}
        tickers, _ = await asyncio.to_thread(
            lambda: universe_service.scrape_finviz_filters(sub, max_pages=50),
        )
        ts = set(tickers)
        recovered = [t for t in TARGETS if t in ts and t not in full_set]
        still_missing = [t for t in TARGETS if t not in ts]
        print(f"  drop '{filter_id}'  → {len(tickers)} tickers  "
              f"recovered: {recovered}  still missing: {still_missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
