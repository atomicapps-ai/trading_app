#!/usr/bin/env python
"""
Backtest of Strategy 2 — Double Lock (DL-S2)
=============================================
Replays the same entry rules as `scripts/pine/strategy2_DL.pine` against
15-min yfinance data resampled to 30-min bars.

Signal
------
  c1 (9:30 bar) : BULL.STR.HPRS.HVOL   or   BEAR.STR.LPRS.HVOL
  c2 (10:00 bar): same direction + STR body (HVOL optional)

Entry : close of c2 (i.e. 10:30 AM timestamp mark)
Exit  : first of (CATA_STOP hit intra-session) or (day-close)
Win   : exited in the favourable direction (positive R for long, negative R for short)

The backtest prints a baseline + a parameter sweep. Scanner found ~97-98%
hit-rate using these cutoffs:
  body_thr  = 0.5   (STR body)
  press_thr = 0.5   (HPRS / LPRS split)
  vol_mult  = 1.2   (HVOL = vol > 1.2 × slot median)
  stop_pct  = 3.0   (catastrophic stop from entry)

Run:  python -m scripts.backtest_strategy2_dl  [--symbols SPY NVDA ...]
"""
from __future__ import annotations

import argparse
import warnings
from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")
pd.set_option("display.width", 200)


# ── Data ─────────────────────────────────────────────────────────────────────
def download_15m(symbol: str, period: str = "60d") -> pd.DataFrame | None:
    df = yf.download(symbol, period=period, interval="15m",
                     progress=False, auto_adjust=True)
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert("America/New_York")
    return df


def resample_30m(df15: pd.DataFrame) -> pd.DataFrame:
    return (df15.resample("30min", closed="left", label="left")
            .agg(open=("open", "first"), high=("high", "max"),
                 low=("low", "min"), close=("close", "last"),
                 volume=("volume", "sum"))
            .dropna(subset=["open"]))


def slot_median_volume(df: pd.DataFrame) -> dict:
    out = {}
    for t in set(df.index.time):
        sub = df[df.index.time == t]
        if len(sub):
            out[t] = float(sub["volume"].median() or 1.0)
    return out


# ── Candle predicates ─────────────────────────────────────────────────────────
def body_pct(o: float, h: float, l: float, c: float) -> float:
    rng = h - l
    return abs(c - o) / rng if rng > 1e-9 else 0.0


def close_pct(h: float, l: float, c: float) -> float:
    rng = h - l
    return (c - l) / rng if rng > 1e-9 else 0.5


# ── Strategy ──────────────────────────────────────────────────────────────────
@dataclass
class Params:
    body_thr:  float = 0.5   # STR body threshold
    hprs_thr:  float = 0.5   # HPRS lower bound (scanner: 0.5; pine: 0.6)
    lprs_thr:  float = 0.5   # LPRS upper bound (scanner: 0.5; pine: 0.4)
    vol_mult:  float = 1.2   # HVOL multiplier vs slot median
    stop_pct:  float = 3.0   # catastrophic stop (%)

    def label(self) -> str:
        return (f"body≥{self.body_thr:.2f}  press≥{self.hprs_thr:.2f}/"
                f"≤{self.lprs_thr:.2f}  vol≥{self.vol_mult:.2f}×  stop={self.stop_pct:.2f}%")


@dataclass
class Trade:
    symbol:   str
    date:     str
    dir:      str          # LONG / SHORT
    entry:    float
    exit:     float
    exit_rsn: str          # STOP / EOD
    pnl_pct:  float        # signed pnl %
    win:      bool


def evaluate_day(sym: str, day: pd.Timestamp.date, df30_day: pd.DataFrame,
                 df15_day: pd.DataFrame, slot_avg: dict, p: Params) -> Trade | None:
    if len(df30_day) < 2:
        return None

    c1 = df30_day.iloc[0]
    c2 = df30_day.iloc[1]
    if c1.name.time().hour != 9 or c1.name.time().minute != 30:
        return None
    if c2.name.time().hour != 10 or c2.name.time().minute != 0:
        return None

    c1_o, c1_h, c1_l, c1_c, c1_v = [float(c1[k]) for k in ("open","high","low","close","volume")]
    c2_o, c2_h, c2_l, c2_c       = [float(c2[k]) for k in ("open","high","low","close")]

    c1_body = body_pct(c1_o, c1_h, c1_l, c1_c) >= p.body_thr
    c2_body = body_pct(c2_o, c2_h, c2_l, c2_c) >= p.body_thr
    c1_cp   = close_pct(c1_h, c1_l, c1_c)
    c1_hvol = c1_v >= slot_avg.get(c1.name.time(), 0.0) * p.vol_mult

    c1_bull = c1_c > c1_o and c1_body and c1_cp >= p.hprs_thr and c1_hvol
    c1_bear = c1_c < c1_o and c1_body and c1_cp <= p.lprs_thr and c1_hvol
    c2_bull = c2_c > c2_o and c2_body
    c2_bear = c2_c < c2_o and c2_body

    if c1_bull and c2_bull:
        direction = "LONG"
    elif c1_bear and c2_bear:
        direction = "SHORT"
    else:
        return None

    entry = c2_c
    stop_px = (entry * (1 - p.stop_pct/100) if direction == "LONG"
               else entry * (1 + p.stop_pct/100))

    # Walk the post-10:30 15-min bars until 15:30 EOD or stop is hit
    post = df15_day[(df15_day.index > c2.name) & (df15_day.index.time <= pd.Timestamp("15:59").time())]
    if post.empty:
        return None

    exit_px = None
    exit_rsn = "EOD"
    for _, bar in post.iterrows():
        hi, lo = float(bar["high"]), float(bar["low"])
        if direction == "LONG" and lo <= stop_px:
            exit_px, exit_rsn = stop_px, "STOP"
            break
        if direction == "SHORT" and hi >= stop_px:
            exit_px, exit_rsn = stop_px, "STOP"
            break
    if exit_px is None:
        exit_px = float(post.iloc[-1]["close"])

    raw = (exit_px - entry) / entry * 100
    pnl_pct = raw if direction == "LONG" else -raw

    return Trade(sym, str(day), direction, entry, exit_px, exit_rsn, pnl_pct, pnl_pct > 0)


