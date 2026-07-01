import warnings; warnings.filterwarnings("ignore")
import sys, statistics
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load as _load, atr, syms, Trade, net_r

_CACHE = {}
def load(sym, interval="1d"):
    k = (sym, interval)
    if k not in _CACHE:
        _CACHE[k] = _load(sym, interval)
    return _CACHE[k]

def spy_regime():
    spy = load("SPY", "1d")
    c = spy["close"].values; sma = pd.Series(c).rolling(200).mean().values
    return {spy.index[i].normalize(): bool(not np.isnan(sma[i]) and c[i] > sma[i]) for i in range(len(spy))}

def gen_s7(symlist, lookback=126, stop_mult=1.0, trail_ma=20, regime_ok=None):
    trades = []
    for s in symlist:
        df = load(s, "1d")
        if df is None or len(df) < lookback + 60: continue
        c=df["close"].values;o=df["open"].values;l=df["low"].values;h=df["high"].values
        a=atr(df); smaT=pd.Series(c).rolling(trail_ma).mean().values
        hh=pd.Series(h).rolling(lookback).max().shift(1).values; idx=df.index; n=len(df); i=lookback+5
        while i < n-1:
            if not np.isnan(hh[i]) and c[i]>hh[i] and not np.isnan(a[i]) and a[i]>0:
                if regime_ok is not None and not regime_ok.get(idx[i].normalize(), True):
                    i+=1; continue
                entry=o[i+1]; stop=entry-stop_mult*a[i]; risk=entry-stop
                if risk<=0: i+=1; continue
                rf=risk/entry; exitp=None; j=i+1
                for j in range(i+1, min(i+121, n)):
                    if l[j]<=stop: exitp=stop; break
                    if not np.isnan(smaT[j]) and c[j]<smaT[j]: exitp=c[j]; break
                if exitp is None: exitp=c[min(i+120,n-1)]
                trades.append(Trade(idx[i],(exitp-entry)/risk,rf,1)); i=j+1
            else: i+=1
    return trades

def gen_s5(symlist, stretch=2.5, stop_mult=1.0, max_hold=30, regime_ok=None):
    trades=[]
    for s in symlist:
        df=load(s,"1d")
        if df is None or len(df)<200: continue
        c=df["close"].values;o=df["open"].values;l=df["low"].values;h=df["high"].values
        a=atr(df); sma50=pd.Series(c).rolling(50).mean().values; idx=df.index; n=len(df); i=55
        while i<n-1:
            if not np.isnan(sma50[i]) and not np.isnan(a[i]) and a[i]>0 and c[i] <= sma50[i]-stretch*a[i]:
                if regime_ok is not None and not regime_ok.get(idx[i].normalize(), True):
                    i+=1; continue
                entry=o[i+1]; stop=entry-stop_mult*a[i]; risk=entry-stop
                if risk>0:
                    rf=risk/entry; tgt=sma50[i]; exitp=None; j=i+1
                    for j in range(i+1, min(i+1+max_hold, n)):
                        if l[j]<=stop: exitp=stop; break
                        if h[j]>=tgt: exitp=tgt; break
                    if exitp is None: exitp=c[min(i+max_hold,n-1)]
                    trades.append(Trade(idx[i],(exitp-entry)/risk,rf,1)); i=j+1; continue
            i+=1
    return trades

def exp_net(trades):
    rs=[net_r(t) for t in trades]
    return (round(statistics.mean(rs),4), len(rs)) if rs else (0.0, 0)

def oos_exp(trades):
    t=sorted(trades,key=lambda x:x.ts); rs=[net_r(x) for x in t]; mid=len(rs)//2
    return round(statistics.mean(rs[mid:]),4) if rs[mid:] else 0.0

