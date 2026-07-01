"""bt_followup — (1) retest P1 pullback with an ATR stop (the trigger-low stop was too thin),
(2) correlation of P2 coil-breakout vs the deployed book + MACD-run."""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, syms, atr, Trade, net_r, summarize, random_control, s7_breakout_continuation  # noqa
from bt_video_candidates2 import p2_coil_breakout
from bt_macd_exits import macd_variant


def _ema(x,n): return pd.Series(x).ewm(span=n,adjust=False).mean().values
def _sma(x,n): return pd.Series(x).rolling(n).mean().values


def p1_atrstop(symlist):
    """same entry as p1 but stop = entry-1.5*ATR14, exit close<EMA21 or 3R."""
    trades=[]
    for s in symlist:
        df=load(s,"1d")
        if df is None or len(df)<160: continue
        c=df["close"].values;o=df["open"].values;l=df["low"].values;h=df["high"].values;v=df["volume"].values
        e21=_ema(c,21);s50=_sma(c,50);vavg=_sma(v,20);a=atr(df)
        n=len(df);i=60
        while i<n-1:
            rng=h[i]-l[i]
            if (not np.isnan(s50[i]) and c[i]>s50[i] and s50[i]>s50[i-20] and l[i]<=e21[i]
                    and c[i]>=o[i] and rng>0 and (c[i]-l[i])/rng>=0.6
                    and not np.isnan(vavg[i]) and v[i]>=vavg[i] and not np.isnan(a[i]) and a[i]>0):
                entry=o[i+1];stop=entry-1.5*a[i];risk=entry-stop
                if risk>0:
                    rf=risk/entry;tgt=entry+3*risk;exitp=None
                    for j in range(i+1,min(i+61,n)):
                        if l[j]<=stop: exitp=stop; break
                        if h[j]>=tgt: exitp=tgt; break
                        if c[j]<e21[j]: exitp=c[j]; break
                    if exitp is None: exitp=c[min(i+60,n-1)]
                    trades.append(Trade(df.index[i],(exitp-entry)/risk,rf,+1)); i=j+1; continue
            i+=1
    return trades


def monthly_R(trades):
    if not trades: return pd.Series(dtype=float)
    d=pd.DataFrame({"ts":[t.ts for t in trades],"r":[max(-25,min(25,net_r(t))) for t in trades]})
    d["ts"]=pd.to_datetime(d["ts"],utc=True)
    return d.set_index("ts")["r"].resample("ME").sum()


def main():
    cap=45
    if "--symbols" in sys.argv: cap=int(sys.argv[sys.argv.index("--symbols")+1])
    sl=syms("1d")[:cap]

    tr=p1_atrstop(sl); r=summarize(tr,random_control(tr))
    a=r.get("all",{});oos=r.get("out_sample",{});ctl=r.get("random_control",{})
    print("=== P1 pullback-21EMA, ATR stop + 3R ===")
    print(f"  ALL: n={a.get('n')} win={a.get('win_pct')}% exp={a.get('expectancy_R')}R PF={a.get('profit_factor')}")
    print(f"  OOS: n={oos.get('n')} win={oos.get('win_pct')}% exp={oos.get('expectancy_R')}R PF={oos.get('profit_factor')}  CTL PF={ctl.get('profit_factor')}")

    p2,_=p2_coil_breakout(sl); mb,_=s7_breakout_continuation(sl); mc=macd_variant(sl,"run_macd")
    M=pd.DataFrame({"P2_coil":monthly_R(p2),"MomentumBreakout":monthly_R(mb),"MACD_run":monthly_R(mc)}).fillna(0.0)
    M=M.loc[(M!=0).any(axis=1)]
    print("\n=== correlation (monthly R) ===")
    cols=list(M.columns); print("  "+" ".join(f"{c[:12]:>13s}" for c in cols))
    for rr in cols: print(f"  {rr[:12]:>12s} "+" ".join(f"{M.corr().loc[rr,c]:>13.2f}" for c in cols))


if __name__=="__main__":
    main()
