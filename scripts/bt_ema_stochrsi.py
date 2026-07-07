"""bt_ema_stochrsi — TradePro triple-EMA + Stochastic-RSI scalp, video 7NM7bR2mL7U.

Spec (both directions, demoed on FX intraday with ATR-in-pips TP/SL):
  * EMAs 8, 14, 50 on close.
  * LONG when stacked up: EMA8 > EMA14 > EMA50, a Stoch-RSI %K crosses **up** through %D,
    and the trigger candle **closes above all three EMAs**. Enter next open.
  * SHORT mirror: EMA8 < EMA14 < EMA50, %K crosses **down** through %D, close below all 3 EMAs.
  * Stoch-RSI settings 3,3,14,14 (TradingView default): RSI(14) -> stoch over 14 -> %K sma3 -> %D sma3.
  * Target = 2.0 * ATR(14).  Stop = 3.0 * ATR(14).  (low target / wide stop -> "high win rate scalp")
  * max_hold 40 bars. FX pairs, tested at 15m and 30m. strategy_suite rig.
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, atr, Trade, summarize, random_control

FX = ["EURUSD","USDJPY","EURJPY","GBPJPY","AUDJPY","EURAUD","EURCAD","GBPUSD","AUDUSD","XAUUSD"]


def _ema(c, n):
    return pd.Series(c).ewm(span=n, adjust=False).mean().values


def _stochrsi(c, rsi_n=14, stoch_n=14, k=3, d=3):
    s = pd.Series(c); dlt = s.diff()
    up = dlt.clip(lower=0).ewm(alpha=1.0/rsi_n, adjust=False).mean()
    dn = (-dlt).clip(lower=0).ewm(alpha=1.0/rsi_n, adjust=False).mean()
    rsi = 100 - 100/(1 + up/dn.replace(0, np.nan))
    lo = rsi.rolling(stoch_n).min(); hi = rsi.rolling(stoch_n).max()
    st = 100 * (rsi - lo) / (hi - lo).replace(0, np.nan)
    kk = st.rolling(k).mean(); dd = kk.rolling(d).mean()
    return kk.fillna(50).values, dd.fillna(50).values


def run(interval, max_hold=40):
    trades = []
    for s in FX:
        df = load(s, interval)
        if df is None or len(df) < 300:
            continue
        o = df["open"].values; c = df["close"].values; l = df["low"].values; h = df["high"].values
        e8 = _ema(c, 8); e14 = _ema(c, 14); e50 = _ema(c, 50)
        kk, dd = _stochrsi(c); a = atr(df, 14)
        n = len(df); i = 55
        while i < n - 1:
            xup = kk[i] > dd[i] and kk[i-1] <= dd[i-1]
            xdn = kk[i] < dd[i] and kk[i-1] >= dd[i-1]
            long_ok = e8[i] > e14[i] > e50[i] and c[i] > e8[i] and c[i] > e14[i] and c[i] > e50[i] and xup
            short_ok = e8[i] < e14[i] < e50[i] and c[i] < e8[i] and c[i] < e14[i] and c[i] < e50[i] and xdn
            if (long_ok or short_ok) and not np.isnan(a[i]) and a[i] > 0:
                d = +1 if long_ok else -1
                entry = o[i+1]
                stop = entry - d * 3.0 * a[i]
                tgt = entry + d * 2.0 * a[i]
                risk = abs(entry - stop)
                if risk > 0:
                    rf = risk / entry; exitp = None; jj = i + 1
                    for j in range(i+1, min(i+1+max_hold, n)):
                        jj = j
                        if d == +1:
                            if l[j] <= stop: exitp = stop; break
                            if h[j] >= tgt: exitp = tgt; break
                        else:
                            if h[j] >= stop: exitp = stop; break
                            if l[j] <= tgt: exitp = tgt; break
                    if exitp is None: exitp = c[min(i+max_hold, n-1)]
                    r = d * (exitp - entry) / risk
                    trades.append(Trade(df.index[i], r, rf, d))
                    i = jj + 1; continue
            i += 1
    return trades


if __name__ == "__main__":
    res = {"universe": "FX 10 pairs (9 majors + XAUUSD), both directions", "results": {}}
    for interval in ("15m", "30m"):
        t = run(interval)
        res["results"][f"ema_stochrsi_{interval}"] = summarize(t, random_control(t))
    outp = Path("data/research/strategy_results/ema_stochrsi_video.json")
    outp.write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res, indent=2, default=str))
