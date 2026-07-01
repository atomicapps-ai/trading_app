"""bt_strategy_correlation — do the candidate trend strategies add diversification
over the deployed book, or are they redundant? Builds each strategy's monthly
summed-R series, correlates them, and reports a naive equal-weight combined book.
Run: python scripts/bt_strategy_correlation.py [--symbols N]
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import sys
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import (load, syms, atr, Trade, net_r,  # noqa
                            s7_breakout_continuation, s5_mean_reversion_50ma)
from bt_video_candidates import c2_turtle
from bt_macd_exits import macd_variant


def monthly_R(trades) -> pd.Series:
    if not trades: return pd.Series(dtype=float)
    # clamp per-trade R to kill data-artifact outliers (near-zero-risk blowups)
    df = pd.DataFrame({"ts": [t.ts for t in trades], "r": [max(-25.0, min(25.0, net_r(t))) for t in trades]})
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.set_index("ts")["r"].resample("ME").sum()


def main():
    cap = 45
    if "--symbols" in sys.argv: cap = int(sys.argv[sys.argv.index("--symbols")+1])
    sl = syms("1d")[:cap]

    books = {}
    t, _ = s7_breakout_continuation(sl);          books["MomentumBreakout(s7)"] = t
    books["FearDipFamily(s5)"], _ = (lambda r: (r[0] if isinstance(r, tuple) else r, None))(s5_mean_reversion_50ma(sl))
    t, _ = c2_turtle(sl, 20, 10);                 books["Turtle20/10"] = t
    books["MACD_run"] = macd_variant(sl, "run_macd")

    series = {k: monthly_R(v) for k, v in books.items()}
    M = pd.DataFrame(series).fillna(0.0)
    M = M.loc[(M != 0).any(axis=1)]

    print("Per-strategy (monthly-R series):")
    for k in books:
        s = M[k]; tot = s.sum(); ann = s.mean()*12
        print(f"  {k:24s} months={int((s!=0).sum())} totalR={tot:.0f} mean/mo={s.mean():.2f}R")

    print("\nPairwise correlation of monthly returns:")
    corr = M.corr()
    cols = list(M.columns)
    print("  " + " ".join(f"{c[:10]:>11s}" for c in cols))
    for r in cols:
        print(f"  {r[:10]:>10s} " + " ".join(f"{corr.loc[r,c]:>11.2f}" for c in cols))

    # equal-weight combined book vs best single
    combo = M.sum(axis=1)
    def sharpe(s): return (s.mean()/s.std()*np.sqrt(12)) if s.std() > 0 else float("nan")
    print("\nMonthly-R Sharpe (annualized, R-based):")
    for k in cols: print(f"  {k:24s} {sharpe(M[k]):.2f}")
    print(f"  {'EQUAL-WEIGHT COMBO':24s} {sharpe(combo):.2f}")


if __name__ == "__main__":
    main()
