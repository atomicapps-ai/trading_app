"""bt_stoch_200ema — Stochastic reversal + 200-EMA trend filter, video vLbLZWi_Ypc.

Spec (long side on the long-biased equity universe):
  * 200-EMA trend filter; Stochastic %K(14,3)/%D(3), oversold<20 / overbought>80.
  * LONG: price above 200-EMA, stochastic was oversold, then **crosses back up above 20**
    (confirmation the reversal is underway) -> enter next open.
  * Stop = nearest swing low (10-bar) minus small buffer. Target = 2x stop (2R).
  * (Short mirror below the 200-EMA — not run on the long-biased stock universe.)
  * Variant `obexit`: instead of 2R, exit when stochastic reaches overbought (>80).
  * Daily US stocks, strategy_suite rig.
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, syms, atr, Trade, summarize, random_control


def _stoch(df, n=14, k=3, d=3):
    hi = df["high"].rolling(n).max(); lo = df["low"].rolling(n).min()
    raw = 100*(df["close"]-lo)/(hi-lo).replace(0, np.nan)
    kk = raw.rolling(k).mean(); dd = kk.rolling(d).mean()
    return kk.fillna(50).values, dd.fillna(50).values


def run(symlist, exit_mode="r2", max_hold=30):
    trades = []
    for s in symlist:
        df = load(s, "1d")
        if df is None or len(df) < 260:
            continue
        o = df["open"].values; c = df["close"].values; l = df["low"].values; h = df["high"].values
        ema200 = pd.Series(c).ewm(span=200, adjust=False).mean().values
        kk, dd = _stoch(df); a = atr(df)
        n = len(df); i = 205
        while i < n-1:
            cross_up_20 = kk[i] > 20 and kk[i-1] <= 20
            if cross_up_20 and c[i] > ema200[i] and not np.isnan(a[i]) and a[i] > 0:
                entry = o[i+1]; stop = min(l[max(i-10,0):i+1]) - 0.1*a[i]; risk = entry - stop
                if risk > 0:
                    rf = risk/entry; tgt = entry + 2.0*risk; exitp = None; jj = i+1
                    for j in range(i+1, min(i+1+max_hold, n)):
                        jj = j
                        if l[j] <= stop: exitp = stop; break
                        if exit_mode == "r2" and h[j] >= tgt: exitp = tgt; break
                        if exit_mode == "obexit" and kk[j] > 80: exitp = c[j]; break
                    if exitp is None: exitp = c[min(i+max_hold, n-1)]
                    trades.append(Trade(df.index[i], (exitp-entry)/risk, rf, +1))
                    i = jj+1; continue
            i += 1
    return trades


if __name__ == "__main__":
    cap = None
    if "--symbols" in sys.argv: cap = int(sys.argv[sys.argv.index("--symbols")+1])
    sl = syms("1d")
    if cap: sl = sl[:cap]
    res = {"n_symbols": len(sl), "results": {}}
    for em in ("r2", "obexit"):
        t = run(sl, em)
        res["results"][f"stoch200_{em}"] = summarize(t, random_control(t))
    Path("data/research/strategy_results/stoch_200ema_video.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res, indent=2, default=str))
