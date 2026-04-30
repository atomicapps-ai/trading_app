"""Double Lock — filtered DL-S2 detector (intraday opening pattern).

Pattern
-------
Two consecutive 30-min "conviction" candles in the same direction at the
9:30 and 10:00 ET bars predict the day's close direction. Discovered by
``scripts/scan_opening_patterns.py``: the unfiltered pattern has 60-70%
WR on mega-caps but only ~43% on a broad universe. With the regime
filter below the WR jumps to 82.4% (n=17, 60-day sample, bootstrap 95%
CI [64.7%, 100%]).

Candle conditions
-----------------
  c1 (9:30 bar) — full conviction:
    BULL.STR.HPRS.HVOL  : close > open  AND  body >= 50% of range
                          AND  closepct >= 50% of range  AND  volume >= 1.2x slot median
    BEAR.STR.LPRS.HVOL  : close < open  AND  body >= 50%  AND  closepct <= 50%
                          AND  volume >= 1.2x slot median

  c2 (10:00 bar) — direction + body confirmation only:
    BULL : close > open AND body >= 50%
    BEAR : close < open AND body >= 50%

Regime filter (essential — without it WR is 43%)
------------------------------------------------
  vix_prev_close >= 20      (volatile regime; trends carry through to close)
  daily_adx_14   <= 35      (not in a runaway trend that's about to reverse)
  LONG  setups : daily_rsi_14 in [40, 65]  (mild-neutral momentum, not extremes)
  SHORT setups : daily_rsi_14 in [20, 40]  (already weakening)

Entry / exit
------------
  Entry  : c2 close (10:30 ET timestamp mark)
  Stop   : 3% catastrophic (NEVER tighter — testing showed 1% kills WR)
  Trail  : 1.0% trail at peak, activates only after +1.0R (+3%) favorable
           (saved 0.29% drag on baseline; protects outsized winners)
  Time   : hard exit at 15:00 bar close (no overnight)

Different signature from the swing detectors
--------------------------------------------
This detector needs INTRADAY bars (30m) plus same-day VIX context.
The standard ``(daily, hourly, ...)`` signature in ALL_DETECTORS does
not currently provide that. Until ``services/data_service.py`` adds
30m support, this detector runs through its own narrow workflow path
(``workflows/double_lock_1030.yaml``) instead of the swing analyst.
The HANDOFF.md "Integration TODO" section spells out the small change
to fully merge it into the standard analyst lens.

Pure function — same code runs live and in Phase 5 backtests.
"""
from __future__ import annotations

from datetime import time as dtime
from typing import Any

import pandas as pd

from models.pattern import PatternResult

PATTERN_NAME = "double_lock_filtered"

# Detector fires only when the as_of timestamp matches this wall-clock instant
# in America/New_York (the close of the 10:00 30-min bar).
ENTRY_TIME_ET = dtime(10, 30)


