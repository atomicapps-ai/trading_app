"""Intraday Reversion (VWAP snap-back) — SCAFFOLD / EXAMPLE intraday day-trade detector.

⚠️ This is the reference implementation for the INTRADAY (day-trade) lane, NOT a validated
edge. It demonstrates the full contract so real intraday strategies can be dropped in the same
shape. Validate on scripts/bt_intraday.py and clear the same bar (OOS PF ≥ ~1.2, avg-R > 0,
≥ ~100 trades, beats control) before ever enabling it. See strategies/strategy_docs/
INTRADAY_SCAFFOLD.md.

Style: day_trade (flat by the session close — the plan's TimeStop deadline is anchored to today's
close by portfolio_manager when holding_period == "intraday", and executioner.close_at_time
flattens it). Family: mean_reversion.

Signature is the INTRADAY one (different from the swing detectors):
    detect_intraday_reversion(bars_30m, daily, vix_prev_close, config, as_of_ts) -> PatternResult | None

Rules (long, scaffold):
  * Daily trend filter: prior daily close > its SMA200 (buy dips only in an uptrend).
  * Intraday context: build session VWAP from today's 30m bars; only act after `min_bars` bars.
  * Trigger: the latest 30m close is stretched >= `stretch_pct` % below session VWAP (intraday
    oversold) — a snap-back candidate toward VWAP.
  * Entry: latest close. Stop: today's session low − buffer. Target: session VWAP (the mean).
  * Exit: same-day (TimeStop → session close) or target/stop, whichever first.
"""
from __future__ import annotations
from typing import Any

import numpy as np
import pandas as pd
from agents.detectors._helpers import cap_pqs, safe
from models.pattern import PatternResult

PATTERN_NAME = "intraday_reversion"


def _session_vwap(bars: pd.DataFrame) -> np.ndarray:
    tp = (bars["high"] + bars["low"] + bars["close"]) / 3.0
    vol = bars["volume"].replace(0, np.nan)
    cum_pv = (tp * vol).cumsum()
    cum_v = vol.cumsum()
    return (cum_pv / cum_v).ffill().values


def detect_intraday_reversion(
    bars_30m: pd.DataFrame,
    daily: pd.DataFrame,
    vix_prev_close: float | None,
    config: dict[str, Any],
    as_of_ts: pd.Timestamp | None = None,
) -> PatternResult | None:
    th = (config.get("pattern_thresholds") or {}).get(PATTERN_NAME, {})
    min_bars = int(th.get("min_bars", 3))
    stretch_pct = float(th.get("stretch_pct", 0.5))       # % below VWAP to trigger
    stop_buffer_pct = float(th.get("stop_buffer_pct", 0.1))
    require_trend = bool(th.get("require_trend", True))

    if bars_30m is None or len(bars_30m) < min_bars:
        return None
    b = bars_30m.rename(columns={c: c.lower() for c in bars_30m.columns})
    for col in ("open", "high", "low", "close", "volume"):
        if col not in b.columns:
            return None

    # Daily trend gate — use the last COMPLETE daily row (yesterday), never today's partial bar.
    if daily is None or len(daily) < 2:
        return None
    prior = daily.iloc[-1]
    sma200 = safe(prior, "sma_200")
    prior_close = float(prior["close"])
    uptrend = (not pd.isna(sma200)) and sma200 > 0 and prior_close > sma200
    if require_trend and not uptrend:
        return None

    vwap = _session_vwap(b)
    close = float(b["close"].values[-1])
    vw = float(vwap[-1])
    if not (vw > 0) or np.isnan(vw):
        return None
    stretch = (vw - close) / vw * 100.0
    if stretch < stretch_pct:
        return None

    session_low = float(b["low"].min())
    entry_price = close
    stop_price = session_low * (1 - stop_buffer_pct / 100.0)
    risk = entry_price - stop_price
    if risk <= 0.01 or vw <= entry_price:
        return None
    tp2 = vw                                   # target the session mean (VWAP)
    tp1 = entry_price + max(0.6 * (vw - entry_price), 1.0 * risk)
    if tp1 >= tp2:
        tp1 = entry_price + 0.5 * (vw - entry_price)

    pqs_base = 55
    modifiers: dict[str, int] = {}
    if stretch >= 2 * stretch_pct:
        modifiers["deep_stretch"] = 8
    if vix_prev_close is not None and vix_prev_close >= 22:
        modifiers["elevated_vix"] = 4         # intraday snap-backs are livelier when vol is up
    pqs_total = cap_pqs(pqs_base, modifiers)

    et = as_of_ts.tz_convert("America/New_York") if as_of_ts is not None and as_of_ts.tzinfo else as_of_ts
    return PatternResult(
        pattern_name=PATTERN_NAME, direction="long",
        pqs_base=pqs_base, pqs_modifiers=modifiers, pqs_total=pqs_total,
        entry_price=round(entry_price, 2), stop_price=round(stop_price, 2),
        tp1_price=round(tp1, 2), tp2_price=round(tp2, 2),
        invalidation_level=round(stop_price, 2),
        invalidation_condition="reaches_session_vwap_or_session_low_stop_or_eod",
        evidence_items=[
            {"type": "pattern", "ref": f"intraday {stretch:.2f}% below session VWAP ({close:.2f} vs VWAP {vw:.2f})"},
            {"type": "filter", "ref": f"Daily uptrend gate: prior close {prior_close:.2f} > SMA200 {sma200:.2f}"},
            {"type": "management", "ref": f"target = session VWAP {vw:.2f}; stop {stop_price:.2f} (session low); FLAT BY CLOSE (same-day)"},
            {"type": "note", "ref": "SCAFFOLD/EXAMPLE — not validated. Backtest via scripts/bt_intraday.py before enabling."},
        ],
    )
