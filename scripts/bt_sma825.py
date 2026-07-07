"""bt_sma825 — 8/25 SMA fast pullback mean reversion, video sYRCzSbvOpQ.
  filter/entry : close < SMA8 AND SMA8 > SMA25 (fast pullback in uptrend) -> next open
  exit         : close > SMA8 ; stop = entry - 2.5*ATR ; max_hold 20
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, syms, atr, Trade, summarize, random_control

def run(symlist, max_hold=20):
    trades=[]
    for s in symlist:
        df=load(s,"1d")
        if df is None or len(df)<60: continue
        c=df["close"].values;o=df["open"].values;l=df["low"].values;h=df["high"].values
        s8=pd.Series(c).rolling(8).mean().values; s25=pd.Series(c).rolling(25).mean().values; av=atr(df,14)
        n=len(df); i=30
        while i<n-1:
            if (not np.isnan(s25[i]) and c[i]<s8[i] and s8[i]>s25[i] and not np.isnan(av[i]) and av[i]>0):
                entry=o[i+1]; stop=entry-2.5*av[i]; risk=entry-stop
                if risk>0:
                    rf=risk/entry; exitp=None
                    for j in range(i+1,min(i+1+max_hold,n)):
                        if l[j]<=stop: exitp=stop; break
                        if c[j]>s8[j]: exitp=c[j]; break
                    if exitp is None: exitp=c[min(i+max_hold,n-1)]; j=min(i+max_hold,n-1)
                    trades.append(Trade(df.index[i],(exitp-entry)/risk,rf,+1)); i=j+1; continue
            i+=1
    return trades

if __name__=="__main__":
    cap=None
    if "--symbols" in sys.argv: cap=int(sys.argv[sys.argv.index("--symbols")+1])
    sl=syms("1d")
    if cap: sl=sl[:cap]
    t=run(sl)
    Path("data/research/strategy_results/sma825_video.json").write_text(json.dumps({"n_symbols":len(sl),"results":{"sma825":summarize(t,random_control(t))}},indent=2,default=str))
    print("done",len(sl))
