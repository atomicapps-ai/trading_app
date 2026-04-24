"""Label "successful breakout" bars across cached daily history.

Labels by OUTCOME only — no pre-filter on base length or structure.
This is Stage 1 of the empirical-first approach: find bars that
actually led to big moves, then measure their pre-move structure
separately (see scripts/measure_setup_structure.py, forthcoming).

A bar is a "breakout candidate" if:
    (1) It is at or near a recent high
        — close >= near_high_pct * max(close) over the last
          recent_high_window bars. Default: within 98% of the
          60-day max. This is the only structural pre-filter; by
          definition a breakout is breaking out of something, so
          the bar has to be at the top of its recent range.
    (2) It led to a significant forward gain
        — max(close) over the next forward_window bars >=
          (1 + min_gain_pct) * this_bar_close.

We DON'T filter on base length, volume dry-up, or any other
structural feature. We want a wide net of outcome-labeled examples
so Stage 2 can measure what actually distinguishes them.

Usage:
    python -m scripts.label_breakouts
        (defaults to every cached symbol)

    python -m scripts.label_breakouts AAPL MSFT NVDA
        (specific symbols)

    python -m scripts.label_breakouts --file pool.txt
        (symbols from a one-per-line text file)

    python -m scripts.label_breakouts --csv labels.csv
        (write every labeled bar across ALL (gain%, window) combos)

Output shape — one row per (symbol, bar, gain_threshold, window):
    symbol, date, close, atr, near_high_pct_of_60d_max,
    gain_pct, forward_window_bars,
    peak_close_in_window, bars_to_peak

Plus a summary table at the end:
    (gain_threshold, forward_window) -> count of candidates
    so the user can pick which combo(s) to carry forward.

Runs locally, writes to CSV. No tokens consumed reading this file.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import sys
from pathlib import Path
from typing import Iterable

import pandas as pd

from services.data_service import get_bars
from services.indicator_service import add_indicators
from services.settings_service import DATA_DIR

logging.basicConfig(level=logging.WARNING, format="%(message)s")
log = logging.getLogger("label_breakouts")


# --------------------------------------------------------------------------- #
# Sweep grid — tweak here if you want to add/remove combos
# --------------------------------------------------------------------------- #

GAIN_THRESHOLDS = [0.15, 0.25, 0.50, 1.00]     # 15%, 25%, 50%, 100%
FORWARD_WINDOWS = [60, 120, 252]                # ~3mo, ~6mo, ~12mo
RECENT_HIGH_WINDOW = 60                         # "at the top of its recent range"
NEAR_HIGH_TOLERANCE = 0.02                      # within 2% of the 60d max


# --------------------------------------------------------------------------- #
# Labeling — pure function of a bar series
# --------------------------------------------------------------------------- #


def label_symbol(
    symbol: str,
    df: pd.DataFrame,
    *,
    gain_thresholds: Iterable[float] = GAIN_THRESHOLDS,
    forward_windows: Iterable[int] = FORWARD_WINDOWS,
    recent_high_window: int = RECENT_HIGH_WINDOW,
    near_high_tolerance: float = NEAR_HIGH_TOLERANCE,
) -> pd.DataFrame:
    """Label every bar with max-forward-return across each window,
    flag candidates for each (gain, window) combo.

    Returns a DataFrame with one row per (bar, gain, window) that
    passed both the near-high filter and the forward-gain threshold.
    Empty DataFrame if no candidates found.
    """
    if len(df) < recent_high_window + max(forward_windows) + 5:
        return pd.DataFrame()  # insufficient history

    closes = df["close"].to_numpy()
    atrs = df["atr_14"].to_numpy() if "atr_14" in df.columns else None

    # Rolling max of the last `recent_high_window` closes (inclusive of current).
    rolling_high = df["close"].rolling(recent_high_window, min_periods=1).max().to_numpy()

    rows: list[dict] = []
    max_w = max(forward_windows)
    n = len(df)

    for i in range(recent_high_window, n - max_w):
        cur = closes[i]
        if cur <= 0:
            continue
        rh = rolling_high[i]
        if rh <= 0:
            continue
        near_high_pct = cur / rh
        if near_high_pct < (1.0 - near_high_tolerance):
            continue  # not at a recent high

        # Forward peak for each window
        for W in forward_windows:
            future = closes[i + 1 : i + 1 + W]
            if future.size == 0:
                continue
            peak = float(future.max())
            gain = (peak - cur) / cur
            bars_to_peak = int(future.argmax()) + 1  # 1-indexed from current

            for G in gain_thresholds:
                if gain >= G:
                    rows.append({
                        "symbol":              symbol,
                        "date":                df.index[i].strftime("%Y-%m-%d"),
                        "close":               round(float(cur), 4),
                        "atr_14":              None if atrs is None else round(float(atrs[i]), 4),
                        "near_high_pct":       round(float(near_high_pct), 4),
                        "gain_threshold":      G,
                        "forward_window":      W,
                        "actual_gain":         round(float(gain), 4),
                        "peak_close":          round(peak, 4),
                        "bars_to_peak":        bars_to_peak,
                    })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


async def _load(symbol: str) -> pd.DataFrame:
    df = await get_bars(symbol, "1d", min_bars=100)
    return add_indicators(df)


def _list_cached_symbols() -> list[str]:
    """All symbols with cached daily data. Strips the _1d.csv suffix."""
    hist = DATA_DIR / "historical"
    if not hist.exists():
        return []
    out: list[str] = []
    for p in sorted(hist.glob("*_1d.csv")):
        name = p.stem.replace("_1d", "")
        if name.startswith("^"):  # skip indices like ^VIX
            continue
        out.append(name)
    return out


def _read_symbol_file(path: str) -> list[str]:
    with open(path, "r") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


async def _main(args: argparse.Namespace) -> int:
    if args.file:
        symbols = _read_symbol_file(args.file)
    elif args.symbols:
        symbols = args.symbols
    else:
        symbols = _list_cached_symbols()

    if not symbols:
        print("No symbols given and no cached tickers found. "
              "Run scripts.download_history first.", file=sys.stderr)
        return 1

    print(f"Labeling breakouts across {len(symbols)} symbols...")
    all_rows: list[pd.DataFrame] = []
    for sym in symbols:
        try:
            df = await _load(sym)
        except Exception as e:
            print(f"  {sym}: skip ({e})")
            continue
        labeled = label_symbol(sym, df)
        if not labeled.empty:
            all_rows.append(labeled)
            total_for_sym = len(labeled)
            strongest = labeled.groupby(["gain_threshold", "forward_window"]).size()
            best_combo = strongest.idxmax() if not strongest.empty else None
            best_count = strongest.max() if not strongest.empty else 0
            print(f"  {sym}: {total_for_sym} candidate-rows "
                  f"(peak combo {best_combo} = {best_count})")
        else:
            print(f"  {sym}: 0 candidates")

    if not all_rows:
        print("\nNo candidates found across any symbol.")
        return 0

    full = pd.concat(all_rows, ignore_index=True)
    out_path = args.csv or (DATA_DIR / "labeled_breakouts.csv")
    full.to_csv(out_path, index=False)
    print(f"\nWrote {len(full):,} candidate-rows to {out_path}")

    # Summary: count per (gain, window) combo.
    print("\n=== Candidate count per (gain%, forward window) combo ===")
    summary = (
        full.groupby(["gain_threshold", "forward_window"])
            .size()
            .reset_index(name="count")
            .sort_values(["forward_window", "gain_threshold"])
    )
    for _, r in summary.iterrows():
        g = f"{int(r['gain_threshold'] * 100)}%"
        w = f"{int(r['forward_window'])}b"
        print(f"  gain>={g:>5}  window={w:>5}  count={int(r['count']):>5}")

    # Unique bars per combo (dedupe bars that hit multiple gain thresholds)
    print("\n=== Unique-bars summary (each bar counted once per combo) ===")
    for G in GAIN_THRESHOLDS:
        for W in FORWARD_WINDOWS:
            sub = full[(full["gain_threshold"] == G) & (full["forward_window"] == W)]
            uniq = sub.drop_duplicates(subset=["symbol", "date"])
            print(f"  gain>={int(G*100):>3}%  window={W:>3}b  "
                  f"unique bars={len(uniq):>5}  "
                  f"symbols={uniq['symbol'].nunique():>2}")

    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Label successful-breakout bars by outcome only.",
    )
    p.add_argument("symbols", nargs="*",
                   help="Symbols to label (default: all cached)")
    p.add_argument("--file", default=None,
                   help="Text file, one symbol per line (# comments ok)")
    p.add_argument("--csv", default=None,
                   help="Output CSV path (default: data/labeled_breakouts.csv)")
    args = p.parse_args()
    return asyncio.run(_main(args))


if __name__ == "__main__":
    sys.exit(main())
