"""kronos_planner — turn a Kronos ForecastDistribution into a trade plan.

Design choice (locked 2026-06-25): the reward:risk ratio is a FUNCTION OF CERTAINTY.
Risk is fixed (stop = stop_atr_mult x ATR, defining one R); the take-profit multiple
scales with directional conviction, so a more confident forecast sets a more ambitious
target:

    p_dir 0.60 (gate)  -> RR ~2.0:1
    p_dir 0.75         -> RR ~2.75:1
    p_dir 0.90         -> RR ~3.5:1
    p_dir 1.00         -> RR 4.0:1

The probability shown (p_profit) is the RAW measured hit-probability for this exact
entry/stop/TP across the forecast paths. It is NOT yet calibrated — until we have
logged paper trades it is for research/ranking only (see KRONOS_UPGRADE_PROPOSAL.md
§4 and §4a). This module produces a lightweight KronosPlan for the dry-run scan; it is
mapped onto the app's full TradePlan when we wire the pipeline.
"""
from __future__ import annotations

import logging
from typing import Literal

import pandas as pd
from pydantic import BaseModel

from models.forecast import ForecastDistribution

logger = logging.getLogger(__name__)

STOP_ATR_MULT = 1.5     # stop distance in ATRs (one unit of risk)
RR_MIN = 1.5            # reward:risk at low conviction
RR_MAX = 4.0            # reward:risk at full conviction

# Gates are applied by the scan on the MEASURED setup, not on raw direction —
# a name only qualifies if its hit-probability and expected R clear these.
MIN_PROFIT_PROB = 0.60  # P(profit) for THIS entry/stop/TP
MIN_EXPECTED_R = 0.0    # mean R must be positive


class KronosPlan(BaseModel):
    symbol: str
    direction: Literal["long", "short"]
    entry: float
    stop: float
    take_profit: float
    rr: float                  # reward:risk ratio (certainty-scaled)
    atr: float
    risk_per_share: float
    p_up: float                # raw directional prob at the horizon
    dir_conviction: float      # p_dir, 0.5..1.0
    p_profit: float            # RAW measured hit-prob for THIS setup (uncalibrated)
    expected_r: float          # mean R multiple across forecast paths
    path_sigma_pct: float


def atr(bars: pd.DataFrame, period: int = 14) -> float:
    high, low, close = bars["high"], bars["low"], bars["close"]
    prev = close.shift(1)
    tr = pd.concat([(high - low), (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return float(tr.tail(period).mean())


def build_plan(
    *,
    symbol: str,
    dist: ForecastDistribution,
    bars: pd.DataFrame,
    stop_atr_mult: float = STOP_ATR_MULT,
    rr_min: float = RR_MIN,
    rr_max: float = RR_MAX,
) -> KronosPlan | None:
    """Build a certainty-scaled plan for every name. Gating (on the measured
    p_profit / expected R) is the scan's job, not the planner's."""
    direction = "long" if dist.p_up >= 0.5 else "short"
    p_dir = dist.p_up if direction == "long" else 1.0 - dist.p_up

    a = atr(bars)
    if a <= 0:
        logger.warning("%s: non-positive ATR, skipping", symbol)
        return None

    entry = dist.last_close
    conviction = (p_dir - 0.5) / 0.5                 # 0 at coin-flip, 1 at full conviction
    rr = rr_min + conviction * (rr_max - rr_min)
    stop_dist = stop_atr_mult * a

    if direction == "long":
        stop, tp = entry - stop_dist, entry + rr * stop_dist
    else:
        stop, tp = entry + stop_dist, entry - rr * stop_dist

    hit = dist.hit_probabilities(entry=entry, stop=stop, take_profit=tp, direction=direction)

    return KronosPlan(
        symbol=symbol,
        direction=direction,
        entry=round(entry, 2),
        stop=round(stop, 2),
        take_profit=round(tp, 2),
        rr=round(rr, 2),
        atr=round(a, 2),
        risk_per_share=round(stop_dist, 2),
        p_up=dist.p_up,
        dir_conviction=round(p_dir, 4),
        p_profit=hit.p_profit,
        expected_r=hit.expected_r,
        path_sigma_pct=dist.path_sigma_pct,
    )
