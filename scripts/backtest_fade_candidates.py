"""backtest_fade_candidates.py — validate the two range-FADE day-trade candidates
that survived transcript assessment:

  opening_range_fade (6WfTIyJ-YzQ) — if the first 15m (3x5m) opening range is
    "over-extended" (range >= atr_frac * dailyATR), fade the opening candle's
    direction back toward the range; stop beyond the OR extreme, target the
    opposite OR side.

  false_break_fade (2WmeKqsGTQk) — define the first `range_hrs` of the session;
    a 5m body closes OUTSIDE the range then a later 5m body closes back INSIDE
    -> fade toward the opposite range edge; stop at the breakout extreme, 2R.

Reuses the shared simulate_trades / summarize / cost model. FX 5m + gold, IS/OOS,
gross + net. PASS bar: PF>=1.3 net, avg-R>0, ~100+ trades, beats control.

    python -m scripts.backtest_fade_candidates --since 2015-01-01 --oos 2022-01-01
"""
from __future__ import annotations

import argparse
import numpy as np
import pandas as pd
from pathlib import Path

from agents.detectors.external._base import Signal, simulate_trades, summarize_trades
from scripts.backtest_prospects import load_bars, _apply_cost, PIP

COST_PIPS = {"XAUUSD": 2.0, "EURUSD": 0.7, "GBPUSD": 0.8, "AUDUSD": 0.8}


def _daily_atr(bars: pd.DataFrame, period: int = 14) -> pd.Series:
    d = bars.resample("1D").agg(high=("high", "max"), low=("low", "min"),
                                close=("close", "last")).dropna()
    pc = d["close"].shift(1)
    tr = np.maximum.reduce([d["high"] - d["low"], (d["high"] - pc).abs(),
                            (d["low"] - pc).abs()])
    atr = pd.Series(tr, index=d.index).ewm(span=period, adjust=False).mean()
    return atr


def _day_groups(bars: pd.DataFrame):
    date = bars.index.normalize()
    groups: dict = {}
    for pos, dd in enumerate(date):
        groups.setdefault(dd, []).append(pos)
    return groups


def opening_range_fade(bars, pip, *, open_hour=13, or_bars=3, atr_frac=0.20,
                       tgt="opp", buf_pips=2.0, hold_hours=6) -> list[Signal]:
    o = bars["open"].to_numpy(); h = bars["high"].to_numpy()
    l = bars["low"].to_numpy(); c = bars["close"].to_numpy()
    hour = bars.index.hour.to_numpy()
    atr = _daily_atr(bars)
    atr_map = {ts.normalize(): v for ts, v in atr.items()}
    sigs = []; hold = hold_hours * 12; buf = buf_pips * pip
    for d, rows in _day_groups(bars).items():
        rows = np.array(rows)
        da = atr_map.get(d)
        if not da or da <= 0:
            continue
        open_rows = rows[hour[rows] == open_hour]
        if len(open_rows) < or_bars + 1:
            continue
        orr = open_rows[:or_bars]
        or_hi = h[orr].max(); or_lo = l[orr].min(); rng = or_hi - or_lo
        if rng < atr_frac * da:
            continue
        last = orr[-1]
        up = c[last] > o[orr[0]]           # opening candle direction
        entry = c[last]
        if up:  # extended up -> fade short
            stop = or_hi + buf
            target = or_lo if tgt == "opp" else entry - rng
            if stop > entry and target < entry:
                sigs.append(Signal(int(last), "short", entry, stop, target,
                                   time_stop_bars=hold, note="orfade_short"))
        else:   # extended down -> fade long
            stop = or_lo - buf
            target = or_hi if tgt == "opp" else entry + rng
            if stop < entry and target > entry:
                sigs.append(Signal(int(last), "long", entry, stop, target,
                                   time_stop_bars=hold, note="orfade_long"))
    sigs.sort(key=lambda s: s.bar_idx)
    return sigs


def false_break_fade(bars, pip, *, open_hour=13, range_hrs=4, rr=2.0,
                     buf_pips=2.0, hold_hours=6) -> list[Signal]:
    o = bars["open"].to_numpy(); h = bars["high"].to_numpy()
    l = bars["low"].to_numpy(); c = bars["close"].to_numpy()
    hour = bars.index.hour.to_numpy()
    sigs = []; rbars = range_hrs * 12; hold = hold_hours * 12; buf = buf_pips * pip
    for d, rows in _day_groups(bars).items():
        rows = np.array(rows)
        open_rows = rows[hour[rows] >= open_hour]
        if len(open_rows) < rbars + 4:
            continue
        rng_rows = open_rows[:rbars]
        r_hi = h[rng_rows].max(); r_lo = l[rng_rows].min()
        after = open_rows[rbars:rbars + hold]
        broke = None; ext = None
        for j in after:
            if broke is None:
                if c[j] > r_hi:
                    broke, ext = "up", h[j]
                elif c[j] < r_lo:
                    broke, ext = "down", l[j]
                continue
            ext = max(ext, h[j]) if broke == "up" else min(ext, l[j])
            # close back inside the range -> fade
            if broke == "up" and c[j] < r_hi:
                entry = c[j]; stop = ext + buf
                if stop > entry:
                    target = entry - rr * (stop - entry)
                    sigs.append(Signal(int(j), "short", entry, stop, target,
                                       time_stop_bars=hold, note="fbf_short"))
                break
            if broke == "down" and c[j] > r_lo:
                entry = c[j]; stop = ext - buf
                if stop < entry:
                    target = entry + rr * (entry - stop)
                    sigs.append(Signal(int(j), "long", entry, stop, target,
                                       time_stop_bars=hold, note="fbf_long"))
                break
    sigs.sort(key=lambda s: s.bar_idx)
    return sigs


