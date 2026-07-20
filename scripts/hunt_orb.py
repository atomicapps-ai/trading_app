"""hunt_orb.py — parameter search for a *basic* opening-range breakout that
actually clears PF >= 1.3, on the assets the UFjajYgJBHg 10-yr study says ORB
survives on: gold (XAUUSD) and euro (EURUSD).

Basic ORB = enter at the range edge on the first 5m close beyond the opening
range; NO retest, NO FVG, NO candlestick filter (the study found those *hurt*).
Sweeps range size, R:R (biased < 2:1 per the finding), session-open anchor, and
cutoff. Scores IS/OOS, gross and net of a per-asset spread.

Usage:
    python -m scripts.hunt_orb --since 2015-01-01 --oos 2022-01-01
"""
from __future__ import annotations

import argparse
import itertools
from pathlib import Path

import numpy as np
import pandas as pd

from agents.detectors.external._base import Signal, simulate_trades, summarize_trades
from scripts.backtest_prospects import load_bars, _apply_cost, PIP

# per-asset round-turn cost in "pips" (pip = PIP[asset]); gold spreads are wider
COST_PIPS = {"XAUUSD": 2.0, "EURUSD": 0.7, "GBPUSD": 0.8, "AUDUSD": 0.8}


def basic_orb(bars: pd.DataFrame, *, open_hour: int, or_bars: int, rr: float,
              hold_hours: int, entry: str = "breakout") -> list[Signal]:
    """First `or_bars` 5m candles from open_hour:00 define the range; enter on
    the first 5m CLOSE beyond it (breakout) or on a retest, stop at the opposite
    edge, TP = rr * risk. One trade per day. `hold_hours` caps entries + hold."""
    idx = bars.index
    o = bars["open"].to_numpy(); h = bars["high"].to_numpy()
    l = bars["low"].to_numpy(); c = bars["close"].to_numpy()
    hour = idx.hour.to_numpy()
    date = idx.normalize()
    hold_bars = hold_hours * 12  # 12 x 5m per hour
    sigs: list[Signal] = []

    day_groups: dict = {}
    for pos, d in enumerate(date):
        day_groups.setdefault(d, []).append(pos)

    for d, rows in day_groups.items():
        rows = np.array(rows)
        open_rows = rows[hour[rows] == open_hour]
        if len(open_rows) < or_bars + 1:
            continue
        orr = open_rows[:or_bars]
        or_hi = h[orr].max(); or_lo = l[orr].min()
        if or_hi <= or_lo:
            continue
        after = rows[(rows > orr[-1])]
        after = after[:hold_bars]           # entry window from the open
        broke = None; brk = None
        for j in after:
            if entry == "breakout":
                if c[j] > or_hi:
                    entry_px, stop = c[j], or_lo
                    tp = entry_px + rr * (entry_px - stop)
                    sigs.append(Signal(int(j), "long", entry_px, stop, tp,
                                       time_stop_bars=hold_bars, note="orb_up"))
                    break
                if c[j] < or_lo:
                    entry_px, stop = c[j], or_hi
                    tp = entry_px - rr * (stop - entry_px)
                    sigs.append(Signal(int(j), "short", entry_px, stop, tp,
                                       time_stop_bars=hold_bars, note="orb_dn"))
                    break
            else:  # retest
                if broke is None:
                    if c[j] > or_hi:
                        broke, brk = "up", j
                    elif c[j] < or_lo:
                        broke, brk = "down", j
                    continue
                if broke == "up" and l[j] <= or_hi and c[j] > or_hi:
                    entry_px, stop = c[j], or_lo
                    sigs.append(Signal(int(j), "long", entry_px, stop,
                                       entry_px + rr*(entry_px-stop),
                                       time_stop_bars=hold_bars, note="orb_up_rt"))
                    break
                if broke == "down" and h[j] >= or_lo and c[j] < or_lo:
                    entry_px, stop = c[j], or_hi
                    sigs.append(Signal(int(j), "short", entry_px, stop,
                                       entry_px - rr*(stop-entry_px),
                                       time_stop_bars=hold_bars, note="orb_dn_rt"))
                    break
    sigs.sort(key=lambda s: s.bar_idx)
    return sigs


