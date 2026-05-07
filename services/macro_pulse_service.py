"""macro_pulse_service.py — Layer 2 of the Alpha Score: the global macro lens.

Builds a ``MacroPulse`` snapshot at a given timestamp by composing three
external feeds:

* **Yield curve** — DGS2 + DGS10 from FRED (or the pre-computed T10Y2Y
  spread). Detects normal / flat / inverted / steep regimes and
  measures 5-day change so the strategy can react to *rapid* steepening
  or inversion as the spec calls out.

* **DXY** — Trade-Weighted Broad Dollar Index (DTWEXBGS) as a free,
  FRED-hosted proxy for ICE DXY. We track level + 5-day change and
  bucket into weak / neutral / strong.

* **International overnight moves** — Nikkei (^N225) and DAX (^GDAXI)
  via the regular yfinance bar cache, used to project SPY gap risk
  for the US open. (No new data dependency — `services/data_service`
  already supports yfinance tickers including indices.)

Pure async function: ``compute_macro_pulse(as_of_ts)`` is what callers
should reach for. Errors degrade to ``None`` fields, never raise.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

import pandas as pd

from models.alpha_score import MacroPulse
from services.economic_calendar_service import change_over, latest_value

log = logging.getLogger(__name__)


def _classify_curve(spread: float) -> Literal[
    "inverted_deep", "inverted", "flat", "normal", "steep"
]:
    if spread <= -0.50:
        return "inverted_deep"
    if spread <  0.0:
        return "inverted"
    if spread <  0.20:
        return "flat"
    if spread <  1.50:
        return "normal"
    return "steep"


def _classify_dxy(level: float, change_5d: float | None) -> Literal[
    "weak", "neutral", "strong"
]:
    """Heuristic regime classification on the trade-weighted broad index.

    DTWEXBGS is centered around 120 in 2024-2026; the bands here are
    rules-of-thumb for headline regime, not a precise model.
    """
    if change_5d is not None and change_5d >= 1.0 and level >= 120:
        return "strong"
    if change_5d is not None and change_5d <= -1.0:
        return "weak"
    if level >= 125:
        return "strong"
    if level <= 115:
        return "weak"
    return "neutral"


async def _overnight_pct(symbol: str, as_of: datetime | None) -> float | None:
    """Last full bar's pct change for an international index."""
    from services.data_service import DataNotAvailableError, get_bars  # lazy import
    try:
        df = await get_bars(symbol, "1d", as_of_ts=pd.Timestamp(as_of) if as_of else None, min_bars=2)
    except DataNotAvailableError as e:
        log.warning("macro_pulse: no bars for %s: %s", symbol, e)
        return None
    last = float(df["close"].iloc[-1])
    prev = float(df["close"].iloc[-2])
    if prev == 0:
        return None
    return round((last - prev) / prev * 100, 2)


def _classify_gap_risk(
    nikkei: float | None,
    dax: float | None,
) -> Literal["bullish", "bearish", "neutral", "unknown"]:
    if nikkei is None and dax is None:
        return "unknown"
    score = 0.0
    n = 0
    if nikkei is not None:
        score += nikkei
        n += 1
    if dax is not None:
        score += dax
        n += 1
    avg = score / n
    if avg >= 0.5:
        return "bullish"
    if avg <= -0.5:
        return "bearish"
    return "neutral"


async def compute_macro_pulse(as_of_ts: datetime | None = None) -> MacroPulse:
    """Top-level: build the ``MacroPulse`` snapshot.

    Pure of side-effects beyond FRED + bar caches. Designed to be called
    once per backtest tick — cheap when caches are warm.
    """
    as_of = as_of_ts or datetime.now(timezone.utc)
    pulse = MacroPulse(as_of_ts=as_of)
    notes: list[str] = []

    # Yields
    y2 = await latest_value("DGS2", as_of=as_of)
    y10 = await latest_value("DGS10", as_of=as_of)
    pulse.yield_2y = y2
    pulse.yield_10y = y10

    spread = await latest_value("T10Y2Y", as_of=as_of)
    if spread is None and y2 is not None and y10 is not None:
        spread = round(y10 - y2, 3)
    pulse.yield_curve_2s10s = spread
    if spread is not None:
        pulse.yield_curve_regime = _classify_curve(spread)

    pulse.yield_curve_change_5d = await change_over("T10Y2Y", days=5, as_of=as_of)
    if pulse.yield_curve_change_5d is not None and abs(pulse.yield_curve_change_5d) >= 0.15:
        notes.append(
            f"yield curve moved {pulse.yield_curve_change_5d:+.2f} bps over 5d "
            f"(rapid {'steepening' if pulse.yield_curve_change_5d > 0 else 'inversion'})"
        )

    # DXY
    dxy = await latest_value("DTWEXBGS", as_of=as_of)
    pulse.dxy_level = dxy
    pulse.dxy_change_5d = await change_over("DTWEXBGS", days=5, as_of=as_of)
    if dxy is not None:
        pulse.dxy_regime = _classify_dxy(dxy, pulse.dxy_change_5d)
        if pulse.dxy_regime == "strong":
            notes.append("strong USD — headwind for international-revenue names")
        elif pulse.dxy_regime == "weak":
            notes.append("weak USD — tailwind for international-revenue names")

    # Fed funds
    pulse.fed_funds_rate = await latest_value("DFF", as_of=as_of)

    # International overnight moves
    pulse.nikkei_overnight_pct = await _overnight_pct("^N225", as_of)
    pulse.dax_overnight_pct = await _overnight_pct("^GDAXI", as_of)
    pulse.spy_gap_risk = _classify_gap_risk(
        pulse.nikkei_overnight_pct, pulse.dax_overnight_pct,
    )

    pulse.notes = notes
    return pulse


def intermarket_score_0_100(pulse: MacroPulse) -> tuple[float, str]:
    """Map the macro pulse onto the 0-100 sub-score space.

    Pillars (additive, then clamped):

    * Curve regime (40 pts):
        steep / normal → +40, flat → +20, inverted → 0, inverted_deep → -10.
    * Curve momentum (10 pts): bonus when steepening rapidly.
    * DXY regime (30 pts):
        weak → +30, neutral → +15, strong → 0.
    * Overnight moves (20 pts):
        bullish gap → +20, neutral → +10, bearish → 0.
    """
    score = 0.0
    parts: list[str] = []

    curve_pts = {
        "steep": 40, "normal": 40, "flat": 20,
        "inverted": 0, "inverted_deep": -10, "unknown": 20,
    }[pulse.yield_curve_regime]
    score += curve_pts
    parts.append(f"curve({pulse.yield_curve_regime}):+{curve_pts}")

    if pulse.yield_curve_change_5d is not None and pulse.yield_curve_change_5d >= 0.10:
        score += 10
        parts.append("curve_steepening:+10")

    dxy_pts = {
        "weak": 30, "neutral": 15, "strong": 0, "unknown": 15,
    }[pulse.dxy_regime]
    score += dxy_pts
    parts.append(f"dxy({pulse.dxy_regime}):+{dxy_pts}")

    gap_pts = {
        "bullish": 20, "neutral": 10, "bearish": 0, "unknown": 10,
    }[pulse.spy_gap_risk]
    score += gap_pts
    parts.append(f"overnight({pulse.spy_gap_risk}):+{gap_pts}")

    score = max(0.0, min(100.0, score))
    return round(score, 1), "; ".join(parts)
