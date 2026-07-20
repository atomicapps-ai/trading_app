"""bt_equity_open_setups.py — re-test the video-mined *equity-native* intraday setups
on real US-equity RTH 5-minute bars (09:30 ET anchor), instead of the FX stand-ins
that the original day_intra pass used.

Why this exists
---------------
`scripts/backtest_prospects.py` ran `orb_retest` (an SPY/QQQ/ES setup) on FX majors at a
London-open anchor because the project believed it had "no cached 5m equity data". That
belief is false: `data/historical/{SPY,QQQ,IWM,DIA}_5m.csv` hold ~421k RTH bars each
(2005-2026). Likewise `false_break_fade` / `opening_range_fade` were run on FX at a
13:00-UTC anchor although both source videos demonstrate them on stocks/indices around
the cash open.

This module re-implements those setups with an execution model a professional would
accept, so a rejection can be blamed on the strategy rather than the harness:

  * session anchored to **09:30 ET** (DST-aware via tz conversion), flat by 15:55 ET;
  * **entry at the NEXT bar's open** after the trigger bar closes (never the signal
    bar's close in hindsight);
  * stops/targets checked intrabar on High/Low, and when a bar touches both the
    stop resolves first (conservative);
  * a round-turn cost in basis points applied to every trade;
  * a direction-randomised control with identical timing/geometry, so payoff geometry
    alone cannot manufacture a PF;
  * per-year PF so a regime artifact cannot hide inside a headline number.

    python -m scripts.bt_equity_open_setups --symbols SPY,QQQ,IWM,DIA --since 2005-01-01
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
SESSION_END = (15, 55)


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
_RTH_CACHE: dict[tuple[str, str, str], pd.DataFrame] = {}


def load_rth(symbol: str, since: str, interval: str = "5m") -> pd.DataFrame:
    key = (symbol, since, interval)
    if key in _RTH_CACHE:
        return _RTH_CACHE[key]
    df = _load_rth_uncached(symbol, since, interval)
    _RTH_CACHE[key] = df
    return df


def _load_rth_uncached(symbol: str, since: str, interval: str = "5m") -> pd.DataFrame:
    path = HIST / f"{symbol}_{interval}.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_csv(path)
    dc = df.columns[0]
    df[dc] = pd.to_datetime(df[dc], utc=True, errors="coerce")
    df = df.dropna(subset=[dc]).set_index(dc).sort_index().tz_convert(ET)
    df.columns = [c.lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]]
    df = df[~df.index.duplicated(keep="first")]
    if since:
        df = df[df.index >= pd.Timestamp(since, tz=ET)]
    # keep regular trading hours only; drop half-days with too few bars
    df = df.between_time("09:30", "15:55")
    counts = df.groupby(df.index.date).size()
    good = set(counts[counts >= 60].index)
    return df[[d in good for d in df.index.date]]


# --------------------------------------------------------------------------- #
# Trade model
# --------------------------------------------------------------------------- #
@dataclass
class Trade:
    symbol: str
    date: str
    direction: str
    entry_ts: pd.Timestamp
    exit_ts: pd.Timestamp
    entry: float
    stop: float
    target: float
    exit_price: float
    reason: str
    r: float


@dataclass
class Setup:
    """A trigger produced by a detector; entry happens at bar `entry_idx`'s OPEN."""
    entry_idx: int
    direction: str
    stop: float
    target_r: float
    note: str = ""


