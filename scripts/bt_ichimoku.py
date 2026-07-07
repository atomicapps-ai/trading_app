"""bt_ichimoku — Ichimoku cloud 4-criteria trend entry, video 8gWIykJgMNY.

Spec (long; test long side on the long-biased equity universe):
  * Standard Ichimoku 9/26/52.
  * LONG requires all four: (1) price closes above the cloud, (2) Tenkan > Kijun
    (conversion over baseline), (3) future cloud green (SpanA > SpanB), (4) lagging
    span (chikou) above the cloud. Enter next open on the bar the setup first completes.
  * Stop: the video uses swing-high/baseline/cloud; for longs we test stop = Kijun
    (baseline) and stop = 10-bar swing low.
  * Exit: no fixed TP given (traded discretionarily). Test two: ride until Tenkan<Kijun
    (`tkcross`), or fixed 2R (`r2`). max_hold 90. Daily US stocks, strategy_suite rig.
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, syms, Trade, summarize, random_control


def ichimoku(df):
    h = df["high"]; l = df["low"]; c = df["close"]
    conv = ((h.rolling(9).max() + l.rolling(9).min()) / 2)
    base = ((h.rolling(26).max() + l.rolling(26).min()) / 2)
    spanA = ((conv + base) / 2)
    spanB = ((h.rolling(52).max() + l.rolling(52).min()) / 2)
    cloud_top_now = np.maximum(spanA.shift(26), spanB.shift(26)).values
    cloud_bot_now = np.minimum(spanA.shift(26), spanB.shift(26)).values
    return conv.values, base.values, spanA.values, spanB.values, cloud_top_now, cloud_bot_now


def run(symlist, stop_mode="kijun", exit_mode="tkcross", max_hold=90):
    trades = []
    for s in symlist:
        df = load(s, "1d")
        if df is None or len(df) < 160:
            continue
        o = df["open"].values; c = df["close"].values; l = df["low"].values; h = df["high"].values
        conv, base, spanA, spanB, ctop, cbot = ichimoku(df)
        n = len(df)
        def setup(i):
            if i < 53 or i-26 < 0 or np.isnan(ctop[i]) or np.isnan(ctop[i-26]): return False
            return (c[i] > ctop[i] and conv[i] > base[i] and spanA[i] > spanB[i]
                    and c[i] > ctop[i-26])
        i = 55
        while i < n-1:
            if setup(i) and not setup(i-1):
                if not np.isnan(base[i]):
                    entry = o[i+1]
                    stop = base[i] if stop_mode == "kijun" else min(l[max(i-10,0):i+1])
                    risk = entry - stop
                    if risk > 0:
                        rf = risk/entry; tgt = entry + 2.0*risk; exitp = None; jj = i+1
                        for j in range(i+1, min(i+1+max_hold, n)):
                            jj = j
                            if l[j] <= stop: exitp = stop; break
                            if exit_mode == "r2" and h[j] >= tgt: exitp = tgt; break
                            if exit_mode == "tkcross" and conv[j] < base[j]: exitp = c[j]; break
                        if exitp is None: exitp = c[min(i+max_hold, n-1)]
                        trades.append(Trade(df.index[i], (exitp-entry)/risk, rf, +1))
                        i = jj + 1; continue
            i += 1
    return trades


if __name__ == "__main__":
    cap = None
    if "--symbols" in sys.argv: cap = int(sys.argv[sys.argv.index("--symbols")+1])
    sl = syms("1d")
    if cap: sl = sl[:cap]
    res = {"n_symbols": len(sl), "results": {}}
    for sm in ("kijun", "swing"):
        for em in ("tkcross", "r2"):
            t = run(sl, sm, em)
            res["results"][f"ichimoku_{sm}_{em}"] = summarize(t, random_control(t))
    Path("data/research/strategy_results/ichimoku_video.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res, indent=2, default=str))
