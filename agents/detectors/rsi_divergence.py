"""RSI Divergence detector (bullish and bearish).

Bullish divergence:
  * Price makes a lower low (two distinct swing lows, L2 < L1).
  * RSI makes a higher low at the same two points (R2 > R1).
  * RSI at L1 is ≤ ~40 so the divergence is in oversold territory.
  * Trigger fires when the current close breaks above the swing high
    between L1 and L2 (the "neckline").

Bearish mirror: price makes a higher high, RSI makes a lower high,
trigger on break below the swing low between H1 and H2.

PQS classes (spec):
  A — RSI at L2 ≤ 30 (strong / oversold)   base+18
  B — RSI at L2 in (30, 40]                 base
  C — RSI at L2 > 40                        base-10

Pure function of (daily, hourly, config, as_of_ts). No clock, no I/O.
"""
from __future__ import annotations

import pandas as pd

from agents.detectors._helpers import (
    apply_universal_modifiers,
    cap_pqs,
    last_row,
    safe,
    slice_as_of,
)
from models.pattern import PatternResult

PATTERN_NAME = "rsi_divergence"


def _swing_low_index(lows: pd.Series, left: int = 2, right: int = 2) -> list[int]:
    """Indices of swing lows: a bar lower than ``left`` bars before and
    ``right`` bars after. Pure function of the series."""
    out: list[int] = []
    vals = lows.values
    n = len(vals)
    for i in range(left, n - right):
        v = vals[i]
        if all(vals[i - k] > v for k in range(1, left + 1)) and \
           all(vals[i + k] > v for k in range(1, right + 1)):
            out.append(i)
    return out


def _swing_high_index(highs: pd.Series, left: int = 2, right: int = 2) -> list[int]:
    out: list[int] = []
    vals = highs.values
    n = len(vals)
    for i in range(left, n - right):
        v = vals[i]
        if all(vals[i - k] < v for k in range(1, left + 1)) and \
           all(vals[i + k] < v for k in range(1, right + 1)):
            out.append(i)
    return out


