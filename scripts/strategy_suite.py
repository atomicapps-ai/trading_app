"""strategy_suite — standardized backtest harness for the video-mined strategies.

One rig so every strategy is measured identically and comparably:
  * same universe (cached daily / 15m CSVs in data/historical/)
  * chronological out-of-sample split (IS = first half, OOS = second half by trade time)
  * 10 bps round-trip cost, charged per trade in R using each trade's own risk fraction
  * a random-direction control on the SAME entries (is the signal better than a coin flip?)
  * a fixed metrics set (n, win%, expectancy R, profit factor, max DD in R, IS vs OOS)

Every strategy returns a list of Trade(ts, r, risk_frac, direction) where r is the GROSS
R-multiple; the harness nets cost and computes metrics. Run:
    python scripts/strategy_suite.py <strategy_key> [--symbols N]
Results print as JSON and save to data/research/strategy_results/<key>.json
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, random, statistics, sys
from dataclasses import dataclass, asdict
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parent.parent
HIST = ROOT / "data" / "historical"
OUT = ROOT / "data" / "research" / "strategy_results"
OUT.mkdir(parents=True, exist_ok=True)
BPS = 0.0010          # 10 bps round-trip, as a fraction of notional
random.seed(13)

# ---------------------------------------------------------------- data
def load(sym: str, interval: str) -> pd.DataFrame | None:
    f = HIST / f"{sym}_{interval}.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f)
    dc = df.columns[0]
    df[dc] = pd.to_datetime(df[dc], utc=True, errors="coerce")
    df = df.dropna(subset=[dc]).set_index(dc).sort_index()
    df.columns = [c.lower() for c in df.columns]
    for c in ("open", "high", "low", "close"):
        if c not in df.columns:
            return None
    if "volume" not in df.columns:
        df["volume"] = 0.0
    return df

def syms(interval: str) -> list[str]:
    return sorted(p.name.replace(f"_{interval}.csv", "") for p in HIST.glob(f"*_{interval}.csv"))

def atr(df: pd.DataFrame, n: int = 14) -> np.ndarray:
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(n).mean().values

# ---------------------------------------------------------------- trade record
@dataclass
class Trade:
    ts: pd.Timestamp
    r: float            # gross R-multiple
    risk_frac: float    # |entry-stop|/entry  (for cost-in-R conversion)
    direction: int      # +1 long / -1 short

def net_r(t: Trade) -> float:
    """Gross R minus 10 bps round-trip expressed in R via the trade's risk fraction."""
    cost_r = (2 * BPS) / t.risk_frac if t.risk_frac and t.risk_frac > 0 else 0.0
    return t.r - cost_r

# ---------------------------------------------------------------- metrics
def _stats(rs: list[float]) -> dict:
    if not rs:
        return {"n": 0}
    wins = [x for x in rs if x > 0]; losses = [x for x in rs if x <= 0]
    gp = sum(wins); gl = -sum(losses)
    eq = np.cumsum(rs); peak = np.maximum.accumulate(eq); dd = eq - peak
    return {
        "n": len(rs),
        "win_pct": round(len(wins) / len(rs) * 100, 1),
        "expectancy_R": round(statistics.mean(rs), 4),
        "profit_factor": round(gp / gl, 2) if gl > 0 else float("inf"),
        "avg_win_R": round(statistics.mean(wins), 3) if wins else 0.0,
        "avg_loss_R": round(statistics.mean(losses), 3) if losses else 0.0,
        "max_dd_R": round(float(dd.min()), 2),
        "total_R": round(float(sum(rs)), 1),
    }

def summarize(trades: list[Trade], control: list[float] | None = None) -> dict:
    trades = sorted(trades, key=lambda t: t.ts)
    rs = [net_r(t) for t in trades]
    out = {"all": _stats(rs)}
    if trades:
        mid = len(trades) // 2
        out["in_sample"] = _stats(rs[:mid])
        out["out_sample"] = _stats(rs[mid:])
    if control is not None:
        out["random_control"] = _stats(control)
    return out

def random_control(trades: list[Trade]) -> list[float]:
    """Same trades, coin-flipped direction → kills any directional edge, keeps the payoff shape."""
    out = []
    for t in trades:
        flip = random.choice([1, -1])
        out.append(net_r(Trade(t.ts, t.r * flip, t.risk_frac, t.direction)))
    return out

# ================================================================ STRATEGIES
# Each returns (trades, config_dict). config is copied verbatim into the doc.

