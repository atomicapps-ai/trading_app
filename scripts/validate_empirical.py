"""Validate `agents/detectors/breakout_empirical.py` against labeled
breakouts AND a random-bar sample. Answers the question:

  "Does the detector fire more often on real winner setups than on
  random bars? If so, by how much (lift)?"

Methodology:
    1. Load breakout_events.csv (anchor dates of the 502 winners at
       gain>=50%, window=120b). These are TRUE POSITIVES — bars where
       a 50%+ rally actually followed.
    2. Sample N random bars per symbol from the cached history.
       These are the BASELINE — most bars are not breakout precursors.
    3. Run the detector on both sets (using as_of_ts replay).
    4. Report:
        - winner_capture_rate = fraction of winner anchors that fired
        - random_fire_rate    = fraction of random bars that fired
        - lift = winner_capture_rate / random_fire_rate
          (lift >> 1 = signal; lift ~= 1 = random; lift < 1 = broken)

Interpretation:
    * lift >= 3.0 → strong signal
    * lift 2.0 - 3.0 → usable
    * lift 1.2 - 2.0 → weak, probably won't be profitable
    * lift < 1.2 → no real signal, rethink

Usage:
    python -m scripts.validate_empirical
    python -m scripts.validate_empirical --gain 0.50 --window 120
    python -m scripts.validate_empirical --random-per-symbol 500
    python -m scripts.validate_empirical --min-score 60
"""
from __future__ import annotations

import argparse
import asyncio
import random
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from agents.detectors.breakout_empirical import (
    PATTERN_NAME,
    detect_breakout_empirical,
)
from services.data_service import get_bars
from services.indicator_service import add_indicators
from services.settings_service import DATA_DIR


async def _load(symbol: str) -> pd.DataFrame:
    df = await get_bars(symbol, "1d", min_bars=200)
    return add_indicators(df)


def _run_detector(df: pd.DataFrame, ts: pd.Timestamp, min_score: float) -> tuple[bool, float]:
    """Returns (fired, score). Score is 0.0 if detector returned None."""
    cfg = {"pattern_thresholds": {PATTERN_NAME: {"min_score": min_score}}}
    res = detect_breakout_empirical(df, config=cfg, as_of_ts=ts)
    if res is None:
        return False, 0.0
    # Pull score from diagnostic evidence
    for ev in res.evidence_items:
        if ev.get("type") == "diagnostic":
            return True, float(ev["ref"].get("score", 0.0))
    return True, 0.0


async def _evaluate(
    events: pd.DataFrame,
    random_per_symbol: int,
    min_score: float,
    seed: int,
) -> dict:
    """Run detector on anchor dates + random samples. Returns summary dict."""
    rng = random.Random(seed)

    anchor_rows: list[dict] = []
    random_rows: list[dict] = []

    symbols_in_events = events["symbol"].unique().tolist()
    print(f"Evaluating {len(symbols_in_events)} symbols with events + baseline samples...")

    for i, sym in enumerate(sorted(symbols_in_events), 1):
        try:
            df = await _load(sym)
        except Exception as e:
            print(f"  [{i}/{len(symbols_in_events)}] {sym}: load failed ({e})")
            continue

        # Anchor evaluation
        sym_events = events[events["symbol"] == sym]
        anchor_fires = 0
        anchor_scores: list[float] = []
        for _, ev in sym_events.iterrows():
            # Anchor_date is a calendar date; the actual bar timestamp
            # carries a time component (04:00 or 05:00 UTC for US daily
            # bars). Match by calendar date — take the last bar whose
            # date equals the anchor date, or the next prior bar.
            anchor_date = pd.Timestamp(ev["anchor_date"]).date()
            end_of_day = pd.Timestamp(ev["anchor_date"], tz="UTC") + pd.Timedelta(hours=23, minutes=59, seconds=59)
            pos = df.index.searchsorted(end_of_day, side="right") - 1
            if pos < 0:
                continue
            ts = df.index[pos]
            # Sanity check: the bar we snapped to should be on or
            # before the anchor date (not days earlier from a gap).
            if (anchor_date - ts.date()).days > 5:
                continue
            fired, score = _run_detector(df, ts, min_score)
            anchor_rows.append({
                "symbol": sym, "date": ts.strftime("%Y-%m-%d"),
                "type": "anchor", "fired": fired, "score": score,
            })
            if fired:
                anchor_fires += 1
                anchor_scores.append(score)

        # Random sampling — uniform over all bars, excluding the first
        # 200 (insufficient history for the detector).
        n_bars = len(df)
        if n_bars <= 201:
            random_fires = 0
        else:
            sample_size = min(random_per_symbol, n_bars - 200)
            sampled_positions = rng.sample(range(200, n_bars), sample_size)
            random_fires = 0
            for pos in sampled_positions:
                ts = df.index[pos]
                fired, score = _run_detector(df, ts, min_score)
                random_rows.append({
                    "symbol": sym, "date": ts.strftime("%Y-%m-%d"),
                    "type": "random", "fired": fired, "score": score,
                })
                if fired:
                    random_fires += 1

        print(f"  [{i:>2}/{len(symbols_in_events)}] {sym}: "
              f"anchors {anchor_fires}/{len(sym_events)} "
              f"({100 * anchor_fires / max(1, len(sym_events)):.0f}%)  "
              f"random {random_fires}/{random_per_symbol} "
              f"({100 * random_fires / max(1, random_per_symbol):.1f}%)")

    anchor_df = pd.DataFrame(anchor_rows)
    random_df = pd.DataFrame(random_rows)
    all_df = pd.concat([anchor_df, random_df], ignore_index=True)

    out_path = DATA_DIR / "validation_results.csv"
    all_df.to_csv(out_path, index=False)

    summary = {
        "n_anchors":            len(anchor_df),
        "n_random":             len(random_df),
        "anchor_fires":         int(anchor_df["fired"].sum()),
        "random_fires":         int(random_df["fired"].sum()),
        "winner_capture_rate":  float(anchor_df["fired"].mean()) if len(anchor_df) else 0.0,
        "random_fire_rate":     float(random_df["fired"].mean()) if len(random_df) else 0.0,
        "anchor_median_score":  float(anchor_df[anchor_df["fired"]]["score"].median())
                                    if anchor_df["fired"].any() else 0.0,
        "random_median_score":  float(random_df[random_df["fired"]]["score"].median())
                                    if random_df["fired"].any() else 0.0,
    }
    lift = (summary["winner_capture_rate"] / summary["random_fire_rate"]
            if summary["random_fire_rate"] > 0 else float("inf"))
    summary["lift"] = lift
    summary["output_csv"] = str(out_path)
    return summary


