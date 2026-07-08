"""Turn-of-the-Month — calendar seasonality (sourced: QuantifiedStrategies / Quantpedia).

Equities drift up around the month boundary (salaries, dividend/pension reinvestment). Buy near
month-end, exit a few days into the new month. Validated on the daily US-stock universe (OOS PF
1.28, +0.11R) and correlation-gated as a DIVERSIFIER (max |corr| 0.36 to the live book — a
seasonality family, orthogonal to the trend/mean-reversion strategies). See
strategies/SOURCED_CANDIDATES.md and STRATEGY_GRID.md.

Rules:
  * Fire on the **Kth-last trading day of the month** (default 5); enter next open.
  * Exit ~`hold_bars` sessions later (≈ the 3rd trading day of the new month) — handled by the
    `turn_of_month` branch in scripts/replay_swing.py::_simulate.
  * No price signal / no real stop: a wide disaster stop (entry − stop_atr·ATR) defines R and caps
    tail risk; the exit is calendar-based.

NOTE: with no exchange-calendar library installed, the "Kth-last trading day" is approximated by the
Kth-last **business day** (weekday) of the month. Holidays can shift the entry by a day a few times
a year; for a window-based seasonal edge this is immaterial. Install pandas_market_calendars for
exactness later. Pure function of (daily, hourly, config, as_of_ts, macro_context) -> PatternResult.
"""
from __future__ import annotations
import pandas as pd
from agents.detectors._helpers import cap_pqs, safe, slice_as_of
from models.pattern import PatternResult

PATTERN_NAME = "turn_of_month"


def _kth_last_business_day(ts: pd.Timestamp, k: int):
    """Date of the Kth-last business day of ts's month (weekday approximation)."""
    first = ts.replace(day=1).normalize().tz_localize(None)
    nxt = first + pd.offsets.MonthBegin(1)
    bdays = pd.bdate_range(first, nxt - pd.Timedelta(days=1))
    if len(bdays) < k:
        return None
    return bdays[-k].date()


def detect_turn_of_month(daily, hourly, config, as_of_ts, macro_context=None):
    th = (config.get("pattern_thresholds") or {}).get(PATTERN_NAME, {})
    k_last = int(th.get("k_last", 5))
    stop_atr_mult = float(th.get("stop_atr_mult", 3.0))
    hold_bars = int(th.get("hold_bars", 7))

    df = slice_as_of(daily, as_of_ts)
    if df is None or len(df) < 30:
        return None
    last = df.iloc[-1]
    d = df.index[-1]
    target = _kth_last_business_day(d, k_last)
    if target is None or d.date() != target:
        return None

    close = float(last["close"])
    atr = safe(last, "atr_14")
    if pd.isna(atr) or atr <= 0:
        return None
    entry_price = close
    stop_price = entry_price - stop_atr_mult * atr        # disaster stop (calendar exit is primary)
    risk = entry_price - stop_price
    if risk <= 0.01:
        return None
    tp1 = entry_price + 1.0 * risk
    tp2 = entry_price + 3.0 * risk

    pqs_base = 56
    modifiers: dict[str, int] = {}
    spy_above = (macro_context or {}).get("spy_above_sma200")
    if spy_above is True:
        modifiers["uptrend_regime"] = 6      # the seasonal drift is stronger in up markets
    elif spy_above is False:
        modifiers["downtrend_regime"] = -4
    sma200 = safe(last, "sma_200")
    if not pd.isna(sma200) and close > sma200:
        modifiers["above_200"] = 4
    pqs_total = cap_pqs(pqs_base, modifiers)

    return PatternResult(
        pattern_name=PATTERN_NAME, direction="long",
        pqs_base=pqs_base, pqs_modifiers=modifiers, pqs_total=pqs_total,
        entry_price=round(entry_price, 2), stop_price=round(stop_price, 2),
        tp1_price=round(tp1, 2), tp2_price=round(tp2, 2),
        invalidation_level=round(stop_price, 2),
        invalidation_condition="calendar_exit_3rd_trading_day_next_month_or_disaster_stop",
        evidence_items=[
            {"type": "pattern", "ref": f"Turn-of-the-Month: {k_last}th-last trading day ({d.date()}) — enter next open"},
            {"type": "management", "ref": f"calendar exit ~{hold_bars} sessions (≈3rd trading day next month); disaster stop {stop_price:.2f}"},
            {"type": "note", "ref": "Seasonality/calendar edge (QuantifiedStrategies/Quantpedia). OOS PF 1.28; diversifier (0.36 corr to book)."},
        ],
    )
