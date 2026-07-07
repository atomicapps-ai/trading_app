"""strategy_correlation_gate — does each passed candidate DIVERSIFY the live book?

Builds a monthly summed-R series for every strategy (live anchors + candidates), correlates
them, and applies the promotion gate:
  * a candidate is a DIVERSIFIER if its max |correlation| to the LIVE anchors is < THRESH
    AND its OOS expectancy is positive;
  * within a family, if two candidates correlate > FAM_THRESH with each other, keep only the
    higher-OOS-PF one (the rest are redundant duplicates).
Run: python scripts/strategy_correlation_gate.py [--symbols N]
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import sys, json
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import (load, syms, net_r, summarize,
                            s7_breakout_continuation, s5_mean_reversion_50ma)

THRESH = 0.60      # max corr to a live anchor to still count as a diversifier
FAM_THRESH = 0.70  # within-family dedup threshold

import bt_connors_pullback, bt_bb3sd_fade, bt_bbrsi, bt_hidden_divergence
import bt_ma_crossover, bt_turtle, bt_supertrend, bt_4candles
from bt_macd_exits import macd_variant


def monthly_R(trades) -> pd.Series:
    if not trades:
        return pd.Series(dtype=float)
    df = pd.DataFrame({"ts": [t.ts for t in trades],
                       "r": [max(-25.0, min(25.0, net_r(t))) for t in trades]})
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.set_index("ts")["r"].resample("ME").sum()


def oos_pf(trades):
    try:
        return summarize(trades)["out_sample"]["profit_factor"]
    except Exception:
        return float("nan")


def build(sl):
    books = {}
    # ---- LIVE anchors (representative reproductions) ----
    t, _ = s7_breakout_continuation(sl); books["LIVE:MomentumBreakout"] = ("trend", t)
    r = s5_mean_reversion_50ma(sl); t = r[0] if isinstance(r, tuple) else r
    books["LIVE:FearDip(50MAmr)"] = ("meanrev", t)
    books["LIVE:MACD_run"] = ("trend", macd_variant(sl, "run_macd"))
    # ---- CANDIDATES ----
    books["cand:rsi_pullback(Connors)"] = ("meanrev", bt_connors_pullback.run(sl))
    books["cand:band_extreme_fade(BB3SD)"] = ("meanrev", bt_bb3sd_fade.run(sl, "1d", True, False, "basis"))
    books["cand:band_rsi_reversion(BBRSI)"] = ("meanrev", bt_bbrsi.run(sl))
    books["cand:down_days_reversion(4red)"] = ("meanrev", bt_4candles.run(sl, "ma"))
    books["cand:hidden_divergence"] = ("trend", bt_hidden_divergence.run(sl, "trail", True))
    books["cand:donchian_breakout(Turtle55/20)"] = ("trend", bt_turtle.turtle(sl, 55, 20))
    books["cand:supertrend_run(DEMA+ST)"] = ("trend", bt_supertrend.run_st(sl, "long", True))
    books["cand:ma_crossover(HELD)"] = ("trend", bt_ma_crossover.run(sl))
    return books


def main():
    cap = 400
    if "--symbols" in sys.argv:
        cap = int(sys.argv[sys.argv.index("--symbols")+1])
    sl = syms("1d")
    if cap:
        sl = sl[:cap]
    books = build(sl)

    series = {k: monthly_R(v[1]) for k, v in books.items()}
    fam = {k: v[0] for k, v in books.items()}
    pf = {k: oos_pf(v[1]) for k, v in books.items()}
    n = {k: len(v[1]) for k, v in books.items()}
    M = pd.DataFrame(series).fillna(0.0)
    M = M.loc[(M != 0).any(axis=1)]
    C = M.corr()

    live = [k for k in books if k.startswith("LIVE:")]
    cands = [k for k in books if k.startswith("cand:")]

    out = {"n_symbols": len(sl), "months": len(M), "threshold_vs_live": THRESH,
           "fam_dedup_threshold": FAM_THRESH,
           "corr_matrix": {a: {b: round(float(C.loc[a, b]), 2) for b in C.columns} for a in C.index},
           "candidates": {}}
    for c in cands:
        max_live = max(abs(float(C.loc[c, l])) for l in live)
        worst_live = max(live, key=lambda l: abs(float(C.loc[c, l])))
        out["candidates"][c] = {
            "family": fam[c], "n_trades": n[c], "oos_pf": pf[c],
            "max_corr_to_live": round(max_live, 2), "most_correlated_live": worst_live,
            "diversifies_live": bool(max_live < THRESH and (pf[c] == pf[c]) and pf[c] > 1.0),
        }
    # within-family dedup among candidates
    for c in cands:
        dups = []
        for d in cands:
            if d != c and fam[d] == fam[c] and abs(float(C.loc[c, d])) >= FAM_THRESH:
                dups.append((d, round(float(C.loc[c, d]), 2)))
        out["candidates"][c]["family_dups_over_thresh"] = dups

    Path("data/research/strategy_results/correlation_gate.json").write_text(json.dumps(out, indent=2, default=str))
    # console summary
    print(f"symbols={len(sl)} months={len(M)}\n")
    print("=== correlation matrix (monthly R) ===")
    print(C.round(2).to_string())
    print("\n=== candidate verdicts ===")
    for c in cands:
        v = out["candidates"][c]
        tag = "DIVERSIFIER" if v["diversifies_live"] else "redundant-vs-live"
        print(f"{c:38} fam={v['family']:8} n={v['n_trades']:6} OOS_PF={v['oos_pf']}"
              f"  maxCorrLive={v['max_corr_to_live']} ({v['most_correlated_live'].replace('LIVE:','')})  -> {tag}")
        if v["family_dups_over_thresh"]:
            print(f"    family-correlated with: {v['family_dups_over_thresh']}")


if __name__ == "__main__":
    main()
