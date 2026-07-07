"""bt_bb3sd_fade — Bollinger "Extreme Fade" (3SD stretch -> 2SD confirmation), video FqxEKDxemtI.

Spec (mean reversion, both directions; demoed on FX 15m):
  * Bollinger 20-SMA, plot both the 2SD and 3SD bands.
  * LONG: a bar closes **below the 3SD lower band** (extreme stretch) -> ARM. Then wait for a
    later bar to close **back above the 2SD lower band** (confirmation the snap-back started)
    -> enter next open.
  * Stop: just below the recent swing low (emergency), then trail (we model a fixed stop).
  * Target: the **basis (20-SMA / middle band)**; also test the opposite 2SD band.
  * SHORT: mirror (close above 3SD upper -> close back below 2SD upper).
  * Tested on daily US stocks (long side) and FX (both directions). strategy_suite rig.
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, syms, atr, Trade, summarize, random_control

FX = ["EURUSD","USDJPY","EURJPY","GBPJPY","AUDJPY","EURAUD","EURCAD","GBPUSD","AUDUSD","XAUUSD"]


def _bands(c, n=20):
    s = pd.Series(c); ma = s.rolling(n).mean(); sd = s.rolling(n).std()
    return ma.values, sd.values


def run(symlist, interval, longs=True, shorts=False, target="basis", max_hold=30):
    trades = []
    for s in symlist:
        df = load(s, interval)
        if df is None or len(df) < 120:
            continue
        o = df["open"].values; c = df["close"].values; l = df["low"].values; h = df["high"].values
        ma, sd = _bands(c); a = atr(df)
        lo3 = ma - 3*sd; lo2 = ma - 2*sd; up3 = ma + 3*sd; up2 = ma + 2*sd
        n = len(df); i = 25
        armed_long = armed_short = False
        while i < n-1:
            if np.isnan(sd[i]) or sd[i] <= 0 or np.isnan(a[i]) or a[i] <= 0:
                i += 1; continue
            if longs:
                if c[i] < lo3[i]: armed_long = True
                elif armed_long and c[i] > lo2[i] and c[i] < ma[i]:
                    entry = o[i+1]; stop = min(l[max(i-5,0):i+1]) - 0.1*a[i]; risk = entry - stop
                    armed_long = False
                    if risk > 0:
                        rf = risk/entry; tgt = ma[i] if target == "basis" else up2[i]; exitp = None; jj = i+1
                        for j in range(i+1, min(i+1+max_hold, n)):
                            jj = j
                            if l[j] <= stop: exitp = stop; break
                            if h[j] >= tgt: exitp = tgt; break
                        if exitp is None: exitp = c[min(i+max_hold, n-1)]
                        trades.append(Trade(df.index[i], (exitp-entry)/risk, rf, +1))
                        i = jj+1; continue
            if shorts:
                if c[i] > up3[i]: armed_short = True
                elif armed_short and c[i] < up2[i] and c[i] > ma[i]:
                    entry = o[i+1]; stop = max(h[max(i-5,0):i+1]) + 0.1*a[i]; risk = stop - entry
                    armed_short = False
                    if risk > 0:
                        rf = risk/entry; tgt = ma[i] if target == "basis" else lo2[i]; exitp = None; jj = i+1
                        for j in range(i+1, min(i+1+max_hold, n)):
                            jj = j
                            if h[j] >= stop: exitp = stop; break
                            if l[j] <= tgt: exitp = tgt; break
                        if exitp is None: exitp = c[min(i+max_hold, n-1)]
                        trades.append(Trade(df.index[i], (entry-exitp)/risk, rf, -1))
                        i = jj+1; continue
            i += 1
    return trades


if __name__ == "__main__":
    res = {"results": {}}
    sl = syms("1d")
    for tgt in ("basis", "band"):
        t = run(sl, "1d", longs=True, shorts=False, target=tgt)
        res["results"][f"bb3sd_stocks_long_{tgt}"] = summarize(t, random_control(t))
    for interval in ("15m", "30m"):
        t = run(FX, interval, longs=True, shorts=True, target="basis")
        res["results"][f"bb3sd_fx_{interval}_basis"] = summarize(t, random_control(t))
    Path("data/research/strategy_results/bb3sd_fade_video.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res, indent=2, default=str))
