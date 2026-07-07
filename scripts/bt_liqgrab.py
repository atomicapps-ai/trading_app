"""bt_liqgrab — 'liquidity grab' failed-breakout reversal, video 4cT8WTyxhYY.
Core mechanical kernel (stripping the proprietary indicator / discretionary S/R):
  sell-side grab (LONG): today's low < prior M-day low  AND  close back > prior M-day low
      -> failed breakdown; enter next open, stop = today's low, target = prior M-day high
  buy-side grab (SHORT): today's high > prior M-day high AND close back < prior M-day high
      -> failed breakout; enter next open, stop = today's high, target = prior M-day low
Daily US stocks, strategy_suite rig (10 bps, IS/OOS, random control).
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, syms, atr, Trade, summarize, random_control

def liqgrab(symlist, M=20, max_hold=30, side="both"):
    trades=[]
    for s in symlist:
        df=load(s,"1d")
        if df is None or len(df)<M+40: continue
        c=df["close"].values;o=df["open"].values;l=df["low"].values;h=df["high"].values
        av=atr(df,14)
        lloM=pd.Series(l).rolling(M).min().shift(1).values
        hhiM=pd.Series(h).rolling(M).max().shift(1).values
        n=len(df); i=M+1
        while i<n-1:
            did=False
            if side in ("both","long") and not np.isnan(lloM[i]) and l[i]<lloM[i] and c[i]>lloM[i]:
                entry=o[i+1]; stop=min(l[i], entry-0.5*av[i]); tgt=hhiM[i]; risk=entry-stop
                if risk>0 and tgt>entry:
                    rf=risk/entry; exitp=None
                    for j in range(i+1,min(i+1+max_hold,n)):
                        if l[j]<=stop: exitp=stop; break
                        if h[j]>=tgt: exitp=tgt; break
                    if exitp is None: exitp=c[min(i+max_hold,n-1)]
                    trades.append(Trade(df.index[i],(exitp-entry)/risk,rf,+1)); i=j+1; did=True
            elif side in ("both","short") and not np.isnan(hhiM[i]) and h[i]>hhiM[i] and c[i]<hhiM[i]:
                entry=o[i+1]; stop=max(h[i], entry+0.5*av[i]); tgt=lloM[i]; risk=stop-entry
                if risk>0 and tgt<entry:
                    rf=risk/entry; exitp=None
                    for j in range(i+1,min(i+1+max_hold,n)):
                        if h[j]>=stop: exitp=stop; break
                        if l[j]<=tgt: exitp=tgt; break
                    if exitp is None: exitp=c[min(i+max_hold,n-1)]
                    trades.append(Trade(df.index[i],(entry-exitp)/risk,rf,-1)); i=j+1; did=True
            if not did: i+=1
    return trades

if __name__=="__main__":
    cap=None
    if "--symbols" in sys.argv: cap=int(sys.argv[sys.argv.index("--symbols")+1])
    sl=syms("1d")
    if cap: sl=sl[:cap]
    res={"n_symbols":len(sl),"results":{}}
    for key,side in {"liqgrab_long":"long","liqgrab_short":"short","liqgrab_both":"both"}.items():
        t=liqgrab(sl,side=side)
        res["results"][key]=summarize(t,random_control(t))
    Path("data/research/strategy_results/liqgrab_video.json").write_text(json.dumps(res,indent=2,default=str))
    print("done",res["n_symbols"])
