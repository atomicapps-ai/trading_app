"""bt_qs — Quantified Strategies swing set, video KuXV0LRfJx8 (SPY-designed; tested per-stock).
Common exit: sell when close > yesterday's high (mean-reversion strength exit).
Entry at signal-day CLOSE (as in the video). Stop floored at 2.5*ATR(14) for R-accounting.
  s2 turnaround_tue : buy if close down 2 days in a row AND weekday==Monday
  s3 five_day_low   : buy if close < min(low, prior 5 days)
  s5 hi10_ibs       : buy if high > prior 10-day high AND IBS<0.15  (IBS=(c-l)/(h-l))
Daily US stocks, strategy_suite rig (10bps, IS/OOS, random control).
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, syms, atr, Trade, summarize, random_control

def _exit_fwd(i,entry,stop,l,h,c,n,max_hold=15):
    for j in range(i+1,min(i+1+max_hold,n)):
        if l[j]<=stop: return stop,j
        if c[j]>h[j-1]: return c[j],j
    j=min(i+max_hold,n-1); return c[j],j

def run(symlist, strat):
    trades=[]
    for s in symlist:
        df=load(s,"1d")
        if df is None or len(df)<60: continue
        c=df["close"].values;o=df["open"].values;l=df["low"].values;h=df["high"].values
        av=atr(df,14); idx=df.index
        ll5=pd.Series(l).rolling(5).min().shift(1).values
        hh10=pd.Series(h).rolling(10).max().shift(1).values
        rng=h-l; ibs=np.where(rng>0,(c-l)/rng,0.5)
        n=len(df); i=15
        while i<n-1:
            sig=False
            if strat=="s3" and not np.isnan(ll5[i]) and c[i]<ll5[i]: sig=True
            elif strat=="s2" and idx[i].weekday()==0 and c[i]<c[i-1] and c[i-1]<c[i-2]: sig=True
            elif strat=="s5" and not np.isnan(hh10[i]) and h[i]>hh10[i] and ibs[i]<0.15: sig=True
            if sig and not np.isnan(av[i]) and av[i]>0:
                entry=c[i]; stop=entry-2.5*av[i]; risk=entry-stop
                if risk>0:
                    rf=risk/entry; exitp,j=_exit_fwd(i,entry,stop,l,h,c,n)
                    trades.append(Trade(idx[i],(exitp-entry)/risk,rf,+1)); i=j+1; continue
            i+=1
    return trades

if __name__=="__main__":
    cap=None
    if "--symbols" in sys.argv: cap=int(sys.argv[sys.argv.index("--symbols")+1])
    sl=syms("1d")
    if cap: sl=sl[:cap]
    res={"n_symbols":len(sl),"results":{}}
    for key in ("s2","s3","s5"):
        t=run(sl,key); res["results"][key]=summarize(t,random_control(t))
    Path("data/research/strategy_results/qs_video.json").write_text(json.dumps(res,indent=2,default=str))
    print("done",res["n_symbols"])
