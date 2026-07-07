"""bt_ma_crossover — 20/50 MA crossover "done right", video k_kSCjdf8D0.

The video's mechanical core is a plain 20/50 MA crossover on the daily; its only differentiator
is a discretionary market-selection filter ("only trade pairs that historically react to the
crossover"), which is hindsight-based and not mechanizable. Here we test the mechanical core.

Spec (long side on the long-biased equity universe):
  * SMA 20 and SMA 50 on daily closes.
  * Enter long when SMA20 crosses **above** SMA50 -> next open. Exit when it crosses back
    **below** -> next open. Variant `f200`: only take longs while price > 200-SMA (trend filter).
  * No hard stop (trend-following, exit on opposite cross). R normalised to fixed 5% nominal
    risk (constant) so PF/win% equal the true dollar figures. strategy_suite rig, daily US stocks.
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, syms, Trade, summarize, random_control

RISK_FRAC = 0.05


def run(symlist, filt200=False):
    trades = []
    for s in symlist:
        df = load(s, "1d")
        if df is None or len(df) < 260:
            continue
        o = df["open"].values; c = df["close"].values
        sma20 = pd.Series(c).rolling(20).mean().values
        sma50 = pd.Series(c).rolling(50).mean().values
        sma200 = pd.Series(c).rolling(200).mean().values
        n = len(df); i = 205
        while i < n - 1:
            cross_up = sma20[i] > sma50[i] and sma20[i-1] <= sma50[i-1]
            if cross_up and (not filt200 or (not np.isnan(sma200[i]) and c[i] > sma200[i])):
                entry = o[i+1]; exitp = None; xj = i+1
                for j in range(i+1, n-1):
                    xj = j
                    if sma20[j] < sma50[j] and sma20[j-1] >= sma50[j-1]:
                        exitp = o[j+1]; xj = j+1; break
                if exitp is None:
                    xj = n-1; exitp = c[xj]
                r = (exitp - entry) / (RISK_FRAC * entry)
                trades.append(Trade(df.index[i], r, RISK_FRAC, +1))
                i = xj + 1; continue
            i += 1
    return trades


if __name__ == "__main__":
    cap = None
    if "--symbols" in sys.argv: cap = int(sys.argv[sys.argv.index("--symbols")+1])
    sl = syms("1d")
    if cap: sl = sl[:cap]
    res = {"n_symbols": len(sl), "results": {}}
    for name, f in {"macross_2050": False, "macross_2050_f200": True}.items():
        t = run(sl, f)
        res["results"][name] = summarize(t, random_control(t))
    Path("data/research/strategy_results/ma_crossover_video.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res, indent=2, default=str))
