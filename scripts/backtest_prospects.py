"""backtest_prospects.py — validate the 4 video-mined day_intra prospect
strategies against cached FX 5m history.

Reuses the shared trade simulator/scorer in
``agents/detectors/external/_base.py`` so the numbers line up with the rest of
the research rig. Each detector is a *pure function of bars* that emits a list
of ``Signal`` objects; exits (stop / TP / time-stop) are handled by
``simulate_trades``.

Prospects (source: research/video_library/day_intra/<id>):
  1. three_line_strike     RyTlRkMujuk — FX 5m, with-trend candlestick continuation
  2. ema_reclaim_pullback  7Ds9djcEKB4 — 50-EMA reclaim + micro-pullback breakout
  3. amd_session_reversal  Bdgev1or-7M — ICT Asian/London/NY liquidity-sweep reversal
  4. orb_retest            7teij9jI7mg — opening-range break + retest (equity-native;
                           run here on FX with a session-open anchor as a stand-in)

PASS bar (project standard): PF >= 1.3, avg-R > 0, ~100+ trades, beats the
with-trend control, and (checked separately) corr < 0.60 to the live book.

Usage:
    python -m scripts.backtest_prospects --since 2015-01-01 --oos 2022-01-01 \
        --pairs AUDUSD,GBPUSD,EURUSD
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from agents.detectors.external._base import Signal, simulate_trades, summarize_trades
from services.settings_service import DATA_DIR

HIST = DATA_DIR / "historical"

# pip size per instrument (price move of "1 pip")
PIP = {
    "AUDUSD": 0.0001, "EURUSD": 0.0001, "GBPUSD": 0.0001, "NZDUSD": 0.0001,
    "EURAUD": 0.0001, "EURCAD": 0.0001,
    "USDJPY": 0.01, "EURJPY": 0.01, "GBPJPY": 0.01, "AUDJPY": 0.01,
    "XAUUSD": 0.1,
}


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #
def load_bars(symbol: str, interval: str, since: str | None) -> pd.DataFrame:
    """Load a cached OHLCV csv → tz-aware DateTimeIndex, lowercase columns."""
    path = HIST / f"{symbol}_{interval}.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_csv(path)
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    df = df.set_index("datetime").sort_index()
    df = df.rename(columns={c: c.lower() for c in df.columns})
    df = df[["open", "high", "low", "close", "volume"]]
    if since:
        df = df[df.index >= pd.Timestamp(since, tz="UTC")]
    df = df[~df.index.duplicated(keep="first")]
    return df


def _ema(a: np.ndarray, span: int) -> np.ndarray:
    return pd.Series(a).ewm(span=span, adjust=False).mean().to_numpy()


def _atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, period: int) -> np.ndarray:
    prev_c = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum.reduce([h - l, np.abs(h - prev_c), np.abs(l - prev_c)])
    return pd.Series(tr).ewm(span=period, adjust=False).mean().to_numpy()


# --------------------------------------------------------------------------- #
# 1) Three-line strike (RyTlRkMujuk)
# --------------------------------------------------------------------------- #
def three_line_strike(bars: pd.DataFrame, pip: float, *, ema_len: int = 50,
                      stop_pips: float = 10, tp_pips: float = 20,
                      max_engulf_pips: float = 10) -> list[Signal]:
    o = bars["open"].to_numpy(); h = bars["high"].to_numpy()
    l = bars["low"].to_numpy(); c = bars["close"].to_numpy()
    ema = _ema(c, ema_len)
    bull = c > o; bear = c < o
    sigs: list[Signal] = []
    stop_d, tp_d, max_eng = stop_pips * pip, tp_pips * pip, max_engulf_pips * pip
    for i in range(3, len(bars)):
        rng = h[i] - l[i]
        if rng > max_eng:
            continue
        up = c[i] > ema[i]; dn = c[i] < ema[i]
        # bullish three-line strike (long, uptrend): 3 up + 1 bearish engulf of last up body
        if up and bull[i-3] and bull[i-2] and bull[i-1] and bear[i] \
                and o[i] >= c[i-1] and c[i] <= o[i-1]:
            entry = c[i]
            sigs.append(Signal(i, "long", entry, entry - stop_d, entry + tp_d,
                               time_stop_bars=48, note="bull_3ls"))
        # bearish three-line strike (short, downtrend)
        elif dn and bear[i-3] and bear[i-2] and bear[i-1] and bull[i] \
                and o[i] <= c[i-1] and c[i] >= o[i-1]:
            entry = c[i]
            sigs.append(Signal(i, "short", entry, entry + stop_d, entry - tp_d,
                               time_stop_bars=48, note="bear_3ls"))
    return sigs


# --------------------------------------------------------------------------- #
# 2) 50-EMA reclaim + micro-pullback breakout (7Ds9djcEKB4)
# --------------------------------------------------------------------------- #
def ema_reclaim_pullback(bars: pd.DataFrame, pip: float, *, ema_len: int = 50,
                         min_pullback: int = 2, atr_len: int = 22,
                         atr_mult: float = 3.0, rr: float = 2.0,
                         max_break_mult: float = 4.0) -> list[Signal]:
    o = bars["open"].to_numpy(); h = bars["high"].to_numpy()
    l = bars["low"].to_numpy(); c = bars["close"].to_numpy()
    ema = _ema(c, ema_len)
    atr = _atr(h, l, c, atr_len)
    avg_body = pd.Series(np.abs(c - o)).rolling(20, min_periods=5).mean().to_numpy()
    bull = c > o; bear = c < o
    sigs: list[Signal] = []

    def scan(direction: str) -> None:
        # state machine: look for reclaim -> pullback (>=min_pullback opp candles)
        # -> mark swing extreme -> breakout of that level (body close beyond)
        state = "wait_reclaim"; line = np.nan; pullback = 0
        for i in range(1, len(bars)):
            if direction == "long":
                reclaimed = c[i] > ema[i] and c[i-1] <= ema[i-1]
            else:
                reclaimed = c[i] < ema[i] and c[i-1] >= ema[i-1]
            if state == "wait_reclaim":
                if reclaimed:
                    state = "wait_pullback"; pullback = 0
                    line = h[i] if direction == "long" else l[i]
                continue
            # in an active setup: invalidate if we lose the EMA the wrong way
            if direction == "long" and c[i] < ema[i]:
                state = "wait_reclaim"; continue
            if direction == "short" and c[i] > ema[i]:
                state = "wait_reclaim"; continue
            if state == "wait_pullback":
                # extend the pre-pullback swing extreme while price still pushing
                if direction == "long":
                    line = max(line, h[i])
                    if bear[i]:
                        pullback += 1
                else:
                    line = min(line, l[i])
                    if bull[i]:
                        pullback += 1
                if pullback >= min_pullback:
                    state = "wait_breakout"
                continue
            if state == "wait_breakout":
                big = avg_body[i] > 0 and abs(c[i] - o[i]) > max_break_mult * avg_body[i]
                if direction == "long" and c[i] > line and not big:
                    entry = c[i]; stop = entry - atr_mult * atr[i]
                    if stop < entry:
                        tp = entry + rr * (entry - stop)
                        sigs.append(Signal(i, "long", entry, stop, tp,
                                           time_stop_bars=96, note="ema_reclaim_long"))
                    state = "wait_reclaim"
                elif direction == "short" and c[i] < line and not big:
                    entry = c[i]; stop = entry + atr_mult * atr[i]
                    if stop > entry:
                        tp = entry - rr * (stop - entry)
                        sigs.append(Signal(i, "short", entry, stop, tp,
                                           time_stop_bars=96, note="ema_reclaim_short"))
                    state = "wait_reclaim"

    scan("long"); scan("short")
    sigs.sort(key=lambda s: s.bar_idx)
    return sigs


# --------------------------------------------------------------------------- #
# 3) ICT AMD session reversal (Bdgev1or-7M)
# --------------------------------------------------------------------------- #
def amd_session_reversal(bars: pd.DataFrame, pip: float, *,
                         max_asian_pips: float = 60.0, rr: float = 2.0) -> list[Signal]:
    """Asian range (00-07 UTC) -> London sweep (07-12) -> NY reversal (12-17)
    entered on an engulfing candle in the reversal direction."""
    idx = bars.index
    o = bars["open"].to_numpy(); h = bars["high"].to_numpy()
    l = bars["low"].to_numpy(); c = bars["close"].to_numpy()
    hour = idx.hour.to_numpy()
    date = idx.normalize()
    bull = c > o; bear = c < o
    sigs: list[Signal] = []
    max_asian = max_asian_pips * pip

    # group row positions by calendar day
    day_groups: dict = {}
    for pos, d in enumerate(date):
        day_groups.setdefault(d, []).append(pos)

    for d, rows in day_groups.items():
        rows = np.array(rows)
        hh = hour[rows]
        asian = rows[(hh >= 0) & (hh < 7)]
        london = rows[(hh >= 7) & (hh < 12)]
        ny = rows[(hh >= 12) & (hh < 17)]
        if len(asian) < 6 or len(london) < 6 or len(ny) < 6:
            continue
        a_hi = h[asian].max(); a_lo = l[asian].min()
        if (a_hi - a_lo) > max_asian:      # accumulation failed → skip pair/day
            continue
        swept_low = l[london].min() < a_lo
        swept_high = h[london].max() > a_hi
        if swept_low == swept_high:        # need exactly one clean sweep
            continue
        bias = "long" if swept_low else "short"   # reverse the swept side
        # first engulfing candle in the NY window in the bias direction
        for j in ny:
            if j == 0:
                continue
            if bias == "long" and bull[j] and o[j] <= c[j-1] and c[j] >= o[j-1]:
                entry = c[j]; stop = min(l[london].min(), a_lo) - 2 * pip
                if stop < entry:
                    tp = entry + rr * (entry - stop)
                    sigs.append(Signal(int(j), "long", entry, stop, tp,
                                       time_stop_bars=60, note="amd_long"))
                break
            if bias == "short" and bear[j] and o[j] >= c[j-1] and c[j] <= o[j-1]:
                entry = c[j]; stop = max(h[london].max(), a_hi) + 2 * pip
                if stop > entry:
                    tp = entry - rr * (stop - entry)
                    sigs.append(Signal(int(j), "short", entry, stop, tp,
                                       time_stop_bars=60, note="amd_short"))
                break
    sigs.sort(key=lambda s: s.bar_idx)
    return sigs


# --------------------------------------------------------------------------- #
# 4) Opening-range break + retest (7teij9jI7mg) — FX stand-in, London open
# --------------------------------------------------------------------------- #
def orb_retest(bars: pd.DataFrame, pip: float, *, open_hour: int = 7,
               or_bars: int = 3, rr: float = 2.0, retest_window: int = 24) -> list[Signal]:
    """First 15 min (3x 5m) after the session open define the range; wait for a
    5m CLOSE beyond it, then a retest of the broken level, enter on rejection."""
    idx = bars.index
    o = bars["open"].to_numpy(); h = bars["high"].to_numpy()
    l = bars["low"].to_numpy(); c = bars["close"].to_numpy()
    minute = idx.minute.to_numpy(); hour = idx.hour.to_numpy()
    date = idx.normalize()
    sigs: list[Signal] = []

    day_groups: dict = {}
    for pos, d in enumerate(date):
        day_groups.setdefault(d, []).append(pos)

    for d, rows in day_groups.items():
        rows = np.array(rows)
        # opening range = first `or_bars` bars at/after the open hour:00
        open_rows = rows[(hour[rows] == open_hour)]
        if len(open_rows) < or_bars + 1:
            continue
        orr = open_rows[:or_bars]
        or_hi = h[orr].max(); or_lo = l[orr].min()
        after = rows[rows > orr[-1]]
        broke = None; brk_pos = None
        for k, j in enumerate(after):
            if broke is None:
                if c[j] > or_hi:
                    broke, brk_pos = "up", j
                elif c[j] < or_lo:
                    broke, brk_pos = "down", j
                continue
            # retest window after the break
            if j - brk_pos > retest_window:
                break
            if broke == "up":
                # retest the OR high from above, close back up = rejection long
                if l[j] <= or_hi and c[j] > or_hi and c[j] > o[j]:
                    entry = c[j]; stop = or_lo - 2 * pip
                    if stop < entry:
                        tp = entry + rr * (entry - stop)
                        sigs.append(Signal(int(j), "long", entry, stop, tp,
                                           time_stop_bars=48, note="orb_long"))
                    break
            else:
                if h[j] >= or_lo and c[j] < or_lo and c[j] < o[j]:
                    entry = c[j]; stop = or_hi + 2 * pip
                    if stop > entry:
                        tp = entry - rr * (stop - entry)
                        sigs.append(Signal(int(j), "short", entry, stop, tp,
                                           time_stop_bars=48, note="orb_short"))
                    break
    sigs.sort(key=lambda s: s.bar_idx)
    return sigs


# --------------------------------------------------------------------------- #
# Control: naive with-trend fixed 2:1 entry (baseline PF to beat)
# --------------------------------------------------------------------------- #
def control_with_trend(bars: pd.DataFrame, pip: float, *, ema_len: int = 50,
                       stop_pips: float = 10, tp_pips: float = 20,
                       every: int = 60) -> list[Signal]:
    c = bars["close"].to_numpy(); ema = _ema(c, ema_len)
    sigs: list[Signal] = []
    stop_d, tp_d = stop_pips * pip, tp_pips * pip
    for i in range(ema_len, len(bars), every):
        if c[i] > ema[i]:
            sigs.append(Signal(i, "long", c[i], c[i]-stop_d, c[i]+tp_d, time_stop_bars=48))
        elif c[i] < ema[i]:
            sigs.append(Signal(i, "short", c[i], c[i]+stop_d, c[i]-tp_d, time_stop_bars=48))
    return sigs


DETECTORS = {
    "three_line_strike": three_line_strike,
    "ema_reclaim_pullback": ema_reclaim_pullback,
    "amd_session_reversal": amd_session_reversal,
    "orb_retest": orb_retest,
    "control_with_trend": control_with_trend,
}
VIDEO_ID = {
    "three_line_strike": "RyTlRkMujuk",
    "ema_reclaim_pullback": "7Ds9djcEKB4",
    "amd_session_reversal": "Bdgev1or-7M",
    "orb_retest": "7teij9jI7mg",
    "control_with_trend": "—",
}


def _apply_cost(trades: list, cost_pips: float, pip: float) -> list:
    """Deduct a round-turn transaction cost (spread+commission, in pips) from
    every trade's return. Mutates copies so the gross ledger is untouched."""
    if cost_pips <= 0:
        return trades
    out = []
    for t in trades:
        cost_frac = cost_pips * pip / t.entry_price
        r_frac = cost_pips * pip / abs(t.entry_price - t.stop_price) if t.stop_price != t.entry_price else 0.0
        import dataclasses
        nt = dataclasses.replace(
            t, pnl_pct=t.pnl_pct - cost_frac, pnl_r=t.pnl_r - r_frac,
            win=(t.pnl_pct - cost_frac) > 0,
        )
        out.append(nt)
    return out


