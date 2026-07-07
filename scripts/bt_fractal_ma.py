"""bt_fractal_ma — Williams Fractals + 20/50/100 MA pullback, video bKPs2aOsvsk.

Spec (long side on the long-biased equity universe):
  * MAs 20/50/100 must be stacked up (SMA20 > SMA50 > SMA100), not crossing.
  * Pullback: price dips **under the 20-MA** (shallow) or **under the 50-MA** (deeper), then a
    **Williams fractal low** (period 2: low[i] is the min of i-2..i+2, confirmed 2 bars later)
    prints -> enter next open.
  * Stop: below the 50-MA if the pullback only reached the 20; below the 100-MA if it reached the
    50. If price is below the 100-MA -> no trade.
  * Target = 1.5 x risk (1.5R). Daily US stocks, strategy_suite rig.
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, syms, Trade, summarize, random_control


def run(symlist, rr=1.5, max_hold=30):
    trades = []
    for s in symlist:
        df = load(s, "1d")
        if df is None or len(df) < 160:
            continue
        o = df["open"].values; c = df["close"].values; l = df["low"].values; h = df["high"].values
        sma20 = pd.Series(c).rolling(20).mean().values
        sma50 = pd.Series(c).rolling(50).mean().values
        sma100 = pd.Series(c).rolling(100).mean().values
        n = len(df); i = 104
        while i < n-3:
            f = i  # candidate fractal-low bar
            is_frac_low = (l[f] <= l[f-1] and l[f] <= l[f-2] and l[f] <= l[f+1] and l[f] <= l[f+2])
            if is_frac_low and not np.isnan(sma100[f]):
                stacked = sma20[f] > sma50[f] > sma100[f]
                if stacked and l[f] >= sma100[f]:
                    stop = None
                    if l[f] < sma50[f]:
                        stop = sma100[f]
                    elif l[f] < sma20[f]:
                        stop = sma50[f]
                    if stop is not None:
                        e = f + 2  # fractal confirmed 2 bars later
                        if e + 1 < n:
                            entry = o[e+1]; risk = entry - stop
                            if risk > 0:
                                rf = risk/entry; tgt = entry + rr*risk; exitp = None; jj = e+1
                                for j in range(e+1, min(e+1+max_hold, n)):
                                    jj = j
                                    if l[j] <= stop: exitp = stop; break
                                    if h[j] >= tgt: exitp = tgt; break
                                if exitp is None: exitp = c[min(e+max_hold, n-1)]
                                trades.append(Trade(df.index[f], (exitp-entry)/risk, rf, +1))
                                i = jj + 1; continue
            i += 1
    return trades


if __name__ == "__main__":
    cap = None
    if "--symbols" in sys.argv: cap = int(sys.argv[sys.argv.index("--symbols")+1])
    sl = syms("1d")
    if cap: sl = sl[:cap]
    res = {"n_symbols": len(sl), "results": {}}
    for rr in (1.5, 2.0):
        t = run(sl, rr)
        res["results"][f"fractal_ma_rr{rr}"] = summarize(t, random_control(t))
    Path("data/research/strategy_results/fractal_ma_video.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res, indent=2, default=str))