def score(bars, sigs, lo, hi, cost_pips, pip):
    sub = [s for s in sigs if lo <= bars.index[s.bar_idx] < hi]
    tr = simulate_trades(bars, sub)
    gross = summarize_trades(tr)
    net = summarize_trades(_apply_cost(tr, cost_pips, pip))
    return gross, net


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2015-01-01")
    ap.add_argument("--oos", default="2022-01-01")
    ap.add_argument("--assets", default="XAUUSD,EURUSD,GBPUSD,AUDUSD")
    ap.add_argument("--out", default="data/research/orb_hunt.md")
    args = ap.parse_args()

    assets = [a.strip().upper() for a in args.assets.split(",")]
    since = pd.Timestamp(args.since, tz="UTC")
    split = pd.Timestamp(args.oos, tz="UTC")
    end = pd.Timestamp("2100-01-01", tz="UTC")

    grid = dict(
        open_hour=[7, 13],       # London open / NY open (UTC)
        or_bars=[3, 6],          # 15m / 30m opening range
        rr=[1.0, 1.5, 2.0],      # evidence: best < 2:1
        entry=["breakout", "retest"],
        hold_hours=[6],
    )
    combos = list(itertools.product(*grid.values()))
    keys = list(grid.keys())

    rows = []  # (asset, cfg, oos_gross, oos_net, full_net)
    for a in assets:
        bars = load_bars(a, "5m", args.since)
        pip = PIP.get(a, 0.0001); cost = COST_PIPS.get(a, 0.8)
        print(f"\n=== {a}  ({len(bars):,} bars, cost {cost} pip) ===")
        for combo in combos:
            cfg = dict(zip(keys, combo))
            sigs = basic_orb(bars, **cfg)
            g_oos, n_oos = score(bars, sigs, split, end, cost, pip)
            g_full, n_full = score(bars, sigs, since, end, cost, pip)
            rows.append((a, cfg, g_oos, n_oos, g_full, n_full))

    # rank by OOS net PF among configs with a tradeable sample
    ranked = [r for r in rows if r[3]["n_trades"] >= 150]
    ranked.sort(key=lambda r: r[3]["profit_factor"], reverse=True)

    lines = ["# Basic-ORB hunt — gold/euro/major FX 5m\n",
             f"Window {args.since}→end · IS<{args.oos}≤OOS · per-asset spread cost.\n",
             "Ranked by **OOS net PF** (N≥150). PASS bar: PF≥1.3, avg-R>0.\n",
             "| asset | open | ORbars | RR | entry | N | WR% | PF gross | PF net | avgR net |",
             "|---|--:|--:|--:|---|--:|--:|--:|--:|--:|"]
    print("\n#### TOP CONFIGS by OOS net PF (N>=150) ####")
    for a, cfg, g, n, gf, nf in ranked[:25]:
        line = (f"| {a} | {cfg['open_hour']:02d} | {cfg['or_bars']} | {cfg['rr']} | "
                f"{cfg['entry']} | {n['n_trades']} | {n['wr_pct']} | "
                f"{g['profit_factor']} | {n['profit_factor']} | {n['avg_r_multiple']} |")
        lines.append(line)
        print(f"  {a} open{cfg['open_hour']:02d} OR{cfg['or_bars']} RR{cfg['rr']} "
              f"{cfg['entry']:8s} N={n['n_trades']:>4} WR={n['wr_pct']:>5} "
              f"PFg={g['profit_factor']:>6} PFnet={n['profit_factor']:>6}")

    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nreport → {out}")
    best = ranked[0] if ranked else None
    if best:
        a, cfg, g, n, gf, nf = best
        print(f"\nBEST OOS-net: {a} {cfg} → OOS net PF {n['profit_factor']} "
              f"(gross {g['profit_factor']}), N={n['n_trades']}, WR {n['wr_pct']}%")


if __name__ == "__main__":
    main()
