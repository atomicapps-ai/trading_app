import warnings; warnings.filterwarnings("ignore")
import sys, glob, statistics
import pandas as pd, numpy as np
HIST="data/historical"; BPS=0.0010
def load(sym):
    import os
    f=f"{HIST}/{sym}_1d.csv"
    if not os.path.exists(f): return None
    df=pd.read_csv(f); dc=df.columns[0]; df[dc]=pd.to_datetime(df[dc],utc=True,errors="coerce")
    df=df.dropna(subset=[dc]).set_index(dc).sort_index(); df.columns=[c.lower() for c in df.columns]
    return df
def atr(df,n=14):
    h,l,c=df["high"].values,df["low"].values,df["close"].values; pc=np.roll(c,1); pc[0]=c[0]
    tr=np.maximum(h-l,np.maximum(np.abs(h-pc),np.abs(l-pc))); return pd.Series(tr).rolling(n).mean().values
def rsi(c,n=14):
    d=pd.Series(c).diff(); up=d.clip(lower=0).rolling(n).mean(); dn=(-d.clip(upper=0)).rolling(n).mean()
    return (100-100/(1+up/dn.replace(0,np.nan))).values
# market context
spy=load("SPY"); sc=spy["close"]; spy_s200=sc.rolling(200).mean()
spy_ctx={}
sret20=sc.pct_change(20); sret1=sc.pct_change(1)
for i in range(len(spy)):
    k=spy.index[i].normalize()
    spy_ctx[k]=(bool(sc.iloc[i]>spy_s200.iloc[i]) if spy_s200.iloc[i]==spy_s200.iloc[i] else None,
                (1 if sret20.iloc[i]>0 else 0) if sret20.iloc[i]==sret20.iloc[i] else None,
                (1 if sret1.iloc[i]>0 else 0) if sret1.iloc[i]==sret1.iloc[i] else None)
vix=load("^VIX"); vix_ctx={vix.index[i].normalize(): float(vix["close"].iloc[i]) for i in range(len(vix))}

def feats(df,i,a,s50,s200,r,direction):
    k=df.index[i].normalize(); sx=spy_ctx.get(k,(None,None,None)); v=vix_ctx.get(k)
    c=df["close"].values
    f={}
    f["spy>200ma"]= "yes" if sx[0] else ("no" if sx[0] is not None else None)
    f["spy20d_up"]= "yes" if sx[1]==1 else ("no" if sx[1]==0 else None)
    f["spy_day_up"]= "yes" if sx[2]==1 else ("no" if sx[2]==0 else None)
    f["vix"]= None if v is None else ("calm<18" if v<18 else ("mid18-26" if v<26 else "stress>26"))
    f["stk>200ma"]= "yes" if (s200[i]==s200[i] and c[i]>s200[i]) else "no"
    f["golden_50>200"]= "yes" if (s50[i]==s50[i] and s200[i]==s200[i] and s50[i]>s200[i]) else "no"
    rv=r[i]
    f["rsi"]= None if rv!=rv else ("<=30" if rv<=30 else ("30-50" if rv<50 else ("50-70" if rv<70 else ">70")))
    return f

def gen(strat, sl):
    rows=[]
    for sym in sl:
        df=load(sym)
        if df is None or len(df)<260: continue
        c=df["close"].values;o=df["open"].values;l=df["low"].values;h=df["high"].values
        a=atr(df); s50=pd.Series(c).rolling(50).mean().values; s200=pd.Series(c).rolling(200).mean().values
        r=rsi(c); n=len(df)
        if strat=="s5":
            i=205
            while i<n-1:
                if a[i]>0 and s50[i]==s50[i] and (s50[i]-c[i])/a[i]>=3.0:
                    entry=o[i+1]; stop=entry-a[i]; risk=entry-stop; tgt=s50[i]
                    if risk>0 and tgt>entry:
                        ex=None
                        for j in range(i+1,min(i+46,n)):
                            if l[j]<=stop: ex=stop;break
                            if h[j]>=tgt: ex=tgt;break
                        if ex is None: ex=c[min(i+45,n-1)]
                        R=(ex-entry)/risk - 0.002*entry/risk
                        fr=feats(df,i,a,s50,s200,r,"long"); fr["__ts"]=df.index[i]; fr["__R"]=R
                        fr["stretch"]= "deep>=3.5" if (s50[i]-c[i])/a[i]>=3.5 else "mid3-3.5"
                        rows.append(fr); i=j+1; continue
                i+=1
        else:
            i=131
            while i<n-1:
                ph=df["high"].iloc[i-126:i].max()
                if a[i]>0 and c[i]>ph:
                    entry=o[i+1]; stop=entry-a[i]; risk=entry-stop
                    if risk>0:
                        ex=None
                        for j in range(i+1,min(i+121,n)):
                            if l[j]<=stop: ex=stop;break
                            if s50[j]==s50[j] and c[j]<s50[j]: ex=c[j];break
                        if ex is None: ex=c[min(i+120,n-1)]
                        R=(ex-entry)/risk - 0.002*entry/risk
                        fr=feats(df,i,a,s50,s200,r,"long"); fr["__ts"]=df.index[i]; fr["__R"]=R
                        relv=df["volume"].values[i]/pd.Series(df["volume"].values).rolling(20).mean().values[i]
                        fr["breakout_vol>=1.5"]= "yes" if relv>=1.5 else "no"
                        fr["clears>=0.5atr"]= "yes" if (c[i]-ph)/a[i]>=0.5 else "no"
                        rows.append(fr); i=j+1; continue
                i+=1
    return rows

def stats(rs):
    if not rs: return (0,0,0)
    w=sum(1 for x in rs if x>0)/len(rs)*100; return (len(rs), round(w,1), round(statistics.mean(rs),3))

strat=sys.argv[1]; sl=sorted(p.split("/")[-1].replace("_1d.csv","") for p in glob.glob(f"{HIST}/*_1d.csv"))
rows=gen(strat, sl)
rows.sort(key=lambda x:x["__ts"]); mid=len(rows)//2; oos=rows[mid:]
bn,bw,be=stats([r["__R"] for r in oos])
print(f"== {strat.upper()} filter attribution (OOS half, net cost) ==")
print(f"BASELINE (no filter): n={bn} win%={bw} exp={be}R\n")
feat_keys=[k for k in rows[0].keys() if not k.startswith("__")]
out=[]
for fk in feat_keys:
    vals=sorted(set(r[fk] for r in oos if r.get(fk) is not None))
    for val in vals:
        sub=[r["__R"] for r in oos if r.get(fk)==val]
        if len(sub)<80: continue
        n,w,e=stats(sub)
        out.append((fk,val,n,w,e,w-bw,e-be))
out.sort(key=lambda x:x[4], reverse=True)
print(f"{'feature':16}{'value':12}{'n':>6}{'win%':>7}{'exp':>8}{'dWin':>7}{'dExp':>7}")
for fk,val,n,w,e,dw,de in out:
    flag=" <<" if (dw>0 and de>0) else ""
    print(f"{fk:16}{str(val):12}{n:>6}{w:>7}{e:>8}{dw:>+7.1f}{de:>+7.3f}{flag}")
