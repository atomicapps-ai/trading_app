"""Double Bottom / Double Top detector.

Pattern: two swing lows (or highs) at approximately the same price
level, separated by a meaningful bounce, with a breakout of the
neckline as the trigger.

Bullish (double bottom) — spec:
  * First low forms after a downtrend of ≥ 15% from a prior swing high.
  * Second low within ±3% of the first (``second_low_tolerance_pct``),
    does NOT close below the first by more than 0.5%.
  * Time between lows: 10–60 bars.
  * Neckline = the highest bar between the two lows.
  * Trigger: current close breaks above the neckline.
  * RSI divergence at L2 (RSI at L2 > RSI at L1 by ≥ ``rsi_divergence_min_diff``)
    is the most important confirmation — pattern still valid without it,
    but at a PQS penalty.
  * Breakout volume should be ≥ ``breakout_volume_ratio_min``.

Pure function of (daily, hourly, config, as_of_ts).
"""
from __future__ import annotations

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

PATTERN_NAME = "double_bottom_top"


def _try_bullish(
    window: pd.DataFrame, config_thresh: dict, macro: dict | None,
) -> PatternResult | None:
    min_prior_down_pct = float(config_thresh.get("prior_downtrend_min_pct", 15.0))
    tol_pct = float(config_thresh.get("second_low_tolerance_pct", 3.0))
    rsi_min_diff = float(config_thresh.get("rsi_divergence_min_diff", 3.0))
    vol_min = float(config_thresh.get("breakout_volume_ratio_min", 1.5))

    lows_idx = swing_low_indices(window["low"])
    if len(lows_idx) < 2:
        return None

    l1 = lows_idx[-2]
    l2 = lows_idx[-1]
    if not (10 <= (l2 - l1) <= 60):
        return None

    p1 = float(window["low"].iloc[l1])
    p2 = float(window["low"].iloc[l2])
    neckline = float(window["high"].iloc[l1:l2 + 1].max())

    # Same-price check (within tolerance) + second low doesn't undercut first
    if abs(p2 - p1) / max(p1, 1e-6) * 100.0 > tol_pct:
        return None
    close_at_l2 = float(window["close"].iloc[l2])
    if close_at_l2 < p1 * 0.995:  # >0.5% undercut = invalidation
        return None

    # Prior downtrend from some peak before L1 — look back 60 bars max
    peak_search_start = max(0, l1 - 60)
    if peak_search_start >= l1:
        return None
    prior_peak = float(window["high"].iloc[peak_search_start:l1].max())
    downtrend_pct = (prior_peak - p1) / prior_peak * 100.0 if prior_peak > 0 else 0
    if downtrend_pct < min_prior_down_pct:
        return None

    # Trigger: latest close > neckline
    last_close = float(window["close"].iloc[-1])
    if last_close <= neckline:
        return None

    # Volume on trigger bar
    last = window.iloc[-1]
    volume_ratio = safe(last, "volume_ratio")
    if pd.isna(volume_ratio) or volume_ratio < vol_min:
        return None

    # RSI divergence check (confirmation, not requirement)
    r1 = safe(window.iloc[l1], "rsi_14")
    r2 = safe(window.iloc[l2], "rsi_14")
    has_rsi_divergence = (
        not (pd.isna(r1) or pd.isna(r2)) and (r2 - r1) >= rsi_min_diff
    )

    atr = safe(last, "atr_14")
    if pd.isna(atr) or atr <= 0:
        return None

    # Levels
    lower_low = min(p1, p2)
    stop = lower_low - 0.15 * atr
    pattern_height = neckline - (p1 + p2) / 2.0
    if pattern_height <= 0 or last_close - stop <= 0.01:
        return None
    tp1 = neckline + pattern_height * 0.75
    tp2 = neckline + pattern_height * 1.00

    pqs_base = 58
    modifiers: dict[str, int] = {
        "neckline_break": 10,
        "prior_downtrend": min(10, int(downtrend_pct / 5)),
    }
    if has_rsi_divergence:
        modifiers["rsi_divergence"] = 15
    else:
        modifiers["no_rsi_divergence"] = -15
    if abs(p2 - p1) / max(p1, 1e-6) * 100.0 <= 1.0:
        modifiers["precise_retest"] = 8

    apply_universal_modifiers(
        modifiers, row=last, direction="long", macro_context=macro,
    )
    pqs_total = cap_pqs(pqs_base, modifiers)

    return PatternResult(
        pattern_name=PATTERN_NAME,
        direction="long",
        pqs_base=pqs_base,
        pqs_modifiers=modifiers,
        pqs_total=pqs_total,
        entry_price=round(last_close, 2),
        stop_price=round(stop, 2),
        tp1_price=round(tp1, 2),
        tp2_price=round(tp2, 2),
        invalidation_level=round(stop, 2),
        invalidation_condition="daily_close_below_lower_of_two_lows",
        evidence_items=[
            {"type": "pattern",
             "ref": f"double bottom: L1={p1:.2f}, L2={p2:.2f}, spacing {l2 - l1} bars"},
            {"type": "pattern",
             "ref": f"neckline {neckline:.2f}, pattern height {pattern_height:.2f}"},
            {"type": "pattern",
             "ref": f"prior downtrend {downtrend_pct:.1f}% from peak {prior_peak:.2f}"},
            {"type": "indicator",
             "ref": (f"RSI divergence confirmed ({r1:.1f}->{r2:.1f})"
                      if has_rsi_divergence else "no RSI divergence (-15 PQS)")},
            {"type": "indicator",
             "ref": f"breakout volume {volume_ratio:.2f}×"},
        ],
    )