def s7_breakout_continuation(symlist):
    """S7: multi-month (126-day) high breakout; stop 1.0xATR below entry; trail 20-day MA."""
    cfg = {"universe": "daily stocks", "lookback_high": 126, "entry": "close > prior 126-day high -> next open",
           "stop": "entry - 1.0*ATR14", "trail_exit": "close < 20-day SMA", "max_hold_bars": 120}
    trades = []
    for s in symlist:
        df = load(s, "1d")
        if df is None or len(df) < 300: continue
        c = df["close"].values; o = df["open"].values; l = df["low"].values; h = df["high"].values
        a = atr(df); sma20 = pd.Series(c).rolling(20).mean().values
        hh = pd.Series(h).rolling(126).max().shift(1).values
        i = 130; n = len(df)
        while i < n - 1:
            if not np.isnan(hh[i]) and c[i] > hh[i] and not np.isnan(a[i]) and a[i] > 0:
                entry = o[i+1] if i+1 < n else c[i]
                stop = entry - 1.0 * a[i]; risk = entry - stop
                if risk <= 0: i += 1; continue
                rf = risk / entry; exitp = None
                for j in range(i+1, min(i+1+cfg["max_hold_bars"], n)):
                    if l[j] <= stop: exitp = stop; break
                    if not np.isnan(sma20[j]) and c[j] < sma20[j]: exitp = c[j]; break
                if exitp is None: exitp = c[min(i+cfg["max_hold_bars"], n-1)]
                r = (exitp - entry) / risk
                trades.append(Trade(df.index[i], r, rf, +1))
                i = j + 1 if 'j' in dir() else i + 1
            else:
                i += 1
    return trades, cfg

def s6_capitulation_v(symlist):
    """S6: capitulation (>=10% drop over 10d + volume>=2x20d avg) then buy first close above prior high."""
    cfg = {"universe": "daily stocks", "capitulation": "10-day return <= -10% AND vol >= 2x 20d avg AND down day",
           "entry": "first close > prior day's high after climax -> next open (right side of V)",
           "stop": "recent 5-day low", "exit": "trail prior-bar low OR 40-bar time stop"}
    trades = []
    for s in symlist:
        df = load(s, "1d")
        if df is None or len(df) < 300: continue
        c=df["close"].values;o=df["open"].values;l=df["low"].values;h=df["high"].values;v=df["volume"].values
        ret10 = pd.Series(c).pct_change(10).values
        vavg = pd.Series(v).rolling(20).mean().values
        n=len(df); i=25
        while i < n-1:
            climax = (ret10[i] <= -0.10 and vavg[i]>0 and v[i] >= 2*vavg[i] and c[i] < c[i-1])
            if climax:
                # wait up to 8 bars for first close above prior high = trend break
                entry=None; ei=None
                for k in range(i+1, min(i+9, n)):
                    if c[k] > h[k-1]:
                        ei=k; entry = o[k+1] if k+1<n else c[k]; break
                if entry is not None:
                    stop = min(l[max(ei-5,0):ei+1]); risk = entry-stop
                    if risk>0:
                        rf=risk/entry; exitp=None; trail=stop
                        for j in range(ei+1, min(ei+41, n)):
                            if l[j] <= trail: exitp=trail; break
                            trail = max(trail, l[j-1])
                        if exitp is None: exitp = c[min(ei+40,n-1)]
                        trades.append(Trade(df.index[ei], (exitp-entry)/risk, rf, +1))
                        i = ei+1; continue
            i += 1
    return trades, cfg

def s5_mean_reversion_50ma(symlist):
    """S5/H-PA2: buy when close is >=2.5xATR below the 50-day MA; exit on tag of 50MA or 1xATR stop."""
    cfg = {"universe":"daily stocks","signal":"close <= SMA50 - 2.5*ATR14 (stretched below mean)",
           "entry":"next open","target":"SMA50 (mean)","stop":"entry - 1.0*ATR14","max_hold_bars":30}
    trades=[]
    for s in symlist:
        df=load(s,"1d")
        if df is None or len(df)<200: continue
        c=df["close"].values;o=df["open"].values;l=df["low"].values;h=df["high"].values
        a=atr(df); sma50=pd.Series(c).rolling(50).mean().values
        n=len(df); i=55
        while i<n-1:
            if not np.isnan(sma50[i]) and not np.isnan(a[i]) and a[i]>0 and c[i] <= sma50[i]-2.5*a[i]:
                entry=o[i+1] if i+1<n else c[i]; stop=entry-1.0*a[i]; risk=entry-stop
                if risk>0:
                    rf=risk/entry; tgt=sma50[i]; exitp=None
                    for j in range(i+1, min(i+1+cfg["max_hold_bars"], n)):
                        if l[j]<=stop: exitp=stop; break
                        if h[j]>=tgt: exitp=tgt; break
                    if exitp is None: exitp=c[min(i+cfg["max_hold_bars"],n-1)]
                    trades.append(Trade(df.index[i],(exitp-entry)/risk,rf,+1)); i=j+1; continue
            i+=1
    return trades, cfg

