"""bt_tom — Turn-of-the-Month seasonality (sourced: QuantifiedStrategies / Quantpedia).

Enter at the close of the Kth-last trading day of the month; exit at the close of the Mth trading
day of the new month. Calendar-deterministic (the month's trading days are known from the
exchange calendar), so entering on the signal-day close is not look-ahead.
  * default: enter on the 5th-last trading day, exit on the 3rd trading day of next month.
No stop (calendar hold). R normalised to a fixed 5% nominal risk. Daily US stocks, strategy_suite rig.
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, syms, Trade, summarize, random_control

RF = 0.05


def run(symlist, k_last=5, m_into=3):
    trades = []
    for s in symlist:
        df = load(s, "1d")
        if df is None or len(df) < 260:
            continue
        c = df["close"].values
        idx = df.index
        # group positions by (year, month)
        ym = [(t.year, t.month) for t in idx]
        groups = {}
        for pos, key in enumerate(ym):
            groups.setdefault(key, []).append(pos)
        months = sorted(groups.keys())
        for a in range(len(months) - 1):
            cur = groups[months[a]]; nxt = groups[months[a + 1]]
            if len(cur) < k_last or len(nxt) < m_into:
                continue
            entry_pos = cur[-k_last]          # Kth-last trading day of current month
            exit_pos = nxt[m_into - 1]        # Mth trading day of next month
            entry = c[entry_pos]; exitp = c[exit_pos]
            if entry <= 0:
                continue
            trades.append(Trade(idx[entry_pos], (exitp - entry) / (RF * entry), RF, +1))
    return trades


if __name__ == "__main__":
    cap = None
    if "--symbols" in sys.argv: cap = int(sys.argv[sys.argv.index("--symbols")+1])
    sl = syms("1d")
    if cap: sl = sl[:cap]
    res = {"n_symbols": len(sl), "results": {}}
    for name, kw in {"tom_5_3": dict(k_last=5, m_into=3), "tom_3_3": dict(k_last=3, m_into=3),
                     "tom_2_3": dict(k_last=2, m_into=3)}.items():
        t = run(sl, **kw)
        res["results"][name] = summarize(t, random_control(t))
    Path("data/research/strategy_results/tom_sourced.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res, indent=2, default=str))
