"""bt_ibs — Internal Bar Strength mean reversion (sourced: QuantifiedStrategies / Pagonidis 2013).

IBS = (close - low) / (high - low)  in [0,1]. Buy weakness (close near the low), sell strength.
  * Long: IBS < ibs_lo (0.2) -> enter next open.
  * Exit: IBS > ibs_hi (0.8) -> next open, OR max_hold days.
  * Variant `_t`: only long when close > SMA200 (trend filter).
No hard stop (mean reversion; exit on IBS>0.8 / time). R normalised to a fixed 5% nominal risk
(constant), so profit_factor & win% equal the true dollar figures. Daily US stocks, strategy_suite rig.
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, syms, Trade, summarize, random_control

RF = 0.05


def run(symlist, ibs_lo=0.2, ibs_hi=0.8, max_hold=4, trend=False):
    trades = []
    for s in symlist:
        df = load(s, "1d")
        if df is None or len(df) < 260:
            continue
        o = df["open"].values; h = df["high"].values; l = df["low"].values; c = df["close"].values
        rng = np.maximum(h - l, 1e-9)
        ibs = (c - l) / rng
        sma200 = pd.Series(c).rolling(200).mean().values
        n = len(df); i = 205
        while i < n - 1:
            if ibs[i] < ibs_lo and (not trend or (not np.isnan(sma200[i]) and c[i] > sma200[i])):
                ei = i + 1; entry = o[ei]; exitp = None; xj = ei
                for j in range(ei, min(ei + max_hold + 1, n)):
                    xj = j
                    if ibs[j] > ibs_hi:
                        xj = min(j + 1, n - 1); exitp = o[xj]; break
                    if j - ei >= max_hold:
                        xj = min(j + 1, n - 1); exitp = o[xj]; break
                if exitp is None:
                    xj = min(ei + max_hold, n - 1); exitp = o[xj]
                trades.append(Trade(df.index[i], (exitp - entry) / (RF * entry), RF, +1))
                i = xj + 1; continue
            i += 1
    return trades


if __name__ == "__main__":
    cap = None
    if "--symbols" in sys.argv: cap = int(sys.argv[sys.argv.index("--symbols")+1])
    sl = syms("1d")
    if cap: sl = sl[:cap]
    res = {"n_symbols": len(sl), "results": {}}
    for name, kw in {"ibs": dict(trend=False), "ibs_trend": dict(trend=True),
                     "ibs_hold3": dict(trend=False, max_hold=3)}.items():
        t = run(sl, **kw)
        res["results"][name] = summarize(t, random_control(t))
    Path("data/research/strategy_results/ibs_sourced.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res, indent=2, default=str))
