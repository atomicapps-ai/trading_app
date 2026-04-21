"""Download historical daily OHLCV for a list of symbols into data/historical/.

Uses yfinance. One CSV per symbol at `data/historical/{SYMBOL}_1d.csv`,
which HistoricalAdapter reads on demand.

Usage:
    python -m scripts.download_history SPY AAPL NVDA
    python -m scripts.download_history SPY --years 20
    python -m scripts.download_history --file watchlist.txt   (one symbol per line)
    python -m scripts.download_history --refresh-all          (re-download existing files)

Notes:
- yfinance is unofficial; the Yahoo ToS prohibits commercial use. Fine for
  personal research. If it breaks, swap to Tiingo / Polygon.
- Data is adjusted for splits but dividends are kept as a separate column
  (as yfinance returns them). That matches TradeStation's default behavior.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import yfinance as yf

# Allow `python -m scripts.download_history` from project root.
# (Absolute import works because the script is invoked as a module.)
from services.settings_service import DATA_DIR

HISTORICAL_DIR: Path = DATA_DIR / "historical"

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("download_history")


def download_symbol(symbol: str, years: int, overwrite: bool) -> tuple[str, str]:
    """Returns (symbol, status_msg). Never raises — bad tickers are logged."""
    out = HISTORICAL_DIR / f"{symbol.upper()}_1d.csv"
    if out.exists() and not overwrite:
        return symbol, f"skipped (exists — use --refresh-all to overwrite): {out.name}"
    try:
        df = yf.Ticker(symbol).history(period=f"{years}y", auto_adjust=False)
    except Exception as e:  # yfinance raises a grab-bag of types
        return symbol, f"FAILED ({type(e).__name__}: {e})"
    if df.empty:
        return symbol, "FAILED (empty dataframe — bad ticker?)"
    df.to_csv(out)
    return symbol, f"wrote {len(df)} rows → {out.name}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Download historical OHLCV via yfinance.")
    parser.add_argument("symbols", nargs="*", help="Ticker symbols (e.g. SPY AAPL NVDA)")
    parser.add_argument("--file", "-f", type=Path, help="File with one symbol per line")
    parser.add_argument("--years", "-y", type=int, default=20, help="Years of history (default 20)")
    parser.add_argument("--refresh-all", action="store_true", help="Re-download even if CSV exists")
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds between symbols (rate-limit politeness)")
    args = parser.parse_args()

    symbols: list[str] = list(args.symbols)
    if args.file:
        symbols.extend(
            s.strip().upper()
            for s in args.file.read_text(encoding="utf-8").splitlines()
            if s.strip() and not s.startswith("#")
        )
    # dedupe, preserve order
    seen: set[str] = set()
    symbols = [s.upper() for s in symbols if not (s.upper() in seen or seen.add(s.upper()))]

    if not symbols:
        parser.print_help()
        return 1

    HISTORICAL_DIR.mkdir(parents=True, exist_ok=True)
    log.info("Downloading %d symbols · %d years · → %s", len(symbols), args.years, HISTORICAL_DIR)
    log.info("-" * 72)

    ok = fail = 0
    for i, sym in enumerate(symbols, 1):
        _, msg = download_symbol(sym, args.years, args.refresh_all)
        prefix = "FAIL" if "FAILED" in msg else "OK  "
        log.info("[%3d/%d] %s %s · %s", i, len(symbols), prefix, sym, msg)
        ok += (prefix == "OK  ")
        fail += (prefix == "FAIL")
        if i < len(symbols):
            time.sleep(args.delay)

    log.info("-" * 72)
    log.info("done — %d ok, %d failed, %d skipped", ok, fail, len(symbols) - ok - fail)
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
