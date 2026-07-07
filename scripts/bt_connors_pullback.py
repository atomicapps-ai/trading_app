"""bt_connors_pullback — Larry Connors RSI pullback, video W8ENIXvcGlQ.

Spec (long; the classic Connors mean-reversion pullback):
  * Trend filter: price above its **200-day SMA** (else stay in cash).
  * Entry: **RSI(10) < 30** -> buy next day's open.
  * Exit: **RSI(10) crosses above 40** -> sell next open; OR a **10-trading-day time stop**.
  * No hard stop-loss (pure mean reversion; time stop caps duration).
Because the strategy has no protective stop, R is normalised to a fixed nominal risk of 5% of
price (risk_frac = 0.05, constant) — so profit_factor and win% equal the true dollar figures and
the 10-bps cost maps to a negligible 0.04R. Tested on the 955-symbol daily US-stock universe
(per-symbol 200-SMA + RSI10). strategy_suite rig.
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, syms, Trade, summarize, random_control

RISK_FRAC = 0.05


def _rsi(c, n=10):
    d = pd.Series(c).diff(); up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d).clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    return (100 - 100/(1 + up/dn.replace(0, np.nan))).fillna(50).values


def run(symlist, rsi_entry=30, rsi_exit=40, time_stop=10):
    trades = []
    for s in symlist:
        df = load(s, "1d")
        if df is None or len(df) < 260:
            continue
        o = df["open"].values; c = df["close"].values
        sma200 = pd.Series(c).rolling(200).mean().values
        rsi = _rsi(c, 10)
        n = len(df); i = 205
        while i < n - 1:
            if not np.isnan(sma200[i]) and c[i] > sma200[i] and rsi[i] < rsi_entry:
                ei = i + 1  # enter next open
                entry = o[ei]; exitp = None; xj = ei
                for j in range(ei, min(ei + time_stop + 1, n)):
                    xj = j
                    if rsi[j] > rsi_exit:
                        xj = min(j + 1, n - 1); exitp = o[xj]; break
                    if j - ei >= time_stop:
                        xj = min(j + 1, n - 1); exitp = o[xj]; break
                if exitp is None:
                    xj = min(ei + time_stop, n - 1); exitp = o[xj]
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
    t = run(sl)
    res["results"]["connors_rsi10_pullback"] = summarize(t, random_control(t))
    # tighter variant (RSI2<10, exit>50) for comparison
    Path("data/research/strategy_results/connors_pullback_video.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res, indent=2, default=str))