def s4_supply_demand(symlist, rr_floor=None):
    """S4: trend-aligned demand-zone retest. Uptrend = close>SMA200. Demand zone = a candle
    followed by an impulse up (>=1.5xATR over next 3 bars); enter on later retest of zone low;
    stop below zone; target prior 20-bar swing high. Optional R:R>=floor filter (H-RR1)."""
    cfg = {"universe":"daily stocks","trend_filter":"close > SMA200 (longs only)",
           "demand_zone":"candle whose next 3 bars gain >= 1.5*ATR14; zone=[low,high] of that candle",
           "entry":"price retraces into zone (low touched) -> zone high","stop":"zone low - 0.1*ATR",
           "target":"prior 20-bar swing high","rr_floor":rr_floor}
    trades=[]
    for s in symlist:
        df=load(s,"1d")
        if df is None or len(df)<260: continue
        c=df["close"].values;o=df["open"].values;l=df["low"].values;h=df["high"].values
        a=atr(df); sma200=pd.Series(c).rolling(200).mean().values
        n=len(df); i=205
        while i<n-4:
            if (not np.isnan(a[i]) and a[i]>0 and not np.isnan(sma200[i]) and c[i]>sma200[i]
                    and (max(h[i+1:i+4]) - c[i]) >= 1.5*a[i]):
                zlo, zhi = l[i], h[i]; entry=zhi; stop=zlo-0.1*a[i]; risk=entry-stop
                if risk>0:
                    tgt=max(h[max(i-20,0):i+1]); rr=(tgt-entry)/risk if risk>0 else 0
                    if tgt>entry and (rr_floor is None or rr>=rr_floor):
                        rf=risk/entry; exitp=None
                        # find retest within next 40 bars
                        for j in range(i+4, min(i+44,n)):
                            if l[j] <= zhi:   # retraced into zone
                                for k in range(j, min(j+60,n)):
                                    if l[k]<=stop: exitp=stop; break
                                    if h[k]>=tgt: exitp=tgt; break
                                if exitp is None: exitp=c[min(j+59,n-1)]
                                trades.append(Trade(df.index[j],(exitp-entry)/risk,rf,+1)); break
                        i = i+4; continue
            i+=1
    return trades, cfg

def s8_presidential_cycle(symlist):
    """S8: buy ~2 years before a US general election, sell in the election year (Jan->Nov).
    Headline on SPY; robustness across all stocks: is the (E-2 -> E) 2-yr window > avg 2-yr window?"""
    elections=[2008,2012,2016,2020,2024]
    cfg={"universe":"SPY (headline) + all stocks (robustness)","rule":"buy Jan 2 yrs pre-election, sell Nov of election year",
         "elections":elections,"benchmark":"all overlapping 2-yr windows"}
    def yr_close(df, year, month):
        sub=df[(df.index.year==year)&(df.index.month==month)]
        return sub["close"].iloc[-1] if len(sub) else None
    # headline SPY
    spy=load("SPY","1d"); head=[]
    if spy is not None:
        for e in elections:
            b=yr_close(spy,e-2,1); s=yr_close(spy,e,11)
            if b and s: head.append((e, round((s/b-1)*100,1)))
    # robustness: pre-election 2-yr returns vs all 2-yr windows, pooled across stocks
    pre=[]; allw=[]
    for sym in symlist:
        df=load(sym,"1d")
        if df is None: continue
        for y in range(2007, 2025):
            b=yr_close(df,y,1); s=yr_close(df,y+2,1)
            if b and s and b>0:
                rr=(s/b-1)
                allw.append(rr)
                if (y+2) in elections: pre.append(rr)
    cfg["spy_per_cycle_pct"]=head
    cfg["spy_avg_cycle_pct"]=round(statistics.mean([x for _,x in head]),1) if head else None
    cfg["preelection_2yr_mean_pct"]=round(statistics.mean(pre)*100,1) if pre else None
    cfg["all_2yr_window_mean_pct"]=round(statistics.mean(allw)*100,1) if allw else None
    cfg["preelection_n"]=len(pre); cfg["all_windows_n"]=len(allw)
    # represent as "trades" in % terms (not R) — flag separately
    trades=[Trade(pd.Timestamp(f"{e}-11-01", tz="UTC"), r/100.0, 1.0, +1) for e,r in head]
    return trades, cfg

REGISTRY = {
    "s4_supply_demand": lambda sl: s4_supply_demand(sl),
    "s4_supply_demand_rr25": lambda sl: s4_supply_demand(sl, rr_floor=2.5),
    "s5_mean_reversion_50ma": s5_mean_reversion_50ma,
    "s6_capitulation_v": s6_capitulation_v,
    "s7_breakout_continuation": s7_breakout_continuation,
    "s8_presidential_cycle": s8_presidential_cycle,
}

def main():
    key = sys.argv[1]
    cap = None
    if "--symbols" in sys.argv:
        cap = int(sys.argv[sys.argv.index("--symbols")+1])
    sl = syms("1d")
    if cap: sl = sl[:cap]
    fn = REGISTRY[key]
    trades, cfg = fn(sl)
    res = {"strategy": key, "config": cfg, "n_symbols": len(sl)}
    if key != "s8_presidential_cycle":
        res["results"] = summarize(trades, random_control(trades))
    else:
        res["results"] = summarize(trades)  # % terms, n tiny — see config
    Path(OUT / f"{key}.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res, indent=2, default=str))

if __name__ == "__main__":
    main()
