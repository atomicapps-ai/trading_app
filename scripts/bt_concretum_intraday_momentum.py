"""bt_concretum_intraday_momentum — Zarattini/Aziz/Barbon "Beat the Market" Intraday Momentum (SSRN 4824172).

FULLY DEFINED academic day-trade (passes the definitional-completeness gate). Final "current-band + VWAP
trailing" version:

  * Bars: 1-min RTH; decisions ONLY at :00 / :30 marks, first entry 10:00, flat by 16:00.
  * Noise band, recomputed each HH:MM (anchored to today's open, gap-adjusted by prior close):
      move_{t-i, 9:30->HH:MM} = | Close_{t-i,HH:MM} / Open_{t-i,9:30} - 1 |,  i=1..14
      sigma_{t,HH:MM}         = mean of those 14 ABSOLUTE moves      (mean of |ret|, NOT a stdev)
      Upper = max(Open_t, PrevClose) * (1 + VM*sigma) ;  Lower = min(Open_t, PrevClose) * (1 - VM*sigma)
      VM = 1
  * Entry at a mark: LONG if price > Upper, SHORT if price < Lower. One position; reverse on opposite band.
  * Trailing stop (checked at marks): long exits if price < max(Upper, VWAP); short if price > min(Lower, VWAP).
    VWAP = session-anchored, RTH only. Flat at 16:00.
Per-trade % return; fair per-symbol cost; 5/10/20yr windows + IS/OOS + random control. Ledger for images.

  python scripts/bt_concretum_intraday_momentum.py --symbols SPY QQQ
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
RF = 0.05                          # nominal R for reporting (no fixed stop)
VM = 1.0
MARKS = [time(h, m) for h in range(10, 16) for m in (0, 30)]   # 10:00 .. 15:30


def load_1m_et(sym):
    p = SRC / f"{sym}.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df.tz_convert("America/New_York").between_time(time(9, 30), time(16, 0), inclusive="left")


def backtest(sym):
    df = load_1m_et(sym)
    if df is None or len(df) < 5000:
        return []
    sessions = {d: g for d, g in df.groupby(df.index.date)}
    dates = sorted(sessions)
    # per-date open@9:30, prev close, and close at each mark
    open930, close_at, prevclose = {}, {}, {}
    prior = None
    for d in dates:
        g = sessions[d]
        t = np.array([x.time() for x in g.index])
        c = g["close"].values.astype(float); o = g["open"].values.astype(float)
        if not (t == time(9, 30)).any():
            prior = float(c[-1]); continue
        open930[d] = float(o[np.where(t == time(9, 30))[0][0]])
        prevclose[d] = prior if prior is not None else open930[d]
        cm = {}
        for m in MARKS:
            w = np.where(t == m)[0]
            if len(w):
                cm[m] = float(c[w[0]])
        close_at[d] = cm
        prior = float(c[-1])
    trades = []
    for di, d in enumerate(dates):
        if d not in open930 or di < 14:
            continue
        g = sessions[d]
        t = np.array([x.time() for x in g.index])
        c = g["close"].values.astype(float); h = g["high"].values.astype(float)
        l = g["low"].values.astype(float); v = g["volume"].values.astype(float)
        tp = (h + l + c) / 3.0
        cumv = np.cumsum(np.where(v > 0, v, 0.0)); cumpv = np.cumsum(tp * np.where(v > 0, v, 0.0))
        vwap = np.where(cumv > 0, cumpv / np.maximum(cumv, 1e-9), c)
        o930 = open930[d]; pc = prevclose[d]
        prior14 = [close_at.get(dates[di - k], {}) for k in range(1, 15)]
        o930_prior = [open930.get(dates[di - k]) for k in range(1, 15)]
        pos = 0; entry = None; entry_i = None
        for m in MARKS:
            w = np.where(t == m)[0]
            if not len(w):
                continue
            i = w[0]; price = c[i]; vw = vwap[i]
            moves = [abs(prior14[k].get(m, np.nan) / o930_prior[k] - 1.0)
                     for k in range(14) if prior14[k].get(m) and o930_prior[k]]
            if len(moves) < 7:
                continue
            sigma = float(np.nanmean(moves))
            upper = max(o930, pc) * (1 + VM * sigma); lower = min(o930, pc) * (1 - VM * sigma)
            if pos == 0:
                if price > upper:
                    pos = 1; entry = price; entry_i = i
                elif price < lower:
                    pos = -1; entry = price; entry_i = i
            else:
                exit_now = False
                if pos == 1 and price < max(upper, vw):
                    exit_now = True
                elif pos == -1 and price > min(lower, vw):
                    exit_now = True
                # opposite-band reversal
                rev = (pos == 1 and price < lower) or (pos == -1 and price > upper)
                if exit_now or rev:
                    ret = (price - entry) / entry * pos
                    trades.append(_mk(sym, d, g, entry_i, entry, i, price, pos, ret))
                    pos = 0; entry = None
                    if rev:
                        pos = 1 if price > upper else -1; entry = price; entry_i = i
        if pos != 0:                              # flat at close
            price = c[-1]; ret = (price - entry) / entry * pos
            trades.append(_mk(sym, d, g, entry_i, entry, len(c) - 1, price, pos, ret))
    return trades


def _mk(sym, d, g, ei, entry, xi, xpx, pos, ret):
    return {"symbol": sym, "date": str(d), "direction": "long" if pos == 1 else "short",
            "entry_time": str(g.index[ei].time())[:5], "entry": round(entry, 4),
            "stop": None, "target": None, "exit_time": str(g.index[xi].time())[:5], "exit": round(xpx, 4),
            "r_gross": round(ret / RF, 3), "risk_frac": RF, "ret_pct": round(ret * 100, 4)}


def _stats(rs):
    if not rs:
        return {"n": 0}
    w = [x for x in rs if x > 0]; loss = [x for x in rs if x <= 0]
    gp = sum(w); gl = -sum(loss)
    return {"n": len(rs), "win": round(len(w) / len(rs) * 100, 1),
            "avgR": round(statistics.mean(rs), 3), "PF": round(gp / gl, 2) if gl > 0 else 0.0}


def _window(led, latest_year, yrs):
    cut = f"{latest_year - yrs + 1}-01-01"
    sub = [t for t in led if t["date"] >= cut]
    net = [t["r_net"] for t in sub]
    return {"yrs": yrs, **_stats(net)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=["SPY", "QQQ"])
    args = ap.parse_args()
    allt = []
    for sym in args.symbols:
        tr = backtest(sym)
        cf = cost_model.roundtrip_frac(sym)
        for t in tr:
            t["r_net"] = round(t["r_gross"] - cf / RF, 3)
        allt.extend(tr); print(f"{sym}: {len(tr)} trades")
    allt.sort(key=lambda t: (t["date"], t["symbol"]))
    (OUT / "concretum_intraday_momentum_ledger.json").write_text(json.dumps(allt, indent=2))
    gross = [t["r_gross"] for t in allt]; net = [t["r_net"] for t in allt]; mid = len(net) // 2
    ly = max(int(t["date"][:4]) for t in allt) if allt else 2026
    summary = {"n": len(allt), "gross": _stats(gross), "net": _stats(net),
               "net_OOS": _stats(net[mid:]), "control_OOS": _stats([x * random.choice([1, -1]) for x in net[mid:]]),
               "windows": [_window(allt, ly, y) for y in (5, 10, 20)]}
    (OUT / "concretum_intraday_momentum.json").write_text(json.dumps(summary, indent=2))
    g = summary["gross"]; na = summary["net"]; oo = summary["net_OOS"]; ct = summary["control_OOS"]
    print(f"\n=== Concretum Intraday Momentum ===")
    print(f"n={summary['n']}  GROSS win {g.get('win')}% PF {g.get('PF')} avgR {g.get('avgR')}")
    print(f"   NET win {na.get('win')}% PF {na.get('PF')}  OOS PF {oo.get('PF')} avgR {oo.get('avgR')}  ctrl {ct.get('PF')}")
    for w in summary["windows"]:
        print(f"   last {w['yrs']:>2}y: n={w.get('n')}  win {w.get('win')}%  net PF {w.get('PF')}  net avgR {w.get('avgR')}")


if __name__ == "__main__":
    main()
