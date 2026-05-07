"""volume_profile_service.py — VPVR / POC / Value Area calculations.

Bucket each bar's traded volume into N price bins across a lookback
window, then identify:

* **POC** (Point of Control)  — single highest-volume bin.
* **Value Area** — contiguous block of bins around the POC that
  contains 70 % (configurable) of the lookback's total volume.

Bin width and approach follows the standard market-profile literature:
we treat each bar's volume as evenly spread between its low and high
(a "TPO-by-volume" approximation, NOT real intraday tick distribution).
For daily bars this is the same approximation TradingView's VPVR
overlay uses, and it's the only thing that's tractable from cached
OHLCV without raw tick data.

Output is a ``VolumeProfile`` model with the price's location relative
to value area, used directly by the Alpha Score agent.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from models.alpha_score import VolumeProfile

log = logging.getLogger(__name__)


def compute_volume_profile(
    df: pd.DataFrame,
    *,
    bins: int = 50,
    value_area_pct: float = 0.70,
) -> dict[str, Any]:
    """Compute POC and value-area bounds over the bars in ``df``.

    Parameters
    ----------
    df : DataFrame
        Must have ``high``, ``low``, ``volume`` columns. Index ignored.
    bins : int
        Number of price buckets across the high-low envelope. 50 is a
        reasonable default for a 60-day daily window.
    value_area_pct : float
        Volume share that defines the Value Area (default 0.70 = the
        classic 1-sigma cut).

    Returns
    -------
    dict with: poc_price, value_area_high, value_area_low, bin_edges,
    bin_volumes, total_volume.
    """
    if df is None or df.empty:
        raise ValueError("compute_volume_profile: empty DataFrame")
    required = {"high", "low", "volume"}
    if not required.issubset(df.columns):
        raise ValueError(f"compute_volume_profile: need cols {required}, got {list(df.columns)}")

    lo = float(df["low"].min())
    hi = float(df["high"].max())
    if hi <= lo:
        raise ValueError(f"compute_volume_profile: degenerate price range {lo}..{hi}")

    edges = np.linspace(lo, hi, bins + 1)
    bin_volumes = np.zeros(bins, dtype=np.float64)

    highs = df["high"].to_numpy(dtype=np.float64)
    lows = df["low"].to_numpy(dtype=np.float64)
    vols = df["volume"].to_numpy(dtype=np.float64)

    for h, l, v in zip(highs, lows, vols):
        if v <= 0 or h <= l:
            continue
        # Find the bin indices the bar's range overlaps.
        i_lo = max(0, np.searchsorted(edges, l, side="right") - 1)
        i_hi = min(bins - 1, np.searchsorted(edges, h, side="right") - 1)
        if i_hi < i_lo:
            continue
        # Distribute volume proportionally to the price-overlap of each bin.
        bar_range = h - l
        for i in range(i_lo, i_hi + 1):
            bin_lo = edges[i]
            bin_hi = edges[i + 1]
            overlap = min(h, bin_hi) - max(l, bin_lo)
            if overlap <= 0:
                continue
            bin_volumes[i] += v * (overlap / bar_range)

    total = float(bin_volumes.sum())
    if total <= 0:
        raise ValueError("compute_volume_profile: zero total volume")

    poc_idx = int(np.argmax(bin_volumes))
    poc_price = float((edges[poc_idx] + edges[poc_idx + 1]) / 2)

    # Expand symmetrically from POC until we capture >= value_area_pct of total.
    target = total * value_area_pct
    captured = bin_volumes[poc_idx]
    lo_idx = poc_idx
    hi_idx = poc_idx
    while captured < target and (lo_idx > 0 or hi_idx < bins - 1):
        # Pick the side that adds more volume.
        next_lo = bin_volumes[lo_idx - 1] if lo_idx > 0 else -1
        next_hi = bin_volumes[hi_idx + 1] if hi_idx < bins - 1 else -1
        if next_hi >= next_lo:
            hi_idx += 1
            captured += bin_volumes[hi_idx]
        else:
            lo_idx -= 1
            captured += bin_volumes[lo_idx]

    value_area_low = float(edges[lo_idx])
    value_area_high = float(edges[hi_idx + 1])

    return {
        "poc_price": poc_price,
        "value_area_high": value_area_high,
        "value_area_low": value_area_low,
        "bin_edges": edges.tolist(),
        "bin_volumes": bin_volumes.tolist(),
        "total_volume": total,
    }


def build_profile(symbol: str, df: pd.DataFrame, *, bins: int = 50) -> VolumeProfile:
    """Convenience: run ``compute_volume_profile`` and wrap into the model."""
    res = compute_volume_profile(df, bins=bins)
    current = float(df["close"].iloc[-1])
    poc = res["poc_price"]
    vah = res["value_area_high"]
    val = res["value_area_low"]

    if abs(current - poc) / poc < 0.005:
        location = "at_poc"
    elif current > vah:
        location = "above_vah"
    elif current < val:
        location = "below_val"
    else:
        location = "in_value_area"

    return VolumeProfile(
        symbol=symbol,
        lookback_bars=int(len(df)),
        poc_price=round(poc, 4),
        value_area_high=round(vah, 4),
        value_area_low=round(val, 4),
        current_price=round(current, 4),
        distance_to_poc_pct=round((current - poc) / poc * 100, 3),
        in_value_area=(val <= current <= vah),
        location=location,
    )


def volume_profile_score_0_100(vp: VolumeProfile) -> tuple[float, str]:
    """Translate volume-profile location into a 0-100 score.

    Heuristic:
      * Breakout above VAH on conviction → highest score (price establishing
        new acceptance level higher).
      * In-value-area, above POC → bullish accumulation (rotation up).
      * At POC → neutral (battle line).
      * In value area, below POC → mild bearish.
      * Below VAL → bearish breakdown (lowest score).
    """
    rationale = (
        f"loc={vp.location}, dist_to_poc={vp.distance_to_poc_pct:+.2f}%"
    )
    if vp.location == "above_vah":
        score = 80 + min(15.0, max(0.0, vp.distance_to_poc_pct - 2))
    elif vp.location == "in_value_area" and vp.current_price > vp.poc_price:
        score = 60.0
    elif vp.location == "at_poc":
        score = 50.0
    elif vp.location == "in_value_area" and vp.current_price <= vp.poc_price:
        score = 40.0
    elif vp.location == "below_val":
        score = max(5.0, 25 - abs(vp.distance_to_poc_pct))
    else:
        score = 50.0
    return round(min(100.0, max(0.0, score)), 1), rationale
