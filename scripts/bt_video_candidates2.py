"""bt_video_candidates2 — backtest the 3 mechanical candidates from batch-B triage,
on the shared harness so metrics compare to the deployed book.
  P1 AKkeB8RJ6jM  trend-continuation pullback to 21-EMA (buy weakness in strength)
  P2 YWBLKRLnrZ0  range-coil volatility-contraction breakout
  P3 JL7HdUKRxfI  Fib-discount trend pullback
Run: python scripts/bt_video_candidates2.py [--symbols N]
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import sys
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, syms, atr, Trade, summarize, random_control  # noqa


def _ema(x, n): return pd.Series(x).ewm(span=n, adjust=False).mean().values
def _sma(x, n): return pd.Series(x).rolling(n).mean().values


# ---- P1: pullback-to-21EMA continuation ------------------------------------
def p1_pullback(symlist):
    cfg = {"entry": "uptrend(close>SMA50,SMA50 rising 20d) + low<=EMA21 + green + close top40% + vol>=20davg -> next open",
           "stop": "trigger-day low", "exit": "first close<EMA21", "max_hold": 60}
    trades = []
    for s in symlist:
        df = load(s, "1d")
        if df is None or len(df) < 160: continue
        c=df["close"].values;o=df["open"].values;l=df["low"].values;h=df["high"].values;v=df["volume"].values
        e21=_ema(c,21); s50=_sma(c,50); vavg=_sma(v,20)
        n=len(df); i=60
        while i<n-1:
            rng=h[i]-l[i]
            if (not np.isnan(s50[i]) and c[i]>s50[i] and s50[i]>s50[i-20]
                    and l[i]<=e21[i] and c[i]>=o[i] and rng>0 and (c[i]-l[i])/rng>=0.6
                    and not np.isnan(vavg[i]) and v[i]>=vavg[i]):
                entry=o[i+1]; stop=l[i]; risk=entry-stop
                if risk>0:
                    rf=risk/entry; exitp=None
                    for j in range(i+1,min(i+1+cfg["max_hold"],n)):
                        if l[j]<=stop: exitp=stop; break
                        if c[j]<e21[j]: exitp=c[j]; break
                    if exitp is None: exitp=c[min(i+cfg["max_hold"],n-1)]
                    trades.append(Trade(df.index[i],(exitp-entry)/risk,rf,+1)); i=j+1; continue
            i+=1
    return trades,cfg


# ---- P2: range-coil contraction breakout -----------------------------------
def p2_coil_breakout(symlist):
    cfg={"entry":"close>prior 30-day high AND ATR10<ATR50 (coil) AND breakoutTR>1.5*medTR30 AND vol>=1.5*avg30 -> next open",
         "stop":"30-day range low","target":"3R","trend":"close>SMA200","max_hold":120}
    trades=[]
    for s in symlist:
        df=load(s,"1d")
        if df is None or len(df)<260: continue
        c=df["close"].values;o=df["open"].values;l=df["low"].values;h=df["high"].values;v=df["volume"].values
        a10=atr(df,10);a50=atr(df,50);s200=_sma(c,200);vavg=_sma(v,30)
        hh30=pd.Series(h).rolling(30).max().shift(1).values
        ll30=pd.Series(l).rolling(30).min().shift(1).values
        tr=np.maximum(h-l,np.maximum(np.abs(h-np.roll(c,1)),np.abs(l-np.roll(c,1))))
        medtr=pd.Series(tr).rolling(30).median().shift(1).values
        n=len(df); i=205
        while i<n-1:
            if (not np.isnan(hh30[i]) and c[i]>hh30[i] and not np.isnan(a50[i]) and a10[i]<a50[i]
                    and not np.isnan(medtr[i]) and tr[i]>1.5*medtr[i]
                    and not np.isnan(vavg[i]) and v[i]>=1.5*vavg[i]
                    and not np.isnan(s200[i]) and c[i]>s200[i]):
                entry=o[i+1]; stop=ll30[i]; risk=entry-stop
                if risk>0:
                    rf=risk/entry; tgt=entry+3*risk; exitp=None
                    for j in range(i+1,min(i+1+cfg["max_hold"],n)):
                        if l[j]<=stop: exitp=stop; break
                        if h[j]>=tgt: exitp=tgt; break
                    if exitp is None: exitp=c[min(i+cfg["max_hold"],n-1)]
                    trades.append(Trade(df.index[i],(exitp-entry)/risk,rf,+1)); i=j+1; continue
            i+=1
    return trades,cfg


# ---- P3: Fib-discount trend pullback ---------------------------------------
def p3_fib_pullback(symlist):
    cfg={"entry":"close>EMA50, swing over 20b, price<50% fib(swing_lo->hi), green day -> next open",
         "stop":"min low last 5 bars","target":"3R or close<EMA50","max_hold":60}
    trades=[]
    for s in symlist:
        df=load(s,"1d")
        if df is None or len(df)<120: continue
        c=df["close"].values;o=df["open"].values;l=df["low"].values;h=df["high"].values
        e50=_ema(c,50)
        n=len(df); i=60
        while i<n-1:
            win_h=max(h[i-20:i+1]); win_l=min(l[i-20:i+1]); fib=(win_h+win_l)/2
            if (c[i]>e50[i] and win_h>win_l and c[i]<fib and c[i]>o[i]):
                entry=o[i+1]; stop=min(l[i-4:i+1]); risk=entry-stop
                if risk>0:
                    rf=risk/entry; tgt=entry+3*risk; exitp=None
                    for j in range(i+1,min(i+1+cfg["max_hold"],n)):
                        if l[j]<=stop: exitp=stop; break
                        if h[j]>=tgt: exitp=tgt; break
                        if c[j]<e50[j]: exitp=c[j]; break
                    if exitp is None: exitp=c[min(i+cfg["max_hold"],n-1)]
                    trades.append(Trade(df.index[i],(exitp-entry)/risk,rf,+1)); i=j+1; continue
            i+=1
    return trades,cfg


REG={"p1_pullback_21ema":p1_pullback,"p2_coil_breakout":p2_coil_breakout,"p3_fib_pullback":p3_fib_pullback}


def main():
    cap=45
    if "--symbols" in sys.argv: cap=int(sys.argv[sys.argv.index("--symbols")+1])
    sl=syms("1d")[:cap]
    for k,fn in REG.items():
        tr,_=fn(sl); r=summarize(tr,random_control(tr))
        a=r.get("all",{});oos=r.get("out_sample",{});ctl=r.get("random_control",{})
        print(f"\n=== {k} ===")
        print(f"  ALL: n={a.get('n')} win={a.get('win_pct')}% exp={a.get('expectancy_R')}R PF={a.get('profit_factor')} avgWin={a.get('avg_win_R')} avgLoss={a.get('avg_loss_R')}")
        print(f"  OOS: n={oos.get('n')} win={oos.get('win_pct')}% exp={oos.get('expectancy_R')}R PF={oos.get('profit_factor')}")
        print(f"  CTL: PF={ctl.get('profit_factor')} exp={ctl.get('expectancy_R')}")


if __name__=="__main__":
    main()
