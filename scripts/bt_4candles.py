"""bt_4candles — buy after 4 red daily candles mean reversion, video qpkCxEUdoMo.
  entry : 4 consecutive red candles (close<open) -> buy at that close (long-only on stocks)
  stop  : entry - 3*ATR(14) (wide fail-safe, per the video)
  exits : (a) close > SMA25 (mean)  (b) time 20 days  (c) first profitable close
Daily US stocks, strategy_suite rig.
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, syms, atr, Trade, summarize, random_control

def run(symlist, exit_mode="ma", max_hold=20):
    trades=[]
    for s in symlist:
        df=load(s,"1d")
        if df is None or len(df)<60: continue
        c=df["close"].values;o=df["open"].values;l=df["low"].values;h=df["high"].values
        sma25=pd.Series(c).rolling(25).mean().values; av=atr(df,14)
        n=len(df); i=30
        while i<n-1:
            red4 = c[i]<o[i] and c[i-1]<o[i-1] and c[i-2]<o[i-2] and c[i-3]<o[i-3]
            if red4 and not np.isnan(av[i]) and av[i]>0 and (exit_mode!="ma" or (not np.isnan(sma25[i]) and c[i]<sma25[i])):
                entry=c[i]; stop=entry-3.0*av[i]; risk=entry-stop
                if risk>0:
                    rf=risk/entry; exitp=None
                    for k,j in enumerate(range(i+1,min(i+1+ (60 if exit_mode=='ma' else max_hold),n))):
                        if l[j]<=stop: exitp=stop; break
                        if exit_mode=="ma" and c[j]>sma25[j]: exitp=c[j]; break
                        if exit_mode=="fpc" and c[j]>entry: exitp=c[j]; break
                        if exit_mode=="time" and k>=max_hold-1: exitp=c[j]; break
                    if exitp is None: exitp=c[j]
                    trades.append(Trade(df.index[i],(exitp-entry)/risk,rf,+1)); i=j+1; continue
            i+=1
    return trades

if __name__=="__main__":
    cap=None
    if "--symbols" in sys.argv: cap=int(sys.argv[sys.argv.index("--symbols")+1])
    sl=syms("1d")
    if cap: sl=sl[:cap]
    res={"n_symbols":len(sl),"results":{}}
    for key,em in {"c4_ma":"ma","c4_fpc":"fpc","c4_time20":"time"}.items():
        t=run(sl,em); res["results"][key]=summarize(t,random_control(t))
    Path("data/research/strategy_results/c4_video.json").write_text(json.dumps(res,indent=2,default=str))
    print("done",res["n_symbols"])
