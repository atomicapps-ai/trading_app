"""pivot_service — deterministic support/resistance context for Kronos candidates.

Pure OHLC math (no model). For each symbol we compute classic floor-trader pivots
from the last completed WEEK and MONTH (appropriate horizons for daily/swing holds),
plus recent swing highs/lows (structural S/R). We then find the nearest support below
and resistance above the current price and assess whether a planned trade has clear
runway to its target or is heading into a level.

Design (per the user's plan, 2026-06-25): pivots are DISPLAYED CONTEXT and are LOGGED
with every plan, but they are NOT folded into the Kronos probability. Later we test the
hypothesis "does pivot confluence improve outcomes?" from the logged data and conclude
then — we don't assume it now.
"""
from __future__ import annotations

import logging
from typing import Literal

import pandas as pd

logger = logging.getLogger(__name__)


def classic_pivots(high: float, low: float, close: float) -> dict:
    """Standard floor-trader pivots from a period's H/L/C."""
    p = (high + low + close) / 3.0
    rng = high - low
    return {
        "P": round(p, 2),
        "R1": round(2 * p - low, 2), "S1": round(2 * p - high, 2),
        "R2": round(p + rng, 2),     "S2": round(p - rng, 2),
        "R3": round(high + 2 * (p - low), 2), "S3": round(low - 2 * (p - high), 2),
    }


def _period_pivots(bars: pd.DataFrame, rule: str) -> dict | None:
    """Pivots from the last COMPLETED resampled period (week/month)."""
    try:
        agg = bars.resample(rule).agg({"high": "max", "low": "min", "close": "last"}).dropna()
        if len(agg) < 2:
            return None
        row = agg.iloc[-2]  # -1 is the in-progress period; -2 is last completed
        return classic_pivots(float(row["high"]), float(row["low"]), float(row["close"]))
    except Exception as exc:  # noqa: BLE001
        logger.debug("period pivots (%s) failed: %s", rule, exc)
        return None


def swing_levels(bars: pd.DataFrame, k: int = 3, lookback: int = 120) -> tuple[list[float], list[float]]:
    """Recent swing highs (resistance) and swing lows (support) via a simple fractal."""
    sub = bars.tail(lookback)
    hi = [float(x) for x in sub["high"].tolist()]
    lo = [float(x) for x in sub["low"].tolist()]
    highs, lows = [], []
    for i in range(k, len(sub) - k):
        if hi[i] == max(hi[i - k:i + k + 1]):
            highs.append(round(hi[i], 2))
        if lo[i] == min(lo[i - k:i + k + 1]):
            lows.append(round(lo[i], 2))
    return highs, lows


def structural_pivots(bars: pd.DataFrame, left: int = 3, right: int = 3) -> list[dict]:
    """Pivot Points High/Low — structural swing highs/lows by the 'Strength' param.

    A swing high at bar i is a high greater than `left` bars before AND `right` bars
    after it; a swing low is the mirror. Larger left/right = more major (stronger)
    pivots. NO LOOK-AHEAD: a pivot is only *known* once the `right` confirming bars
    have printed, so each result carries `confirm_ts` = the timestamp at i+right, the
    first moment a strategy could legitimately act on the level.

    Returns dicts: {kind: 'support'|'resistance', price, ts (pivot bar), confirm_ts}.
    """
    idx = list(bars.index)
    hi = [float(x) for x in bars["high"].tolist()]
    lo = [float(x) for x in bars["low"].tolist()]
    n = len(bars)
    out: list[dict] = []
    for i in range(left, n - right):
        if hi[i] == max(hi[i - left:i + right + 1]):
            out.append({"kind": "resistance", "price": hi[i], "ts": idx[i], "confirm_ts": idx[i + right]})
        if lo[i] == min(lo[i - left:i + right + 1]):
            out.append({"kind": "support", "price": lo[i], "ts": idx[i], "confirm_ts": idx[i + right]})
    return out


def pivot_context(
    bars: pd.DataFrame,
    *,
    direction: Literal["long", "short"] | None = None,
    entry: float | None = None,
    take_profit: float | None = None,
    near_pct: float = 1.5,
) -> dict:
    """Full S/R context + a confluence read for a planned trade.

    `near_pct` — how close (in %) the entry must be to a level to count as "at" it.
    Returns nearest support/resistance, all levels, and a confluence tag/note.
    """
    price = float(bars["close"].iloc[-1])
    weekly = _period_pivots(bars, "W")
    monthly = _period_pivots(bars, "ME")
    sw_highs, sw_lows = swing_levels(bars)

    # Union of all candidate levels (pivots + swing extremes)
    levels: list[float] = list(sw_highs) + list(sw_lows)
    for pv in (weekly, monthly):
        if pv:
            levels += [pv["R1"], pv["R2"], pv["R3"], pv["S1"], pv["S2"], pv["S3"], pv["P"]]
    levels = sorted(set(levels))

    above = [lv for lv in levels if lv > price]
    below = [lv for lv in levels if lv < price]
    nearest_res = min(above) if above else None
    nearest_sup = max(below) if below else None

    def _dist(lv):
        return round((lv - price) / price * 100, 2) if lv else None

    confluence = "neutral"
    note = "no clear level nearby"
    if direction and entry and take_profit:
        if direction == "long":
            res, sup = nearest_res, nearest_sup
            at_support = sup is not None and abs(entry - sup) / entry * 100 <= near_pct
            wall = res is not None and entry < res < take_profit
            if at_support and not wall:
                confluence, note = "supportive", f"entry near support {sup} with clear runway to TP"
            elif wall:
                confluence, note = "caution", f"resistance {res} sits between entry and TP — possible cap"
            elif res is not None:
                note = f"nearest resistance {res} ({_dist(res)}%)"
        else:  # short
            res, sup = nearest_res, nearest_sup
            at_resistance = res is not None and abs(entry - res) / entry * 100 <= near_pct
            wall = sup is not None and take_profit < sup < entry
            if at_resistance and not wall:
                confluence, note = "supportive", f"entry near resistance {res} with clear runway to TP"
            elif wall:
                confluence, note = "caution", f"support {sup} sits between entry and TP — possible floor"
            elif sup is not None:
                note = f"nearest support {sup} ({_dist(sup)}%)"

    return {
        "price": round(price, 2),
        "weekly": weekly,
        "monthly": monthly,
        "swing_highs": sw_highs[-6:],
        "swing_lows": sw_lows[-6:],
        "nearest_support": {"level": nearest_sup, "dist_pct": _dist(nearest_sup)} if nearest_sup else None,
        "nearest_resistance": {"level": nearest_res, "dist_pct": _dist(nearest_res)} if nearest_res else None,
        "confluence": confluence,
        "note": note,
    }
