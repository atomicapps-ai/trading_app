"""bt_turtle — Donchian channel breakout (Richard Dennis / Turtle Traders), video 2ElrQnn2cZE.
Faithful mechanical spec from the video:
  entry  = close breaks prior N-day high, ONLY when close > SMA200 (long-only trend filter)
  stop   = entry - 2 * ATR(20)   ("2N")
  exit   = close breaks prior M-day low  (let profits run until channel flips)
Two canonical variants: System1 (20 in / 10 out), System2 (55 in / 20 out).
Measured on the same strategy_suite rig (10bps cost, IS/OOS split, random control).
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, syms, atr, Trade, summarize, random_control

def turtle(symlist, n_in, m_out, use_trend=True, atr_mult=2.0):
    trades = []
    for s in symlist:
        df = load(s, "1d")
        if df is None or len(df) < 300: continue
        c=df["close"].values;o=df["open"].values;l=df["low"].values;h=df["high"].values
        a=atr(df,20); sma200=pd.Series(c).rolling(200).mean().values
        hh=pd.Series(h).rolling(n_in).max().shift(1).values
        ll=pd.Series(l).rolling(m_out).min().shift(1).values
        n=len(df); i=205
        while i<n-1:
            if (not np.isnan(hh[i]) and c[i]>hh[i] and not np.isnan(a[i]) and a[i]>0
                    and (not use_trend or (not np.isnan(sma200[i]) and c[i]>sma200[i]))):
                entry=o[i+1]; stop=entry-atr_mult*a[i]; risk=entry-stop
                if risk>0:
                    rf=risk/entry; exitp=None; j=i+1
                    while j<n:
                        if l[j]<=stop: exitp=stop; break
                        if not np.isnan(ll[j]) and c[j]<ll[j]: exitp=c[j]; break
                        j+=1
                    if exitp is None: exitp=c[n-1]; j=n-1
                    trades.append(Trade(df.index[i],(exitp-entry)/risk,rf,+1)); i=j+1; continue
            i+=1
    return trades

def run(sl):
    out={}
    for key,(ni,mo,tr) in {
        "turtle_s1_20_10_trend":(20,10,True),
        "turtle_s2_55_20_trend":(55,20,True),
        "turtle_s1_20_10_notrend":(20,10,False),
    }.items():
        t=turtle(sl,ni,mo,tr)
        out[key]=summarize(t, random_control(t))
    return out

if __name__=="__main__":
    cap=None
    if "--symbols" in sys.argv: cap=int(sys.argv[sys.argv.index("--symbols")+1])
    sl=syms("1d")
    if cap: sl=sl[:cap]
    res={"n_symbols":len(sl),"results":run(sl)}
    print(json.dumps(res,indent=2,default=str))
