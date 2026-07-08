"""bt_intraday_fair — re-test the rejected intraday kernels on FINER bars + REALISTIC per-symbol cost.

The earlier intraday null used 30-minute bars and a flat 10-bps cost. This re-runs the same kernels
on 5-minute bars with a per-symbol round-trip cost (cost_model, ~1.5bps for liquid names) and reports
gross / net(fair) / net(10bps) side by side, so we can tell a real absence of edge from a data/cost
artifact.  python scripts/bt_intraday_fair.py [--interval 5m] [--symbols N]
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, random, statistics, sys
from datetime import time
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from bt_intraday_research import _load_et, KERNELS, RTH_OPEN, RTH_CLOSE  # noqa: E402
import cost_model  # noqa: E402

random.seed(13)
OUT = ROOT / "data" / "research" / "strategy_results"


def _stats(rs):
    if not rs:
        return {"n": 0}
    w = [x for x in rs if x > 0]; l = [x for x in rs if x <= 0]
    gp = sum(w); gl = -sum(l)
    return {"n": len(rs), "win": round(len(w)/len(rs)*100, 1),
            "avgR": round(statistics.mean(rs), 4), "PF": round(gp/gl, 2) if gl > 0 else 0.0}


def run(symlist, interval="5m"):
    # per kernel: gross r list, net(fair) r list, net(10bps) r list
    G = {k: [] for k in KERNELS}; NF = {k: [] for k in KERNELS}; N10 = {k: [] for k in KERNELS}
    for s in symlist:
        m = _load_et(s, interval); daily = _load_et(s, "1d")
        if m is None or daily is None or len(m) < 100 or len(daily) < 210:
            continue
        m = m.between_time(RTH_OPEN, RTH_CLOSE, inclusive="left")
        cbps = cost_model.roundtrip_frac(s)                 # per-symbol round-trip fraction
        dc = daily["close"].values.astype(float)
        dh = daily["high"].values.astype(float); dl = daily["low"].values.astype(float)
        sma200 = pd.Series(dc).rolling(200).mean().values
        pc = np.roll(dc, 1); pc[0] = dc[0]
        tr = np.maximum(dh-dl, np.maximum(np.abs(dh-pc), np.abs(dl-pc)))
        atrpct = pd.Series(tr).rolling(14).mean().values / dc
        d_list = list(daily.index.date)
        for day, sess in m.groupby(m.index.date):
            if len(sess) < 5:
                continue
            idx = np.searchsorted(d_list, day) - 1
            if idx < 205 or np.isnan(sma200[idx]):
                continue
            prior = {"close": dc[idx], "sma200": sma200[idx],
                     "atrpct": atrpct[idx] if not np.isnan(atrpct[idx]) else 0.02}
            for k, fn in KERNELS.items():
                try:
                    for t in fn(sess, prior):
                        rf = t.risk_frac if t.risk_frac and t.risk_frac > 0 else 0.02
                        G[k].append(t.r)
                        NF[k].append(t.r - (2*cbps)/rf)          # fair per-symbol cost
                        N10[k].append(t.r - (2*0.0010)/rf)       # old flat 10bps
                except Exception:
                    pass
    return G, NF, N10


def main():
    interval = sys.argv[sys.argv.index("--interval")+1] if "--interval" in sys.argv else "5m"
    cap = int(sys.argv[sys.argv.index("--symbols")+1]) if "--symbols" in sys.argv else 80
    from bt_intraday_research import stock_symbols
    sl = stock_symbols()[:cap]
    G, NF, N10 = run(sl, interval)
    out = {"interval": interval, "n_symbols": len(sl), "results": {}}
    print(f"interval={interval} symbols={len(sl)}\n{'kernel':26} {'n':>6} {'GROSS_PF':>9} {'NET_fair_PF':>11} {'NET_10bps_PF':>12}")
    for k in KERNELS:
        g = _stats(G[k]); nf = _stats(NF[k]); n10 = _stats(N10[k])
        out["results"][k] = {"gross": g, "net_fair": nf, "net_10bps": n10}
        if g.get("n", 0):
            print(f"{k:26} {g['n']:>6} {g['PF']:>9} {nf['PF']:>11} {n10['PF']:>12}   (fair avgR {nf['avgR']}, win {g['win']}%)")
    (OUT / f"intraday_fair_{interval}.json").write_text(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
