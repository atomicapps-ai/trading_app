"""bt_ema9 — backtest the two mechanical 9-EMA day-trade variants (video PdJ5X0exfdU, HowToTrade).

ema9_cross    : enter when a candle CLOSES through the 9-EMA (long above / short below); stop at the
                recent swing (last 5 bars); exit when a candle closes back through the 9-EMA; EOD flat.
ema9_20_cross : enter on a 9-EMA/20-EMA crossover w/ candle confirmation; exit on the opposite
                crossover; stop at the recent swing; EOD flat.
1-min-derived 5-min bars, fair per-symbol cost, IS/OOS + random control. Ledger per variant.

  python scripts/bt_ema9.py --symbols SPY QQQ
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


def backtest(sym, variant):
    df = load_5m_et(sym)
    if df is None or len(df) < 500:
        return []
    o = df["open"].values.astype(float); h = df["high"].values.astype(float)
    l = df["low"].values.astype(float); c = df["close"].values.astype(float)
    ema9 = pd.Series(c).ewm(span=9, adjust=False).mean().values
    ema20 = pd.Series(c).ewm(span=20, adjust=False).mean().values
    dates = df.index.date
    times = np.array([x.time() for x in df.index])
    n = len(c)
    trades = []
    i = 25
    while i < n - 1:
        if dates[i] != dates[i - 1]:                       # only trade intraday continuations
            i += 1; continue
        sig = 0
        if variant == "ema9_cross":
            if c[i - 1] <= ema9[i - 1] and c[i] > ema9[i]: sig = 1
            elif c[i - 1] >= ema9[i - 1] and c[i] < ema9[i]: sig = -1
        else:  # ema9_20_cross
            if ema9[i - 1] <= ema20[i - 1] and ema9[i] > ema20[i] and c[i] > o[i]: sig = 1
            elif ema9[i - 1] >= ema20[i - 1] and ema9[i] < ema20[i] and c[i] < o[i]: sig = -1
        if sig == 0:
            i += 1; continue
        entry = o[i + 1]
        if sig == 1:
            stop = min(l[max(0, i - 4):i + 1])
        else:
            stop = max(h[max(0, i - 4):i + 1])
        risk = abs(entry - stop)
        if risk <= 0 or risk / entry < 1e-4:
            i += 1; continue
        r_mult = None; xi = n - 1; xpx = c[-1]
        for k in range(i + 1, n):
            if dates[k] != dates[i]:
                xi = k - 1; xpx = c[k - 1]; r_mult = (xpx - entry) / risk * sig; break
            if sig == 1 and l[k] <= stop: r_mult = -1.0; xi = k; xpx = stop; break
            if sig == -1 and h[k] >= stop: r_mult = -1.0; xi = k; xpx = stop; break
            exit_sig = ((c[k] < ema9[k]) if sig == 1 else (c[k] > ema9[k])) if variant == "ema9_cross" \
                else ((ema9[k] < ema20[k]) if sig == 1 else (ema9[k] > ema20[k]))
            if exit_sig:
                xi = k; xpx = c[k]; r_mult = (xpx - entry) / risk * sig; break
        if r_mult is None:
            r_mult = (xpx - entry) / risk * sig
        trades.append({"symbol": sym, "date": str(dates[i]), "direction": "long" if sig == 1 else "short",
                       "entry_time": str(times[i + 1])[:5], "entry": round(entry, 4), "stop": round(stop, 4),
                       "target": None, "exit_time": str(times[xi])[:5], "exit": round(xpx, 4),
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
    for variant in ("ema9_cross", "ema9_20_cross"):
        allt = []
        for sym in args.symbols:
            tr = backtest(sym, variant)
            cf = cost_model.roundtrip_frac(sym)
            for t in tr:
                t["r_net"] = round(t["r_gross"] - cf / max(t["risk_frac"], 1e-4), 3)
            allt.extend(tr)
        allt.sort(key=lambda t: (t["date"], t["symbol"]))
        (OUT / f"{variant}_ledger.json").write_text(json.dumps(allt, indent=2))
        gross = [t["r_gross"] for t in allt]; net = [t["r_net"] for t in allt]; mid = len(net) // 2
        summary = {"n": len(allt), "gross": _stats(gross), "net": _stats(net), "net_OOS": _stats(net[mid:]),
                   "control_OOS": _stats([x * random.choice([1, -1]) for x in net[mid:]])}
        (OUT / f"{variant}.json").write_text(json.dumps(summary, indent=2))
        g = summary["gross"]; na = summary["net"]; oo = summary["net_OOS"]; ct = summary["control_OOS"]
        print(f"{variant:14} n={len(allt):5} GROSS win {g.get('win')}% PF {g.get('PF')}  "
              f"NET PF {na.get('PF')}  NET_OOS PF {oo.get('PF')} avgR {oo.get('avgR')}  ctrl {ct.get('PF')}")


if __name__ == "__main__":
    main()
