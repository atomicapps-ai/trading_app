"""bt_one_box_scalper — backtest the 'One Box Scalper / First Candle' day-trade (video FEmD-hK1-yU).

Spec: research/video_library/day_intra/FEmD-hK1-yU/notes.md
Box = first 5-min candle H/L; 1-min execution; breakout close beyond box -> retest -> confirmation
candle (star/hammer or engulfing) -> enter, stop past the confirmation candle, fixed 2R target, one
trade/day inside the first 90 min. Fair per-symbol cost, chronological IS/OOS split, random control.
Writes a per-trade LEDGER (json) that scripts/trade_gallery.py renders for visual confirmation.

  python scripts/bt_one_box_scalper.py [--symbols SPY QQQ ...] [--start 2005-01-01]
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
OPEN, BOX_END, WIN_END, SESS_END = time(9, 30), time(9, 35), time(11, 0), time(16, 0)


def load_1m_et(sym: str) -> pd.DataFrame | None:
    p = SRC / f"{sym}.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df.tz_convert("America/New_York")


def _is_star(o, h, l, c):                 # shooting star / inverted hammer (bearish reversal)
    body = abs(c - o); rng = h - l
    if rng <= 0:
        return False
    upper = h - max(o, c); lower = min(o, c) - l
    return upper >= 2 * body and lower <= body and body <= 0.5 * rng


def _is_hammer(o, h, l, c):               # hammer (bullish reversal)
    body = abs(c - o); rng = h - l
    if rng <= 0:
        return False
    upper = h - max(o, c); lower = min(o, c) - l
    return lower >= 2 * body and upper <= body and body <= 0.5 * rng


def _bear_engulf(po, pc, o, c):           # current red body engulfs prior body
    return c < o and pc > po and o >= pc and c <= po


def _bull_engulf(po, pc, o, c):
    return c > o and pc < po and o <= pc and c >= po


def backtest_symbol(sym: str, start: str | None):
    df = load_1m_et(sym)
    if df is None or len(df) < 2000:
        return []
    df = df.between_time(OPEN, SESS_END, inclusive="left")
    if start:
        df = df[df.index >= pd.Timestamp(start, tz="America/New_York")]
    trades = []
    for day, s in df.groupby(df.index.date):
        t = np.array([x.time() for x in s.index])
        o = s["open"].values.astype(float); h = s["high"].values.astype(float)
        l = s["low"].values.astype(float); c = s["close"].values.astype(float)
        box_m = t < BOX_END
        if box_m.sum() < 3:
            continue
        H0 = h[box_m].max(); L0 = l[box_m].min()
        win = np.where((t >= BOX_END) & (t < WIN_END))[0]
        if len(win) < 5:
            continue
        # 1) breakout: first 1-min CLOSE beyond the box
        direction = 0; bo = None
        for i in win:
            if c[i] > H0:
                direction = 1; bo = i; break
            if c[i] < L0:
                direction = -1; bo = i; break
        if direction == 0:
            continue
        # 2)+3) retest + confirmation candle, one trade/day
        entered = False
        for j in range(bo + 1, win[-1] + 1):
            if j >= len(c):
                break
            # invalidation: full reversal to the other side of the box before entry
            if direction == -1 and c[j] > H0:
                break
            if direction == 1 and c[j] < L0:
                break
            in_retest = (h[j] >= L0) if direction == -1 else (l[j] <= H0)
            if not in_retest:
                continue
            if direction == -1:
                conf = _is_star(o[j], h[j], l[j], c[j]) or _bear_engulf(o[j-1], c[j-1], o[j], c[j])
            else:
                conf = _is_hammer(o[j], h[j], l[j], c[j]) or _bull_engulf(o[j-1], c[j-1], o[j], c[j])
            if not conf or j + 1 >= len(c):
                continue
            # 6) entry next bar open; 7) stop past confirmation candle; 8) 2R target
            entry = o[j + 1]
            stop = h[j] if direction == -1 else l[j]
            risk = abs(entry - stop)
            if risk <= 0 or risk / entry < 1e-4:
                continue
            target = entry - 2 * risk if direction == -1 else entry + 2 * risk
            # 9) simulate to session end
            r_mult = None; exit_i = len(c) - 1; exit_px = c[-1]
            for k in range(j + 1, len(c)):
                if direction == -1:
                    if h[k] >= stop:
                        r_mult = -1.0; exit_i = k; exit_px = stop; break
                    if l[k] <= target:
                        r_mult = 2.0; exit_i = k; exit_px = target; break
                else:
                    if l[k] <= stop:
                        r_mult = -1.0; exit_i = k; exit_px = stop; break
                    if h[k] >= target:
                        r_mult = 2.0; exit_i = k; exit_px = target; break
            if r_mult is None:                      # time exit at session close
                r_mult = (exit_px - entry) / risk * direction
            trades.append({
                "symbol": sym, "date": str(day), "direction": "long" if direction == 1 else "short",
                "box_high": round(H0, 4), "box_low": round(L0, 4),
                "breakout_time": str(s.index[bo].time())[:5], "entry_time": str(s.index[j + 1].time())[:5],
                "entry": round(entry, 4), "stop": round(stop, 4), "target": round(target, 4),
                "exit_time": str(s.index[exit_i].time())[:5], "exit": round(exit_px, 4),
                "conf_idx": int(j), "entry_idx": int(j + 1), "exit_idx": int(exit_i),
                "r_gross": round(r_mult, 3), "risk_frac": round(risk / entry, 5),
            })
            entered = True
            break
        _ = entered
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
    ap.add_argument("--symbols", nargs="*")
    ap.add_argument("--start", default=None)
    ap.add_argument("--tag", default="one_box_scalper")
    args = ap.parse_args()
    syms = args.symbols or sorted(p.stem for p in SRC.glob("*.parquet"))
    all_tr = []
    for sym in syms:
        tr = backtest_symbol(sym, args.start)
        # net R after fair per-symbol round-trip cost (in R units)
        cf = cost_model.roundtrip_frac(sym)
        for t in tr:
            t["r_net"] = round(t["r_gross"] - cf / max(t["risk_frac"], 1e-4), 3)
        all_tr.extend(tr)
        if tr:
            print(f"{sym}: {len(tr)} trades")
    all_tr.sort(key=lambda t: (t["date"], t["symbol"]))
    gross = [t["r_gross"] for t in all_tr]; net = [t["r_net"] for t in all_tr]
    mid = len(net) // 2
    summary = {
        "tag": args.tag, "symbols": syms, "n_trades": len(all_tr),
        "gross_all": _stats(gross), "net_all": _stats(net),
        "net_IS": _stats(net[:mid]), "net_OOS": _stats(net[mid:]),
        "control_OOS": _stats([x * random.choice([1, -1]) for x in net[mid:]]),
    }
    (OUT / f"{args.tag}.json").write_text(json.dumps(summary, indent=2))
    (OUT / f"{args.tag}_ledger.json").write_text(json.dumps(all_tr, indent=2))
    print("\n=== One Box Scalper ===")
    g = summary["gross_all"]; na = summary["net_all"]; oo = summary["net_OOS"]; ct = summary["control_OOS"]
    print(f"n={summary['n_trades']}  GROSS: win {g.get('win')}% PF {g.get('PF')} avgR {g.get('avgR')}")
    print(f"           NET:   win {na.get('win')}% PF {na.get('PF')} avgR {na.get('avgR')}")
    print(f"   NET OOS PF {oo.get('PF')} avgR {oo.get('avgR')} (n {oo.get('n')})  vs control PF {ct.get('PF')}")
    print(f"\nledger -> {OUT / f'{args.tag}_ledger.json'}")


if __name__ == "__main__":
    main()
