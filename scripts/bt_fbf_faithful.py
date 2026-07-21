"""bt_fbf_faithful.py — re-test the 4-hour-range false-break fade (video 2WmeKqsGTQk)
against what the creator actually demonstrates, and isolate which implementation choice
(if any) was responsible for the original rejection.

The original harness (`scripts/backtest_fade_candidates.py::false_break_fade`) diverged
from the video in five ways. Each is a switch here, so we can attribute the result:

  1. **Session anchor.** The video marks the *first 4-hour candle of the New York day*,
     i.e. 00:00-04:00 ET, and fades breaks of it for the rest of the session. The old
     harness built the range from 13:00 UTC for four hours (09:00-13:00 ET) — it defined
     the "range" over the London/NY overlap, the most volatile block of the FX day, then
     faded breaks of it during the quieter afternoon. That inverts the setup's logic.
  2. **One trade per day.** The old harness `break`s after the first fade. The creator
     takes every re-entry the session offers (his own examples show 3-4 in a session).
  3. **Entry timing.** Old harness fills at the re-entry bar's close; this one fills at
     the next bar's open.
  4. **The >1% escape hatch.** The creator explicitly stops fading once price has run
     more than ~1% beyond the range ("we're no longer looking at a range reversal play")
     and switches to a trend trade. The old harness faded those too — the exact trades a
     trend day turns into maximum-size losers.
  5. **Stop placement.** Video: the extreme of the breakout move; when that is
     impractically far he uses a nearer structural level. Modelled here as an optional
     cap on risk in pips.

    python -m scripts.bt_fbf_faithful --variants all
"""
from __future__ import annotations

import argparse
import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from services.settings_service import DATA_DIR

HIST = DATA_DIR / "historical"
ET = "America/New_York"
PIP = {"EURUSD": 0.0001, "GBPUSD": 0.0001, "AUDUSD": 0.0001,
       "USDJPY": 0.01, "XAUUSD": 0.1}
COST_PIPS = {"EURUSD": 0.7, "GBPUSD": 0.8, "AUDUSD": 0.8, "USDJPY": 0.8, "XAUUSD": 2.0}


def load_et(symbol: str, since: str) -> pd.DataFrame:
    path = HIST / f"{symbol}_5m.csv"
    df = pd.read_csv(path)
    dc = df.columns[0]
    df[dc] = pd.to_datetime(df[dc], utc=True, errors="coerce")
    df = df.dropna(subset=[dc]).set_index(dc).sort_index().tz_convert(ET)
    df.columns = [c.lower() for c in df.columns]
    df = df[["open", "high", "low", "close"]]
    df = df[~df.index.duplicated(keep="first")]
    if since:
        df = df[df.index >= pd.Timestamp(since, tz=ET)]
    return df


@dataclass
class Trade:
    symbol: str; date: str; direction: str
    entry_ts: pd.Timestamp; exit_ts: pd.Timestamp
    entry: float; stop: float; target: float; exit_price: float
    reason: str; r: float


def _fill(sym, day, i, direction, stop, target_r, cost_pips, pip) -> Trade | None:
    o = day["open"].to_numpy(); h = day["high"].to_numpy()
    l = day["low"].to_numpy(); c = day["close"].to_numpy()
    if i >= len(day):
        return None
    entry = float(o[i])
    risk = entry - stop if direction == "long" else stop - entry
    if risk <= 0:
        return None
    target = entry + target_r * risk if direction == "long" else entry - target_r * risk
    exit_price, reason, xi = float(c[-1]), "eod", len(day) - 1
    for j in range(i, len(day)):
        if direction == "long":
            hs, ht = l[j] <= stop, h[j] >= target
        else:
            hs, ht = h[j] >= stop, l[j] <= target
        if hs:
            exit_price, reason, xi = stop, "stop", j; break
        if ht:
            exit_price, reason, xi = target, "tp", j; break
    gross = (exit_price - entry) if direction == "long" else (entry - exit_price)
    r = (gross - cost_pips * pip) / risk
    return Trade(sym, str(day.index[i].date()), direction, day.index[i], day.index[xi],
                 entry, stop, target, exit_price, reason, r)


def session_trades(sym, day, *, range_end_hour, target_r, multi, excursion_skip,
                   max_risk_pips, cost_pips, pip, rng=None) -> list[Trade]:
    """One NY calendar day of 5m bars. Range = 00:00 -> range_end_hour ET."""
    hrs = day.index.hour.to_numpy()
    rmask = hrs < range_end_hour
    if rmask.sum() < 24 or (~rmask).sum() < 12:
        return []
    rng_bars = day[rmask]
    r_hi = float(rng_bars["high"].max()); r_lo = float(rng_bars["low"].min())
    if r_hi <= r_lo:
        return []
    after = day[~rmask]
    c = after["close"].to_numpy(); h = after["high"].to_numpy(); l = after["low"].to_numpy()
    out: list[Trade] = []
    broke = None; ext = None
    for j in range(len(after) - 1):
        if broke is None:
            if c[j] > r_hi:
                broke, ext = "up", h[j]
            elif c[j] < r_lo:
                broke, ext = "down", l[j]
            continue
        ext = max(ext, h[j]) if broke == "up" else min(ext, l[j])
        back_in = (broke == "up" and c[j] < r_hi) or (broke == "down" and c[j] > r_lo)
        if not back_in:
            continue
        run = (ext - r_hi) / r_hi if broke == "up" else (r_lo - ext) / r_lo
        direction = "short" if broke == "up" else "long"
        stop = float(ext)
        skip = bool(excursion_skip) and run > excursion_skip
        if max_risk_pips:                       # cap an impractically wide stop
            entry_ref = float(after["open"].to_numpy()[j + 1])
            if abs(entry_ref - stop) > max_risk_pips * pip:
                stop = (entry_ref + max_risk_pips * pip if direction == "short"
                        else entry_ref - max_risk_pips * pip)
        if not skip:
            d = direction if rng is None else ("long" if rng.random() < 0.5 else "short")
            t = _fill(sym, after, j + 1, d, stop, target_r, cost_pips, pip)
            if t is not None:
                out.append(t)
        broke, ext = None, None
        if not multi:
            break
    return out


