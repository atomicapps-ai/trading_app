"""bt_intraday_momentum — Market Intraday Momentum (Gao, Han, Li & Zhou, JFE).

Academic edge (SOURCED, Track B): the FIRST half-hour return predicts the LAST half-hour return.
  * r1 = first-30min close / prior daily close - 1.
  * At the start of the last 30 min (15:30 ET) go LONG if the predictor > 0 else SHORT; exit at
    the close (flat, ~30-min hold).
  * base predictor = r1 ; `enh` predictor = r1 + r12 (r12 = the 15:00-15:30 half-hour return).
Same-day, tiny hold. Tested on liquid ETFs + stocks with 5m bars and REALISTIC per-symbol cost
(cost_model). No stop -> 5% nominal risk normalisation. Reports gross / net(fair) / control.
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, random, statistics, sys
from datetime import time
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import cost_model  # noqa: E402

random.seed(13)
HIST = ROOT / "data" / "historical"; OUT = ROOT / "data" / "research" / "strategy_results"
RF = 0.05
ETFS = ["SPY", "QQQ", "IWM", "DIA"]
STOCKS = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "TSLA", "GOOGL", "AMD", "NFLX", "AVGO"]


def _load_et(sym, interval):
    f = HIST / f"{sym}_{interval}.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f); dc = df.columns[0]
    df[dc] = pd.to_datetime(df[dc], utc=True, errors="coerce")
    df = df.dropna(subset=[dc]).set_index(dc).sort_index()
    df.columns = [c.lower() for c in df.columns]
    return df.tz_convert("America/New_York") if interval != "1d" else df


def run(symlist, predictor="base", interval="5m"):
    G, NF = [], []
    for s in symlist:
        m = _load_et(s, interval); daily = _load_et(s, "1d")
        if m is None or daily is None:
            continue
        m = m.between_time(time(9, 30), time(16, 0), inclusive="left")
        cbps = cost_model.roundtrip_frac(s)
        dclose = {d.date(): float(c) for d, c in daily["close"].items()}
        d_sorted = sorted(dclose)
        for day, sess in m.groupby(m.index.date):
            if len(sess) < 12:
                continue
            t = np.array([x.time() for x in sess.index])
            o = sess["open"].values.astype(float); c = sess["close"].values.astype(float)
            # prior daily close
            i = np.searchsorted(d_sorted, day) - 1
            if i < 0:
                continue
            prior_close = dclose[d_sorted[i]]
            if prior_close <= 0:
                continue
            first_mask = t < time(10, 0)
            last_mask = t >= time(15, 30)
            mid_mask = (t >= time(15, 0)) & (t < time(15, 30))
            if not first_mask.any() or not last_mask.any():
                continue
            first_close = c[first_mask][-1]
            r1 = first_close / prior_close - 1.0
            pred = r1
            if predictor == "enh" and mid_mask.any():
                r12 = c[mid_mask][-1] / o[mid_mask][0] - 1.0
                pred = r1 + r12
            if pred == 0:
                continue
            direction = 1 if pred > 0 else -1
            entry = o[last_mask][0]; exitp = c[last_mask][-1]
            if entry <= 0:
                continue
            gross = direction * (exitp - entry) / entry / RF     # in nominal-R units
            G.append(gross)
            NF.append(gross - (2 * cbps) / RF)
    return G, NF


def _stats(rs):
    if not rs:
        return {"n": 0}
    w = [x for x in rs if x > 0]; l = [x for x in rs if x <= 0]
    gp = sum(w); gl = -sum(l)
    return {"n": len(rs), "win": round(len(w)/len(rs)*100, 1),
            "avgR": round(statistics.mean(rs), 4), "PF": round(gp/gl, 2) if gl > 0 else 0.0}


def summ(rs):
    mid = len(rs)//2; ctrl = [x*random.choice([1, -1]) for x in rs]
    return {"all": _stats(rs), "in_sample": _stats(rs[:mid]), "out_sample": _stats(rs[mid:]),
            "control": _stats(ctrl)}


if __name__ == "__main__":
    interval = sys.argv[sys.argv.index("--interval")+1] if "--interval" in sys.argv else "5m"
    syms = [s for s in (ETFS + STOCKS) if (HIST / f"{s}_{interval}.csv").exists()]
    out = {"interval": interval, "symbols": syms, "results": {}}
    print(f"interval={interval} symbols={len(syms)}: {syms}\n")
    for pred in ("base", "enh"):
        G, NF = run(syms, pred, interval)
        sg = summ(G); sn = summ(NF)
        out["results"][pred] = {"gross": sg, "net_fair": sn}
        g = sg["all"]; oo_g = sg["out_sample"]; oo_n = sn["out_sample"]; ct = sg["control"]
        print(f"{pred:5} n={g['n']:6} win={g['win']}%  GROSS OOS_PF={oo_g['PF']} avgR={oo_g['avgR']}  "
              f"NET_fair OOS_PF={oo_n['PF']} avgR={oo_n['avgR']}  ctrlPF={ct['PF']}")
    (OUT / "intraday_momentum.json").write_text(json.dumps(out, indent=2, default=str))
