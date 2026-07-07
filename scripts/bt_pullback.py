"""bt_pullback — 21-EMA pullback-in-uptrend continuation, video AKkeB8RJ6jM.
Faithful spec: strong market + strong stock, buy a supported pullback to the 21-EMA.
  market filter : SPY close > SPY SMA50 (bull regime)
  stock uptrend : close > SMA50 AND SMA50 rising over 20 bars
  pullback+rev  : today's low <= EMA21 AND green day AND close in top 40% of range AND vol >= 20d avg
  entry         : next open
  stop          : below the reversal-day low, FLOORED to >= 0.5*ATR14 (kills tiny-risk artifact)
  exit          : first close < EMA21 (let winners run) OR stop; max_hold 60
Also a 3R-target variant. strategy_suite rig (10bps, IS/OOS, random control).
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, syms, atr, Trade, summarize, random_control

def _ema(x,n): return pd.Series(x).ewm(span=n,adjust=False).mean().values
def _sma(x,n): return pd.Series(x).rolling(n).mean().values

def _spy_bull():
    spy=load("SPY","1d")
    if spy is None: return None
    c=spy["close"].values; s50=_sma(c,50)
    return {spy.index[i].normalize(): (c[i]>s50[i]) for i in range(len(spy)) if s50[i]==s50[i]}

def pullback(symlist, use_market=True, exit_mode="ema", max_hold=60):
    bull=_spy_bull() if use_market else None
    trades=[]
    for s in symlist:
        df=load(s,"1d")
        if df is None or len(df)<160: continue
        c=df["close"].values;o=df["open"].values;l=df["low"].values;h=df["high"].values;v=df["volume"].values
        e21=_ema(c,21); s50=_sma(c,50); vavg=_sma(v,20); av=atr(df,14)
        n=len(df); i=60
        while i<n-1:
            rng=h[i]-l[i]
            mkt = True if bull is None else bull.get(df.index[i].normalize(), False)
            if (mkt and not np.isnan(s50[i]) and c[i]>s50[i] and s50[i]>s50[i-20]
                    and l[i]<=e21[i] and c[i]>=o[i] and rng>0 and (c[i]-l[i])/rng>=0.6
                    and not np.isnan(vavg[i]) and v[i]>=vavg[i] and not np.isnan(av[i]) and av[i]>0):
                entry=o[i+1]; stop=min(l[i], entry-0.5*av[i]); risk=entry-stop
                if risk>0:
                    rf=risk/entry; tgt=entry+3*risk; exitp=None
                    for j in range(i+1,min(i+1+max_hold,n)):
                        if l[j]<=stop: exitp=stop; break
                        if exit_mode=="3R" and h[j]>=tgt: exitp=tgt; break
                        if exit_mode=="ema" and c[j]<e21[j]: exitp=c[j]; break
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
    for key,(mk,em) in {"pull_ema_mkt":(True,"ema"),"pull_3R_mkt":(True,"3R"),"pull_ema_nomkt":(False,"ema")}.items():
        t=pullback(sl,use_market=mk,exit_mode=em)
        res["results"][key]=summarize(t,random_control(t))
    Path("data/research/strategy_results/pullback_video.json").write_text(json.dumps(res,indent=2,default=str))
    print("done",res["n_symbols"])
