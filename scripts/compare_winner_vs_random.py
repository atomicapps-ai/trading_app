"""Compare WINNER feature distributions vs RANDOM-BAR feature distributions.

Phase 1 taught us that "cross-set" comparison (broad winners vs elite
winners) doesn't tell us what actually drives the detector — features
can shift between elite and broad while looking identical on random
bars. The detector's real job is "winner vs random," not "winner vs
better winner."

This script does THAT comparison. For every cached symbol:
  1. Use the existing event_features.csv as the WINNER side
  2. Sample N random bars per symbol, compute the same 38 features
     (using the exact measure_event() function from
     scripts.measure_setup_structure — guarantees feature parity)
  3. For each feature: print winner P50 vs random P50, gap, and a
     simple separability score (Cohen's d-style)
  4. Sort features by separability — top of the list = predictive,
     bottom = noise

Use the output to drive Phase 2 detector tuning: only score features
that SEPARATE winners from random bars.

Usage:
    python -m scripts.compare_winner_vs_random
    python -m scripts.compare_winner_vs_random --random-per-symbol 500
    python -m scripts.compare_winner_vs_random --top 15
"""
from __future__ import annotations

import argparse
import asyncio
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.measure_setup_structure import measure_event, LOOKBACK
from services.data_service import get_bars
from services.indicator_service import add_indicators
from services.settings_service import DATA_DIR


# Features whose values are bounded — we use absolute gap instead of
# Cohen's d for them. For unbounded features (RSI, base length, vol
# ratios), Cohen's d is more appropriate.
BOUNDED_FEATURES = {
    "anchor_cpr", "avg_cpr_20",
    "anchor_upper_wick", "anchor_lower_wick",
    "avg_upper_wick_20", "avg_lower_wick_20",
    "up_vol_share_60",
    "max_dd_180", "max_dd_base",
    "pct_of_52w_high", "pct_of_60d_high",
}

# Features where LOWER is bullish (so winner_p50 < random_p50 = good signal)
LOWER_IS_BETTER = {
    "max_dd_180", "max_dd_base",
    "anchor_upper_wick", "avg_upper_wick_20",
    "atr_ratio_now_vs_180", "atr_ratio_now_vs_60",
    "final_depth_pct", "compression",
    "gap_down_count_60",
}


async def _measure_random_bars(
    symbol: str,
    df_indicators: pd.DataFrame,
    n_samples: int,
    rng: random.Random,
) -> list[dict]:
    """Sample N random bars from df, compute the full feature set on each."""
    n_bars = len(df_indicators)
    if n_bars <= LOOKBACK + 50:
        return []
    sample_size = min(n_samples, n_bars - LOOKBACK)
    positions = rng.sample(range(LOOKBACK, n_bars), sample_size)
    rows = []
    for pos in positions:
        ts = df_indicators.index[pos]
        features = measure_event(df_indicators, ts)
        if features is not None:
            features["symbol"] = symbol
            features["date"] = ts.strftime("%Y-%m-%d")
            rows.append(features)
    return rows


async def _gather_random_features(
    symbols: list[str],
    n_per_symbol: int,
    seed: int,
) -> pd.DataFrame:
    rng = random.Random(seed)
    all_rows: list[dict] = []
    for i, sym in enumerate(sorted(symbols), 1):
        try:
            df = await get_bars(sym, "1d", min_bars=LOOKBACK + 50)
            df = add_indicators(df)
        except Exception as e:
            print(f"  [{i}/{len(symbols)}] {sym}: skip ({e})")
            continue
        rows = await _measure_random_bars(sym, df, n_per_symbol, rng)
        all_rows.extend(rows)
        print(f"  [{i:>2}/{len(symbols)}] {sym}: {len(rows)} random bars measured")
    return pd.DataFrame(all_rows)


def cohens_d(a: pd.Series, b: pd.Series) -> float:
    a = a.dropna()
    b = b.dropna()
    if len(a) < 5 or len(b) < 5:
        return float("nan")
    ma, mb = a.mean(), b.mean()
    pooled = np.sqrt(((a.var(ddof=1) * (len(a) - 1)) +
                      (b.var(ddof=1) * (len(b) - 1))) /
                     (len(a) + len(b) - 2))
    return float((ma - mb) / pooled) if pooled > 0 else float("nan")


