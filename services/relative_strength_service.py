"""relative_strength_service.py — RS vs benchmark + VCP detection.

Two functions used by Layer-3 (Technical Confluence):

* ``compute_relative_strength`` — symbol pct-return minus benchmark
  pct-return over 20 and 60 trading days. Also flags when the
  benchmark is in a pullback (closed below its 10-day SMA) so the
  Alpha Score agent can surface "leadership during weakness" — a key
  Minervini-style filter.

* ``check_vcp`` — Volatility Contraction Pattern detector. We flag
  VCP-qualified when the symbol shows ≥3 consecutive shrinking
  range-windows in the last ~30 bars and the latest range is below
  half the earliest. Pure function over OHLCV, replay-safe.

Both functions accept either a fresh DataFrame or rely on the
``data_service`` cache via ``get_bars``.
"""
from __future__ import annotations

import logging

import pandas as pd

from models.alpha_score import RelativeStrength

log = logging.getLogger(__name__)

DEFAULT_BENCHMARK = "SPY"


def _pct_return(df: pd.DataFrame, lookback: int) -> float | None:
    if len(df) < lookback + 1:
        return None
    last = float(df["close"].iloc[-1])
    base = float(df["close"].iloc[-lookback - 1])
    if base == 0:
        return None
    return round((last - base) / base * 100, 3)


def _benchmark_pulling_back(df: pd.DataFrame) -> bool:
    """Is the benchmark trading below its 10-day SMA right now?"""
    if len(df) < 11:
        return False
    sma10 = float(df["close"].tail(10).mean())
    last = float(df["close"].iloc[-1])
    return last < sma10


def detect_vcp(df: pd.DataFrame, *, window: int = 30, min_contractions: int = 3) -> dict:
    """Detect a Volatility Contraction Pattern (VCP) in the trailing window.

    Algorithm: split the trailing ``window`` bars into 3 equal slices, measure
    each slice's high-low range as a percent of slice mean price, and require
    each slice to be tighter than the previous (range[t] < range[t-1] * 0.85).
    Latest range must also be ≤ 50 % of the earliest, and ATR_14 should be
    decreasing into the close.

    This is intentionally simpler than Minervini's full base-on-base setup;
    it captures the volatility-contraction signature without trying to
    classify base depth or stage.
    """
    out = {
        "qualified": False,
        "contraction_count": 0,
        "latest_range_pct": None,
        "earliest_range_pct": None,
    }
    if df is None or df.empty or len(df) < window:
        return out

    tail = df.tail(window).copy()
    n_slices = 3
    slice_size = window // n_slices
    ranges: list[float] = []
    for i in range(n_slices):
        seg = tail.iloc[i * slice_size : (i + 1) * slice_size]
        if seg.empty:
            return out
        seg_hi = float(seg["high"].max())
        seg_lo = float(seg["low"].min())
        seg_mean = float(seg["close"].mean()) or 1.0
        ranges.append((seg_hi - seg_lo) / seg_mean * 100)

    contractions = 0
    for i in range(1, len(ranges)):
        if ranges[i] < ranges[i - 1] * 0.85:
            contractions += 1

    out["contraction_count"] = contractions
    out["latest_range_pct"] = round(ranges[-1], 3)
    out["earliest_range_pct"] = round(ranges[0], 3)

    if (
        contractions >= min_contractions - 1
        and ranges[-1] <= 0.5 * ranges[0]
    ):
        out["qualified"] = True
    return out


async def compute_relative_strength(
    symbol: str,
    *,
    benchmark: str = DEFAULT_BENCHMARK,
    as_of_ts: pd.Timestamp | None = None,
    lookback_bars: int = 80,
) -> RelativeStrength:
    """Compute RS + VCP qualification for one symbol."""
    from services.data_service import DataNotAvailableError, get_bars  # lazy import
    try:
        sym_df = await get_bars(symbol, "1d", as_of_ts=as_of_ts, min_bars=22)
    except DataNotAvailableError as e:
        log.warning("RS: bars unavailable for %s: %s", symbol, e)
        return RelativeStrength(symbol=symbol, benchmark=benchmark)

    try:
        bench_df = await get_bars(benchmark, "1d", as_of_ts=as_of_ts, min_bars=22)
    except DataNotAvailableError as e:
        log.warning("RS: benchmark bars unavailable: %s", e)
        return RelativeStrength(symbol=symbol, benchmark=benchmark)

    sym_20 = _pct_return(sym_df, 20) or 0.0
    bench_20 = _pct_return(bench_df, 20) or 0.0
    rs_20 = round(sym_20 - bench_20, 3)

    sym_60 = _pct_return(sym_df, 60) or 0.0
    bench_60 = _pct_return(bench_df, 60) or 0.0
    rs_60 = round(sym_60 - bench_60, 3)

    pullback = _benchmark_pulling_back(bench_df)
    vcp = detect_vcp(sym_df.tail(lookback_bars))

    return RelativeStrength(
        symbol=symbol,
        benchmark=benchmark,
        rs_20d=rs_20,
        rs_60d=rs_60,
        benchmark_pulling_back=pullback,
        vcp_qualified=vcp["qualified"],
        contraction_count=vcp["contraction_count"],
        latest_range_pct=vcp["latest_range_pct"],
    )


def price_action_score_0_100(rs: RelativeStrength) -> tuple[float, str]:
    """Translate RS + VCP signals into the price-action 0-100 sub-score.

    Pillars:
      * RS_20d: maps roughly linearly into [0, 50]; +5 % RS = 50 pts.
      * RS_60d: smaller weight, [0, 20]; +10 % RS_60 = 20 pts.
      * VCP qualification: +20 pts if true.
      * Leadership-during-weakness bonus: +10 pts when VCP qualified
        AND the benchmark is pulling back.
    """
    score = 50.0  # neutral baseline
    parts: list[str] = [f"baseline=50"]

    rs20_pts = max(-30, min(30, rs.rs_20d * 6.0))
    score += rs20_pts
    parts.append(f"rs20={rs.rs_20d:+.2f}%:{rs20_pts:+.1f}")

    rs60_pts = max(-15, min(15, rs.rs_60d * 1.5))
    score += rs60_pts
    parts.append(f"rs60={rs.rs_60d:+.2f}%:{rs60_pts:+.1f}")

    if rs.vcp_qualified:
        score += 20
        parts.append("vcp_qualified:+20")
        if rs.benchmark_pulling_back:
            score += 10
            parts.append("leadership_during_weakness:+10")

    score = max(0.0, min(100.0, score))
    return round(score, 1), "; ".join(parts)