def _window(bars: pd.DataFrame, sigs: list[Signal], lo, hi,
            cost_pips: float = 0.0, pip: float = 0.0001) -> dict:
    """Score only the signals whose entry bar falls in [lo, hi)."""
    sub = [s for s in sigs if lo <= bars.index[s.bar_idx] < hi]
    trades = simulate_trades(bars, sub)
    trades = _apply_cost(trades, cost_pips, pip)
    return summarize_trades(trades)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2015-01-01")
    ap.add_argument("--oos", default="2022-01-01", help="IS/OOS split date")
    ap.add_argument("--pairs", default="AUDUSD,GBPUSD,EURUSD")
    ap.add_argument("--interval", default="5m")
    ap.add_argument("--cost-pips", type=float, default=0.0,
                    help="round-turn spread+commission in pips deducted per trade")
    ap.add_argument("--out", default=str(Path("data/research/prospect_backtest.md")))
    args = ap.parse_args()

    pairs = [p.strip().upper() for p in args.pairs.split(",")]
    since = pd.Timestamp(args.since, tz="UTC")
    split = pd.Timestamp(args.oos, tz="UTC")
    end = pd.Timestamp("2100-01-01", tz="UTC")

    data = {}
    for p in pairs:
        try:
            data[p] = load_bars(p, args.interval, args.since)
            print(f"loaded {p}: {len(data[p]):,} bars "
                  f"{data[p].index[0].date()}→{data[p].index[-1].date()}")
        except FileNotFoundError:
            print(f"!! {p}: no {args.interval} csv, skipping")

    lines: list[str] = []
    lines.append("# Prospect strategy backtest — FX 5m\n")
    lines.append(f"Window {args.since} → data end · IS<{args.oos}≤OOS · pairs {pairs}\n")
    lines.append("PASS bar: PF≥1.3, avg-R>0, ~100+ trades, beats control.\n")

    # aggregate across pairs per (strategy, window)
    for strat, fn in DETECTORS.items():
        header = f"\n## {strat}  ({VIDEO_ID[strat]})\n"
        print(header.rstrip())
        lines.append(header)
        lines.append("| pair | window | N | WR% | PF | avgR | net$ | maxDD% |")
        lines.append("|---|---|--:|--:|--:|--:|--:|--:|")
        agg = {"full": [], "IS": [], "OOS": []}
        for p in pairs:
            if p not in data:
                continue
            bars = data[p]
            pip = PIP.get(p, 0.0001)
            sigs = fn(bars, pip)
            for wname, lo, hi in [("full", since, end), ("IS", since, split),
                                  ("OOS", split, end)]:
                m = _window(bars, sigs, lo, hi, args.cost_pips, pip)
                agg[wname].append(m)
                row = (f"| {p} | {wname} | {m['n_trades']} | {m['wr_pct']} | "
                       f"{m['profit_factor']} | {m['avg_r_multiple']} | "
                       f"{m['net_pnl_usd']:.0f} | {m['max_drawdown_pct']:.1f} |")
                lines.append(row)
                if wname == "OOS":
                    print(f"  {p:8s} OOS  N={m['n_trades']:>4}  WR={m['wr_pct']:>5}%  "
                          f"PF={m['profit_factor']:>6}  avgR={m['avg_r_multiple']:>6}")
        # pooled summary (sum N, weighted PF via gross profit/loss)
        for wname in ("full", "IS", "OOS"):
            ms = agg[wname]
            if not ms:
                continue
            N = sum(m["n_trades"] for m in ms)
            gp = sum(m["gross_profit_usd"] for m in ms)
            gl = sum(m["gross_loss_usd"] for m in ms)
            wins = sum(m["wins"] for m in ms)
            pf = round(gp / gl, 3) if gl > 0 else 999.0
            wr = round(wins / N * 100, 2) if N else 0.0
            avgr = round(sum(m["avg_r_multiple"] * m["n_trades"] for m in ms) / N, 3) if N else 0.0
            lines.append(f"| **POOLED** | **{wname}** | **{N}** | **{wr}** | "
                         f"**{pf}** | **{avgr}** | **{gp-gl:.0f}** | |")
            if wname in ("full", "OOS"):
                print(f"  POOLED {wname:4s}  N={N:>5}  WR={wr:>5}%  PF={pf:>6}  avgR={avgr:>6}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nreport → {out}")


if __name__ == "__main__":
    main()
