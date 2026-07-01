"""bt_macd_exits — does the MACD+200MA entry get better if we let winners run
instead of capping at 1.5R? Tests several exit styles on the same entry.
Run: python scripts/bt_macd_exits.py [--symbols N]
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import sys
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_suite import load, syms, atr, Trade, summarize, random_control  # noqa


def _ema(x, n): return pd.Series(x).ewm(span=n, adjust=False).mean().values


def macd_variant(symlist, exit_style, target_R=1.5, trail_ma=20, max_hold=120):
    """entry: MACD(12,26,9) cross up below zero, close>SMA200, next open. stop=entry-1.5*ATR14.
    exit_style in {fixed, run_macd, trail_ma, target3}."""
    trades = []
    for s in symlist:
        df = load(s, "1d")
        if df is None or len(df) < 260: continue
        c = df["close"].values; o = df["open"].values; l = df["low"].values; h = df["high"].values
        a = atr(df); sma200 = pd.Series(c).rolling(200).mean().values
        sma_t = pd.Series(c).rolling(trail_ma).mean().values
        macd = _ema(c, 12) - _ema(c, 26); sig = _ema(macd, 9)
        n = len(df); i = 205
        while i < n - 1:
            cross = macd[i] > sig[i] and macd[i-1] <= sig[i-1]
            if cross and macd[i] < 0 and not np.isnan(sma200[i]) and c[i] > sma200[i] and not np.isnan(a[i]) and a[i] > 0:
                entry = o[i+1] if i+1 < n else c[i]
                stop = entry - 1.5 * a[i]; risk = entry - stop
                if risk <= 0: i += 1; continue
                rf = risk / entry; exitp = None
                for j in range(i+1, min(i+1+max_hold, n)):
                    if l[j] <= stop: exitp = stop; break
                    if exit_style == "fixed" and h[j] >= entry + target_R*risk: exitp = entry + target_R*risk; break
                    if exit_style == "target3" and h[j] >= entry + 3.0*risk: exitp = entry + 3.0*risk; break
                    if exit_style == "run_macd" and macd[j] < sig[j]: exitp = c[j]; break
                    if exit_style == "trail_ma" and not np.isnan(sma_t[j]) and c[j] < sma_t[j]: exitp = c[j]; break
                if exitp is None: exitp = c[min(i+max_hold, n-1)]
                trades.append(Trade(df.index[i], (exitp-entry)/risk, rf, +1)); i = j+1; continue
            i += 1
    return trades


def main():
    cap = 45
    if "--symbols" in sys.argv: cap = int(sys.argv[sys.argv.index("--symbols")+1])
    sl = syms("1d")[:cap]
    for style in ["fixed", "target3", "run_macd", "trail_ma"]:
        tr = macd_variant(sl, style)
        r = summarize(tr, random_control(tr))
        a = r.get("all", {}); oos = r.get("out_sample", {}); ctl = r.get("random_control", {})
        print(f"\n=== MACD exit={style} ===")
        print(f"  ALL: n={a.get('n')} win={a.get('win_pct')}% exp={a.get('expectancy_R')}R PF={a.get('profit_factor')} avgWin={a.get('avg_win_R')} avgLoss={a.get('avg_loss_R')}")
        print(f"  OOS: n={oos.get('n')} win={oos.get('win_pct')}% exp={oos.get('expectancy_R')}R PF={oos.get('profit_factor')}")
        print(f"  CTL: PF={ctl.get('profit_factor')} exp={ctl.get('expectancy_R')}")


if __name__ == "__main__":
    main()