def run_day(sym: str, day: pd.DataFrame, setup: Setup, cost_bps: float) -> Trade | None:
    """Fill `setup` at the open of its entry bar and walk forward to stop/target/EOD."""
    o = day["open"].to_numpy(); h = day["high"].to_numpy(); l = day["low"].to_numpy()
    c = day["close"].to_numpy()
    i = setup.entry_idx
    if i >= len(day):
        return None
    entry = float(o[i])
    stop = float(setup.stop)
    risk = entry - stop if setup.direction == "long" else stop - entry
    if risk <= 0:
        return None
    target = (entry + setup.target_r * risk if setup.direction == "long"
              else entry - setup.target_r * risk)

    exit_price, reason, exit_idx = float(c[-1]), "eod", len(day) - 1
    for j in range(i, len(day)):
        if setup.direction == "long":
            hit_stop = l[j] <= stop
            hit_tp = h[j] >= target
        else:
            hit_stop = h[j] >= stop
            hit_tp = l[j] <= target
        if hit_stop:                      # conservative: stop wins a both-touched bar
            exit_price, reason, exit_idx = stop, "stop", j
            break
        if hit_tp:
            exit_price, reason, exit_idx = target, "tp", j
            break

    gross = (exit_price - entry) if setup.direction == "long" else (entry - exit_price)
    cost = entry * cost_bps / 10_000.0
    r = (gross - cost) / risk
    return Trade(sym, str(day.index[i].date()), setup.direction,
                 day.index[i], day.index[exit_idx], entry, stop, target,
                 exit_price, reason, r)


# --------------------------------------------------------------------------- #
# Detectors — each returns at most `max_trades` Setups for one RTH session
# --------------------------------------------------------------------------- #
def orb_retest(day: pd.DataFrame, *, or_bars: int = 3, target_r: float = 2.0,
               retest_window: int = 24, stop_mode: str = "or_opposite",
               **_) -> list[Setup]:
    """7teij9jI7mg: mark the first 15 min (3x5m); wait for a 5m CLOSE beyond it;
    wait for a retest of the broken level; enter on the rejection candle's close ->
    filled at the NEXT bar's open. Stop beyond the far side of the opening range."""
    o = day["open"].to_numpy(); h = day["high"].to_numpy()
    l = day["low"].to_numpy(); c = day["close"].to_numpy()
    if len(day) < or_bars + 5:
        return []
    or_hi = h[:or_bars].max(); or_lo = l[:or_bars].min()
    if or_hi <= or_lo:
        return []
    broke = None; brk = None
    for j in range(or_bars, len(day) - 1):
        if broke is None:
            if c[j] > or_hi:
                broke, brk = "up", j
            elif c[j] < or_lo:
                broke, brk = "down", j
            continue
        if j - brk > retest_window:
            return []
        if broke == "up" and l[j] <= or_hi and c[j] > or_hi and c[j] > o[j]:
            stop = or_lo if stop_mode == "or_opposite" else min(l[j], or_hi) * 0.9999
            return [Setup(j + 1, "long", stop, target_r, "orb_retest_long")]
        if broke == "down" and h[j] >= or_lo and c[j] < or_lo and c[j] < o[j]:
            stop = or_hi if stop_mode == "or_opposite" else max(h[j], or_lo) * 1.0001
            return [Setup(j + 1, "short", stop, target_r, "orb_retest_short")]
    return []


def false_break_fade(day: pd.DataFrame, *, range_bars: int = 12, target_r: float = 2.0,
                     max_trades: int = 4, excursion_skip: float = 0.0,
                     **_) -> list[Setup]:
    """2WmeKqsGTQk on an equity session: the first `range_bars` bars (default the first
    hour) define the range; a 5m BODY closes outside, then a later body closes back
    inside -> fade toward the opposite edge at 2R, stop at the breakout extreme.

    Faithful details the FX version dropped:
      * the creator takes **several** setups per session, not one;
      * when price runs more than `excursion_skip` beyond the range he explicitly stops
        fading and switches to a trend trade, so those breaks are skipped here.
    """
    o = day["open"].to_numpy(); h = day["high"].to_numpy()
    l = day["low"].to_numpy(); c = day["close"].to_numpy()
    if len(day) < range_bars + 6:
        return []
    r_hi = h[:range_bars].max(); r_lo = l[:range_bars].min()
    rng = r_hi - r_lo
    if rng <= 0:
        return []
    out: list[Setup] = []
    broke = None; ext = None
    for j in range(range_bars, len(day) - 1):
        if broke is None:
            if c[j] > r_hi:
                broke, ext = "up", h[j]
            elif c[j] < r_lo:
                broke, ext = "down", l[j]
            continue
        ext = max(ext, h[j]) if broke == "up" else min(ext, l[j])
        if broke == "up" and c[j] < r_hi:
            run = (ext - r_hi) / r_hi
            if not (excursion_skip and run > excursion_skip):
                out.append(Setup(j + 1, "short", float(ext), target_r, "fbf_short"))
            broke, ext = None, None
        elif broke == "down" and c[j] > r_lo:
            run = (r_lo - ext) / r_lo
            if not (excursion_skip and run > excursion_skip):
                out.append(Setup(j + 1, "long", float(ext), target_r, "fbf_long"))
            broke, ext = None, None
        if len(out) >= max_trades:
            break
    return out


