"""bt_fib_goldenpocket — Fibonacci golden-pocket (0.5-0.618) continuation, video 2GAAK_JhNW0.

Spec (both directions, FX intraday):
  * Identify an impulse leg (swing low->high = up impulse; swing high->low = down impulse),
    confirmed by a break of structure.
  * Draw fib from start to end of the leg; wait for price to pull back into the 0.5-0.618
    "golden pocket".
  * Enter in the impulse direction (continuation) with a limit at the 0.618 level.
  * Stop beyond the leg origin (0.0). Target the leg extension (video shows the -0.5 ext,
    i.e. leg_end + 0.5*leg). Also test a fixed 2R target.
  * max_hold 60 bars. FX pairs, 15m + 30m. strategy_suite rig.

Swing detection: fractal pivots over +-K bars (K=5).
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, Trade, summarize, random_control

FX = ["EURUSD","USDJPY","EURJPY","GBPJPY","AUDJPY","EURAUD","EURCAD","GBPUSD","AUDUSD","XAUUSD"]
K = 5


def pivots(h, l, k=K):
    n = len(h); ph = np.zeros(n, bool); pl = np.zeros(n, bool)
    for i in range(k, n-k):
        if h[i] == max(h[i-k:i+k+1]): ph[i] = True
        if l[i] == min(l[i-k:i+k+1]): pl[i] = True
    return ph, pl


def run(interval, target="ext", max_hold=60):
    trades = []
    for s in FX:
        df = load(s, interval)
        if df is None or len(df) < 300:
            continue
        o = df["open"].values; c = df["close"].values; l = df["low"].values; h = df["high"].values
        ph, pl = pivots(h, l)
        n = len(df); i = K + 1
        while i < n - 1:
            # up impulse: a confirmed swing low at lo_idx then swing high at hi_idx (hi later, higher)
            if ph[i]:
                # find most recent prior pivot low before i
                lo_idx = None
                for j in range(i-1, max(i-60, 0), -1):
                    if pl[j]: lo_idx = j; break
                if lo_idx is not None and h[i] > l[lo_idx]:
                    swing_hi = h[i]; swing_lo = l[lo_idx]; leg = swing_hi - swing_lo
                    if leg > 0:
                        gp = swing_hi - 0.618 * leg  # golden-pocket entry (limit)
                        stop = swing_lo - 0.05 * leg
                        tgt = swing_hi + 0.5 * leg if target == "ext" else None
                        entered = False
                        for j in range(i+1, min(i+1+max_hold, n)):
                            if not entered and l[j] <= gp:  # pulled back into pocket
                                entry = gp; risk = entry - stop
                                if risk <= 0: break
                                if target == "r2": tgt = entry + 2.0 * risk
                                rf = risk / entry; entered = True; ej = j; exitp = None
                                for kk in range(j, min(j+max_hold, n)):
                                    ek = kk
                                    if l[kk] <= stop: exitp = stop; break
                                    if h[kk] >= tgt: exitp = tgt; break
                                if exitp is None: exitp = c[min(j+max_hold-1, n-1)]
                                trades.append(Trade(df.index[i], (exitp-entry)/risk, rf, +1))
                                break
                            if h[j] >= swing_hi + 0.001*leg:  # broke out before pullback -> skip
                                break
            # down impulse mirror
            if pl[i]:
                hi_idx = None
                for j in range(i-1, max(i-60, 0), -1):
                    if ph[j]: hi_idx = j; break
                if hi_idx is not None and l[i] < h[hi_idx]:
                    swing_lo = l[i]; swing_hi = h[hi_idx]; leg = swing_hi - swing_lo
                    if leg > 0:
                        gp = swing_lo + 0.618 * leg
                        stop = swing_hi + 0.05 * leg
                        tgt = swing_lo - 0.5 * leg if target == "ext" else None
                        for j in range(i+1, min(i+1+max_hold, n)):
                            if h[j] >= gp:
                                entry = gp; risk = stop - entry
                                if risk <= 0: break
                                if target == "r2": tgt = entry - 2.0 * risk
                                rf = risk / entry; exitp = None
                                for kk in range(j, min(j+max_hold, n)):
                                    if h[kk] >= stop: exitp = stop; break
                                    if l[kk] <= tgt: exitp = tgt; break
                                if exitp is None: exitp = c[min(j+max_hold-1, n-1)]
                                trades.append(Trade(df.index[i], (entry-exitp)/risk, rf, -1))
                                break
                            if l[j] <= swing_lo - 0.001*leg:
                                break
            i += 1
    return trades


if __name__ == "__main__":
    res = {"universe": "FX 10 pairs, both directions, golden-pocket continuation", "results": {}}
    for interval in ("15m", "30m"):
        for tgt in ("ext", "r2"):
            t = run(interval, target=tgt)
            res["results"][f"fibgp_{interval}_{tgt}"] = summarize(t, random_control(t))
    outp = Path("data/research/strategy_results/fib_goldenpocket_video.json")
    outp.write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res, indent=2, default=str))