def comparison_row(
    feature: str, winners: pd.DataFrame, randoms: pd.DataFrame,
) -> dict:
    if feature not in winners.columns or feature not in randoms.columns:
        return {"feature": feature, "skipped": "column missing"}
    w = pd.to_numeric(winners[feature], errors="coerce").dropna()
    r = pd.to_numeric(randoms[feature], errors="coerce").dropna()
    if len(w) < 5 or len(r) < 5:
        return {"feature": feature, "skipped": "insufficient samples"}
    w_med = float(w.median())
    r_med = float(r.median())
    abs_gap = abs(w_med - r_med)
    d = cohens_d(w, r)
    # Sign so positive = "winners > random" (in the bullish direction)
    if feature in LOWER_IS_BETTER:
        signed_gap = r_med - w_med  # positive = winners are LOWER
        signed_d = -d if not np.isnan(d) else d
    else:
        signed_gap = w_med - r_med  # positive = winners are HIGHER
        signed_d = d
    return {
        "feature":      feature,
        "winner_p50":   round(w_med, 4),
        "random_p50":   round(r_med, 4),
        "abs_gap":      round(abs_gap, 4),
        "signed_gap":   round(signed_gap, 4),
        "cohens_d":     round(signed_d, 3) if not np.isnan(signed_d) else None,
        "n_winners":    len(w),
        "n_randoms":    len(r),
    }


async def _main(args: argparse.Namespace) -> int:
    winners_path = Path(args.winners or DATA_DIR / "features_50_120.csv")
    if not winners_path.exists():
        print(f"Winner features not found: {winners_path}", file=sys.stderr)
        print("Run scripts.measure_setup_structure first.", file=sys.stderr)
        return 1

    winners = pd.read_csv(winners_path)
    print(f"Loaded {len(winners)} winner-anchor feature rows from {winners_path}")
    symbols = winners["symbol"].unique().tolist()
    print(f"Sampling {args.random_per_symbol} random bars per symbol "
          f"from {len(symbols)} symbols...")

    randoms = await _gather_random_features(symbols, args.random_per_symbol,
                                              args.seed)
    out_random = DATA_DIR / "features_random.csv"
    randoms.to_csv(out_random, index=False)
    print(f"\nWrote {len(randoms)} random-bar feature rows to {out_random}")

    # Skip non-numeric / metadata columns
    skip = {"symbol", "date", "anchor_date", "anchor_close",
            "anchor_near_high_pct", "peak_date", "peak_close",
            "peak_gain", "cluster_size", "cluster_span_days",
            "gain_threshold", "forward_window", "_base_low"}
    feature_cols = [c for c in winners.columns
                    if c not in skip and pd.api.types.is_numeric_dtype(winners[c])]

    rows = [comparison_row(f, winners, randoms) for f in feature_cols]
    df = pd.DataFrame([r for r in rows if "skipped" not in r])
    if df.empty:
        print("No comparable features.")
        return 1

    # Rank by absolute Cohen's d (best separability first)
    df["abs_d"] = df["cohens_d"].abs()
    df = df.sort_values("abs_d", ascending=False)

    print(f"\n{'='*100}")
    print(f"WINNER vs RANDOM separability — top {args.top} features by Cohen's d")
    print(f"{'='*100}")
    print(f"{'feature':>26}  {'winner_p50':>10}  {'random_p50':>10}  "
          f"{'signed_gap':>10}  {'cohens_d':>9}  {'verdict':>15}")
    for _, r in df.head(args.top).iterrows():
        d = r["cohens_d"]
        if d is None or pd.isna(d):
            verdict = "n/a"
        elif abs(d) >= 0.8:
            verdict = "STRONG"
        elif abs(d) >= 0.5:
            verdict = "MODERATE"
        elif abs(d) >= 0.2:
            verdict = "WEAK"
        else:
            verdict = "negligible"
        if d is not None and d < 0 and abs(d) >= 0.2:
            verdict += " (wrong dir!)"
        print(f"{r['feature']:>26}  "
              f"{r['winner_p50']:>10.4f}  {r['random_p50']:>10.4f}  "
              f"{r['signed_gap']:>10.4f}  {r['cohens_d']:>9.3f}  {verdict:>15}")

    print(f"\n{'='*100}")
    print(f"BOTTOM features by separability (least useful — candidates to drop)")
    print(f"{'='*100}")
    for _, r in df.tail(10).iterrows():
        print(f"{r['feature']:>26}  d={r['cohens_d']:>6.3f}  "
              f"winner={r['winner_p50']:>8.3f}  random={r['random_p50']:>8.3f}")

    out = DATA_DIR / "winner_vs_random_separability.csv"
    df.to_csv(out, index=False)
    print(f"\nFull table: {out}")
    print("\nInterpretation:")
    print("  STRONG (d >= 0.8) -> these features really separate winners from random")
    print("  MODERATE (0.5-0.8) -> useful but not dominant")
    print("  WEAK (0.2-0.5) -> minor signal, can include with low weight")
    print("  negligible (<0.2) -> drop from scoring; they're noise")
    print("  'wrong dir!' -> winners go OPPOSITE of expected; flip the direction or drop")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--winners", default=None,
                   help="Path to winner features CSV (default features_50_120.csv)")
    p.add_argument("--random-per-symbol", type=int, default=300)
    p.add_argument("--top", type=int, default=20,
                   help="How many top-ranked features to show in stdout")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    return asyncio.run(_main(args))


if __name__ == "__main__":
    sys.exit(main())
