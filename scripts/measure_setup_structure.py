"""Stage 2: measure pre-breakout structure for each labeled event.

For every breakout event in `data/breakout_events.csv`, rewind to its
anchor_date and compute a battery of structural features from the
preceding 180 bars. One row per event, wide CSV for pivot analysis.

Features computed (all relative to anchor bar):
    # Base geometry
    base_len_25pct:      bars since last close < anchor_close × 0.75
    base_len_15pct:      bars since last close < anchor_close × 0.85
    base_len_10pct:      bars since last close < anchor_close × 0.90
    max_drawdown_180:    (anchor - min_close_180) / anchor
    max_drawdown_base:   (anchor - min_close_in_25pct_base) / anchor

    # Resistance / touch structure
    swing_high_count:    pivot highs in last 180 bars
    touches_near_anchor: pivot highs within 2%/5%/10% of anchor close

    # Contraction
    first_depth_pct:     deepest pivot-pair depth in base, first occurrence
    final_depth_pct:     deepest pivot-pair depth, last occurrence
    compression:         final_depth / first_depth

    # Volatility
    atr_pct:             atr_14 / close at anchor
    atr_ratio_now_vs_180: atr_14[anchor] / atr_14[anchor-180]
    atr_ratio_now_vs_60: atr_14[anchor] / atr_14[anchor-60]

    # Volume
    vol_ratio_30_180:    vol_avg_30 / vol_avg_180
    vol_ratio_10_50:     vol_avg_10 / vol_avg_50
    anchor_vol_vs_avg:   anchor_volume / vol_avg_50

    # Trend context
    close_vs_sma50:      close / sma_50
    close_vs_sma200:     close / sma_200
    sma50_vs_sma200:     sma_50 / sma_200
    sma50_slope_60:      (sma_50 - sma_50[-60]) / sma_50[-60]
    pct_of_52w_high:     close / high_52w
    pct_above_52w_low:   (close - low_52w) / low_52w

    # Momentum
    rsi_14:              rsi at anchor
    run_up_60:           close / close[-60]
    run_up_180:          close / close[-180]

Run locally from the project root:
    python -m scripts.measure_setup_structure
    python -m scripts.measure_setup_structure --gain 0.50 --window 120
    python -m scripts.measure_setup_structure --gain 0.50 --window 120 --csv fifty_in_120.csv

Without a filter, measures ALL 13k+ events. With a filter, only the
matching ones. ~5-10 minutes local runtime for the full set.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

from agents.detectors._helpers import swing_high_indices, swing_low_indices
from services.data_service import get_bars
from services.indicator_service import add_indicators
from services.settings_service import DATA_DIR


LOOKBACK = 180  # fixed analysis window; base_len features are dynamic within


def _safe_div(a, b, default=np.nan):
    try:
        return float(a) / float(b) if b not in (0, 0.0) and not pd.isna(b) else default
    except Exception:
        return default


def _base_len(closes: np.ndarray, anchor: float, drawdown: float) -> int:
    """Bars since the last close that was >= drawdown below anchor.
    drawdown is fractional (0.25 = -25%). Returns len(closes) if no such
    bar exists within the window (i.e. base extends back to the start)."""
    threshold = anchor * (1.0 - drawdown)
    # Walk backward
    for k in range(1, len(closes) + 1):
        if closes[-k] < threshold:
            return k - 1
    return len(closes)


def _first_last_depth(
    highs: np.ndarray, lows: np.ndarray,
    ph_idx: list[int], pl_idx: list[int],
) -> tuple[float, float, int]:
    """Pair each pivot high with its immediately following pivot low.
    Return (first_depth_pct, last_depth_pct, num_pairs). 0 pairs → NaN."""
    depths = []
    for i, ph_i in enumerate(ph_idx):
        next_ph_i = ph_idx[i + 1] if i + 1 < len(ph_idx) else 10**9
        for pl_i in pl_idx:
            if pl_i > ph_i and pl_i < next_ph_i:
                ph = highs[ph_i]
                pl = lows[pl_i]
                if ph > 0:
                    depths.append((ph - pl) / ph)
                break
    if not depths:
        return float("nan"), float("nan"), 0
    return depths[0], depths[-1], len(depths)


def measure_event(df: pd.DataFrame, anchor_ts: pd.Timestamp) -> dict | None:
    """Compute all features for one event. Returns None if insufficient history.

    ``anchor_ts`` is parsed from anchor_date (a calendar date string).
    US daily bars are indexed at 04:00 or 05:00 UTC (midnight Eastern),
    so a naive ``searchsorted(anchor_ts_midnight)`` snaps to the PRIOR
    trading day. Fix: search at end-of-day so we match the actual bar
    stamped on the anchor date.
    """
    anchor_date = anchor_ts.date()
    end_of_day = pd.Timestamp(anchor_date, tz="UTC") + pd.Timedelta(
        hours=23, minutes=59, seconds=59,
    )
    try:
        idx_pos = df.index.searchsorted(end_of_day, side="right") - 1
        if idx_pos < 0:
            return None
        anchor_ts = df.index[idx_pos]
    except Exception:
        return None
    # If the snapped bar is more than a few trading days before the
    # anchor date, this anchor has no matching bar in our data.
    if (anchor_date - anchor_ts.date()).days > 5:
        return None

    pos = df.index.get_loc(anchor_ts)
    if pos < LOOKBACK:
        return None

    window = df.iloc[pos - LOOKBACK + 1 : pos + 1]  # LOOKBACK bars ending at anchor
    last = window.iloc[-1]
    anchor = float(last["close"])
    if anchor <= 0:
        return None

    closes = window["close"].to_numpy()
    highs = window["high"].to_numpy()
    lows = window["low"].to_numpy()
    vols = window["volume"].to_numpy()

    # Full symbol history up to anchor (for SMA/RSI/ATR stability)
    full_up_to = df.iloc[: pos + 1]

    # Base lengths at three pullback thresholds
    bl_25 = _base_len(closes, anchor, 0.25)
    bl_15 = _base_len(closes, anchor, 0.15)
    bl_10 = _base_len(closes, anchor, 0.10)

    # Drawdown
    min_close_180 = float(closes.min())
    max_dd_180 = (anchor - min_close_180) / anchor
    if bl_25 > 0:
        base_closes = closes[-bl_25:]
        max_dd_base = (anchor - float(base_closes.min())) / anchor
    else:
        max_dd_base = 0.0

    # Pivot structure over the 180-bar window
    win_highs = pd.Series(highs)
    win_lows = pd.Series(lows)
    ph_idx = swing_high_indices(win_highs, 5, 5)
    pl_idx = swing_low_indices(win_lows, 5, 5)

    swing_high_count = len(ph_idx)

    # Touches near anchor close
    touches_2 = sum(1 for i in ph_idx if abs(highs[i] - anchor) / anchor <= 0.02)
    touches_5 = sum(1 for i in ph_idx if abs(highs[i] - anchor) / anchor <= 0.05)
    touches_10 = sum(1 for i in ph_idx if abs(highs[i] - anchor) / anchor <= 0.10)

    # Contraction (first & last H→L depth pair)
    first_d, last_d, n_pairs = _first_last_depth(highs, lows, ph_idx, pl_idx)
    compression = _safe_div(last_d, first_d)

    # Volatility
    atr_now = float(last.get("atr_14", np.nan))
    atr_pct = _safe_div(atr_now, anchor)
    atr_180 = float(full_up_to["atr_14"].iloc[-LOOKBACK]) if len(full_up_to) >= LOOKBACK else np.nan
    atr_60 = float(full_up_to["atr_14"].iloc[-60]) if len(full_up_to) >= 60 else np.nan
    atr_ratio_180 = _safe_div(atr_now, atr_180)
    atr_ratio_60 = _safe_div(atr_now, atr_60)

    # Volume
    vol_avg_10 = float(pd.Series(vols[-10:]).mean())
    vol_avg_30 = float(pd.Series(vols[-30:]).mean())
    vol_avg_50 = float(pd.Series(vols[-50:]).mean())
    vol_avg_180 = float(pd.Series(vols).mean())
    vol_ratio_30_180 = _safe_div(vol_avg_30, vol_avg_180)
    vol_ratio_10_50 = _safe_div(vol_avg_10, vol_avg_50)
    anchor_vol = float(last["volume"])
    anchor_vol_vs_avg = _safe_div(anchor_vol, vol_avg_50)

    # Trend context
    sma50 = float(last.get("sma_50", np.nan))
    sma200 = float(last.get("sma_200", np.nan))
    close_vs_sma50 = _safe_div(anchor, sma50)
    close_vs_sma200 = _safe_div(anchor, sma200)
    sma50_vs_sma200 = _safe_div(sma50, sma200)
    sma50_60_ago = float(full_up_to["sma_50"].iloc[-60]) if len(full_up_to) >= 60 else np.nan
    sma50_slope = _safe_div(sma50 - sma50_60_ago, sma50_60_ago)

    # 52-week high/low positioning (use last 252 bars of full history)
    if len(full_up_to) >= 252:
        hi52 = float(full_up_to["high"].iloc[-252:].max())
        lo52 = float(full_up_to["low"].iloc[-252:].min())
    else:
        hi52 = float(full_up_to["high"].max())
        lo52 = float(full_up_to["low"].min())
    pct_of_52w_high = _safe_div(anchor, hi52)
    pct_above_52w_low = _safe_div(anchor - lo52, lo52)

    # Momentum
    rsi = float(last.get("rsi_14", np.nan))
    c_60 = float(full_up_to["close"].iloc[-60]) if len(full_up_to) >= 60 else np.nan
    c_180 = float(full_up_to["close"].iloc[-LOOKBACK]) if len(full_up_to) >= LOOKBACK else np.nan
    run_up_60 = _safe_div(anchor, c_60)
    run_up_180 = _safe_div(anchor, c_180)

    # ── Tier-2 bar-derived features (Phase 1 extension) ─────────────
    # OHLCV-only features beyond simple trend / MAs. Designed to
    # capture who "won" each bar (wick geometry), where bars closed
    # in their range (CPR), overnight momentum via gaps, and a bar-
    # level accumulation proxy (up-vs-down volume share).
    opens = window["open"].to_numpy()
    ranges = highs - lows
    safe_ranges = np.where(ranges > 0, ranges, np.nan)

    # Wick ratios (0 = no wick, 1 = all wick)
    # Clip to [0, 1] — yfinance auto-adjusted data sometimes produces
    # bars where adjusted close > adjusted high (or similar) due to
    # split-rounding artifacts in older history. Without clipping,
    # those outliers wreck percentile estimates downstream.
    upper_wicks = highs - np.maximum(opens, closes)
    lower_wicks = np.minimum(opens, closes) - lows
    upper_wick_ratios = np.clip(
        np.where(ranges > 0, upper_wicks / safe_ranges, 0.0), 0.0, 1.0,
    )
    lower_wick_ratios = np.clip(
        np.where(ranges > 0, lower_wicks / safe_ranges, 0.0), 0.0, 1.0,
    )
    anchor_upper_wick = float(upper_wick_ratios[-1])
    anchor_lower_wick = float(lower_wick_ratios[-1])
    avg_upper_wick_20 = float(np.nanmean(upper_wick_ratios[-20:]))
    avg_lower_wick_20 = float(np.nanmean(lower_wick_ratios[-20:]))

    # Close position in range — 0=close at day low, 1=close at day high
    # Same clipping rationale as above.
    cpr_arr = np.clip(
        np.where(ranges > 0, (closes - lows) / safe_ranges, 0.5), 0.0, 1.0,
    )
    anchor_cpr = float(cpr_arr[-1])
    avg_cpr_20 = float(np.nanmean(cpr_arr[-20:]))

    # Gap analysis — overnight open vs prior close (filter 0.5% noise)
    if len(opens) >= 61:
        prior_closes_60 = closes[-61:-1]
        cur_opens_60 = opens[-60:]
        gap_pcts = (cur_opens_60 - prior_closes_60) / prior_closes_60
        gap_up_count_60 = int(np.sum(gap_pcts > 0.005))
        gap_down_count_60 = int(np.sum(gap_pcts < -0.005))
        largest_gap_up_60 = float(np.max(gap_pcts))
    else:
        gap_up_count_60 = 0
        gap_down_count_60 = 0
        largest_gap_up_60 = 0.0

    # Up-volume share over last 60 bars (accumulation proxy)
    up_mask_60 = closes[-60:] > opens[-60:]
    total_vol_60 = float(vols[-60:].sum())
    up_vol_share_60 = (
        float(vols[-60:][up_mask_60].sum() / total_vol_60)
        if total_vol_60 > 0 else 0.5
    )

    return {
        # Base geometry
        "base_len_25pct":       bl_25,
        "base_len_15pct":       bl_15,
        "base_len_10pct":       bl_10,
        "max_dd_180":           round(max_dd_180, 4),
        "max_dd_base":          round(max_dd_base, 4),

        # Resistance structure
        "swing_high_count":     swing_high_count,
        "touches_within_2pct":  touches_2,
        "touches_within_5pct":  touches_5,
        "touches_within_10pct": touches_10,

        # Contraction
        "n_contraction_pairs":  n_pairs,
        "first_depth_pct":      round(first_d, 4) if not pd.isna(first_d) else None,
        "final_depth_pct":      round(last_d, 4)  if not pd.isna(last_d) else None,
        "compression":          round(compression, 4) if not pd.isna(compression) else None,

        # Volatility
        "atr_pct":              round(atr_pct, 4) if not pd.isna(atr_pct) else None,
        "atr_ratio_now_vs_180": round(atr_ratio_180, 4) if not pd.isna(atr_ratio_180) else None,
        "atr_ratio_now_vs_60":  round(atr_ratio_60, 4) if not pd.isna(atr_ratio_60) else None,

        # Volume
        "vol_ratio_30_180":     round(vol_ratio_30_180, 4) if not pd.isna(vol_ratio_30_180) else None,
        "vol_ratio_10_50":      round(vol_ratio_10_50, 4) if not pd.isna(vol_ratio_10_50) else None,
        "anchor_vol_vs_avg":    round(anchor_vol_vs_avg, 4) if not pd.isna(anchor_vol_vs_avg) else None,

        # Trend context
        "close_vs_sma50":       round(close_vs_sma50, 4) if not pd.isna(close_vs_sma50) else None,
        "close_vs_sma200":      round(close_vs_sma200, 4) if not pd.isna(close_vs_sma200) else None,
        "sma50_vs_sma200":      round(sma50_vs_sma200, 4) if not pd.isna(sma50_vs_sma200) else None,
        "sma50_slope_60":       round(sma50_slope, 4) if not pd.isna(sma50_slope) else None,
        "pct_of_52w_high":      round(pct_of_52w_high, 4) if not pd.isna(pct_of_52w_high) else None,
        "pct_above_52w_low":    round(pct_above_52w_low, 4) if not pd.isna(pct_above_52w_low) else None,

        # Momentum
        "rsi_14":               round(rsi, 2) if not pd.isna(rsi) else None,
        "run_up_60":            round(run_up_60, 4) if not pd.isna(run_up_60) else None,
        "run_up_180":           round(run_up_180, 4) if not pd.isna(run_up_180) else None,

        # Wick geometry (Phase 1 extension)
        "anchor_upper_wick":    round(anchor_upper_wick, 4),
        "anchor_lower_wick":    round(anchor_lower_wick, 4),
        "avg_upper_wick_20":    round(avg_upper_wick_20, 4),
        "avg_lower_wick_20":    round(avg_lower_wick_20, 4),

        # Close position in range (Phase 1)
        "anchor_cpr":           round(anchor_cpr, 4),
        "avg_cpr_20":           round(avg_cpr_20, 4),

        # Gap analysis (Phase 1)
        "gap_up_count_60":      gap_up_count_60,
        "gap_down_count_60":    gap_down_count_60,
        "largest_gap_up_60":    round(largest_gap_up_60, 4),

        # Up volume share (Phase 1)
        "up_vol_share_60":      round(up_vol_share_60, 4),
    }


async def _process_symbol(symbol: str, events_for_symbol: pd.DataFrame) -> list[dict]:
    try:
        df = await get_bars(symbol, "1d", min_bars=LOOKBACK + 50)
    except Exception as e:
        print(f"  {symbol}: load failed ({e})")
        return []
    df = add_indicators(df)

    out = []
    for _, ev in events_for_symbol.iterrows():
        anchor_ts = pd.Timestamp(ev["anchor_date"], tz="UTC")
        features = measure_event(df, anchor_ts)
        if features is None:
            continue
        out.append({**ev.to_dict(), **features})
    return out


async def _main(args: argparse.Namespace) -> int:
    events = pd.read_csv(args.input)
    if args.gain is not None and args.window is not None:
        n_before = len(events)
        events = events[
            (events["gain_threshold"].astype(float) == float(args.gain)) &
            (events["forward_window"].astype(int) == int(args.window))
        ]
        print(f"Filtered to gain={args.gain}, window={args.window}: "
              f"{len(events):,} of {n_before:,} events")

    if events.empty:
        print("No events match the filter.")
        return 1

    print(f"Measuring structure for {len(events):,} events "
          f"across {events['symbol'].nunique()} symbols "
          f"(fixed {LOOKBACK}-bar lookback per event)...")

    by_symbol: dict[str, pd.DataFrame] = {
        sym: group for sym, group in events.groupby("symbol")
    }

    all_rows: list[dict] = []
    for i, (sym, group) in enumerate(by_symbol.items(), 1):
        rows = await _process_symbol(sym, group)
        all_rows.extend(rows)
        print(f"  [{i:>2}/{len(by_symbol)}] {sym}: {len(rows)} events measured")

    if not all_rows:
        print("No rows produced.")
        return 1

    out_path = args.csv or (DATA_DIR / "event_features.csv")
    out = pd.DataFrame(all_rows)
    out.to_csv(out_path, index=False)
    print(f"\nWrote {len(out):,} rows with "
          f"{len([c for c in out.columns if c not in events.columns])} feature "
          f"columns to {out_path}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", default=str(DATA_DIR / "breakout_events.csv"))
    p.add_argument("--csv", default=None,
                   help="Output path (default data/event_features.csv)")
    p.add_argument("--gain", type=float, default=None,
                   help="Filter to this gain_threshold (e.g. 0.50)")
    p.add_argument("--window", type=int, default=None,
                   help="Filter to this forward_window (e.g. 120)")
    args = p.parse_args()
    return asyncio.run(_main(args))


if __name__ == "__main__":
    sys.exit(main())
