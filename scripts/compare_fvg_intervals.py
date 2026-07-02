"""compare_fvg_intervals.py — FVG backtest across intervals/symbols on cached candles.

Reads data/historical/{SYM}_{interval}.csv (fetch first via fetch_fx_history.py).
Answers the conclusive 30m-vs-5m and FX-vs-gold question once real history exists.

Usage:
    python scripts/compare_fvg_intervals.py --since 2015-01-01 --intervals 30m,5m
    python scripts/compare_fvg_intervals.py --symbols XAUUSD --intervals 30m,5m,15m
"""
import argparse
from datetime import date

from scripts.replay_fvg import _run_pair, FX_PAIRS


def _stats(trades):
    n = len(trades)
    if not n:
        return None
    wins = [t.pnl_pct for t in trades if t.pnl_pct > 0]
    losses = [t.pnl_pct for t in trades if t.pnl_pct <= 0]
    gp, gl = sum(wins), -sum(losses)
    return dict(n=n, wr=len(wins) / n * 100,
                pf=(gp / gl if gl > 0 else float("inf")),
                exp=sum(t.pnl_pct for t in trades) / n,
                net=sum(t.pnl_pct for t in trades))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2015-01-01")
    ap.add_argument("--until", default=date.today().isoformat())
    ap.add_argument("--intervals", default="30m,5m")
    ap.add_argument("--symbols", default=",".join(FX_PAIRS))
    a = ap.parse_args()
    since = date.fromisoformat(a.since)
    until = date.fromisoformat(a.until)
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    ivs = [i.strip() for i in a.intervals.split(",") if i.strip()]
    print(f"FVG comparison | {len(syms)} symbols | {since} → {until}\n")
    for iv in ivs:
        trades = []
        for s in syms:
            trades += _run_pair(s, since, until, interval=iv)
        st = _stats(trades)
        if st:
            print(f"[{iv:4}] trades={st['n']:>5}  WR={st['wr']:.0f}%  PF={st['pf']:.2f}  "
                  f"exp={st['exp']:+.3f}%/trade  net={st['net']:+.2f}%")
        else:
            print(f"[{iv:4}] 0 trades — no {iv} candles cached for these symbols "
                  f"(run fetch_fx_history.py first)")


if __name__ == "__main__":
    main()