def backtest(symbols: list[str], p: Params, period: str = "60d",
             cached: dict | None = None) -> tuple[list[Trade], dict]:
    cached = cached if cached is not None else {}
    trades: list[Trade] = []

    for sym in symbols:
        if sym in cached:
            df15 = cached[sym]
        else:
            df15 = download_15m(sym, period)
            cached[sym] = df15
        if df15 is None or df15.empty:
            continue

        df30 = resample_30m(df15)
        slot_avg = slot_median_volume(df30)

        for day in sorted(set(df15.index.date)):
            df15_day = df15[df15.index.date == day].between_time("09:30", "15:59")
            df30_day = df30[df30.index.date == day].between_time("09:30", "15:59")
            if len(df15_day) < 5 or len(df30_day) < 2:
                continue
            t = evaluate_day(sym, day, df30_day, df15_day, slot_avg, p)
            if t is not None:
                trades.append(t)

    if not trades:
        return trades, dict(n=0, win_rate=float("nan"), pf=float("nan"),
                            max_dd=float("nan"), avg_pnl=float("nan"),
                            stop_hit_rate=float("nan"))

    pnls = np.array([t.pnl_pct for t in trades])
    wins = pnls[pnls > 0].sum()
    losses = -pnls[pnls < 0].sum()
    pf = wins / losses if losses > 0 else float("inf")

    equity = np.cumsum(pnls)
    peak = np.maximum.accumulate(equity)
    dd = peak - equity
    max_dd = float(dd.max()) if len(dd) else 0.0

    stats = dict(
        n=len(trades),
        win_rate=float((pnls > 0).mean() * 100),
        pf=pf,
        max_dd=max_dd,
        avg_pnl=float(pnls.mean()),
        stop_hit_rate=float(sum(t.exit_rsn == "STOP" for t in trades) / len(trades) * 100),
    )
    return trades, stats


# ── Reporting ─────────────────────────────────────────────────────────────────
def print_stats(tag: str, stats: dict) -> None:
    if stats["n"] == 0:
        print(f"  {tag:<55}  n=0  (no signals)")
        return
    print(f"  {tag:<55}  n={stats['n']:3d}  win={stats['win_rate']:5.1f}%  "
          f"PF={stats['pf']:5.2f}  avg={stats['avg_pnl']:+.2f}%  "
          f"DD={stats['max_dd']:5.2f}%  stops={stats['stop_hit_rate']:4.1f}%")


def parameter_sweep(symbols: list[str]) -> None:
    cached: dict = {}
    print(f"\nUniverse: {symbols}   period: 60d   timeframe: 30-min")

    # Prime the cache once
    for s in symbols:
        cached[s] = download_15m(s)

    BAR = "-" * 72

    # 1. Baseline matching the Pine strategy defaults
    print("\n-- BASELINE (Pine defaults) " + BAR)
    p = Params(body_thr=0.5, hprs_thr=0.6, lprs_thr=0.4, vol_mult=1.0, stop_pct=3.0)
    _, s = backtest(symbols, p, cached=cached)
    print_stats(p.label(), s)

    # 2. Scanner-aligned (HPRS/LPRS 0.5, vol_mult 1.2)
    print("\n-- SCANNER-ALIGNED (matches scan_opening_patterns.py) " + BAR)
    p = Params(body_thr=0.5, hprs_thr=0.5, lprs_thr=0.5, vol_mult=1.2, stop_pct=3.0)
    _, s = backtest(symbols, p, cached=cached)
    print_stats(p.label(), s)

    # 3. Sweep stop width
    print("\n-- STOP-WIDTH SWEEP (scanner-aligned press & vol) " + BAR)
    for stop in (2.0, 3.0, 4.0, 5.0, 7.0, 10.0):
        p = Params(body_thr=0.5, hprs_thr=0.5, lprs_thr=0.5, vol_mult=1.2, stop_pct=stop)
        _, s = backtest(symbols, p, cached=cached)
        print_stats(p.label(), s)

    # 4. Sweep volume multiplier
    print("\n-- VOLUME-MULT SWEEP (stop=5%, press=0.5) " + BAR)
    for vm in (1.0, 1.2, 1.4, 1.6, 1.8, 2.0):
        p = Params(body_thr=0.5, hprs_thr=0.5, lprs_thr=0.5, vol_mult=vm, stop_pct=5.0)
        _, s = backtest(symbols, p, cached=cached)
        print_stats(p.label(), s)

    # 5. Sweep pressure threshold
    print("\n-- PRESSURE-THRESH SWEEP (stop=5%, vol=1.2) " + BAR)
    for press in (0.50, 0.55, 0.60, 0.65, 0.70):
        p = Params(body_thr=0.5, hprs_thr=press, lprs_thr=1-press, vol_mult=1.2, stop_pct=5.0)
        _, s = backtest(symbols, p, cached=cached)
        print_stats(p.label(), s)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+",
                    default=["SPY", "QQQ", "NVDA", "AAPL", "MSFT",
                             "META", "AMZN", "TSLA", "GOOGL"])
    args = ap.parse_args()
    parameter_sweep(args.symbols)


if __name__ == "__main__":
    main()
