"""bt_bbrsi — Bollinger(30,2) + RSI(13) mean reversion, video pCmJ8wsAS_w.
  long entry : close < lower BB(30,2) AND RSI(13) < 25 -> next open
  target     : middle band (SMA30)
  stop       : entry - 2*ATR(14)
  exit       : hit mean (target) OR stop ; max_hold 20
Variant '_nosqz' skips narrow-band (squeeze) days: BBwidth/close > 20th pctile-ish (bw > 0.5*ATR%).
Daily US stocks, strategy_suite rig.
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, syms, atr, Trade, summarize, random_control

def _rsi(c,n=13):
    d=pd.Series(c).diff(); up=d.clip(lower=0); dn=(-d).clip(lower=0)
    au=up.ewm(alpha=1.0/n,adjust=False).mean(); ad=dn.ewm(alpha=1.0/n,adjust=False).mean()
    return (100-100/(1+au/ad.replace(0,np.nan))).fillna(50).values

def run(symlist, skip_squeeze=False, max_hold=20):
    trades=[]
    for s in symlist:
        df=load(s,"1d")
        if df is None or len(df)<80: continue
        c=df["close"].values;o=df["open"].values;l=df["low"].values;h=df["high"].values
        ma=pd.Series(c).rolling(30).mean(); sd=pd.Series(c).rolling(30).std()
        lb=(ma-2*sd).values; mb=ma.values; bw=((4*sd)/ma).values
        r=_rsi(c,13); av=atr(df,14)
        n=len(df); i=35
        while i<n-1:
            sig = (not np.isnan(lb[i]) and c[i]<lb[i] and r[i]<25)
            if skip_squeeze and (np.isnan(bw[i]) or bw[i]<0.08): sig=False
            if sig and not np.isnan(av[i]) and av[i]>0:
                entry=o[i+1]; stop=entry-2.0*av[i]; tgt=mb[i]; risk=entry-stop
                if risk>0 and tgt>entry:
                    rf=risk/entry; exitp=None
                    for j in range(i+1,min(i+1+max_hold,n)):
                        if l[j]<=stop: exitp=stop; break
                        if h[j]>=tgt: exitp=tgt; break
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
    for key,sq in {"bbrsi":False,"bbrsi_nosqueeze":True}.items():
        t=run(sl,sq); res["results"][key]=summarize(t,random_control(t))
    Path("data/research/strategy_results/bbrsi_video.json").write_text(json.dumps(res,indent=2,default=str))
    print("done",res["n_symbols"])
