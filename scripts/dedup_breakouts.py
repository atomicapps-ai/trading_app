"""Collapse consecutive labeled bars into discrete breakout events.

Problem: `label_breakouts.py` tags every bar that precedes a big move.
A single breakout produces dozens of consecutive labels because each
bar in the run-up independently satisfies "at a recent high AND next
N days gain X%". To count actual setups we need to cluster consecutive
labels into one event.

This script reads `data/labeled_breakouts.csv` and writes
`data/breakout_events.csv` with one row per event, and prints a summary
of event counts per (gain%, window) combo — the real pool size that
Stage 2 (structure measurement) will work from.

Clustering rule:
    Within the same (symbol, gain_threshold, forward_window), two
    labels belong to the same event if the date gap between them is
    <= `max_gap_days`. The event's anchor is the FIRST bar of the
    cluster (the earliest "this will lead to a big move" signal).

Usage:
    python -m scripts.dedup_breakouts
    python -m scripts.dedup_breakouts --gap 10
    python -m scripts.dedup_breakouts --combo 0.50 120
        (only print events for gain>=50%, window=120 bars)
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from services.settings_service import DATA_DIR


def cluster_events(group: pd.DataFrame, max_gap_days: int) -> pd.DataFrame:
    """Cluster a group of labeled bars (same symbol + combo) by date gap.

    Returns a DataFrame with one row per event. The row carries:
        anchor_date:  first bar of the cluster (the breakout signal)
        peak_date:    bar within the cluster with the largest gain
        cluster_size: how many consecutive bars made this cluster
        anchor fields from the first bar
    """
    g = group.sort_values("date").reset_index(drop=True).copy()
    gap_days = g["date"].diff().dt.days.fillna(0)
    cluster_id = (gap_days > max_gap_days).cumsum()
    g["cluster_id"] = cluster_id

    events = []
    for _, cluster in g.groupby("cluster_id"):
        anchor = cluster.iloc[0]
        # Peak within cluster = bar with highest actual_gain
        peak_row = cluster.loc[cluster["actual_gain"].idxmax()]
        events.append({
            "symbol":          anchor["symbol"],
            "gain_threshold":  anchor["gain_threshold"],
            "forward_window":  int(anchor["forward_window"]),
            "anchor_date":     anchor["date"].strftime("%Y-%m-%d"),
            "anchor_close":    anchor["close"],
            "anchor_near_high_pct": anchor["near_high_pct"],
            "peak_date":       peak_row["date"].strftime("%Y-%m-%d"),
            "peak_close":      peak_row["peak_close"],
            "peak_gain":       peak_row["actual_gain"],
            "cluster_size":    len(cluster),
            "cluster_span_days": int((cluster["date"].max() - cluster["date"].min()).days),
        })
    return pd.DataFrame(events)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", default=str(DATA_DIR / "labeled_breakouts.csv"))
    p.add_argument("--output", default=str(DATA_DIR / "breakout_events.csv"))
    p.add_argument("--gap", type=int, default=10,
                   help="Max days between consecutive labels to still count "
                        "as same cluster (default 10)")
    p.add_argument("--combo", nargs=2, metavar=("GAIN", "WINDOW"),
                   help="Filter summary to this (gain%%, window) combo")
    args = p.parse_args()

    print(f"Reading {args.input}...")
    df = pd.read_csv(args.input)
    df["date"] = pd.to_datetime(df["date"])
    print(f"  {len(df):,} labeled bars, "
          f"{df['symbol'].nunique()} symbols")

    print(f"\nClustering with max_gap_days={args.gap}...")
    parts = []
    for (sym, g, w), group in df.groupby(["symbol", "gain_threshold", "forward_window"]):
        ev = cluster_events(group, args.gap)
        if not ev.empty:
            parts.append(ev)
    if not parts:
        print("No events produced.")
        return 1

    events = pd.concat(parts, ignore_index=True)
    events.to_csv(args.output, index=False)
    print(f"  wrote {len(events):,} events to {args.output}")

    # Summary: events per (gain, window)
    print("\n=== Event counts per combo (post-dedup) ===")
    summary = (
        events.groupby(["gain_threshold", "forward_window"])
              .agg(events=("anchor_date", "count"),
                   symbols=("symbol", "nunique"),
                   median_cluster_size=("cluster_size", "median"),
                   median_span_days=("cluster_span_days", "median"))
              .reset_index()
              .sort_values(["forward_window", "gain_threshold"])
    )
    print(f"  {'gain':>6} {'window':>7} {'events':>7} {'symbols':>8} "
          f"{'median_cluster':>15} {'median_span_days':>17}")
    for _, r in summary.iterrows():
        print(f"  {int(r['gain_threshold']*100):>5}% "
              f"{int(r['forward_window']):>6}b "
              f"{int(r['events']):>7} "
              f"{int(r['symbols']):>8} "
              f"{int(r['median_cluster_size']):>15} "
              f"{int(r['median_span_days']):>17}")

    # If user asked for a specific combo, dump the events for that combo
    if args.combo:
        gain = float(args.combo[0])
        win = int(args.combo[1])
        sub = events[(events["gain_threshold"] == gain) &
                     (events["forward_window"] == win)]
        sub = sub.sort_values("peak_gain", ascending=False)
        print(f"\n=== Top 30 events for gain>={int(gain*100)}%, window={win}b ===")
        print(f"  (of {len(sub)} total for this combo)")
        print(f"  {'symbol':>7} {'anchor':>11} {'close':>10} "
              f"{'peak_gain':>10} {'peak_date':>11} {'cluster':>8}")
        for _, r in sub.head(30).iterrows():
            print(f"  {r['symbol']:>7} {r['anchor_date']:>11} "
                  f"${r['anchor_close']:>9.2f} "
                  f"{r['peak_gain']*100:>9.1f}% "
                  f"{r['peak_date']:>11} {int(r['cluster_size']):>8}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