def opening_range_fade(day: pd.DataFrame, *, or_bars: int = 3, atr_frac: float = 0.20,
                       daily_atr: float | None = None, target_r: float = 2.0,
                       buffer_atr: float = 0.0, min_risk_bps: float = 0.0,
                       **_) -> list[Setup]:
    """6WfTIyJ-YzQ: if the first 15 min consumed >= `atr_frac` of the daily ATR, fade
    the opening candle's direction; stop beyond the OR extreme, target the far side.

    `buffer_atr` pushes the stop past the OR extreme (the video places it beyond the
    wick, not on it) and `min_risk_bps` drops setups whose stop sits so close to the
    entry that transaction cost would dominate the risk unit — without one of these the
    naive version produces ~6bp stops that no discretionary trader would ever take.
    """
    o = day["open"].to_numpy(); h = day["high"].to_numpy()
    l = day["low"].to_numpy(); c = day["close"].to_numpy()
    if len(day) < or_bars + 5 or not daily_atr or daily_atr <= 0:
        return []
    or_hi = h[:or_bars].max(); or_lo = l[:or_bars].min()
    if (or_hi - or_lo) < atr_frac * daily_atr:
        return []
    up = c[or_bars - 1] > o[0]
    j = or_bars
    entry_ref = float(o[j])
    buf = buffer_atr * daily_atr
    direction = "short" if up else "long"
    stop = float(or_hi) + buf if up else float(or_lo) - buf
    risk = (stop - entry_ref) if up else (entry_ref - stop)
    if risk <= 0 or (min_risk_bps and risk / entry_ref * 10_000 < min_risk_bps):
        return []
    return [Setup(j, direction, stop, target_r, f"orfade_{direction}")]


DETECTORS = {
    "orb_retest": orb_retest,
    "false_break_fade": false_break_fade,
    "opening_range_fade": opening_range_fade,
}


def randomize(setups: list[Setup], rng: random.Random) -> list[Setup]:
    """Control: identical trigger timing / stop distance / target geometry, coin-flip
    direction. Anything a random direction can earn is payoff geometry, not edge."""
    out = []
    for s in setups:
        d = "long" if rng.random() < 0.5 else "short"
        out.append(Setup(s.entry_idx, d, s.stop, s.target_r, s.note + "_ctrl"))
    return out


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def pf(rs: list[float]) -> float:
    w = sum(r for r in rs if r > 0); ls = -sum(r for r in rs if r <= 0)
    return round(w / ls, 3) if ls > 0 else float("inf") if w > 0 else 0.0


def summarize(trades: list[Trade]) -> dict:
    rs = [t.r for t in trades]
    n = len(rs)
    return {"n": n, "wr": round(sum(1 for r in rs if r > 0) / n * 100, 1) if n else 0.0,
            "pf": pf(rs), "avg_r": round(float(np.mean(rs)), 4) if n else 0.0,
            "sum_r": round(float(np.sum(rs)), 1) if n else 0.0}


def daily_atr_map(day_frames: dict, period: int = 14) -> dict:
    dates = sorted(day_frames)
    highs = np.array([day_frames[d]["high"].max() for d in dates])
    lows = np.array([day_frames[d]["low"].min() for d in dates])
    closes = np.array([day_frames[d]["close"].iloc[-1] for d in dates])
    pc = np.concatenate([[closes[0]], closes[:-1]])
    tr = np.maximum.reduce([highs - lows, np.abs(highs - pc), np.abs(lows - pc)])
    atr = pd.Series(tr).ewm(span=period, adjust=False).mean().to_numpy()
    # use the PRIOR day's ATR so today's range never informs today's filter
    return {d: (atr[i - 1] if i > 0 else np.nan) for i, d in enumerate(dates)}