def run(symbols, since, *, range_end_hour, target_r, multi, excursion_skip,
        max_risk_pips, seed=None) -> list[Trade]:
    rng = random.Random(seed) if seed is not None else None
    trades: list[Trade] = []
    for sym in symbols:
        bars = load_et(sym, since)
        pip = PIP.get(sym, 0.0001); cost = COST_PIPS.get(sym, 0.8)
        for _, day in bars.groupby(bars.index.date):
            trades += session_trades(sym, day, range_end_hour=range_end_hour,
                                     target_r=target_r, multi=multi,
                                     excursion_skip=excursion_skip,
                                     max_risk_pips=max_risk_pips,
                                     cost_pips=cost, pip=pip, rng=rng)
    return trades


def pf(rs):
    w = sum(r for r in rs if r > 0); ls = -sum(r for r in rs if r <= 0)
    return round(w / ls, 3) if ls > 0 else 0.0


def summarize(ts):
    rs = [t.r for t in ts]; n = len(rs)
    return {"n": n, "wr": round(sum(1 for r in rs if r > 0) / n * 100, 1) if n else 0,
            "pf": pf(rs), "avg_r": round(float(np.mean(rs)), 4) if n else 0}


def per_year(ts):
    by = {}
    for t in ts:
        by.setdefault(t.date[:4], []).append(t.r)
    return "  ".join(f"{y}:{pf(rs):.2f}" for y, rs in sorted(by.items()))


VARIANTS = {
    # name: (range_end_hour ET, multi-trade, excursion_skip, max_risk_pips)
    "old_harness_anchor":  (13, False, 0.0, 0),     # 13:00 UTC-ish block, 1 trade/day
    "faithful_4h_ny":      (4,  True,  0.0, 0),     # video anchor, every re-entry
    "faithful_plus_skip":  (4,  True,  0.01, 0),    # + the creator's >1% no-fade rule
    "faithful_skip_cap":   (4,  True,  0.01, 25),   # + capped stop distance
    "london_anchor":       (3,  True,  0.01, 0),    # London open as the range end
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="EURUSD,GBPUSD,AUDUSD,XAUUSD")
    ap.add_argument("--since", default="2015-01-01")
    ap.add_argument("--oos", default="2021-01-01")
    ap.add_argument("--target-r", type=float, default=2.0)
    ap.add_argument("--variants", default="all")
    ap.add_argument("--control-seeds", type=int, default=3)
    ap.add_argument("--out", default="data/research/fbf_faithful.md")
    a = ap.parse_args()
    syms = [s.strip().upper() for s in a.symbols.split(",")]
    names = list(VARIANTS) if a.variants == "all" else a.variants.split(",")

    lines = ["# False-break fade — implementation-fidelity sweep\n",
             f"{syms} · 5m · since {a.since} · IS<{a.oos}<=OOS · net of per-asset spread · "
             f"entry at next bar open · target {a.target_r}R\n",
             "| variant | scope | N | WR% | PF | avgR |", "|---|---|--:|--:|--:|--:|"]
    for name in names:
        reh, multi, skip, cap = VARIANTS[name]
        print(f"\n## {name}  (range 00:00-{reh:02d} ET · multi={multi} · skip>{skip:.0%} · cap={cap or '-'})")
        ts = run(syms, a.since, range_end_hour=reh, target_r=a.target_r, multi=multi,
                 excursion_skip=skip, max_risk_pips=cap)
        oos = [t for t in ts if t.date >= a.oos]
        for scope, sub in (("FULL", ts), ("IS", [t for t in ts if t.date < a.oos]), ("OOS", oos)):
            m = summarize(sub)
            print(f"  {scope:5} N={m['n']:>5} WR={m['wr']:>5} PF={m['pf']:>6} avgR={m['avg_r']:>8}")
            lines.append(f"| {name} | {scope} | {m['n']} | {m['wr']} | {m['pf']} | {m['avg_r']} |")
        cp = []
        for s in range(a.control_seeds):
            ct = run(syms, a.since, range_end_hour=reh, target_r=a.target_r, multi=multi,
                     excursion_skip=skip, max_risk_pips=cap, seed=s)
            cp.append(summarize([t for t in ct if t.date >= a.oos])["pf"])
        print(f"  control OOS PF {np.mean(cp):.3f}  {[round(x,2) for x in cp]}")
        print(f"  per-year: {per_year(ts)}")
        lines.append(f"| {name} | CONTROL OOS | | | {np.mean(cp):.3f} | |")
        lines.append(f"\nper-year PF ({name}): `{per_year(ts)}`\n")
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nreport -> {out}")


if __name__ == "__main__":
    main()