def control_fade(bars, pip, *, open_hour=13, **kw) -> list[Signal]:
    """Baseline: fade the opening candle every day, no ATR/break filter, 1:1."""
    o = bars["open"].to_numpy(); c = bars["close"].to_numpy(); h = bars["high"].to_numpy()
    l = bars["low"].to_numpy(); hour = bars.index.hour.to_numpy()
    sigs = []
    for d, rows in _day_groups(bars).items():
        rows = np.array(rows); orr = rows[hour[rows] == open_hour][:3]
        if len(orr) < 3:
            continue
        last = orr[-1]; rng = h[orr].max() - l[orr].min()
        if rng <= 0:
            continue
        up = c[last] > o[orr[0]]; entry = c[last]
        if up:
            sigs.append(Signal(int(last), "short", entry, entry+rng, entry-rng, time_stop_bars=72))
        else:
            sigs.append(Signal(int(last), "long", entry, entry-rng, entry+rng, time_stop_bars=72))
    return sigs


DETECTORS = {"opening_range_fade": opening_range_fade,
             "false_break_fade": false_break_fade,
             "control_fade": control_fade}


def score(bars, sigs, lo, hi, cost, pip):
    sub = [s for s in sigs if lo <= bars.index[s.bar_idx] < hi]
    tr = simulate_trades(bars, sub)
    g = summarize_trades(tr); n = summarize_trades(_apply_cost(tr, cost, pip))
    return g, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2015-01-01")
    ap.add_argument("--oos", default="2022-01-01")
    ap.add_argument("--symbols", default="EURUSD,GBPUSD,AUDUSD,XAUUSD")
    ap.add_argument("--open-hour", type=int, default=13)   # ~NY open UTC
    ap.add_argument("--out", default="data/research/fade_candidates.md")
    a = ap.parse_args()
    syms = [s.strip().upper() for s in a.symbols.split(",")]
    since = pd.Timestamp(a.since, tz="UTC"); split = pd.Timestamp(a.oos, tz="UTC")
    end = pd.Timestamp("2100-01-01", tz="UTC")
    data = {s: load_bars(s, "5m", a.since) for s in syms}
    for s in syms:
        print(f"loaded {s}: {len(data[s]):,} bars")

    lines = ["# Fade candidate backtest — FX 5m + gold\n",
             f"open_hour={a.open_hour}UTC · IS<{a.oos}<=OOS · net of per-asset spread\n",
             "| strategy | scope | N | WR% | PF gross | PF net | avgR |",
             "|---|---|--:|--:|--:|--:|--:|"]
    for name, fn in DETECTORS.items():
        print(f"\n## {name}")
        pool = {"full": [], "OOS": []}
        for s in syms:
            bars = data[s]; pip = PIP.get(s, 0.0001); cost = COST_PIPS.get(s, 0.8)
            sigs = fn(bars, pip, open_hour=a.open_hour)
            for scope, lo, hi in [("full", since, end), ("OOS", split, end)]:
                g, n = score(bars, sigs, lo, hi, cost, pip)
                pool[scope].append((g, n))
                if scope == "OOS":
                    print(f"  {s:7} OOS N={n['n_trades']:>4} WR={n['wr_pct']:>5} "
                          f"PFg={g['profit_factor']:>6} PFnet={n['profit_factor']:>6}")
                lines.append(f"| {name} | {s} {scope} | {n['n_trades']} | {n['wr_pct']} | "
                             f"{g['profit_factor']} | {n['profit_factor']} | {n['avg_r_multiple']} |")
        for scope in ("full", "OOS"):
            gs = [g for g, n in pool[scope]]; ns = [n for g, n in pool[scope]]
            N = sum(x["n_trades"] for x in ns)
            gp = sum(x["gross_profit_usd"] for x in ns); gl = sum(x["gross_loss_usd"] for x in ns)
            wins = sum(x["wins"] for x in ns)
            pf = round(gp/gl, 3) if gl > 0 else 999
            wr = round(wins/N*100, 2) if N else 0
            avgr = round(sum(x["avg_r_multiple"]*x["n_trades"] for x in ns)/N, 3) if N else 0
            print(f"  POOLED {scope:4} N={N:>5} WR={wr:>5} PFnet={pf:>6} avgR={avgr:>6}")
            lines.append(f"| **{name}** | **POOLED {scope}** | **{N}** | **{wr}** | | **{pf}** | **{avgr}** |")
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nreport -> {out}")


if __name__ == "__main__":
    main()