def backtest(symbols, since, detector, cost_bps, seed=None, **kw) -> list[Trade]:
    fn = DETECTORS[detector]
    rng = random.Random(seed) if seed is not None else None
    trades: list[Trade] = []
    for sym in symbols:
        try:
            bars = load_rth(sym, since)
        except FileNotFoundError:
            print(f"  !! {sym}: no 5m csv"); continue
        frames = {d: g for d, g in bars.groupby(bars.index.date)}
        atr = daily_atr_map(frames) if detector == "opening_range_fade" else {}
        for d, day in frames.items():
            setups = fn(day, daily_atr=atr.get(d), **kw)
            if rng is not None:
                setups = randomize(setups, rng)
            for s in setups:
                t = run_day(sym, day, s, cost_bps)
                if t is not None:
                    trades.append(t)
    return trades


def per_year(trades: list[Trade]) -> str:
    by: dict[str, list[float]] = {}
    for t in trades:
        by.setdefault(t.date[:4], []).append(t.r)
    return "  ".join(f"{y}:{pf(rs):.2f}({len(rs)})" for y, rs in sorted(by.items()))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="SPY,QQQ,IWM,DIA")
    ap.add_argument("--since", default="2005-01-01")
    ap.add_argument("--oos", default="2016-01-01")
    ap.add_argument("--cost-bps", type=float, default=2.0)
    ap.add_argument("--detectors", default="orb_retest,false_break_fade,opening_range_fade")
    ap.add_argument("--target-r", type=float, default=2.0)
    ap.add_argument("--control-seeds", type=int, default=5)
    ap.add_argument("--out", default="data/research/equity_open_setups.md")
    a = ap.parse_args()

    syms = [s.strip().upper() for s in a.symbols.split(",")]
    lines = ["# Equity-RTH re-test of the video-mined intraday setups\n",
             f"{syms} · 5m RTH · since {a.since} · IS<{a.oos}<=OOS · "
             f"{a.cost_bps}bp round-turn · entry at next bar open · flat 15:55 ET\n",
             "| detector | scope | N | WR% | PF | avgR |", "|---|---|--:|--:|--:|--:|"]

    for det in [d.strip() for d in a.detectors.split(",")]:
        print(f"\n## {det}")
        trades = backtest(syms, a.since, det, a.cost_bps, target_r=a.target_r)
        oos = [t for t in trades if t.date >= a.oos]
        ins = [t for t in trades if t.date < a.oos]
        for scope, ts in (("FULL", trades), ("IS", ins), ("OOS", oos)):
            m = summarize(ts)
            print(f"  {scope:5} N={m['n']:>5}  WR={m['wr']:>5}  PF={m['pf']:>6}  avgR={m['avg_r']:>7}")
            lines.append(f"| {det} | {scope} | {m['n']} | {m['wr']} | {m['pf']} | {m['avg_r']} |")
        # random-direction control, averaged over seeds
        cpfs = []
        for s in range(a.control_seeds):
            ct = backtest(syms, a.since, det, a.cost_bps, seed=s, target_r=a.target_r)
            cpfs.append(summarize([t for t in ct if t.date >= a.oos])["pf"])
        print(f"  control OOS PF {np.mean(cpfs):.3f}  (seeds {[round(x,2) for x in cpfs]})")
        lines.append(f"| {det} | CONTROL OOS (rand dir, {a.control_seeds} seeds) | | | "
                     f"{np.mean(cpfs):.3f} | |")
        print(f"  per-year PF: {per_year(trades)}")
        lines.append(f"\nper-year PF ({det}): `{per_year(trades)}`\n")

    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nreport -> {out}")


if __name__ == "__main__":
    main()