def _try_bearish(
    window: pd.DataFrame, config_thresh: dict, macro: dict | None,
) -> PatternResult | None:
    # Mirror of bullish — same thresholds, just inverted
    min_prior_up_pct = float(config_thresh.get("prior_downtrend_min_pct", 15.0))
    tol_pct = float(config_thresh.get("second_low_tolerance_pct", 3.0))
    rsi_min_diff = float(config_thresh.get("rsi_divergence_min_diff", 3.0))
    vol_min = float(config_thresh.get("breakout_volume_ratio_min", 1.5))

    highs_idx = swing_high_indices(window["high"])
    if len(highs_idx) < 2:
        return None

    h1, h2 = highs_idx[-2], highs_idx[-1]
    if not (10 <= (h2 - h1) <= 60):
        return None

    p1 = float(window["high"].iloc[h1])
    p2 = float(window["high"].iloc[h2])
    neckline = float(window["low"].iloc[h1:h2 + 1].min())

    if abs(p2 - p1) / max(p1, 1e-6) * 100.0 > tol_pct:
        return None
    close_at_h2 = float(window["close"].iloc[h2])
    if close_at_h2 > p1 * 1.005:
        return None

    peak_search_start = max(0, h1 - 60)
    if peak_search_start >= h1:
        return None
    prior_low = float(window["low"].iloc[peak_search_start:h1].min())
    uptrend_pct = (p1 - prior_low) / prior_low * 100.0 if prior_low > 0 else 0
    if uptrend_pct < min_prior_up_pct:
        return None

    last_close = float(window["close"].iloc[-1])
    if last_close >= neckline:
        return None

    last = window.iloc[-1]
    volume_ratio = safe(last, "volume_ratio")
    if pd.isna(volume_ratio) or volume_ratio < vol_min:
        return None

    r1 = safe(window.iloc[h1], "rsi_14")
    r2 = safe(window.iloc[h2], "rsi_14")
    has_rsi_divergence = (
        not (pd.isna(r1) or pd.isna(r2)) and (r1 - r2) >= rsi_min_diff
    )

    atr = safe(last, "atr_14")
    if pd.isna(atr) or atr <= 0:
        return None

    higher_high = max(p1, p2)
    stop = higher_high + 0.15 * atr
    pattern_height = (p1 + p2) / 2.0 - neckline
    if pattern_height <= 0 or stop - last_close <= 0.01:
        return None
    tp1 = neckline - pattern_height * 0.75
    tp2 = neckline - pattern_height * 1.00

    pqs_base = 58
    modifiers: dict[str, int] = {
        "neckline_break": 10,
        "prior_uptrend": min(10, int(uptrend_pct / 5)),
    }
    if has_rsi_divergence:
        modifiers["rsi_divergence"] = 15
    else:
        modifiers["no_rsi_divergence"] = -15

    apply_universal_modifiers(
        modifiers, row=last, direction="short", macro_context=macro,
    )
    pqs_total = cap_pqs(pqs_base, modifiers)

    return PatternResult(
        pattern_name=PATTERN_NAME,
        direction="short",
        pqs_base=pqs_base,
        pqs_modifiers=modifiers,
        pqs_total=pqs_total,
        entry_price=round(last_close, 2),
        stop_price=round(stop, 2),
        tp1_price=round(tp1, 2),
        tp2_price=round(tp2, 2),
        invalidation_level=round(stop, 2),
        invalidation_condition="daily_close_above_higher_of_two_highs",
        evidence_items=[
            {"type": "pattern",
             "ref": f"double top: H1={p1:.2f}, H2={p2:.2f}, spacing {h2 - h1} bars"},
            {"type": "pattern",
             "ref": f"neckline {neckline:.2f}, pattern height {pattern_height:.2f}"},
        ],
    )


def detect_double_bottom_top(
    daily: pd.DataFrame,
    hourly: pd.DataFrame,
    config: dict,
    as_of_ts: pd.Timestamp,
    macro_context: dict | None = None,
) -> PatternResult | None:
    daily = slice_as_of(daily, as_of_ts)
    if len(daily) < 100:
        return None

    thresholds = (config.get("pattern_thresholds") or {}).get("double_bottom", {})
    window = daily.tail(120).copy().reset_index(drop=False)

    bull = _try_bullish(window, thresholds, macro_context)
    bear = _try_bearish(window, thresholds, macro_context)
    if bull and bear:
        return bull if bull.pqs_total >= bear.pqs_total else bear
    return bull or bear