def _interpret(lift: float) -> str:
    if lift >= 3.0:
        return "STRONG signal — detector is clearly picking up winners"
    if lift >= 2.0:
        return "USABLE — meaningful signal, worth pursuing"
    if lift >= 1.2:
        return "WEAK — rethink features or thresholds"
    return "NO SIGNAL — back to the drawing board"


async def _main(args: argparse.Namespace) -> int:
    events_path = Path(args.events or DATA_DIR / "breakout_events.csv")
    if not events_path.exists():
        print(f"Events CSV not found: {events_path}", file=sys.stderr)
        print("Run scripts.label_breakouts + scripts.dedup_breakouts first.",
              file=sys.stderr)
        return 1

    events = pd.read_csv(events_path)
    events = events[
        (events["gain_threshold"].astype(float) == float(args.gain)) &
        (events["forward_window"].astype(int) == int(args.window))
    ]
    print(f"Loaded {len(events)} anchor events at gain>={args.gain}, "
          f"window={args.window}b across {events['symbol'].nunique()} symbols")

    summary = await _evaluate(
        events=events,
        random_per_symbol=args.random_per_symbol,
        min_score=args.min_score,
        seed=args.seed,
    )

    print(f"\n{'='*65}")
    print("VALIDATION SUMMARY")
    print(f"{'='*65}")
    print(f"  Anchor events (true positives):     {summary['n_anchors']:>6}")
    print(f"  Random bars (baseline):             {summary['n_random']:>6}")
    print()
    print(f"  Winner capture rate:  {summary['winner_capture_rate']*100:>6.2f}%  "
          f"({summary['anchor_fires']} / {summary['n_anchors']})")
    print(f"  Random fire rate:     {summary['random_fire_rate']*100:>6.2f}%  "
          f"({summary['random_fires']} / {summary['n_random']})")
    print()
    print(f"  LIFT:                 {summary['lift']:>6.2f}x  — {_interpret(summary['lift'])}")
    print()
    print(f"  Median score on fires — anchors: {summary['anchor_median_score']:.1f}  "
          f"random: {summary['random_median_score']:.1f}")
    print()
    print(f"  Detailed per-event results: {summary['output_csv']}")

    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--events", default=None,
                   help="Path to breakout_events.csv (default data/)")
    p.add_argument("--gain", type=float, default=0.50,
                   help="gain_threshold to validate against (default 0.50)")
    p.add_argument("--window", type=int, default=120,
                   help="forward_window to validate against (default 120)")
    p.add_argument("--random-per-symbol", type=int, default=300,
                   help="Random bars sampled per symbol (default 300)")
    p.add_argument("--min-score", type=float, default=50.0,
                   help="Detector score floor (default 50)")
    p.add_argument("--seed", type=int, default=42,
                   help="Random sample seed (default 42)")
    args = p.parse_args()
    return asyncio.run(_main(args))


if __name__ == "__main__":
    sys.exit(main())
