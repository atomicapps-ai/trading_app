"""bt_candidate3 — 20/50-EMA pullback + outside-bar (engulfing) trigger (s4DSY3Y_N4Y).
Run: python scripts/bt_candidate3.py [--symbols N]
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, syms, atr, Trade, summarize, random_control  # noqa


def _ema(x, n): return pd.Series(x).ewm(span=n, adjust=False).mean().values


def outside_bar_ema(symlist, exit_style="t3", target_R=3.0):
    """regime EMA20>EMA50 rising, close>EMA50; trigger = outside green bar tagging the
    [EMA50,EMA20] zone; stop = trigger-bar low; exit per style."""
    trades = []
    for s in symlist:
        df = load(s, "1d")
        if df is None or len(df) < 120: continue
        c=df["close"].values;o=df["open"].values;l=df["low"].values;h=df["high"].values
        e20=_ema(c,20); e50=_ema(c,50)
        n=len(df); i=55
        while i<n-1:
            regime=(e20[i]>e50[i] and e20[i]>e20[i-5] and e50[i]>e50[i-5] and c[i]>e50[i])
            outside=(h[i]>h[i-1] and l[i]<l[i-1] and c[i]>o[i])
            tagged=(l[i]<=e20[i] and c[i]>e50[i])      # pulled into the zone but held above EMA50
            if regime and outside and tagged:
                entry=o[i+1]; stop=l[i]; risk=entry-stop
                if risk>0:
                    rf=risk/entry; tgt=entry+target_R*risk; exitp=None
                    for j in range(i+1,min(i+61,n)):
                        if l[j]<=stop: exitp=stop; break
                        if exit_style=="t3" and h[j]>=tgt: exitp=tgt; break
                        if exit_style=="t2" and h[j]>=entry+2*risk: exitp=entry+2*risk; break
                        if exit_style=="trail20" and c[j]<e20[j]: exitp=c[j]; break
                    if exitp is None: exitp=c[min(i+60,n-1)]
                    trades.append(Trade(df.index[i],(exitp-entry)/risk,rf,+1)); i=j+1; continue
            i+=1
    return trades


def main():
    cap=45
    if "--symbols" in sys.argv: cap=int(sys.argv[sys.argv.index("--symbols")+1])
    sl=syms("1d")[:cap]
    for style in ["t3","t2","trail20"]:
        tr=outside_bar_ema(sl, style)
        r=summarize(tr, random_control(tr))
        a=r.get("all",{});oos=r.get("out_sample",{});ctl=r.get("random_control",{})
        print(f"\n=== outside-bar EMA pullback, exit={style} ===")
        print(f"  ALL: n={a.get('n')} win={a.get('win_pct')}% exp={a.get('expectancy_R')}R PF={a.get('profit_factor')}")
        print(f"  OOS: n={oos.get('n')} win={oos.get('win_pct')}% exp={oos.get('expectancy_R')}R PF={oos.get('profit_factor')}  CTL PF={ctl.get('profit_factor')}")


if __name__=="__main__":
    main()
