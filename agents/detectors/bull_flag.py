"""Bull Flag detector (continuation long setup).

Phases:
  1. FLAGPOLE — a strong, fast advance: from bar ``F-start`` to bar
     ``F-end`` the close rose by at least ``flagpole_min_atr_multiple``
     ATRs over a window of ``[2, 15]`` bars.
  2. FLAG — a sideways / mild pullback consolidation of ``[3, 20]`` bars
     where the deepest low retraces ``[30%, 60%]`` of the flagpole and
     the sequence does NOT make a new low (this would break the flag).
  3. TRIGGER — the most recent bar closes above the flag's highest high
     on volume >= ``trigger_volume_ratio_min`` × 20-bar average.

At trigger, emit the signal. Entry = trigger bar close; stop = flag
low; targets = measured flagpole move projected from the break.

Bear flag is the mirror. This session ships only bull flag — bear flag
lands in the follow-up with the rest of the detectors.

Pure function of (daily, hourly, config, as_of_ts).
"""
from __future__ import annotations

import pandas as pd

from agents.detectors._helpers import (
    apply_universal_modifiers,
    cap_pqs,
    safe,
    slice_as_of,
)
from models.pattern import PatternResult

PATTERN_NAME = "bull_flag"


def detect_bull_flag(
    daily: pd.DataFrame,
    hourly: pd.DataFrame,
    config: dict,
    as_of_ts: pd.Timestamp,
    macro_context: dict | None = None,
) -> PatternResult | None:
    daily = slice_as_of(daily, as_of_ts)
    if len(daily) < 60:
        return None

    thresholds = (config.get("pattern_thresholds") or {}).get("bull_flag", {})
    flagpole_min_atr_multiple = float(thresholds.get("flagpole_min_atr_multiple", 3.0))
    flag_retrace_min = float(thresholds.get("flag_retracement_min_pct", 30.0)) / 100.0
    flag_retrace_max = float(thresholds.get("flag_retracement_max_pct", 60.0)) / 100.0
    flag_min_bars = int(thresholds.get("flag_duration_min_bars", 3))
    flag_max_bars = int(thresholds.get("flag_duration_max_bars", 20))
    trigger_volume_ratio_min = float(thresholds.get("trigger_volume_ratio_min", 1.5))

    last = daily.iloc[-1]
    trigger_close = float(last["close"])
    atr = safe(last, "atr_14")
    if pd.isna(atr) or atr <= 0:
        return None
    volume_ratio = safe(last, "volume_ratio")
    if pd.isna(volume_ratio) or volume_ratio < trigger_volume_ratio_min:
        return None

    # Scan candidate flag windows ending at N-1 (last bar is the trigger).
    # For each flag length L in [flag_min_bars..flag_max_bars], the flag
    # is bars [N-1-L .. N-2]. The flagpole is the [2..15] bars ending
    # immediately before the flag begins.
    best: PatternResult | None = None
    best_pqs = -1

    for flag_len in range(flag_min_bars, flag_max_bars + 1):
        if len(daily) < flag_len + 15 + 1:
            break
        flag_end_i = len(daily) - 2  # inclusive
        flag_start_i = flag_end_i - flag_len + 1
        if flag_start_i < 15:
            continue

        flag = daily.iloc[flag_start_i : flag_end_i + 1]
        flag_high = float(flag["high"].max())
        flag_low = float(flag["low"].min())

        if trigger_close <= flag_high:
            continue  # not a breakout (yet)

        # Flagpole search — look back from flag_start_i for a 2-15 bar
        # move whose cumulative close gain hits the ATR threshold.
        for pole_len in range(2, 16):
            pole_start_i = flag_start_i - pole_len
            if pole_start_i < 0:
                break
            pole_start = daily.iloc[pole_start_i]
            pole_end = daily.iloc[flag_start_i - 1]
            pole_gain = float(pole_end["close"]) - float(pole_start["close"])
            if pole_gain < flagpole_min_atr_multiple * atr:
                continue

            # Flag retracement check
            pole_range = pole_gain
            if pole_range <= 0:
                continue
            retrace = (float(pole_end["high"]) - flag_low) / pole_range
            if not (flag_retrace_min <= retrace <= flag_retrace_max):
                continue

            # Flag must not take out the pole start low — that's a failed pole
            if flag_low <= float(pole_start["low"]):
                continue

            # Levels
            entry_price = trigger_close
            stop_price = flag_low
            measured_move = pole_gain
            tp1 = entry_price + measured_move * 0.5
            tp2 = entry_price + measured_move
            invalidation_level = flag_low
            invalidation_condition = "daily_close_below_flag_low"

            if abs(entry_price - stop_price) < 0.01:
                continue

            pqs_base = 55
            modifiers: dict[str, int] = {
                "flagpole_magnitude": min(
                    15, int((pole_gain / atr - flagpole_min_atr_multiple) * 3) + 5
                ),
                "breakout_volume": min(10, int((volume_ratio - 1.5) * 10) + 5),
                "retrace_depth": 5 if 0.38 <= retrace <= 0.5 else 3,
            }
            apply_universal_modifiers(
                modifiers, row=last, direction="long", macro_context=macro_context,
            )
            pqs_total = cap_pqs(pqs_base, modifiers)

            if pqs_total > best_pqs:
                evidence = [
                    {"type": "pattern", "ref": (
                        f"flagpole {pole_len}b: +{pole_gain:.2f} "
                        f"({pole_gain/atr:.1f} ATR)"
                    )},
                    {"type": "pattern", "ref": (
                        f"flag {flag_len}b: retrace {retrace*100:.0f}% of pole, "
                        f"low {flag_low:.2f}"
                    )},
                    {"type": "pattern", "ref": (
                        f"breakout: close {trigger_close:.2f} > flag_high "
                        f"{flag_high:.2f} on {volume_ratio:.1f}x volume"
                    )},
                ]
                best = PatternResult(
                    pattern_name=PATTERN_NAME,
                    direction="long",
                    pqs_base=pqs_base,
                    pqs_modifiers=modifiers,
                    pqs_total=pqs_total,
                    entry_price=round(entry_price, 2),
                    stop_price=round(stop_price, 2),
                    tp1_price=round(tp1, 2),
                    tp2_price=round(tp2, 2),
                    invalidation_level=round(invalidation_level, 2),
                    invalidation_condition=invalidation_condition,
                    evidence_items=evidence,
                )
                best_pqs = pqs_total

    return best
