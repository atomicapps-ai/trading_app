"""bt_three_line_strike — backtest the Three-Line Strike trend-continuation pattern (video RyTlRkMujuk).

Pattern (5-min): in an uptrend, three consecutive bearish candles (retrace) then one bullish engulfing
candle -> enter long at its close; mirror for downtrend/short. Trade WITH the trend only (MA proxy for
market structure). Stop just beyond the engulfing candle (R = its range), fixed 2R target, flat by EOD.
Skip oversized engulfing candles (his ">10 pip" cull -> here: range > 1.2x ATR).

  python scripts/bt_three_line_strike.py --symbols SPY QQQ
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import argparse, json, random, statistics, sys
from datetime import time
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import cost_model  # noqa: E402
random.seed(13)
HIST = ROOT / "data" / "historical"
OUT = ROOT / "data" / "research" / "strategy_results"; OUT.mkdir(parents=True, exist_ok=True)


def load_5m_et(sym):
    f = HIST / f"{sym}_5m.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f); dc = df.columns[0]
    df[dc] = pd.to_datetime(df[dc], utc=True, errors="coerce")
    df = df.dropna(subset=[dc]).set_index(dc).sort_index()
    df.columns = [c.lower() for c in df.columns]
    return df.tz_convert("America/New_York").between_time(time(9, 30), time(16, 0), inclusive="left")


def backtest(sym):
    df = load_5m_et(sym)
    if df is None or len(df) < 500:
        return []
    o = df["open"].values.astype(float); h = df["high"].values.astype(float)
    l = df["low"].values.astype(float); c = df["close"].values.astype(float)
    sma20 = pd.Series(c).rolling(20).mean().values
    sma20_prev = pd.Series(c).rolling(20).mean().shift(5).values
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    dates = df.index.date
    times = np.array([x.time() for x in df.index])
    n = len(c)
    trades = []
    i = 23
    while i < n - 1:
        if dates[i] != dates[i - 3]:          # pattern must be within one session
            i += 1; continue
        if np.isnan(sma20[i]) or np.isnan(atr[i]) or atr[i] <= 0:
            i += 1; continue
        up = c[i] > sma20[i] and sma20[i] > sma20_prev[i]
        dn = c[i] < sma20[i] and sma20[i] < sma20_prev[i]
        # bullish setup (uptrend): 3 bearish candles then bullish engulfing
        bull = (up and c[i-3] < o[i-3] and c[i-2] < o[i-2] and c[i-1] < o[i-1]
                and c[i] > o[i] and o[i] <= c[i-1] and c[i] > o[i-3])
        bear = (dn and c[i-3] > o[i-3] and c[i-2] > o[i-2] and c[i-1] > o[i-1]
                and c[i] < o[i] and o[i] >= c[i-1] and c[i] < o[i-3])
        if not (bull or bear):
            i += 1; continue
        rng = h[i] - l[i]
        if rng > 1.2 * atr[i] or rng <= 0:     # oversized-candle cull
            i += 1; continue
        direction = 1 if bull else -1
        entry = o[i + 1]
        stop = l[i] if bull else h[i]
        risk = abs(entry - stop)
        if risk <= 0 or risk / entry < 1e-4:
            i += 1; continue
        target = entry + 2 * risk if bull else entry - 2 * risk
        r_mult = None; xi = n - 1; xpx = c[-1]
        for k in range(i + 1, n):
            if dates[k] != dates[i]:            # EOD flat
                xi = k - 1; xpx = c[k - 1]
                r_mult = (xpx - entry) / risk * direction; break
            if direction == 1:
                if l[k] <= stop: r_mult = -1.0; xi = k; xpx = stop; break
                if h[k] >= target: r_mult = 2.0; xi = k; xpx = target; break
            else:
                if h[k] >= stop: r_mult = -1.0; xi = k; xpx = stop; break
                if l[k] <= target: r_mult = 2.0; xi = k; xpx = target; break
        if r_mult is None:
            r_mult = (xpx - entry) / risk * direction
        trades.append({"symbol": sym, "date": str(dates[i]), "direction": "long" if bull else "short",
                       "entry_time": str(times[i + 1])[:5], "entry": round(entry, 4),
                       "stop": round(stop, 4), "target": round(target, 4),
                       "exit_time": str(times[xi])[:5], "exit": round(xpx, 4),
                       "r_gross": round(r_mult, 3), "risk_frac": round(risk / entry, 5)})
        i = xi + 1
    return trades


def _stats(rs):
    if not rs:
        return {"n": 0}
    w = [x for x in rs if x > 0]; loss = [x for x in rs if x <= 0]
    gp = sum(w); gl = -sum(loss)
    return {"n": len(rs), "win": round(len(w) / len(rs) * 100, 1),
            "avgR": round(statistics.mean(rs), 3), "PF": round(gp / gl, 2) if gl > 0 else 0.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=["SPY", "QQQ"])
    args = ap.parse_args()
    allt = []
    for sym in args.symbols:
        tr = backtest(sym)
        cf = cost_model.roundtrip_frac(sym)
        for t in tr:
            t["r_net"] = round(t["r_gross"] - cf / max(t["risk_frac"], 1e-4), 3)
        allt.extend(tr); print(f"{sym}: {len(tr)} trades")
    allt.sort(key=lambda t: (t["date"], t["symbol"]))
    (OUT / "three_line_strike_ledger.json").write_text(json.dumps(allt, indent=2))
    gross = [t["r_gross"] for t in allt]; net = [t["r_net"] for t in allt]; mid = len(net) // 2
    summary = {"n": len(allt), "gross": _stats(gross), "net": _stats(net), "net_OOS": _stats(net[mid:]),
               "control_OOS": _stats([x * random.choice([1, -1]) for x in net[mid:]])}
    (OUT / "three_line_strike.json").write_text(json.dumps(summary, indent=2))
    g = summary["gross"]; na = summary["net"]; oo = summary["net_OOS"]; ct = summary["control_OOS"]
    print(f"\n=== Three-Line Strike ===\nn={summary['n']}  GROSS win {g.get('win')}% PF {g.get('PF')} avgR {g.get('avgR')}")
    print(f"   NET win {na.get('win')}% PF {na.get('PF')}  NET_OOS PF {oo.get('PF')} avgR {oo.get('avgR')}  ctrl {ct.get('PF')}")


if __name__ == "__main__":
    main()
