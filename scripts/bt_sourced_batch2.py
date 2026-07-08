"""bt_sourced_batch2 — second batch of sourced candidates.

* Double-7s (Connors/Alvarez, "Short Term Trading Strategies That Work"; QuantifiedStrategies):
  close>SMA200; buy at a 7-day low; sell at a 7-day high. No stop. Mean-reversion (ETF-oriented).
* Halloween / Sell-in-May (well documented; QuantifiedStrategies/Quantpedia): long only from the
  close of Oct through the end of Apr; flat May–Sep. Seasonality.

Both no-stop -> fixed 5% nominal risk normalisation. strategy_suite rig (IS/OOS + control).
Run: python scripts/bt_sourced_batch2.py [--symbols N] [--etf]
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, syms, Trade, summarize, random_control

RF = 0.05
ETFS = ["SPY", "IWM", "XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU", "XLB", "XLRE", "XLC"]


def double7(symlist, n_lh=7, max_hold=15):
    trades = []
    for s in symlist:
        df = load(s, "1d")
        if df is None or len(df) < 260:
            continue
        o = df["open"].values; c = df["close"].values
        sma200 = pd.Series(c).rolling(200).mean().values
        lo7 = pd.Series(c).rolling(n_lh).min().values
        hi7 = pd.Series(c).rolling(n_lh).max().values
        n = len(df); i = 205
        while i < n - 1:
            if not np.isnan(sma200[i]) and c[i] > sma200[i] and c[i] <= lo7[i]:
                ei = i + 1; entry = o[ei]; exitp = None; xj = ei
                for j in range(ei, min(ei + max_hold + 1, n)):
                    xj = j
                    if c[j] >= hi7[j]:
                        xj = min(j + 1, n - 1); exitp = o[xj]; break
                    if j - ei >= max_hold:
                        xj = min(j + 1, n - 1); exitp = o[xj]; break
                if exitp is None:
                    xj = min(ei + max_hold, n - 1); exitp = o[xj]
                trades.append(Trade(df.index[i], (exitp - entry) / (RF * entry), RF, +1))
                i = xj + 1; continue
            i += 1
    return trades


def halloween(symlist):
    """Long from the first trading day of November to the last of April; one position per season."""
    trades = []
    for s in symlist:
        df = load(s, "1d")
        if df is None or len(df) < 400:
            continue
        c = df["close"].values; idx = df.index
        months = np.array([t.month for t in idx]); years = np.array([t.year for t in idx])
        n = len(df); i = 1
        while i < n:
            # entry: first bar with month == 11
            if months[i] == 11 and months[i-1] != 11:
                entry_pos = i; entry = c[entry_pos]
                # exit: last bar with month == 4 in the following spring
                xj = entry_pos
                for j in range(entry_pos + 1, n):
                    if months[j] == 4:
                        xj = j
                    if months[j] == 5 and months[j-1] == 4:
                        break
                if xj > entry_pos and entry > 0:
                    trades.append(Trade(idx[entry_pos], (c[xj] - entry) / (RF * entry), RF, +1))
                    i = xj + 1; continue
            i += 1
    return trades


if __name__ == "__main__":
    cap = None
    if "--symbols" in sys.argv: cap = int(sys.argv[sys.argv.index("--symbols")+1])
    sl = ETFS if "--etf" in sys.argv else syms("1d")
    if cap: sl = sl[:cap]
    res = {"universe": "etf" if "--etf" in sys.argv else "stocks", "n_symbols": len(sl), "results": {}}
    for name, t in {"double7": double7(sl), "halloween": halloween(sl)}.items():
        res["results"][name] = summarize(t, random_control(t))
    tag = "etf" if "--etf" in sys.argv else "stocks"
    Path(f"data/research/strategy_results/sourced_batch2_{tag}.json").write_text(json.dumps(res, indent=2, default=str))
    for k, v in res["results"].items():
        a = v["all"]; oo = v["out_sample"]; rc = v["random_control"]
        print(f"{k:12} n={a['n']:6} win%={a['win_pct']} OOS_PF={oo['profit_factor']} avgR={oo['expectancy_R']} "
              f"IS_PF={v['in_sample']['profit_factor']} ctrl={rc['profit_factor']}")
