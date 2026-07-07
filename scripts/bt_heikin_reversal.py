"""bt_heikin_reversal — Heikin-Ashi + Stochastic reversal, video 2G78zkuQSc0.

Spec (long; universe is long-biased equities so we test the long side):
  * Build Heikin-Ashi candles from OHLC.
  * Downtrend context: >=3 of prior 4 HA candles bearish (ha_close < ha_open).
  * Doji HA candle: body <= 0.35*range AND has both an upper and lower wick.
  * Confirmation: the TWO HA candles after the doji are strong-bull:
        green (ha_close>ha_open), body >= 0.5*range, negligible lower wick
        (lower wick <= 0.1*range)  -> "no lower wick" per the video.
  * Stochastic filter: %K(14,3) was <= 25 (oversold) somewhere in the doji->confirm
    window ("crossing below the bottom line").
  * Entry: next real open after the 2nd confirming candle.
  * Exit (video gives none): harness-standard. stop = entry - 1.0*ATR14.
        base    : target = entry + 2.0*ATR (2R), else time stop.
        haflip  : ride until 2 consecutive bearish HA candles, else stop/time.
  * max_hold 20 bars. Daily US stocks, strategy_suite rig.
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, syms, atr, Trade, summarize, random_control


def heikin(df: pd.DataFrame):
    o, h, l, c = (df[x].values for x in ("open", "high", "low", "close"))
    n = len(df)
    ha_c = (o + h + l + c) / 4.0
    ha_o = np.empty(n); ha_o[0] = (o[0] + c[0]) / 2.0
    for i in range(1, n):
        ha_o[i] = (ha_o[i-1] + ha_c[i-1]) / 2.0
    ha_h = np.maximum.reduce([h, ha_o, ha_c])
    ha_l = np.minimum.reduce([l, ha_o, ha_c])
    return ha_o, ha_h, ha_l, ha_c


def _stoch_k(df, n=14, smooth=3):
    h = df["high"].rolling(n).max(); l = df["low"].rolling(n).min()
    raw = 100 * (df["close"] - l) / (h - l).replace(0, np.nan)
    return raw.rolling(smooth).mean().fillna(50).values


def run(symlist, mode="base", max_hold=20):
    trades = []
    for s in symlist:
        df = load(s, "1d")
        if df is None or len(df) < 120:
            continue
        o = df["open"].values; c = df["close"].values; l = df["low"].values; h = df["high"].values
        ha_o, ha_h, ha_l, ha_c = heikin(df)
        rng = np.maximum(ha_h - ha_l, 1e-9)
        body = np.abs(ha_c - ha_o)
        bull = ha_c > ha_o
        low_wick = np.minimum(ha_o, ha_c) - ha_l
        up_wick = ha_h - np.maximum(ha_o, ha_c)
        is_doji = (body <= 0.35 * rng) & (low_wick > 0.05 * rng) & (up_wick > 0.05 * rng)
        strong_bull = bull & (body >= 0.5 * rng) & (low_wick <= 0.10 * rng)
        k = _stoch_k(df); a = atr(df)
        n = len(df); i = 20
        while i < n - 1:
            # i is the doji bar; need downtrend before, 2 strong-bull after (i+1,i+2)
            if is_doji[i] and i + 2 < n:
                prior_bear = sum(1 for j in range(i-4, i) if j >= 0 and not bull[j])
                if prior_bear >= 3 and strong_bull[i+1] and strong_bull[i+2]:
                    if (k[i] <= 25 or k[i+1] <= 25 or k[i+2] <= 25):
                        e = i + 2  # confirmed at close of 2nd bull candle
                        if e + 1 < n and not np.isnan(a[e]) and a[e] > 0:
                            entry = o[e+1]; stop = entry - 1.0 * a[e]; risk = entry - stop
                            if risk > 0:
                                rf = risk / entry; tgt = entry + 2.0 * a[e]; exitp = None
                                jj = e + 1
                                for j in range(e+1, min(e+1+max_hold, n)):
                                    jj = j
                                    if l[j] <= stop: exitp = stop; break
                                    if mode == "base" and h[j] >= tgt: exitp = tgt; break
                                    if mode == "haflip" and j+0 < n and not bull[j] and not bull[j-1]:
                                        exitp = c[j]; break
                                if exitp is None: exitp = c[min(e+max_hold, n-1)]
                                trades.append(Trade(df.index[e], (exitp-entry)/risk, rf, +1))
                                i = jj + 1; continue
            i += 1
    return trades


if __name__ == "__main__":
    cap = None
    if "--symbols" in sys.argv: cap = int(sys.argv[sys.argv.index("--symbols")+1])
    sl = syms("1d")
    if cap: sl = sl[:cap]
    res = {"n_symbols": len(sl), "results": {}}
    for mode in ("base", "haflip"):
        t = run(sl, mode)
        res["results"][f"heikin_{mode}"] = summarize(t, random_control(t))
    outp = Path("data/research/strategy_results/heikin_reversal_video.json")
    outp.write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res, indent=2, default=str))
