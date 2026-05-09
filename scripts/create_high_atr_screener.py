"""scripts/create_high_atr_screener.py — create + populate a new screener.

Creates the `high_atr_liquid` screener with:
  - sh_price: Over $10
  - sh_avgvol: Over 2M
  - ta_averagetruerange: Over $3 USD

Then runs Finviz via the existing universe_service to populate ticker list.
"""
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

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from services import universe_service


SCREENER_NAME = "high_atr_liquid"
SCREENER_TITLE = "High-ATR Liquid (>$10, >2M vol, ATR>$3)"
SCREENER_DESC = (
    "US stocks priced over $10 with average daily volume over 2M shares "
    "and Average True Range above $3 USD. Wide enough to find swing-trade "
    "candidates but liquid enough that fills are clean. Used as the "
    "expanded universe for random_search.py."
)
SCREENER_NOTES = (
    "Filters chosen to surface stocks with enough $-range per day to "
    "produce meaningful swing trades. ATR>$3 in raw USD = at least $3 of "
    "intraday movement on average — too tight a range eliminates the "
    "edge of any directional strategy. This is a much broader universe "
    "than bellwether_16."
)
FILTERS = {
    "sh_price": "o10",
    "sh_avgvol": "o2000",
    "ta_averagetruerange": "o3",
}


async def main() -> int:
    # 1. Upsert the screener config
    existing = await universe_service.get_preset_db(SCREENER_NAME)
    if existing:
        print(f"updating existing screener: {SCREENER_NAME}")
        await universe_service.update_preset_db(
            SCREENER_NAME,
            title=SCREENER_TITLE,
            description=SCREENER_DESC,
            notes=SCREENER_NOTES,
            filters=FILTERS,
            output_tags=["high_atr", "liquid", "swing_universe"],
        )
    else:
        print(f"creating new screener: {SCREENER_NAME}")
        await universe_service.create_preset_db(
            name=SCREENER_NAME,
            title=SCREENER_TITLE,
            description=SCREENER_DESC,
            notes=SCREENER_NOTES,
            filters=FILTERS,
            output_tags=["high_atr", "liquid", "swing_universe"],
        )

    # 2. Scrape Finviz for matching tickers (sync function — wrap in to_thread)
    print(f"scraping Finviz with filters: {FILTERS}")
    tickers, truncated = await asyncio.to_thread(
        lambda: universe_service.scrape_finviz_filters(FILTERS, max_pages=15),
    )
    print(f"  found: {len(tickers)} tickers (truncated={truncated})")
    if truncated:
        print(f"  WARNING: hit max_pages cap — there are MORE matches than 300. "
              f"Tighten the filter (e.g. raise volume threshold) for full coverage.")

    # 3. Save ticker list to the screener
    await universe_service.save_preset_tickers_db(
        SCREENER_NAME, tickers, source="finviz_scrape",
    )
    print(f"  saved {len(tickers)} tickers to screener {SCREENER_NAME!r}")

    # 4. Print first 30 for sanity
    print(f"\nFirst 30 tickers:")
    print("  " + ", ".join(tickers[:30]))
    print(f"\nLast 10 tickers:")
    print("  " + ", ".join(tickers[-10:]))
    print(f"\nTotal: {len(tickers)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
