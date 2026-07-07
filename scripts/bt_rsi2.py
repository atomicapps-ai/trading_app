"""bt_rsi2 — Larry Connors 2-period RSI mean reversion, video gvzCDqjccLs.
  filter : close > SMA200 (long-only uptrend)
  entry  : RSI(2) crosses below 10 -> next open
  exit   : (a) RSI(2) > 70  OR  (b) first profitable close (optional day-delay)
  stop   : entry - 2.5*ATR(14)  (Connors uses none; we floor risk for R-accounting)
Daily US stocks, strategy_suite rig (10bps, IS/OOS, random control).
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, syms, atr, Trade, summarize, random_control

def _rsi(c, n=2):
    d=pd.Series(c).diff()
    up=d.clip(lower=0); dn=(-d).clip(lower=0)
    au=up.ewm(alpha=1.0/n, adjust=False).mean()
    ad=dn.ewm(alpha=1.0/n, adjust=False).mean()
    rs=au/ad.replace(0,np.nan)
    return (100 - 100/(1+rs)).fillna(50).values

def run_rsi2(symlist, exit_mode="rsi70", delay=0, max_hold=20):
    trades=[]
    for s in symlist:
        df=load(s,"1d")
        if df is None or len(df)<260: continue
        c=df["close"].values;o=df["open"].values;l=df["low"].values;h=df["high"].values
        r=_rsi(c,2); s200=pd.Series(c).rolling(200).mean().values; av=atr(df,14)
        n=len(df); i=205
        while i<n-1:
            if (not np.isnan(s200[i]) and c[i]>s200[i] and r[i]<10 and r[i-1]>=10
                    and not np.isnan(av[i]) and av[i]>0):
                entry=o[i+1]; stop=entry-2.5*av[i]; risk=entry-stop
                if risk>0:
                    rf=risk/entry; exitp=None
                    for k,j in enumerate(range(i+1,min(i+1+max_hold,n))):
                        if l[j]<=stop: exitp=stop; break
                        if exit_mode=="rsi70" and r[j]>70: exitp=c[j]; break
                        if exit_mode=="fpc" and k>=delay and c[j]>entry: exitp=c[j]; break
                    if exitp is None: exitp=c[min(i+max_hold,n-1)]; j=min(i+max_hold,n-1)
                    trades.append(Trade(df.index[i],(exitp-entry)/risk,rf,+1)); i=j+1; continue
            i+=1
    return trades

if __name__=="__main__":
    cap=None
    if "--symbols" in sys.argv: cap=int(sys.argv[sys.argv.index("--symbols")+1])
    sl=syms("1d")
    if cap: sl=sl[:cap]
    res={"n_symbols":len(sl),"results":{}}
    for key,(em,dl) in {"rsi2_rsi70":("rsi70",0),"rsi2_fpc":("fpc",0),"rsi2_fpc_delay3":("fpc",3)}.items():
        t=run_rsi2(sl,em,dl); res["results"][key]=summarize(t,random_control(t))
    Path("data/research/strategy_results/rsi2_video.json").write_text(json.dumps(res,indent=2,default=str))
    print("done",res["n_symbols"])
