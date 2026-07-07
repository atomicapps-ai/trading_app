"""bt_supertrend — DEMA200 + SuperTrend(12,3) trend follower, video g-PLctW8aU0.
  filter : close > DEMA(200)  (long only; below = shorts, tested separately)
  entry  : SuperTrend flips DOWN->UP while price is above DEMA200 -> next open
  stop   : the SuperTrend line at entry (its lower band)
  exit   : SuperTrend flips UP->DOWN (the trailing stop) -> that bar's close
Daily US stocks, strategy_suite rig (10bps, IS/OOS, random control).
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, syms, Trade, summarize, random_control

def _dema(x,n):
    e=pd.Series(x).ewm(span=n,adjust=False).mean()
    return (2*e - e.ewm(span=n,adjust=False).mean()).values

def _supertrend(h,l,c,period=12,mult=3.0):
    n=len(c); hl2=(h+l)/2.0
    pc=np.roll(c,1); pc[0]=c[0]
    tr=np.maximum(h-l,np.maximum(np.abs(h-pc),np.abs(l-pc)))
    atr=pd.Series(tr).rolling(period).mean().values
    up=hl2+mult*atr; dn=hl2-mult*atr
    fu=np.full(n,np.nan); fl=np.full(n,np.nan); trend=np.ones(n,dtype=int); st=np.full(n,np.nan)
    for i in range(1,n):
        if np.isnan(atr[i]): trend[i]=1; continue
        if np.isnan(fu[i-1]) or np.isnan(fl[i-1]):
            fu[i]=up[i]; fl[i]=dn[i]; trend[i]=1 if c[i]>=hl2[i] else -1
            st[i]=fl[i] if trend[i]==1 else fu[i]; continue
        fu[i]=up[i] if (up[i]<fu[i-1] or c[i-1]>fu[i-1]) else fu[i-1]
        fl[i]=dn[i] if (dn[i]>fl[i-1] or c[i-1]<fl[i-1]) else fl[i-1]
        if c[i]>fu[i-1]: trend[i]=1
        elif c[i]<fl[i-1]: trend[i]=-1
        else: trend[i]=trend[i-1]
        st[i]=fl[i] if trend[i]==1 else fu[i]
    return trend, st

def run_st(symlist, side="long", use_filter=True):
    trades=[]
    for s in symlist:
        df=load(s,"1d")
        if df is None or len(df)<260: continue
        c=df["close"].values;o=df["open"].values;l=df["low"].values;h=df["high"].values
        dema=_dema(c,200); trend,st=_supertrend(h,l,c,12,3.0)
        n=len(df); i=205
        while i<n-1:
            flip_up = trend[i]==1 and trend[i-1]==-1
            if side=="long" and flip_up and (not use_filter or (dema[i]==dema[i] and c[i]>dema[i])):
                entry=o[i+1]; stop=st[i]; risk=entry-stop
                if risk>0:
                    rf=risk/entry; exitp=None
                    for j in range(i+1,n):
                        if trend[j]==-1: exitp=c[j]; break
                    if exitp is None: exitp=c[n-1]; j=n-1
                    trades.append(Trade(df.index[i],(exitp-entry)/risk,rf,+1)); i=j+1; continue
            i+=1
    return trades

if __name__=="__main__":
    cap=None
    if "--symbols" in sys.argv: cap=int(sys.argv[sys.argv.index("--symbols")+1])
    sl=syms("1d")
    if cap: sl=sl[:cap]
    res={"n_symbols":len(sl),"results":{}}
    for key,(sd,uf) in {"st_long_dema":("long",True),"st_long_nofilter":("long",False)}.items():
        t=run_st(sl,sd,uf); res["results"][key]=summarize(t,random_control(t))
    Path("data/research/strategy_results/supertrend_video.json").write_text(json.dumps(res,indent=2,default=str))
    print("done",res["n_symbols"])
