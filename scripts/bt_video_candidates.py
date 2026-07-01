"""bt_video_candidates — backtest the two mechanical candidates surfaced from the
batch-1 + batch-A video triage, using the shared strategy_suite harness so the
metrics are directly comparable to the deployed pair.

Candidates:
  C1 = rf_EQvubKlk  MACD(12,26,9) cross-up below zero, in a 200-SMA uptrend.
  C2 = 2ElrQnn2cZE  Turtle/Donchian-20 breakout + 200-SMA filter, 2xATR(20) stop.

Run:  python scripts/bt_video_candidates.py
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, sys
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, syms, atr, Trade, summarize, random_control, OUT  # noqa


def _ema(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).ewm(span=n, adjust=False).mean().values


# ---------------------------------------------------------------- C1: MACD pullback
def c1_macd_200ma(symlist, atr_stop=False):
    """LONG when MACD line crosses up through signal WHILE macd<0, and close>SMA200.
    base: stop just below SMA200 (entry stop = SMA200-0.1*ATR), target 1.5R.
    atr_stop variant: stop = entry-1.5*ATR14, target 1.5R."""
    cfg = {"universe": "daily stocks", "trend": "close>SMA200",
           "entry": "MACD(12,26,9) cross up while macd<0 -> next open",
           "stop": "entry-1.5*ATR14" if atr_stop else "SMA200-0.1*ATR14",
           "target": "1.5R", "max_hold_bars": 40}
    trades = []
    for s in symlist:
        df = load(s, "1d")
        if df is None or len(df) < 260: continue
        c = df["close"].values; o = df["open"].values; l = df["low"].values; h = df["high"].values
        a = atr(df); sma200 = pd.Series(c).rolling(200).mean().values
        macd = _ema(c, 12) - _ema(c, 26); sig = _ema(macd, 9)
        n = len(df); i = 205
        while i < n - 1:
            cross_up = macd[i] > sig[i] and macd[i-1] <= sig[i-1]
            if (cross_up and macd[i] < 0 and not np.isnan(sma200[i]) and c[i] > sma200[i]
                    and not np.isnan(a[i]) and a[i] > 0):
                entry = o[i+1] if i+1 < n else c[i]
                stop = entry - 1.5*a[i] if atr_stop else sma200[i] - 0.1*a[i]
                risk = entry - stop
                if risk <= 0: i += 1; continue
                rf = risk / entry; tgt = entry + 1.5*risk; exitp = None
                for j in range(i+1, min(i+1+cfg["max_hold_bars"], n)):
                    if l[j] <= stop: exitp = stop; break
                    if h[j] >= tgt: exitp = tgt; break
                if exitp is None: exitp = c[min(i+cfg["max_hold_bars"], n-1)]
                trades.append(Trade(df.index[i], (exitp-entry)/risk, rf, +1)); i = j+1; continue
            i += 1
    return trades, cfg


# ---------------------------------------------------------------- C2: Turtle Donchian
def c2_turtle(symlist, entry_lookback=20, exit_lookback=10):
    """LONG when close>prior N-day high AND close>SMA200. stop=entry-2*ATR20.
    exit when close<prior M-day low (Turtle). R = move / (2*ATR20)."""
    cfg = {"universe": "daily stocks", "trend": "close>SMA200",
           "entry": f"close>prior {entry_lookback}-day high -> next open",
           "stop": "entry-2.0*ATR20", "exit": f"close<prior {exit_lookback}-day low",
           "max_hold_bars": 250}
    trades = []
    for s in symlist:
        df = load(s, "1d")
        if df is None or len(df) < 300: continue
        c = df["close"].values; o = df["open"].values; l = df["low"].values; h = df["high"].values
        a20 = atr(df, 20); sma200 = pd.Series(c).rolling(200).mean().values
        hh = pd.Series(h).rolling(entry_lookback).max().shift(1).values
        ll = pd.Series(l).rolling(exit_lookback).min().shift(1).values
        n = len(df); i = 205
        while i < n - 1:
            if (not np.isnan(hh[i]) and c[i] > hh[i] and not np.isnan(sma200[i]) and c[i] > sma200[i]
                    and not np.isnan(a20[i]) and a20[i] > 0):
                entry = o[i+1] if i+1 < n else c[i]
                stop = entry - 2.0*a20[i]; risk = entry - stop
                if risk <= 0: i += 1; continue
                rf = risk / entry; exitp = None
                for j in range(i+1, min(i+1+cfg["max_hold_bars"], n)):
                    if l[j] <= stop: exitp = stop; break
                    if not np.isnan(ll[j]) and c[j] < ll[j]: exitp = c[j]; break
                if exitp is None: exitp = c[min(i+cfg["max_hold_bars"], n-1)]
                trades.append(Trade(df.index[i], (exitp-entry)/risk, rf, +1)); i = j+1; continue
            i += 1
    return trades, cfg


REGISTRY = {
    "c1_macd_200ma": lambda sl: c1_macd_200ma(sl, atr_stop=False),
    "c1_macd_200ma_atrstop": lambda sl: c1_macd_200ma(sl, atr_stop=True),
    "c2_turtle_20_10": lambda sl: c2_turtle(sl, 20, 10),
    "c2_turtle_55_20": lambda sl: c2_turtle(sl, 55, 20),
}


def main():
    cap = 45
    if "--symbols" in sys.argv:
        cap = int(sys.argv[sys.argv.index("--symbols")+1])
    sl = syms("1d")[:cap]
    out = {}
    for key, fn in REGISTRY.items():
        trades, cfg = fn(sl)
        res = summarize(trades, random_control(trades))
        out[key] = {"config": cfg, "n_symbols": len(sl), "results": res}
        a = res.get("all", {}); oos = res.get("out_sample", {}); ctl = res.get("random_control", {})
        print(f"\n=== {key}  (n_sym={len(sl)}) ===")
        print(f"  ALL : n={a.get('n')} win={a.get('win_pct')}% exp={a.get('expectancy_R')}R PF={a.get('profit_factor')} totalR={a.get('total_R')}")
        print(f"  OOS : n={oos.get('n')} win={oos.get('win_pct')}% exp={oos.get('expectancy_R')}R PF={oos.get('profit_factor')}")
        print(f"  CTL : n={ctl.get('n')} win={ctl.get('win_pct')}% exp={ctl.get('expectancy_R')}R PF={ctl.get('profit_factor')}")
    Path(OUT / "video_candidates.json").write_text(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
