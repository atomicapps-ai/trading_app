"""bt_hidden_divergence — RSI hidden-divergence continuation, video 9KVvwJHvcyE.

Spec (long; test long side):
  * Indicators: RSI(14), 200-EMA (trend filter), Stochastic (confirmation).
  * Bullish HIDDEN divergence = price makes a **higher low** while RSI makes a **lower low**
    (signals continuation of the uptrend). Require price above the 200-EMA.
  * Optional stochastic confirmation: %K rising / oversold at the 2nd low.
  * Entry: next open after the higher-low bar confirms. Stop below that swing low.
  * Exit: video implies riding the trend; test fixed 2R and a trailing-swing exit.
  * Daily US stocks, strategy_suite rig. Fractal pivot lows (+-3).
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, syms, atr, Trade, summarize, random_control


def _rsi(c, n=14):
    d = pd.Series(c).diff(); up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d).clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    return (100 - 100/(1 + up/dn.replace(0, np.nan))).fillna(50).values


def _stochk(df, n=14, k=3):
    hi = df["high"].rolling(n).max(); lo = df["low"].rolling(n).min()
    raw = 100*(df["close"]-lo)/(hi-lo).replace(0, np.nan)
    return raw.rolling(k).mean().fillna(50).values


def run(symlist, exit_mode="r2", stoch=False, max_hold=60):
    trades = []
    for s in symlist:
        df = load(s, "1d")
        if df is None or len(df) < 260:
            continue
        o = df["open"].values; c = df["close"].values; l = df["low"].values; h = df["high"].values
        rsi = _rsi(c); ema200 = pd.Series(c).ewm(span=200, adjust=False).mean().values
        k = _stochk(df); a = atr(df)
        # fractal pivot lows (+-3)
        n = len(df); piv = []
        for i in range(3, n-3):
            if l[i] == min(l[i-3:i+4]): piv.append(i)
        # walk consecutive pivot-low pairs
        for pi in range(1, len(piv)):
            i1, i2 = piv[pi-1], piv[pi]
            if i2 - i1 > 40 or i2 < 205: continue
            higher_low = l[i2] > l[i1]
            rsi_lower_low = rsi[i2] < rsi[i1]
            if higher_low and rsi_lower_low and c[i2] > ema200[i2]:
                if stoch and not (k[i2] < 45): continue
                e = i2 + 3  # confirmation bar (pivot confirmed 3 bars later)
                if e+1 < n and not np.isnan(a[e]) and a[e] > 0:
                    entry = o[e+1]; stop = l[i2] - 0.1*a[e]; risk = entry - stop
                    if risk > 0:
                        rf = risk/entry; tgt = entry + 2.0*risk; exitp = None; trail = stop
                        for j in range(e+1, min(e+1+max_hold, n)):
                            if l[j] <= (trail if exit_mode == "trail" else stop): exitp = (trail if exit_mode=="trail" else stop); break
                            if exit_mode == "r2" and h[j] >= tgt: exitp = tgt; break
                            if exit_mode == "trail": trail = max(trail, l[j-1])
                        if exitp is None: exitp = c[min(e+max_hold, n-1)]
                        trades.append(Trade(df.index[e], (exitp-entry)/risk, rf, +1))
    return trades


if __name__ == "__main__":
    cap = None
    if "--symbols" in sys.argv: cap = int(sys.argv[sys.argv.index("--symbols")+1])
    sl = syms("1d")
    if cap: sl = sl[:cap]
    res = {"n_symbols": len(sl), "results": {}}
    for em in ("r2", "trail"):
        for st in (False, True):
            t = run(sl, em, st)
            res["results"][f"hiddendiv_{em}{'_stoch' if st else ''}"] = summarize(t, random_control(t))
    Path("data/research/strategy_results/hidden_divergence_video.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res, indent=2, default=str))
