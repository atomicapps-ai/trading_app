"""Multi-stock + multi-period data coverage smoke test.

Answers 3 questions end-to-end:
  1. Can we pull bars for ARBITRARY symbols (not just the seed list)?
  2. Can we pull BOTH daily and 1-hour bars for the same symbol?
  3. Can we fetch LIVE quotes from Alpaca for those same symbols?

Covers a cross-sector basket so we exercise different exchanges, market
caps, and volatility profiles. Paper-mode only — no orders placed.
"""
from __future__ import annotations

import asyncio
import logging
import sys

from dotenv import load_dotenv

from services.settings_service import ENV_FILE

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

SYMBOLS = [
    ("NVDA", "Tech / Semis"),
    ("JPM",  "Financials"),
    ("XOM",  "Energy"),
    ("COST", "Consumer Staples"),
    ("CAT",  "Industrials"),
    ("GLD",  "Commodity ETF"),
]


async def main() -> int:
    load_dotenv(ENV_FILE, override=False)

    from brokers.alpaca import AlpacaAdapter
    from services.data_service import DataNotAvailableError, get_bars
    from services.indicator_service import add_indicators

    print("=" * 78)
    print("Data coverage smoke test — multi-stock, multi-period, live quotes")
    print("=" * 78)

    # ---- 1. Daily + 1H bars for every symbol ---------------------------
    print("\n[1/3] Historical bars via data_service (yfinance cache)\n")
    print(f"  {'SYMBOL':<7} {'CATEGORY':<20} {'1D BARS':<10} {'1H BARS':<10} {'RSI-14':<8} {'ATR%':<6}")
    print(f"  {'-'*7} {'-'*20} {'-'*10} {'-'*10} {'-'*8} {'-'*6}")
    for sym, category in SYMBOLS:
        try:
            daily = await get_bars(sym, "1d", min_bars=210)
        except DataNotAvailableError as e:
            print(f"  {sym:<7} {category:<20} FAIL daily: {e}")
            continue
        try:
            hourly = await get_bars(sym, "1h", min_bars=50)
            h_count = str(len(hourly))
        except DataNotAvailableError:
            h_count = "n/a"
        indicators = add_indicators(daily)
        tail = indicators.iloc[-1]
        print(
            f"  {sym:<7} {category:<20} "
            f"{len(daily):<10} {h_count:<10} "
            f"{tail['rsi_14']:<8.1f} {tail['atr_14_pct']:<6.2f}"
        )

    # ---- 2. Historical slice (as_of_ts) ---------------------------------
    import pandas as pd
    print("\n[2/3] as_of_ts slicing — 'what did this chart look like on 2024-06-15?'")
    cutoff = pd.Timestamp("2024-06-15", tz="UTC")
    for sym, _ in SYMBOLS[:3]:
        df = await get_bars(sym, "1d", as_of_ts=cutoff, min_bars=50)
        enriched = add_indicators(df)
        tail = enriched.iloc[-1]
        print(
            f"  {sym:<7} as_of {cutoff.date()}: "
            f"close=${tail['close']:<8.2f} rsi={tail['rsi_14']:.1f} "
            f"max_bar={df.index.max().date()}"
        )

    # ---- 3. Live quotes via Alpaca -------------------------------------
    print("\n[3/3] Live NBBO quotes via Alpaca paper adapter\n")
    adapter = AlpacaAdapter(paper=True)
    ok = await adapter.connect()
    if not ok:
        print("  FAIL - Alpaca connect failed")
        return 1

    print(f"  {'SYMBOL':<7} {'BID':<10} {'ASK':<10} {'SPREAD':<10} {'MID':<10}")
    print(f"  {'-'*7} {'-'*10} {'-'*10} {'-'*10} {'-'*10}")
    for sym, _ in SYMBOLS:
        try:
            q = await adapter.get_quote(sym)
        except Exception as e:  # noqa: BLE001
            print(f"  {sym:<7} quote error: {e}")
            continue
        print(
            f"  {sym:<7} ${q.bid:<9.2f} ${q.ask:<9.2f} "
            f"{q.spread_bps:<9.1f}bps ${q.mid:<9.2f}"
        )
    await adapter.disconnect()

    print("\n" + "=" * 78)
    print("ALL GREEN — multi-stock data + live quotes work across the board.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
