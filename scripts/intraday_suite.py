"""intraday_suite — session-aware intraday backtest harness for the shelved FX strategies.

Mirrors strategy_suite (same Trade / net_r / summarize / random-direction control / OOS
split) but loads INTRADAY bars and adds FX session structure (Asia/London/NY). This is
the rig that lets the 9 intraday-FX strategies finally be tested on the HistData bars.

Sessions (UTC, standard FX): Tokyo 00–09, London 07–16, New York 12–21.

First strategy wired: Opening-Range Breakout (ORB) — the cleanest of the shelved set.
Run:  python scripts/intraday_suite.py [--pairs eurusd gbpusd] [--interval 15m] [--session london]
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import sys
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import Trade, summarize, random_control, HIST  # reuse metrics/contract

SESSIONS = {                 # (start_hour_utc, end_hour_utc)
    "tokyo":  (0, 9),
    "london": (7, 16),
    "ny":     (12, 21),
}
FX_PAIRS = ["eurusd", "usdjpy", "eurjpy", "gbpjpy", "audjpy", "euraud", "eurcad", "gbpusd", "audusd"]
BAR_MINUTES = {"5m": 5, "15m": 15, "30m": 30, "1h": 60}

# FX cost model — spread in PIPS (NOT the stock 10bps notional model, which over-penalizes
# tight intraday risk by ~2R/trade). Majors ~0.1-0.5 pip live; 1.0 pip round-trip is conservative.
SPREAD_PIPS = 1.0


def pip_size(sym: str) -> float:
    return 0.01 if sym.upper().endswith("JPY") else 0.0001


def fx_net_r(gross_r: float, risk_price: float, sym: str, spread_pips: float = SPREAD_PIPS) -> float:
    """Net R after an FX spread cost expressed in R via the trade's own price-risk."""
    if risk_price <= 0:
        return gross_r
    cost_r = (spread_pips * pip_size(sym)) / risk_price
    return gross_r - cost_r


def load_fx(sym: str, interval: str) -> pd.DataFrame | None:
    f = HIST / f"{sym.upper()}_{interval}.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f)
    dc = df.columns[0]
    df[dc] = pd.to_datetime(df[dc], utc=True, errors="coerce")
    df = df.dropna(subset=[dc]).set_index(dc).sort_index()
    df.columns = [c.lower() for c in df.columns]
    return df[["open", "high", "low", "close", "volume"]]


def in_session(idx: pd.DatetimeIndex, session: str) -> np.ndarray:
    s, e = SESSIONS[session]
    h = idx.hour
    return (h >= s) & (h < e)


def orb(symlist, interval="15m", session="london", or_minutes=60,
        target_R=2.0, both_sides=True, stop_buffer=0.0):
    """Opening-Range Breakout: build the OR over the first `or_minutes` of the session;
    go long on a bar close above OR-high (short below OR-low), stop at the opposite OR
    edge, target = target_R x OR-range, exit at session end. One trade/session/day."""
    bm = BAR_MINUTES[interval]
    or_bars = max(1, or_minutes // bm)
    trades = []
    for sym in symlist:
        df = load_fx(sym, interval)
        if df is None or len(df) < 500:
            continue
        df = df[in_session(df.index, session)]
        for _, day in df.groupby(df.index.normalize()):
            if len(day) < or_bars + 3:
                continue
            o = day["open"].values; h = day["high"].values
            l = day["low"].values; c = day["close"].values
            ts = day.index
            or_hi = h[:or_bars].max(); or_lo = l[:or_bars].min()
            rng = or_hi - or_lo
            if rng <= 0:
                continue
            entered = False
            for j in range(or_bars, len(day)):
                if not entered and c[j] > or_hi:          # long breakout
                    entry = c[j]; stop = or_lo - stop_buffer * rng; risk = entry - stop
                    if risk <= 0: continue
                    tgt = entry + target_R * risk
                    r = _walk(h, l, c, j + 1, len(day), stop, tgt, +1, entry, risk)
                    trades.append(Trade(ts[j], fx_net_r(r, risk, sym), 1.0, +1)); entered = True; break
                if both_sides and not entered and c[j] < or_lo:   # short breakout
                    entry = c[j]; stop = or_hi + stop_buffer * rng; risk = stop - entry
                    if risk <= 0: continue
                    tgt = entry - target_R * risk
                    r = _walk(h, l, c, j + 1, len(day), stop, tgt, -1, entry, risk)
                    trades.append(Trade(ts[j], fx_net_r(r, risk, sym), 1.0, -1)); entered = True; break
    return trades


def _walk(h, l, c, start, end, stop, tgt, direction, entry, risk):
    """Forward exit within the session; stop/target/EOD-close. Returns R-multiple."""
    for k in range(start, end):
        if direction == +1:
            if l[k] <= stop: return (stop - entry) / risk
            if h[k] >= tgt: return (tgt - entry) / risk
        else:
            if h[k] >= stop: return (entry - stop) / risk
            if l[k] <= tgt: return (entry - tgt) / risk
    last = c[end - 1]
    return (last - entry) / risk if direction == +1 else (entry - last) / risk


def main():
    args = sys.argv
    pairs = FX_PAIRS
    if "--pairs" in args:
        i = args.index("--pairs") + 1
        pairs = []
        while i < len(args) and not args[i].startswith("--"):
            pairs.append(args[i]); i += 1
    interval = args[args.index("--interval") + 1] if "--interval" in args else "15m"
    session = args[args.index("--session") + 1] if "--session" in args else "london"
    orm = int(args[args.index("--or-min") + 1]) if "--or-min" in args else 60
    tR = float(args[args.index("--target-r") + 1]) if "--target-r" in args else 2.0

    tr = orb(pairs, interval=interval, session=session, or_minutes=orm, target_R=tR)
    res = summarize(tr, random_control(tr))
    a = res.get("all", {}); oos = res.get("out_sample", {}); ctl = res.get("random_control", {})
    print(f"ORB  session={session} interval={interval} OR={orm}m target={tR}R  pairs={len(pairs)}")
    print(f"  ALL: n={a.get('n')} win={a.get('win_pct')}% exp={a.get('expectancy_R')}R PF={a.get('profit_factor')}")
    print(f"  OOS: n={oos.get('n')} win={oos.get('win_pct')}% exp={oos.get('expectancy_R')}R PF={oos.get('profit_factor')}")
    print(f"  CTL: PF={ctl.get('profit_factor')} exp={ctl.get('expectancy_R')}")


if __name__ == "__main__":
    main()
