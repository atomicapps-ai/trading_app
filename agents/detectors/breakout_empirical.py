"""Empirical Breakout Precursor detector.

Data-driven detector derived from the distribution of 502 labeled
successful breakouts (50% gain in 120 bars) across a 62-symbol diverse
pool spanning ~20 years. Each threshold below is a percentile of the
winner distribution, not a guess. Full derivation in
`docs/indicators/empirical_breakout.md`.

What the data said when we measured the feature distributions across
winners:
  * There is no single VCP/absorption "pattern." Half of winners had
    ZERO pivot highs within 2% of their anchor price.
  * Volume does not need to dry up. Median winner had vol_ratio ~0.95
    (5% reduction), not the textbook ~0.50.
  * Final contraction does not need to be much tighter than first.
    Median compression is 0.905, barely tightening.
  * Minervini's Trend Template is violated in 10% of winners (SMA50
    below SMA200, or price at 41% of 52w high).
  * Recent 60-day run-up can be negative (P10 = 0.96 means -4%).

What winners DO reliably share, and what this detector therefore
enforces as HARD gates:
  * Price is above SMA50 (close/sma50 >= 1.01, P10 of winners).
  * RSI is in "healthy" zone [50, 68] (P10-P90 band).
  * Recent consolidation is tight (max_dd_base <= 25%).
  * Some swing structure exists (>= 5 contraction pairs in 180 bars).
  * The "base" has lasted at least 24 bars (P10 of winners).

Additionally, each event is SCORED 0-100 based on how close each
feature is to the WINNER MEDIAN (not just "inside P10-P90"). High
score = very typical winner setup; low score (but still passing the
hard gates) = edge-case winner.

Pure function of (daily, hourly, config, as_of_ts). Hourly is ignored
— this pattern is daily-only in v1.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from agents.detectors._helpers import (
    apply_universal_modifiers,
    cap_pqs,
    safe,
    slice_as_of,
    swing_high_indices,
    swing_low_indices,
)
from models.pattern import PatternResult

PATTERN_NAME = "breakout_empirical"

LOOKBACK = 180  # matches Stage-2 measurement window

# --------------------------------------------------------------------------- #
# Empirical feature distribution of 502 labeled winners (50% in 120b).
# Every number below is a PERCENTILE of the winner distribution — direct
# output of scripts/distribution_analysis.py against 502 anchor dates.
# Do NOT edit these by intuition; re-run the analysis to update.
# --------------------------------------------------------------------------- #

# Hard gates: event is REJECTED if any bound is violated.
# Direction: "higher" → feature must be >= bound. "lower" → <= bound.
# "range" → must be within [lo, hi].
#
# All numbers below come from `data/threshold_spec.md` after the
# tz-bar-matching fix. Re-run the distribution_analysis pipeline to
# regenerate the spec if the labeled event pool changes.
GATES: dict[str, tuple[str, float, float]] = {
    #                       direction, lower, upper (or unused sentinel)
    #
    # The labeling criterion itself — every labeled winner was at
    # >= 98% of its 60-day max. Gate REQUIRED or the detector fires
    # on mid-trend bars that meet feature criteria but aren't at a
    # breakout-eligible position.
    "pct_of_60d_high":     ("higher", 0.98, math.inf),

    "close_vs_sma50":      ("higher", 1.053, math.inf),  # P10 winner floor
    "rsi_14":              ("range",  59.17, 71.74),     # P10-P90 band — shifted
                                                           # up vs pre-fix spec
                                                           # (breakouts happen on
                                                           # stronger momentum days
                                                           # than the bar before)
    "max_dd_base":         ("lower",  -math.inf, 0.247), # recent consolidation tight
    "base_len_25pct":      ("range",  12.0,  180.0),     # P10 widened to 12 — elite
                                                           # winners often have short
                                                           # tight bases
    "n_contraction_pairs": ("higher", 5.0,   math.inf),  # P10 structure floor
    # Note: tried `anchor_upper_wick <= 0.88` here in v1.1 but it
    # over-filtered legitimate gap-up winners (ASML, COP, EOG, TSM,
    # XOM all dropped 30-50pp capture). Removed. Upper wick is now
    # only a SCORE feature, not a gate.
}

# Winner distribution used for scoring — (P10, P25, P50, P75, P90)
# A score of 100 sits at the P50 (median winner). Scoring drops
# linearly to 50 at P10/P90, and to 0 at twice the P10-P90 half-width.
# Numbers sourced directly from `data/threshold_spec.md` (post-fix).
WINNER_MEDIANS: dict[str, tuple[float, float, float, float, float]] = {
    "close_vs_sma50":      (1.053, 1.072, 1.118, 1.188, 1.290),
    "close_vs_sma200":     (0.949, 1.066, 1.201, 1.349, 1.571),
    "sma50_vs_sma200":     (0.786, 0.953, 1.086, 1.187, 1.349),
    "rsi_14":              (59.17, 61.60, 64.46, 67.92, 71.74),
    "max_dd_base":         (0.170, 0.213, 0.233, 0.243, 0.247),
    "max_dd_180":          (0.220, 0.301, 0.398, 0.515, 0.640),
    "base_len_25pct":      (12.0,  32.2,  63.5,  125.0, 180.0),
    "n_contraction_pairs": (5.0,   7.0,   8.0,   9.0,   10.0),
    # Touch counts — added v1.3 after winner-vs-random analysis showed
    # touches_within_5pct has d=+0.504 (winners 2 vs random 1).
    "touches_within_2pct": (0.0,   0.0,   1.0,   2.0,   3.0),
    "touches_within_5pct": (0.0,   1.0,   2.0,   4.0,   5.0),
    "first_depth_pct":     (0.055, 0.090, 0.138, 0.216, 0.358),
    "final_depth_pct":     (0.061, 0.088, 0.127, 0.181, 0.256),
    "compression":         (0.400, 0.584, 0.901, 1.366, 1.932),
    "vol_ratio_30_180":    (0.687, 0.806, 0.958, 1.142, 1.484),
    "anchor_vol_vs_avg":   (0.675, 0.859, 1.175, 1.812, 3.191),
    "pct_of_52w_high":     (0.457, 0.659, 0.877, 0.968, 0.984),
    "pct_above_52w_low":   (0.257, 0.482, 0.828, 1.420, 2.526),
    "run_up_60":           (1.015, 1.058, 1.162, 1.327, 1.578),
    "run_up_180":          (0.769, 1.001, 1.316, 1.648, 2.248),

    # Phase 1 additions — cross-set deltas indicate real signal.
    # P10/P25 are 0.0 for some features (post-clip artifact), so the
    # bottom of the score curve is flat below the median.
    "anchor_cpr":          (0.000, 0.000, 0.635, 0.884, 0.972),
    "avg_cpr_20":          (0.000, 0.000, 0.490, 0.544, 0.602),
    "anchor_upper_wick":   (0.020, 0.090, 0.297, 0.595, 0.880),
    "anchor_lower_wick":   (0.000, 0.000, 0.067, 0.234, 0.418),
    "avg_upper_wick_20":   (0.202, 0.248, 0.301, 0.462, 0.543),
    "avg_lower_wick_20":   (0.000, 0.000, 0.232, 0.284, 0.322),
    "up_vol_share_60":     (0.000, 0.096, 0.480, 0.546, 0.601),
    "gap_up_count_60":     (13.0,  19.0,  25.5,  58.0,  60.0),
    "gap_down_count_60":   (0.0,   1.0,   11.0,  17.0,  20.0),
    "largest_gap_up_60":   (0.024, 0.043, 0.081, 0.166, 0.335),
}

# Which features contribute to the score (weights sum to ~1.0). Weighting
# is set by how strongly the cross-set comparison shows that feature
# distinguishes "broad winner" (50%/120b) from "elite winner" (100%/120b).
# Features with large |Δ(elite − broad)| get higher weight; those with
# ~zero delta get minimal weight.
SCORE_WEIGHTS: dict[str, float] = {
    # v1.3 — re-weighted from WINNER-vs-RANDOM Cohen's d (the *correct*
    # discrimination question, not cross-set elite-vs-broad). Features
    # with d >= 0.4 only; everything below was scored as noise in v1.2.
    #
    # Score-function centers on winner P50, so directionality from the
    # comparison script ("wrong dir!") is irrelevant for scoring —
    # bars near winner-median get high scores either way.
    "rsi_14":               0.18,  # d=+1.045 — strongest single signal
    "close_vs_sma50":       0.15,  # d=+0.842
    "anchor_cpr":           0.15,  # d=+0.684 — was massively under-weighted
    "anchor_vol_vs_avg":    0.13,  # d=+0.729
    "base_len_25pct":       0.10,  # d=0.847 (winner short bases vs random saturated)
    "max_dd_180":           0.08,  # d=0.688 (winners had bigger prior pullback)
    "touches_within_5pct":  0.06,  # d=+0.504 — newly-validated discriminator
    "close_vs_sma200":      0.05,  # d=+0.441
    "pct_of_52w_high":      0.05,  # d=+0.436
    "max_dd_base":          0.05,  # d=0.538 (structural)
}
# Dropped from scoring (d < 0.3 — no winner-vs-random separation):
#   anchor_upper_wick (d=-0.06), first_depth_pct (d=0.245),
#   up_vol_share_60 (d=0.297), avg_*_wick_20, gap_*, sma50_slope_60,
#   vol_ratio_30_180, n_contraction_pairs, atr_ratio_*,
#   final_depth_pct, swing_high_count, largest_gap_up_60,
#   pct_above_52w_low. These are still computed for diagnostic
#   inspection but no longer move the score.


# --------------------------------------------------------------------------- #
# Feature computation — mirrors scripts/measure_setup_structure.py exactly
# so the detector's features are IDENTICAL to the features that produced
# the winner distribution we're comparing against.
# --------------------------------------------------------------------------- #


def _compute_features(daily: pd.DataFrame) -> dict[str, float] | None:
    if len(daily) < LOOKBACK:
        return None
    last = daily.iloc[-1]
    close = float(last["close"])
    if close <= 0:
        return None

    window = daily.iloc[-LOOKBACK:]
    closes = window["close"].to_numpy()
    highs = window["high"].to_numpy()
    lows = window["low"].to_numpy()
    vols = window["volume"].to_numpy()

    # Base length at 25% pullback threshold
    def base_len_at(threshold: float) -> int:
        tgt = close * (1.0 - threshold)
        for k in range(1, len(closes) + 1):
            if closes[-k] < tgt:
                return k - 1
        return len(closes)

    base_len_25 = base_len_at(0.25)
    base_len_15 = base_len_at(0.15)
    base_len_10 = base_len_at(0.10)

    # Drawdowns
    min_180 = float(closes.min())
    max_dd_180 = (close - min_180) / close
    if base_len_25 > 0:
        max_dd_base = (close - float(closes[-base_len_25:].min())) / close
    else:
        max_dd_base = 0.0

    # Pivots
    ph_idx = swing_high_indices(pd.Series(highs), 5, 5)
    pl_idx = swing_low_indices(pd.Series(lows), 5, 5)
    swing_high_count = len(ph_idx)

    # Contraction pairs
    depths = []
    for i, ph_i in enumerate(ph_idx):
        next_ph_i = ph_idx[i + 1] if i + 1 < len(ph_idx) else 10 ** 9
        for pl_i in pl_idx:
            if pl_i > ph_i and pl_i < next_ph_i:
                ph = highs[ph_i]
                pl = lows[pl_i]
                if ph > 0:
                    depths.append((ph - pl) / ph)
                break
    first_depth = depths[0] if depths else float("nan")
    final_depth = depths[-1] if depths else float("nan")
    compression = (final_depth / first_depth) if (depths and first_depth > 0) else float("nan")
    n_pairs = len(depths)

    # Touches near current close
    touches_2 = sum(1 for i in ph_idx if abs(highs[i] - close) / close <= 0.02)
    touches_5 = sum(1 for i in ph_idx if abs(highs[i] - close) / close <= 0.05)

    # Volatility
    atr_now = safe(last, "atr_14")
    atr_pct = (atr_now / close) if atr_now > 0 else float("nan")
    atr_180_ago = float(daily["atr_14"].iloc[-LOOKBACK]) if len(daily) >= LOOKBACK else float("nan")
    atr_60_ago = float(daily["atr_14"].iloc[-60]) if len(daily) >= 60 else float("nan")
    atr_ratio_180 = (atr_now / atr_180_ago) if atr_180_ago > 0 else float("nan")
    atr_ratio_60 = (atr_now / atr_60_ago) if atr_60_ago > 0 else float("nan")

    # Volume
    vol_avg_30 = float(pd.Series(vols[-30:]).mean())
    vol_avg_180 = float(pd.Series(vols).mean())
    vol_avg_50 = float(daily["volume"].iloc[-50:].mean()) if len(daily) >= 50 else float("nan")
    vol_ratio_30_180 = (vol_avg_30 / vol_avg_180) if vol_avg_180 > 0 else float("nan")
    anchor_vol = float(last["volume"])
    anchor_vol_vs_avg = (anchor_vol / vol_avg_50) if vol_avg_50 > 0 else float("nan")

    # Trend context
    sma50 = safe(last, "sma_50")
    sma200 = safe(last, "sma_200")
    close_vs_sma50 = (close / sma50) if sma50 > 0 else float("nan")
    close_vs_sma200 = (close / sma200) if sma200 > 0 else float("nan")
    sma50_vs_sma200 = (sma50 / sma200) if (sma50 > 0 and sma200 > 0) else float("nan")

    # 52-week positioning
    if len(daily) >= 252:
        hi52 = float(daily["high"].iloc[-252:].max())
        lo52 = float(daily["low"].iloc[-252:].min())
    else:
        hi52 = float(daily["high"].max())
        lo52 = float(daily["low"].min())
    pct_of_52w_high = (close / hi52) if hi52 > 0 else float("nan")

    # 60-day high positioning (matches the labeling criterion in
    # scripts/label_breakouts.py — required for breakout eligibility).
    if len(daily) >= 60:
        hi60 = float(daily["close"].iloc[-60:].max())
    else:
        hi60 = float(daily["close"].max())
    pct_of_60d_high = (close / hi60) if hi60 > 0 else float("nan")

    # Run-up
    c_60 = float(daily["close"].iloc[-60]) if len(daily) >= 60 else float("nan")
    c_180 = float(daily["close"].iloc[-LOOKBACK]) if len(daily) >= LOOKBACK else float("nan")
    run_up_60 = (close / c_60) if c_60 > 0 else float("nan")
    run_up_180 = (close / c_180) if c_180 > 0 else float("nan")

    # RSI
    rsi = safe(last, "rsi_14")

    # ── Phase 1 bar-derived features (mirror measure_setup_structure.py) ──
    # Wick geometry, close-position-in-range, gaps, up-vol share.
    # Clipped to [0,1] same as measurement script (handles auto-adjust
    # rounding artifacts in old data).
    opens_arr = window["open"].to_numpy()
    ranges_arr = highs - lows
    safe_ranges = np.where(ranges_arr > 0, ranges_arr, np.nan)

    upper_wicks = highs - np.maximum(opens_arr, closes)
    lower_wicks = np.minimum(opens_arr, closes) - lows
    upper_wick_ratios = np.clip(
        np.where(ranges_arr > 0, upper_wicks / safe_ranges, 0.0), 0.0, 1.0,
    )
    lower_wick_ratios = np.clip(
        np.where(ranges_arr > 0, lower_wicks / safe_ranges, 0.0), 0.0, 1.0,
    )
    anchor_upper_wick = float(upper_wick_ratios[-1])
    anchor_lower_wick = float(lower_wick_ratios[-1])
    avg_upper_wick_20 = float(np.nanmean(upper_wick_ratios[-20:]))
    avg_lower_wick_20 = float(np.nanmean(lower_wick_ratios[-20:]))

    cpr_arr = np.clip(
        np.where(ranges_arr > 0, (closes - lows) / safe_ranges, 0.5), 0.0, 1.0,
    )
    anchor_cpr = float(cpr_arr[-1])
    avg_cpr_20 = float(np.nanmean(cpr_arr[-20:]))

    # Gap analysis over last 60 bars
    if len(opens_arr) >= 61:
        prior_closes_60 = closes[-61:-1]
        cur_opens_60 = opens_arr[-60:]
        gap_pcts = (cur_opens_60 - prior_closes_60) / prior_closes_60
        gap_up_count_60 = int(np.sum(gap_pcts > 0.005))
        gap_down_count_60 = int(np.sum(gap_pcts < -0.005))
        largest_gap_up_60 = float(np.max(gap_pcts))
    else:
        gap_up_count_60 = 0
        gap_down_count_60 = 0
        largest_gap_up_60 = 0.0

    # Up-vol share over last 60 bars
    up_mask_60 = closes[-60:] > opens_arr[-60:]
    total_vol_60 = float(vols[-60:].sum())
    up_vol_share_60 = (
        float(vols[-60:][up_mask_60].sum() / total_vol_60)
        if total_vol_60 > 0 else 0.5
    )

    return {
        "close":                 close,
        "atr_14":                atr_now,
        "base_len_25pct":        float(base_len_25),
        "base_len_15pct":        float(base_len_15),
        "base_len_10pct":        float(base_len_10),
        "max_dd_180":            max_dd_180,
        "max_dd_base":           max_dd_base,
        "swing_high_count":      float(swing_high_count),
        "touches_within_2pct":   float(touches_2),
        "touches_within_5pct":   float(touches_5),
        "n_contraction_pairs":   float(n_pairs),
        "first_depth_pct":       first_depth,
        "final_depth_pct":       final_depth,
        "compression":           compression,
        "atr_pct":               atr_pct,
        "atr_ratio_now_vs_180":  atr_ratio_180,
        "atr_ratio_now_vs_60":   atr_ratio_60,
        "vol_ratio_30_180":      vol_ratio_30_180,
        "anchor_vol_vs_avg":     anchor_vol_vs_avg,
        "close_vs_sma50":        close_vs_sma50,
        "close_vs_sma200":       close_vs_sma200,
        "sma50_vs_sma200":       sma50_vs_sma200,
        "pct_of_52w_high":       pct_of_52w_high,
        "pct_of_60d_high":       pct_of_60d_high,
        "rsi_14":                rsi,
        "run_up_60":             run_up_60,
        "run_up_180":            run_up_180,
        "pct_above_52w_low":     ((close - lo52) / lo52) if lo52 > 0 else float("nan"),
        # Phase 1 additions
        "anchor_upper_wick":     anchor_upper_wick,
        "anchor_lower_wick":     anchor_lower_wick,
        "avg_upper_wick_20":     avg_upper_wick_20,
        "avg_lower_wick_20":     avg_lower_wick_20,
        "anchor_cpr":            anchor_cpr,
        "avg_cpr_20":            avg_cpr_20,
        "gap_up_count_60":       float(gap_up_count_60),
        "gap_down_count_60":     float(gap_down_count_60),
        "largest_gap_up_60":     largest_gap_up_60,
        "up_vol_share_60":       up_vol_share_60,
        "_base_low":             float(closes[-max(1, base_len_25):].min()),
    }


def _check_gates(features: dict[str, float]) -> tuple[bool, list[str]]:
    """Evaluate each hard gate. Returns (all_passed, list_of_failed)."""
    failed: list[str] = []
    for name, (direction, lo, hi) in GATES.items():
        v = features.get(name, float("nan"))
        if math.isnan(v):
            failed.append(f"{name}=NaN")
            continue
        if direction == "higher" and v < lo:
            failed.append(f"{name}={v:.3f}<{lo}")
        elif direction == "lower" and v > hi:
            failed.append(f"{name}={v:.3f}>{hi}")
        elif direction == "range" and not (lo <= v <= hi):
            failed.append(f"{name}={v:.3f}!∈[{lo},{hi}]")
    return (len(failed) == 0, failed)


def _feature_score(value: float, p10: float, p25: float, p50: float,
                    p75: float, p90: float) -> float:
    """Score a single feature's closeness to the winner median.
    100 at P50, 75 at P25/P75, 50 at P10/P90, 0 outside the P10-P90 band
    by more than one half-width. Piecewise linear — keeps the math
    transparent and defensible (no tunable fudge factors).
    """
    if math.isnan(value) or p90 <= p10:
        return 0.0
    if value <= p10 or value >= p90:
        # Linear fall to 0 at double-distance outside the band
        half = (p90 - p10) / 2.0
        if half <= 0:
            return 0.0
        if value < p10:
            return max(0.0, 50.0 * (1.0 - (p10 - value) / half))
        return max(0.0, 50.0 * (1.0 - (value - p90) / half))
    if value <= p25:
        return 50.0 + 25.0 * (value - p10) / max(1e-9, p25 - p10)
    if value <= p50:
        return 75.0 + 25.0 * (value - p25) / max(1e-9, p50 - p25)
    if value <= p75:
        return 75.0 + 25.0 * (p75 - value) / max(1e-9, p75 - p50)
    return 50.0 + 25.0 * (p90 - value) / max(1e-9, p90 - p75)


def _total_score(features: dict[str, float]) -> tuple[float, dict[str, float]]:
    """Weighted sum of per-feature scores. Each feature contributes
    its `WEIGHT * closeness-to-median`. Sum is 0-100."""
    per_feature: dict[str, float] = {}
    weighted_sum = 0.0
    total_weight = 0.0
    for feat, weight in SCORE_WEIGHTS.items():
        v = features.get(feat, float("nan"))
        if math.isnan(v) or feat not in WINNER_MEDIANS:
            continue
        p10, p25, p50, p75, p90 = WINNER_MEDIANS[feat]
        s = _feature_score(v, p10, p25, p50, p75, p90)
        per_feature[feat] = s
        weighted_sum += weight * s
        total_weight += weight
    if total_weight == 0:
        return 0.0, per_feature
    return weighted_sum / total_weight, per_feature


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def detect_breakout_empirical(
    daily: pd.DataFrame,
    hourly: pd.DataFrame | None = None,
    config: dict | None = None,
    as_of_ts: pd.Timestamp | None = None,
    macro_context: dict | None = None,
) -> PatternResult | None:
    """Detect an empirical-winner-profile bar at the last bar of
    ``daily`` (sliced to ``as_of_ts`` if provided).

    Returns PatternResult when ALL hard gates pass AND score >= 50.
    Returns None otherwise. The threshold-50 floor filters out edge-
    case events that barely pass the gates — keeps the detector's
    hit rate manageable without losing typical winners.
    """
    daily = slice_as_of(daily, as_of_ts)
    if len(daily) < LOOKBACK:
        return None

    features = _compute_features(daily)
    if features is None:
        return None

    gates_ok, failed = _check_gates(features)
    if not gates_ok:
        return None

    score, per_feat = _total_score(features)
    min_score = (config or {}).get("pattern_thresholds", {}).get(
        PATTERN_NAME, {}).get("min_score", 50.0)
    if score < min_score:
        return None

    close = features["close"]
    atr = features["atr_14"]
    base_low = features["_base_low"]

    # Trade plan: entry at current close, stop below recent base low,
    # TP sized to the empirical winner median return (50%+ over 120b).
    entry = close
    stop = min(base_low - 0.5 * atr, close * 0.90)  # cap at -10%
    if stop <= 0 or entry - stop < 0.01:
        return None
    r_per_share = entry - stop
    tp1 = entry + 2.0 * r_per_share
    tp2 = entry + 4.0 * r_per_share

    pqs_base = 50
    modifiers: dict[str, int] = {
        "empirical_score": int(round((score - 50) / 2)),  # score 50 -> 0, 100 -> 25
    }
    apply_universal_modifiers(
        modifiers, row=daily.iloc[-1], direction="long", macro_context=macro_context,
    )
    pqs_total = cap_pqs(pqs_base, modifiers)

    # Compact evidence — the full feature dump is attached as a
    # diagnostic block for downstream tools / UIs.
    evidence = [
        {"type": "pattern", "ref": (
            f"empirical score {score:.1f}/100 (min 50)"
        )},
        {"type": "pattern", "ref": (
            f"close/SMA50={features['close_vs_sma50']:.3f}, "
            f"RSI={features['rsi_14']:.1f}, "
            f"base_dd={features['max_dd_base']*100:.1f}%, "
            f"base_len={int(features['base_len_25pct'])}b"
        )},
        {"type": "pattern", "ref": (
            f"contractions={int(features['n_contraction_pairs'])} "
            f"({features['first_depth_pct']*100:.1f}% -> "
            f"{features['final_depth_pct']*100:.1f}%, "
            f"compression {features['compression']:.2f})"
        )},
        {"type": "diagnostic", "ref": {
            "score":        round(score, 2),
            "per_feature":  {k: round(v, 2) for k, v in per_feat.items()},
            "features":     {k: (round(v, 4) if isinstance(v, float) else v)
                             for k, v in features.items() if not k.startswith("_")},
        }},
    ]

    return PatternResult(
        pattern_name=PATTERN_NAME,
        direction="long",
        pqs_base=pqs_base,
        pqs_modifiers=modifiers,
        pqs_total=pqs_total,
        entry_price=round(entry, 2),
        stop_price=round(stop, 2),
        tp1_price=round(tp1, 2),
        tp2_price=round(tp2, 2),
        invalidation_level=round(stop, 2),
        invalidation_condition="daily_close_below_stop",
        evidence_items=evidence,
    )
