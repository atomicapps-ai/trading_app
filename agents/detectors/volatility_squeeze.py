"""Volatility Squeeze (TTM Squeeze) detector.

Pattern: Bollinger Bands compress inside Keltner Channels (low volatility)
and then release, with the first bar out of the squeeze accompanied by a
momentum histogram turn. Entry is on the fire bar; stop is the opposite
end of the squeeze range; targets are ATR-based.

Indicator service already computes ``squeeze_on`` / ``squeeze_fired`` /
``momentum`` (TTM-style histogram). This detector consumes those columns.

Pure function of (daily, hourly, config, as_of_ts).
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

PATTERN_NAME = "volatility_squeeze"


def detect_volatility_squeeze(
    daily: pd.DataFrame,
    hourly: pd.DataFrame,
    config: dict,
    as_of_ts: pd.Timestamp,
    macro_context: dict | None = None,
) -> PatternResult | None:
    daily = slice_as_of(daily, as_of_ts)
    if len(daily) < 30:
        return None

    thresholds = (config.get("pattern_thresholds") or {}).get("volatility_squeeze", {})
    min_squeeze_bars = int(thresholds.get("min_squeeze_bars", 6))

    row = last_row(daily)
    squeeze_fired = bool(row.get("squeeze_fired", False))
    if not squeeze_fired:
        return None

    # Confirm the squeeze ran long enough to be meaningful: count the run
    # of `squeeze_on=True` bars immediately before this fire bar.
    prior = daily.iloc[:-1]
    run = 0
    for val in reversed(prior["squeeze_on"].fillna(False).astype(bool).tolist()):
        if val:
            run += 1
        else:
            break
    if run < min_squeeze_bars:
        return None

    momentum = safe(row, "momentum", 0.0)
    direction: str
    if momentum > 0:
        direction = "long"
    elif momentum < 0:
        direction = "short"
    else:
        return None  # ambiguous — skip

    close = safe(row, "close")
    atr = safe(row, "atr_14")
    if pd.isna(close) or pd.isna(atr) or atr <= 0:
        return None

    # Entry: on the fire-bar close (swing trade — next session fills at open)
    entry_price = close
    # Stop: opposite end of the prior squeeze range
    squeeze_range = prior.tail(run)
    if direction == "long":
        stop_price = float(squeeze_range["low"].min())
        tp1 = close + 1.0 * atr
        tp2 = close + 2.0 * atr
        invalidation_level = stop_price
        invalidation_condition = "daily_close_below_squeeze_low"
    else:
        stop_price = float(squeeze_range["high"].max())
        tp1 = close - 1.0 * atr
        tp2 = close - 2.0 * atr
        invalidation_level = stop_price
        invalidation_condition = "daily_close_above_squeeze_high"

    # Guard: degenerate R (stop equals entry)
    if abs(entry_price - stop_price) < 0.01:
        return None

    pqs_base = 55
    modifiers: dict[str, int] = {
        "squeeze_duration": min(15, (run - min_squeeze_bars) * 2 + 5),
        "momentum_aligned": 8,
    }
    apply_universal_modifiers(
        modifiers, row=row, direction=direction,  # type: ignore[arg-type]
        macro_context=macro_context,
    )
    pqs_total = cap_pqs(pqs_base, modifiers)

    evidence = [
        {"type": "indicator", "ref": f"squeeze_fired=True after {run}-bar compression"},
        {"type": "indicator", "ref": f"momentum_histogram={momentum:.3f}"},
        {"type": "indicator", "ref": f"atr_14={atr:.2f}"},
    ]

    return PatternResult(
        pattern_name=PATTERN_NAME,
        direction=direction,  # type: ignore[arg-type]
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
