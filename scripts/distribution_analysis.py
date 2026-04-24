"""Stage 3: turn measured features into empirical detector thresholds.

For each feature column in `data/features_*.csv`, compute the
distribution across the population of successful breakouts. The
detector's thresholds become percentile bands (P10–P90 by default),
which means "X% of successful breakouts had this feature value within
this range" — a math-defensible threshold instead of a guess.

Three outputs:
    1. Per-feature distribution table (mean, median, percentiles)
    2. Cross-set comparison: 50%/120b vs 100%/120b vs 100%/252b
       — features that DIFFER across sets are the ones that
       distinguish "good breakout" from "elite breakout"
    3. Recommended threshold spec — concrete numbers to plug into
       the empirical detector

Usage:
    python -m scripts.distribution_analysis
        (analyzes all 3 default CSVs)
    python -m scripts.distribution_analysis --csv data/features_50_120.csv
        (single set)

Output goes to stdout AND data/threshold_spec.md (so you can re-read it later).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from services.settings_service import DATA_DIR


# Features grouped + classified by "direction" — i.e. is a high or low
# value the bullish signal? This tells us which percentile to use as
# the threshold. The distribution shape (skew + spread) also informs
# whether the threshold should be one-sided or a range.
FEATURE_GROUPS: dict[str, list[tuple[str, str]]] = {
    # group_name : [(feature_name, direction), ...]
    "Base geometry": [
        ("base_len_25pct",       "range"),
        ("base_len_15pct",       "range"),
        ("base_len_10pct",       "range"),
        ("max_dd_180",           "lower"),  # less drawdown = better (but allow some)
        ("max_dd_base",          "lower"),
    ],
    "Resistance touches": [
        ("swing_high_count",     "higher"), # more pivots = more structure
        ("touches_within_2pct",  "higher"),
        ("touches_within_5pct",  "higher"),
        ("touches_within_10pct", "higher"),
    ],
    "Contraction": [
        ("n_contraction_pairs",  "higher"),
        ("first_depth_pct",      "range"),
        ("final_depth_pct",      "lower"),  # tighter final = better
        ("compression",          "lower"),  # final/first < 1 = tightening
    ],
    "Volatility": [
        ("atr_pct",              "range"),
        ("atr_ratio_now_vs_180", "lower"),  # ATR contracted = better
        ("atr_ratio_now_vs_60",  "lower"),
    ],
    "Volume": [
        ("vol_ratio_30_180",     "range"),  # context-dependent
        ("vol_ratio_10_50",      "range"),
        ("anchor_vol_vs_avg",    "higher"), # breakout day volume spike
    ],
    "Trend context": [
        ("close_vs_sma50",       "higher"), # above SMA50 = better
        ("close_vs_sma200",      "higher"),
        ("sma50_vs_sma200",      "higher"),
        ("sma50_slope_60",       "higher"),
        ("pct_of_52w_high",      "higher"), # near 52w high = breakout
        ("pct_above_52w_low",    "higher"),
    ],
    "Momentum": [
        ("rsi_14",               "range"),  # extreme either way is bad
        ("run_up_60",            "higher"),
        ("run_up_180",           "higher"),
    ],
    "Wick geometry (Phase 1)": [
        # Upper wicks = rejection from highs. Lower wicks = support.
        # For bullish setups: we want low upper wicks and healthy
        # lower wicks (buyers absorbing pullbacks intraday).
        ("anchor_upper_wick",    "lower"),
        ("anchor_lower_wick",    "higher"),
        ("avg_upper_wick_20",    "lower"),
        ("avg_lower_wick_20",    "higher"),
    ],
    "Close position (Phase 1)": [
        # CPR (close-position-in-range): 1 = closed at day high.
        # High recent average CPR = consistent closing strength.
        ("anchor_cpr",           "higher"),
        ("avg_cpr_20",           "higher"),
    ],
    "Gaps (Phase 1)": [
        # Gap counts over last 60 bars. Gap ups = news/momentum.
        # Gap downs = overnight selling. Largest gap = biggest event.
        ("gap_up_count_60",      "higher"),
        ("gap_down_count_60",    "lower"),
        ("largest_gap_up_60",    "higher"),
    ],
    "Volume flow (Phase 1)": [
        # Share of total 60d volume that came on green bars. Above
        # 0.5 = accumulation, below 0.5 = distribution. Fed by the
        # bar-level direction — coarse but directional.
        ("up_vol_share_60",      "higher"),
    ],
}

PERCENTILES = [5, 10, 25, 50, 75, 90, 95]


def _percentile(s: pd.Series, p: int) -> float:
    s = s.dropna()
    if s.empty:
        return float("nan")
    return float(np.percentile(s, p))


def feature_distribution(df: pd.DataFrame, feature: str) -> dict:
    if feature not in df.columns:
        return {"feature": feature, "n": 0}
    s = pd.to_numeric(df[feature], errors="coerce").dropna()
    if s.empty:
        return {"feature": feature, "n": 0}
    out = {
        "feature": feature,
        "n":       int(len(s)),
        "mean":    float(s.mean()),
        "std":     float(s.std()),
    }
    for p in PERCENTILES:
        out[f"P{p}"] = _percentile(s, p)
    return out


def render_group_table(
    df: pd.DataFrame, group: str, features: list[tuple[str, str]],
) -> str:
    rows = [feature_distribution(df, f) for f, _ in features]
    direction_lookup = dict(features)
    if not rows or all(r["n"] == 0 for r in rows):
        return f"\n### {group}\n  (no data)\n"

    lines = [f"\n### {group}\n"]
    lines.append("| Feature | Dir | n | mean | P10 | P25 | P50 | P75 | P90 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        if r["n"] == 0:
            continue
        d = direction_lookup.get(r["feature"], "?")
        def fmt(v):
            if v is None or (isinstance(v, float) and np.isnan(v)):
                return "—"
            if abs(v) >= 100:
                return f"{v:.0f}"
            if abs(v) >= 10:
                return f"{v:.1f}"
            return f"{v:.3f}"
        lines.append(
            f"| `{r['feature']}` | {d} | {r['n']} | {fmt(r['mean'])} | "
            f"{fmt(r['P10'])} | {fmt(r['P25'])} | {fmt(r['P50'])} | "
            f"{fmt(r['P75'])} | {fmt(r['P90'])} |"
        )
    return "\n".join(lines) + "\n"


def render_full_distribution(df: pd.DataFrame, set_name: str) -> str:
    out = [f"\n## Distribution — {set_name} ({len(df):,} events)\n"]
    out.append("Direction column: **higher** = bullish if value is higher; "
               "**lower** = bullish if lower; **range** = both ends matter.\n")
    for group, features in FEATURE_GROUPS.items():
        out.append(render_group_table(df, group, features))
    return "\n".join(out)


def render_recommended_thresholds(df: pd.DataFrame, set_name: str) -> str:
    """Build a concrete threshold spec from the percentiles, using
    direction to pick which side of the distribution to clip."""
    out = [f"\n## Recommended detector thresholds — derived from {set_name}\n"]
    out.append("Each threshold below is grounded in the percentile of the "
               "labeled-success distribution, not guessed. The detector should "
               "ACCEPT events whose feature falls inside the cited band.\n")

    for group, features in FEATURE_GROUPS.items():
        out.append(f"\n### {group}\n")
        for feature, direction in features:
            stats = feature_distribution(df, feature)
            if stats["n"] == 0:
                continue
            p10, p25, p50, p75, p90 = (
                stats["P10"], stats["P25"], stats["P50"], stats["P75"], stats["P90"]
            )
            def fmt(v):
                if abs(v) >= 100:
                    return f"{v:.0f}"
                return f"{v:.3f}"
            if direction == "higher":
                out.append(
                    f"- **{feature}** ≥ `{fmt(p10)}` "
                    f"(P10; median {fmt(p50)}, P90 {fmt(p90)}) — "
                    "10% of winners had less, so this is the floor."
                )
            elif direction == "lower":
                out.append(
                    f"- **{feature}** ≤ `{fmt(p90)}` "
                    f"(P90; median {fmt(p50)}, P10 {fmt(p10)}) — "
                    "10% of winners had more, so this is the ceiling."
                )
            else:  # range
                out.append(
                    f"- **{feature}** in `[{fmt(p10)}, {fmt(p90)}]` "
                    f"(P10–P90 band; median {fmt(p50)}) — "
                    "covers 80% of winners."
                )
    return "\n".join(out) + "\n"


def render_cross_set_comparison(
    sets: dict[str, pd.DataFrame],
) -> str:
    """For each feature, show median across the 3 sets side-by-side.
    Features whose median DIFFERS materially across sets are the ones
    that distinguish 'good' from 'elite' breakouts."""
    out = [f"\n## Cross-set median comparison — what distinguishes elite winners?\n"]
    out.append("Features where the median moves substantially across sets are "
               "the most predictive. e.g. if `compression` is 0.6 in the broad "
               "set and 0.4 in the elite set, tighter bases yield bigger moves.\n")

    set_names = list(sets.keys())
    out.append("| Feature | Dir | " + " | ".join(set_names) + " | Δ (elite − broad) |")
    out.append("|---|---|" + "|".join(["---"] * (len(set_names) + 1)) + "|")

    all_features = []
    for group_features in FEATURE_GROUPS.values():
        all_features.extend(group_features)

    for feature, direction in all_features:
        medians = []
        for name in set_names:
            df = sets[name]
            s = pd.to_numeric(df.get(feature, pd.Series(dtype=float)),
                              errors="coerce").dropna()
            medians.append(float(s.median()) if not s.empty else None)
        if all(m is None for m in medians):
            continue
        broad = medians[0]
        elite = medians[-1]
        delta = (elite - broad) if (broad is not None and elite is not None) else None
        def fmt(v):
            if v is None or (isinstance(v, float) and np.isnan(v)):
                return "—"
            if abs(v) >= 100:
                return f"{v:.0f}"
            return f"{v:.3f}"
        med_strs = [fmt(m) for m in medians]
        out.append(
            f"| `{feature}` | {direction} | " + " | ".join(med_strs) +
            f" | {fmt(delta)} |"
        )
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

DEFAULT_CSVS = [
    ("50%/120b (broad winners)",   "data/features_50_120.csv"),
    ("100%/120b (elite winners)",  "data/features_100_120.csv"),
    ("100%/252b (multi-baggers)",  "data/features_100_252.csv"),
]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--csv", action="append", default=None,
                   help="Specific feature CSV(s). Default: all 3 standard sets.")
    p.add_argument("--out", default=str(DATA_DIR / "threshold_spec.md"))
    args = p.parse_args()

    if args.csv:
        sets = {Path(c).stem: pd.read_csv(c) for c in args.csv}
    else:
        sets = {}
        for name, path in DEFAULT_CSVS:
            full = Path(path)
            if full.exists():
                sets[name] = pd.read_csv(full)
            else:
                print(f"Skip (missing): {path}")
    if not sets:
        print("No CSVs found. Run scripts.measure_setup_structure first.",
              file=sys.stderr)
        return 1

    parts: list[str] = [
        "# Empirical Detector Thresholds — Distribution Analysis\n",
        "Generated by `scripts/distribution_analysis.py` from labeled\n"
        "successful breakouts. Numbers are percentiles of the actual\n"
        "feature distributions across the labeled events. Thresholds\n"
        "below should be the empirical defaults for the new detector.\n",
    ]

    for name, df in sets.items():
        parts.append(render_full_distribution(df, name))

    if len(sets) > 1:
        parts.append(render_cross_set_comparison(sets))

    # Use the BROADEST set as the basis for default thresholds — that
    # captures the widest variety of valid setups. Elite-set thresholds
    # would be tighter and miss good-but-not-elite winners.
    primary = list(sets.values())[0]
    primary_name = list(sets.keys())[0]
    parts.append(render_recommended_thresholds(primary, primary_name))

    full_text = "\n".join(parts)
    print(full_text)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(full_text, encoding="utf-8")
    print(f"\n[wrote spec to {out_path}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
