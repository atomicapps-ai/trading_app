"""bt_tom_corr — correlation gate for Turn-of-the-Month vs the live book (monthly summed-R)."""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import syms, net_r, s7_breakout_continuation, s5_mean_reversion_50ma
from bt_macd_exits import macd_variant
import bt_tom, bt_ibs


def monthly_R(trades):
    if not trades:
        return pd.Series(dtype=float)
    df = pd.DataFrame({"ts": [t.ts for t in trades],
                       "r": [max(-25.0, min(25.0, net_r(t))) for t in trades]})
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.set_index("ts")["r"].resample("ME").sum()


def main():
    cap = 400
    if "--symbols" in sys.argv:
        cap = int(sys.argv[sys.argv.index("--symbols")+1])
    sl = syms("1d")[:cap]
    books = {}
    t, _ = s7_breakout_continuation(sl); books["LIVE:Momentum"] = t
    r = s5_mean_reversion_50ma(sl); books["LIVE:FearDip"] = r[0] if isinstance(r, tuple) else r
    books["LIVE:MACD_run"] = macd_variant(sl, "run_macd")
    books["cand:TurnOfMonth"] = bt_tom.run(sl, 5, 3)
    books["cand:IBS"] = bt_ibs.run(sl)
    M = pd.DataFrame({k: monthly_R(v) for k, v in books.items()}).fillna(0.0)
    M = M.loc[(M != 0).any(axis=1)]
    C = M.corr()
    print("months:", len(M))
    print(C.round(2).to_string())
    live = [k for k in books if k.startswith("LIVE:")]
    for cand in [k for k in books if k.startswith("cand:")]:
        mx = max(abs(float(C.loc[cand, l])) for l in live)
        worst = max(live, key=lambda l: abs(float(C.loc[cand, l])))
        print(f"{cand}: max|corr| to live = {mx:.2f} ({worst})  -> "
              f"{'DIVERSIFIER' if mx < 0.6 else 'redundant'}")


if __name__ == "__main__":
    main()
