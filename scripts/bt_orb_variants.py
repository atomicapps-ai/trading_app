"""bt_orb_variants — backtest the plain Opening-Range-Breakout variants that dominate the YouTube
day-trade picks (cluster A in _PROCESSING.md): first N-min box, enter on a close beyond it, in the
break direction, one trade/day inside the first 90 min. Two exit styles per box size.

Variants: orb5_eod, orb5_2R, orb15_eod, orb15_2R.  1-min bars, fair per-symbol cost, IS/OOS + control.
Writes a ledger per variant for render_backtest_images.py.

  python scripts/bt_orb_variants.py --symbols SPY QQQ
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
SRC = ROOT / "data" / "historical_1m"
OUT = ROOT / "data" / "research" / "strategy_results"; OUT.mkdir(parents=True, exist_ok=True)
OPEN, WIN_END, SESS_END = time(9, 30), time(11, 0), time(16, 0)


def load_1m_et(sym):
    p = SRC / f"{sym}.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df.tz_convert("America/New_York").between_time(OPEN, SESS_END, inclusive="left")


def run_variant(sym, box_min, exit_style):
    df = load_1m_et(sym)
    if df is None or len(df) < 2000:
        return []
    box_end = time(9, 30 + box_min)
    trades = []
    for day, s in df.groupby(df.index.date):
        t = np.array([x.time() for x in s.index])
        o = s["open"].values.astype(float); h = s["high"].values.astype(float)
        l = s["low"].values.astype(float); c = s["close"].values.astype(float)
        bm = t < box_end
        if bm.sum() < box_min - 1:
            continue
        H0 = h[bm].max(); L0 = l[bm].min()
        win = np.where((t >= box_end) & (t < WIN_END))[0]
        if len(win) < 3:
            continue
        direction = 0; bo = None
        for i in win:
            if c[i] > H0:
                direction = 1; bo = i; break
            if c[i] < L0:
                direction = -1; bo = i; break
        if direction == 0 or bo + 1 >= len(c):
            continue
        entry = o[bo + 1]
        stop = L0 if direction == 1 else H0
        risk = abs(entry - stop)
        if risk <= 0 or risk / entry < 1e-4:
            continue
        target = (entry + 2 * risk) if direction == 1 else (entry - 2 * risk)
        r_mult = None; exit_i = len(c) - 1; exit_px = c[-1]
        for k in range(bo + 1, len(c)):
            if direction == 1:
                if l[k] <= stop:
                    r_mult = -1.0; exit_i = k; exit_px = stop; break
                if exit_style == "2R" and h[k] >= target:
                    r_mult = 2.0; exit_i = k; exit_px = target; break
            else:
                if h[k] >= stop:
                    r_mult = -1.0; exit_i = k; exit_px = stop; break
                if exit_style == "2R" and l[k] <= target:
                    r_mult = 2.0; exit_i = k; exit_px = target; break
        if r_mult is None:
            r_mult = (exit_px - entry) / risk * direction
        trades.append({"symbol": sym, "date": str(day), "direction": "long" if direction == 1 else "short",
                       "box_high": round(H0, 4), "box_low": round(L0, 4),
                       "entry_time": str(s.index[bo + 1].time())[:5], "entry": round(entry, 4),
                       "stop": round(stop, 4), "target": round(target, 4),
                       "exit_time": str(s.index[exit_i].time())[:5], "exit": round(exit_px, 4),
                       "r_gross": round(r_mult, 3), "risk_frac": round(risk / entry, 5)})
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
    variants = [("orb5_eod", 5, "eod"), ("orb5_2R", 5, "2R"), ("orb15_eod", 15, "eod"), ("orb15_2R", 15, "2R")]
    summary = {}
    for name, bm, style in variants:
        allt = []
        for sym in args.symbols:
            tr = run_variant(sym, bm, style)
            cf = cost_model.roundtrip_frac(sym)
            for t in tr:
                t["r_net"] = round(t["r_gross"] - cf / max(t["risk_frac"], 1e-4), 3)
            allt.extend(tr)
        allt.sort(key=lambda t: (t["date"], t["symbol"]))
        (OUT / f"{name}_ledger.json").write_text(json.dumps(allt, indent=2))
        gross = [t["r_gross"] for t in allt]; net = [t["r_net"] for t in allt]; mid = len(net) // 2
        summary[name] = {"n": len(allt), "gross": _stats(gross), "net": _stats(net),
                         "net_OOS": _stats(net[mid:]),
                         "control_OOS": _stats([x * random.choice([1, -1]) for x in net[mid:]])}
        g = summary[name]["gross"]; noo = summary[name]["net_OOS"]; ct = summary[name]["control_OOS"]
        print(f"{name:10} n={len(allt):5} GROSS win {g.get('win')}% PF {g.get('PF')}  "
              f"NET_OOS PF {noo.get('PF')} avgR {noo.get('avgR')}  ctrl {ct.get('PF')}")
    (OUT / "orb_variants.json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
