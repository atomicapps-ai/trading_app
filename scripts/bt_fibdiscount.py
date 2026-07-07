"""bt_fibdiscount — EMA50-uptrend Fib-discount pullback, video JL7HdUKRxfI (P3, risk-floored).
  trend  : close > EMA50
  swing  : 20-bar window; fib50 = (win_high+win_low)/2
  setup  : close < fib50 (discount zone) AND green confirmation candle (close>open)
  entry  : next open
  stop   : min low of last 5 bars, floored to >= 0.5*ATR14 (kills tiny-risk artifact)
  exit   : 3R target OR first close < EMA50 ; max_hold 60
strategy_suite rig (10bps, IS/OOS, random control).
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, syms, atr, Trade, summarize, random_control

def _ema(x,n): return pd.Series(x).ewm(span=n,adjust=False).mean().values

def fibdisc(symlist, exit_mode="3R", max_hold=60):
    trades=[]
    for s in symlist:
        df=load(s,"1d")
        if df is None or len(df)<120: continue
        c=df["close"].values;o=df["open"].values;l=df["low"].values;h=df["high"].values
        e50=_ema(c,50); av=atr(df,14)
        n=len(df); i=60
        while i<n-1:
            win_h=max(h[i-20:i+1]); win_l=min(l[i-20:i+1]); fib=(win_h+win_l)/2
            if (c[i]>e50[i] and win_h>win_l and c[i]<fib and c[i]>o[i] and not np.isnan(av[i]) and av[i]>0):
                entry=o[i+1]; raw=min(l[i-4:i+1]); stop=min(raw, entry-0.5*av[i]); risk=entry-stop
                if risk>0:
                    rf=risk/entry; tgt=entry+3*risk; exitp=None
                    for j in range(i+1,min(i+1+max_hold,n)):
                        if l[j]<=stop: exitp=stop; break
                        if exit_mode=="3R" and h[j]>=tgt: exitp=tgt; break
                        if exit_mode=="ema" and c[j]<e50[j]: exitp=c[j]; break
                    if exitp is None: exitp=c[min(i+max_hold,n-1)]
                    trades.append(Trade(df.index[i],(exitp-entry)/risk,rf,+1)); i=j+1; continue
            i+=1
    return trades

if __name__=="__main__":
    cap=None
    if "--symbols" in sys.argv: cap=int(sys.argv[sys.argv.index("--symbols")+1])
    sl=syms("1d")
    if cap: sl=sl[:cap]
    res={"n_symbols":len(sl),"results":{}}
    for key,em in {"fib_3R":"3R","fib_ema":"ema"}.items():
        t=fibdisc(sl,exit_mode=em); res["results"][key]=summarize(t,random_control(t))
    Path("data/research/strategy_results/fibdiscount_video.json").write_text(json.dumps(res,indent=2,default=str))
    print("done",res["n_symbols"])