def detect_double_lock_filtered(
    bars_30m: pd.DataFrame,
    daily: pd.DataFrame,
    vix_prev_close: float | None,
    config: dict[str, Any],
    as_of_ts: pd.Timestamp,
    ignore_regime: bool = False,
) -> PatternResult | None:
    """Run the double-lock filter on today's opening bars.

    Parameters
    ----------
    bars_30m : DataFrame
        30-min OHLCV bars for the active session, indexed in ET
        (timezone-aware ``America/New_York``). Must contain the 9:30
        bar and the 10:00 bar of the current trading day. Older bars
        are ignored — the detector reads only today's first two bars.

    daily : DataFrame
        Daily bars with at least ``rsi_14`` and ``adx_14`` columns
        appended (use ``services.indicator_service.add_indicators``).
        The detector reads YESTERDAY's row only — today's incomplete
        daily bar must NOT influence the decision.

    vix_prev_close : float | None
        ^VIX daily close from the previous session. ``None`` causes
        the detector to skip (we never trade without the regime check).

    config : dict
        Loaded from ``strategy_configs/double_lock.yaml``. Reads
        ``thresholds`` -> body_pct / press_lo / press_hi / vol_mult /
        vix_min / adx_max / rsi_long_lo / rsi_long_hi / rsi_short_lo /
        rsi_short_hi / cat_stop_pct.

    as_of_ts : Timestamp
        The "now" — must be the close of the 10:00 30M bar (10:30 ET)
        for the detector to fire. Same-day backtest replay loops set
        this each step.

    Returns
    -------
    PatternResult | None
        ``None`` if any candle / filter / time condition fails.
        Otherwise a fully-priced PatternResult ready for the analyst
        to convert to a Signal.
    """
    t = config.get("thresholds", {}) or {}
    body_pct_thr  = float(t.get("body_pct", 0.5))
    press_hi      = float(t.get("press_hi", 0.5))   # HPRS lower bound
    press_lo      = float(t.get("press_lo", 0.5))   # LPRS upper bound
    vol_mult      = float(t.get("vol_mult", 1.2))
    vix_min       = float(t.get("vix_min", 20.0))
    adx_max       = float(t.get("adx_max", 35.0))
    rsi_long_lo   = float(t.get("rsi_long_lo", 40.0))
    rsi_long_hi   = float(t.get("rsi_long_hi", 65.0))
    rsi_short_lo  = float(t.get("rsi_short_lo", 20.0))
    rsi_short_hi  = float(t.get("rsi_short_hi", 40.0))
    cat_stop_pct  = float(t.get("cat_stop_pct", 3.0))

    # ── Time gate ────────────────────────────────────────────────────────
    if as_of_ts is None or as_of_ts.tzinfo is None:
        return None
    as_of_et = as_of_ts.tz_convert("America/New_York") if as_of_ts.tzinfo else as_of_ts
    if as_of_et.time() != ENTRY_TIME_ET:
        return None

    # ── Slice off any future bars (look-ahead protection for backtest) ───
    # In live the cache has nothing after as_of_ts, so this is a no-op.
    # In Phase 5 replay the caller may pass a multi-year frame and trust
    # the detector to scope itself.
    bars_30m = bars_30m[bars_30m.index <= as_of_ts]
    if len(bars_30m) < 2:
        return None

    # ── Pull today's two opening bars ────────────────────────────────────
    today = as_of_et.date()
    today_bars = bars_30m[bars_30m.index.date == today]
    if len(today_bars) < 2:
        return None

    c1 = today_bars.iloc[0]
    c2 = today_bars.iloc[1]
    if c1.name.time() != dtime(9, 30) or c2.name.time() != dtime(10, 0):
        return None

    o1, h1, l1, cl1, v1 = (float(c1["open"]), float(c1["high"]),
                           float(c1["low"]),  float(c1["close"]),
                           float(c1["volume"]))
    o2, h2, l2, cl2 = (float(c2["open"]), float(c2["high"]),
                       float(c2["low"]),  float(c2["close"]))

    rng1 = h1 - l1
    rng2 = h2 - l2
    if rng1 <= 0 or rng2 <= 0:
        return None

    c1_body = abs(cl1 - o1) / rng1
    c2_body = abs(cl2 - o2) / rng2
    c1_cp   = (cl1 - l1) / rng1

    # ── Slot-volume baseline (median of all 9:30 bars in the frame) ──────
    same_slot = bars_30m[bars_30m.index.time == dtime(9, 30)]
    slot_med = float(same_slot["volume"].median()) if len(same_slot) else 0.0
    if slot_med <= 0:
        return None
    c1_hvol = v1 >= vol_mult * slot_med

    # ── Candle classification ────────────────────────────────────────────
    c1_bull = (cl1 > o1) and (c1_body >= body_pct_thr) and (c1_cp >= press_hi) and c1_hvol
    c1_bear = (cl1 < o1) and (c1_body >= body_pct_thr) and (c1_cp <= press_lo) and c1_hvol
    c2_bull = (cl2 > o2) and (c2_body >= body_pct_thr)
    c2_bear = (cl2 < o2) and (c2_body >= body_pct_thr)

    direction: str | None = None
    if c1_bull and c2_bull:
        direction = "long"
    elif c1_bear and c2_bear:
        direction = "short"
    if direction is None:
        return None

    # ── Regime filter ────────────────────────────────────────────────────
    # When ``ignore_regime`` is True (research / counterfactual replay),
    # we skip the VIX / ADX / RSI gates entirely and only require the
    # core c1+c2 conviction. Production callers ALWAYS pass False — this
    # is a research-only escape hatch surfaced via the History page's
    # "Ignore regime gate" checkbox.
    if not ignore_regime:
        if vix_prev_close is None or vix_prev_close < vix_min:
            return None

    # Yesterday's daily row (no look-ahead — drop today). Compare on date
    # so this works regardless of whether the daily index is tz-naive
    # (smoke fixture) or tz-aware UTC (production data_service path).
    prev_idx = daily.index[daily.index.date < today]
    if len(prev_idx) == 0:
        return None
    prev_daily = daily.loc[prev_idx[-1]]
    rsi_d = float(prev_daily.get("rsi_14")) if pd.notna(prev_daily.get("rsi_14")) else None
    adx_d = float(prev_daily.get("adx_14")) if pd.notna(prev_daily.get("adx_14")) else None

    if not ignore_regime:
        if rsi_d is None or adx_d is None:
            return None
        if adx_d > adx_max:
            return None
        if direction == "long":
            if not (rsi_long_lo <= rsi_d <= rsi_long_hi):
                return None
        else:
            if not (rsi_short_lo <= rsi_d <= rsi_short_hi):
                return None

    # ── Levels ───────────────────────────────────────────────────────────
    entry = cl2
    if direction == "long":
        stop = round(entry * (1 - cat_stop_pct / 100.0), 2)
        # Nominal TPs — schema requires legs summing to 100%, but the
        # actual exit comes from the time-stop at 15:00 ET. These are
        # placeholders the executioner won't reach in normal sessions.
        tp1 = round(entry * (1 + 2 * cat_stop_pct / 100.0), 2)
        tp2 = round(entry * (1 + 3 * cat_stop_pct / 100.0), 2)
        invalidation_level = stop
    else:
        stop = round(entry * (1 + cat_stop_pct / 100.0), 2)
        tp1 = round(entry * (1 - 2 * cat_stop_pct / 100.0), 2)
        tp2 = round(entry * (1 - 3 * cat_stop_pct / 100.0), 2)
        invalidation_level = stop

    invalidation_condition = (
        f"price hits {cat_stop_pct:.1f}% catastrophic stop "
        f"OR session reaches 15:00 ET (time-stop)"
    )

    # ── PQS scoring ──────────────────────────────────────────────────────
    # Backtested WR 82.4% (CI 65-100%); base scores high on a clean fire.
    pqs_base = 70
    modifiers: dict[str, int] = {
        "filter_match": 10,                                 # all 4 filters cleared
    }
    # Reward stronger regime alignment
    if vix_prev_close >= 25:
        modifiers["vix_strong_regime"] = 5
    if adx_d <= 25:
        modifiers["adx_low_regime"] = 5
    if direction == "long" and 45 <= rsi_d <= 60:
        modifiers["rsi_sweet_spot"] = 5
    if direction == "short" and 25 <= rsi_d <= 35:
        modifiers["rsi_sweet_spot"] = 5
    if c1_body >= 0.7:                                      # very strong c1 body
        modifiers["c1_strong_body"] = 3
    if v1 >= 1.5 * slot_med:                                # very high volume
        modifiers["c1_strong_volume"] = 3

    pqs_total = min(100, pqs_base + sum(modifiers.values()))

    evidence = [
        {"type": "pattern", "ref": (
            f"c1 9:30: dir={'BULL' if direction == 'long' else 'BEAR'} "
            f"body={c1_body:.2f} press={c1_cp:.2f} "
            f"vol_mult={v1/slot_med:.2f}x"
        )},
        {"type": "pattern", "ref": (
            f"c2 10:00: dir={'BULL' if direction == 'long' else 'BEAR'} "
            f"body={c2_body:.2f}"
        )},
        {"type": "regime", "ref": f"vix_prev={vix_prev_close:.2f}  adx14={adx_d:.1f}  rsi14={rsi_d:.1f}"},
        {"type": "exit", "ref": (
            f"entry={entry:.2f}  stop={stop:.2f} ({cat_stop_pct:.1f}%)  "
            f"time_stop=15:00 ET"
        )},
    ]

    return PatternResult(
        pattern_name=PATTERN_NAME,
        direction=direction,                  # type: ignore[arg-type]
        pqs_base=pqs_base,
        pqs_modifiers=modifiers,
        pqs_total=pqs_total,
        entry_price=round(entry, 2),
        stop_price=stop,
        tp1_price=tp1,
        tp2_price=tp2,
        invalidation_level=invalidation_level,
        invalidation_condition=invalidation_condition,
        evidence_items=evidence,
    )