def detect_rsi_divergence(
    daily: pd.DataFrame,
    hourly: pd.DataFrame,
    config: dict,
    as_of_ts: pd.Timestamp,
    macro_context: dict | None = None,
) -> PatternResult | None:
    daily = slice_as_of(daily, as_of_ts)
    if len(daily) < 60:
        return None

    thresholds = (config.get("pattern_thresholds") or {}).get("rsi_divergence", {})
    min_rsi_diff = float(thresholds.get("min_rsi_diff", 3.0))
    max_rsi_at_low = float(thresholds.get("max_rsi_at_low", 40.0))
    class_a_ceiling = float(thresholds.get("class_a_rsi_ceiling", 30.0))

    # Limit search window to last 60 bars so we only look at fresh setups.
    window = daily.tail(60).copy()
    window = window.reset_index(drop=False)
    if "rsi_14" not in window.columns or window["rsi_14"].isna().all():
        return None

    last_close = float(window["close"].iloc[-1])
    atr = safe(window.iloc[-1], "atr_14")
    if pd.isna(atr) or atr <= 0:
        return None

    # ---- Bullish divergence search --------------------------------------
    lows_idx = _swing_low_index(window["low"])
    bull: PatternResult | None = None
    if len(lows_idx) >= 2:
        l2 = lows_idx[-1]
        l1 = lows_idx[-2]
        # Require at least 5 bars between the two lows; window cap enforces max ~50
        if 5 <= (l2 - l1) <= 50:
            p1 = float(window["low"].iloc[l1])
            p2 = float(window["low"].iloc[l2])
            r1 = float(window["rsi_14"].iloc[l1])
            r2 = float(window["rsi_14"].iloc[l2])
            if not (pd.isna(r1) or pd.isna(r2)):
                price_lower = p2 < p1
                rsi_higher = (r2 - r1) >= min_rsi_diff
                rsi_oversold_context = r1 <= max_rsi_at_low
                if price_lower and rsi_higher and rsi_oversold_context:
                    neckline = float(window["high"].iloc[l1:l2 + 1].max())
                    if last_close > neckline:
                        # Classify divergence strength
                        if r2 <= class_a_ceiling:
                            pqs_base, cls_bonus = 52, 18
                            cls = "A"
                        elif r2 <= 40.0:
                            pqs_base, cls_bonus = 52, 0
                            cls = "B"
                        else:
                            pqs_base, cls_bonus = 52, -10
                            cls = "C"
                        entry = last_close
                        stop = p2 - 0.1 * atr
                        if entry - stop > 0:
                            tp1 = neckline + (neckline - p2) * 0.5
                            tp2 = neckline + (neckline - p2) * 1.0
                            modifiers: dict[str, int] = {
                                f"divergence_class_{cls}": cls_bonus,
                                "neckline_break": 8,
                            }
                            apply_universal_modifiers(
                                modifiers, row=window.iloc[-1], direction="long",
                                macro_context=macro_context,
                            )
                            pqs_total = cap_pqs(pqs_base, modifiers)
                            bull = PatternResult(
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
                                invalidation_condition="daily_close_below_second_low",
                                evidence_items=[
                                    {"type": "pattern",
                                     "ref": f"bullish RSI divergence class {cls}: "
                                            f"price {p1:.2f}->{p2:.2f}, RSI {r1:.1f}->{r2:.1f}"},
                                    {"type": "pattern",
                                     "ref": f"neckline break at {neckline:.2f}, close {last_close:.2f}"},
                                ],
                            )

    # ---- Bearish divergence search --------------------------------------
    highs_idx = _swing_high_index(window["high"])
    bear: PatternResult | None = None
    if len(highs_idx) >= 2:
        h2 = highs_idx[-1]
        h1 = highs_idx[-2]
        if 5 <= (h2 - h1) <= 50:
            p1 = float(window["high"].iloc[h1])
            p2 = float(window["high"].iloc[h2])
            r1 = float(window["rsi_14"].iloc[h1])
            r2 = float(window["rsi_14"].iloc[h2])
            if not (pd.isna(r1) or pd.isna(r2)):
                price_higher = p2 > p1
                rsi_lower = (r1 - r2) >= min_rsi_diff
                rsi_overbought_context = r1 >= (100 - max_rsi_at_low)  # symmetric
                if price_higher and rsi_lower and rsi_overbought_context:
                    neckline = float(window["low"].iloc[h1:h2 + 1].min())
                    if last_close < neckline:
                        if r2 >= (100 - class_a_ceiling):
                            pqs_base, cls_bonus, cls = 52, 18, "A"
                        elif r2 >= 60.0:
                            pqs_base, cls_bonus, cls = 52, 0, "B"
                        else:
                            pqs_base, cls_bonus, cls = 52, -10, "C"
                        entry = last_close
                        stop = p2 + 0.1 * atr
                        if stop - entry > 0:
                            tp1 = neckline - (p2 - neckline) * 0.5
                            tp2 = neckline - (p2 - neckline) * 1.0
                            modifiers_b: dict[str, int] = {
                                f"divergence_class_{cls}": cls_bonus,
                                "neckline_break": 8,
                            }
                            apply_universal_modifiers(
                                modifiers_b, row=window.iloc[-1], direction="short",
                                macro_context=macro_context,
                            )
                            pqs_total_b = cap_pqs(pqs_base, modifiers_b)
                            bear = PatternResult(
                                pattern_name=PATTERN_NAME,
                                direction="short",
                                pqs_base=pqs_base,
                                pqs_modifiers=modifiers_b,
                                pqs_total=pqs_total_b,
                                entry_price=round(entry, 2),
                                stop_price=round(stop, 2),
                                tp1_price=round(tp1, 2),
                                tp2_price=round(tp2, 2),
                                invalidation_level=round(stop, 2),
                                invalidation_condition="daily_close_above_second_high",
                                evidence_items=[
                                    {"type": "pattern",
                                     "ref": f"bearish RSI divergence class {cls}: "
                                            f"price {p1:.2f}->{p2:.2f}, RSI {r1:.1f}->{r2:.1f}"},
                                    {"type": "pattern",
                                     "ref": f"neckline break at {neckline:.2f}, close {last_close:.2f}"},
                                ],
                            )

    # Prefer the higher-PQS side if both fire (rare on the same day).
    if bull and bear:
        return bull if bull.pqs_total >= bear.pqs_total else bear
    return bull or bear
