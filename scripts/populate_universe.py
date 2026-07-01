"""populate_universe — fill a screener's ticker list from an index (NO Finviz).

The Finviz scrape in the /universe editor is environment-dependent and frequently
blocked (that's why "Run" can get stuck on a stale count). This populates a
screener's universe directly from Wikipedia index constituents — the same source
the app's Stock Lists already use — which is reliable and gives a broad, liquid,
established-company universe ("high volume + doing well" by index membership).

Usage (run on your machine, with the app's venv):
    python scripts/populate_universe.py                       # S&P 500  -> core_universe_100
    python scripts/populate_universe.py --index sp500+sp400   # S&P 500 + 400 mid-cap (~900)
    python scripts/populate_universe.py --preset liquid_momentum_core
"""
from __future__ import annotations
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.stock_lists_service import _fetch_wiki_tickers   # noqa: E402
from services import universe_service                          # noqa: E402

# Wikipedia constituents pages (url, table_index, symbol-column-prefix).
SOURCES = {
    "sp500": ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", 0, "Symbol"),
    "sp400": ("https://en.wikipedia.org/wiki/List_of_S%26P_400_companies", 0, "Symbol"),
}


def _fetch(idx: str) -> list[str]:
    url, ti, col = SOURCES[idx]
    raw = _fetch_wiki_tickers(url, ti, col)
    # Normalize to the format our data layer / yfinance use (BRK.B -> BRK-B).
    return [t.replace(".", "-") for t in raw]


async def main() -> None:
    ap = argparse.ArgumentParser(description="Populate a screener universe from an index (no Finviz).")
    ap.add_argument("--index", default="sp500",
                    help="'+'-joined: sp500 | sp400 | sp500+sp400  (default sp500)")
    ap.add_argument("--preset", default="core_universe_100",
                    help="screener name to save into (default core_universe_100)")
    args = ap.parse_args()

    parts = [p.strip() for p in args.index.split("+") if p.strip()]
    unknown = [p for p in parts if p not in SOURCES]
    if unknown:
        print(f"unknown index(es): {unknown}; choices: {list(SOURCES)}")
        return

    tickers: list[str] = []
    seen: set[str] = set()
    for idx in parts:
        got = _fetch(idx)
        print(f"  {idx}: fetched {len(got)} tickers")
        for t in got:
            if t not in seen:
                seen.add(t)
                tickers.append(t)

    print(f"total unique: {len(tickers)} (sample: {tickers[:12]})")
    ok = await universe_service.save_preset_tickers_db(
        args.preset, tickers, source=f"index:{args.index}",
    )
    print(f"saved to screener {args.preset!r}: {'OK' if ok else 'FAILED'} "
          f"({len(tickers)} tickers)")
    if ok:
        print("Done. The strategies will scan this list on their next run "
              "(no app restart needed).")


if __name__ == "__main__":
    asyncio.run(main())