def walk_forward(trades, k=5):
    t=sorted(trades,key=lambda x:x.ts); rs=[net_r(x) for x in t]; n=len(rs); out=[]
    for b in range(k):
        seg=rs[b*n//k:(b+1)*n//k]
        out.append(round(statistics.mean(seg),3) if seg else 0.0)
    return out

def breadth(gen, symlist, **kw):
    pos=0; tot=0; per=[]
    for s in symlist:
        tr=gen([s], **kw)
        if not tr: continue
        e,n=exp_net(tr); per.append((s,e,n)); tot+=1
        if sum(net_r(x) for x in tr)>0: pos+=1
    per.sort(key=lambda x:x[1])
    return pos, tot, per

def main():
    strat, mode = sys.argv[1], sys.argv[2]
    sl = syms("1d")
    gen = gen_s7 if strat=="s7" else gen_s5
    if mode=="sweep":
        print("== "+strat.upper()+" parameter sweep (expectancy R all / OOS) ==")
        if strat=="s7":
            print("lookback sweep (stop=1.0, trail=20):")
            for lb in (63,126,189,252):
                tr=gen_s7(sl,lookback=lb); e=exp_net(tr); print("  lookback="+str(lb)+": all "+format(e[0],'+.3f')+" (n="+str(e[1])+")  oos "+format(oos_exp(tr),'+.3f'))
            print("stop-ATR sweep (lookback=126, trail=20):")
            for sm in (0.5,1.0,1.5,2.0):
                tr=gen_s7(sl,stop_mult=sm); print("  stop="+str(sm)+"xATR: all "+format(exp_net(tr)[0],'+.3f')+"  oos "+format(oos_exp(tr),'+.3f'))
            print("trail-MA sweep (lookback=126, stop=1.0):")
            for tm in (10,20,50):
                tr=gen_s7(sl,trail_ma=tm); print("  trail="+str(tm)+"MA: all "+format(exp_net(tr)[0],'+.3f')+"  oos "+format(oos_exp(tr),'+.3f'))
        else:
            print("stretch sweep (stop=1.0, hold=30):")
            for st in (2.0,2.5,3.0,3.5):
                tr=gen_s5(sl,stretch=st); e=exp_net(tr); print("  stretch="+str(st)+"xATR: all "+format(e[0],'+.3f')+" (n="+str(e[1])+")  oos "+format(oos_exp(tr),'+.3f'))
            print("stop-ATR sweep (stretch=2.5, hold=30):")
            for sm in (0.5,1.0,1.5,2.0):
                tr=gen_s5(sl,stop_mult=sm); print("  stop="+str(sm)+"xATR: all "+format(exp_net(tr)[0],'+.3f')+"  oos "+format(oos_exp(tr),'+.3f'))
            print("max-hold sweep (stretch=2.5, stop=1.0):")
            for mh in (15,30,45,60):
                tr=gen_s5(sl,max_hold=mh); print("  hold="+str(mh)+": all "+format(exp_net(tr)[0],'+.3f')+"  oos "+format(oos_exp(tr),'+.3f'))
    elif mode=="robust":
        base = gen(sl)
        print("== "+strat.upper()+" robustness (base params) ==")
        e,n=exp_net(base); print("base: expectancy "+format(e,'+.3f')+"R  n="+str(n)+"  oos "+format(oos_exp(base),'+.3f'))
        print("walk-forward (5 blocks): "+str(walk_forward(base)))
        reg=spy_regime()
        rt=gen(sl, regime_ok=reg); e2,n2=exp_net(rt)
        print("regime gate (SPY>200MA): expectancy "+format(e2,'+.3f')+"R  n="+str(n2)+"  oos "+format(oos_exp(rt),'+.3f'))
        pos,tot,per=breadth(gen, sl)
        print("breadth: "+str(pos)+"/"+str(tot)+" symbols net-positive")
        print("  worst 5: "+str([(s,e) for s,e,_ in per[:5]]))
        print("  best 5:  "+str([(s,e) for s,e,_ in per[-5:]]))

if __name__=="__main__":
    main()
