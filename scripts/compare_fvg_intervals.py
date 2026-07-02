"""compare_fvg_intervals.py — FVG backtest across intervals/symbols on cached candles.

Reads data/historical/{SYM}_{interval}.csv (fetch first via fetch_fx_history.py).
Answers the conclusive 30m-vs-5m and FX-vs-gold question once real history exists.

Usage:
    python scripts/compare_fvg_intervals.py --since 2015-01-01 --intervals 30m,5m
    python scripts/compare_fvg_intervals.py --symbols XAUUSD --intervals 30m,5m,15m
"""
import argparse
import sys
from datetime import date

from scripts.replay_fvg import _run_pair, FX_PAIRS

# Windows cp1252 consoles crash on non-ASCII print; force UTF-8 where supported.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass


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
    ap.add_argument("--control", action="store_true",
                    help="random-direction control: same setups/timing/risk, "
                         "coin-flip direction. PF should collapse to ~1.0 if the "
                         "real edge is genuine directional prediction.")
    ap.add_argument("--control-seeds", type=int, default=5,
                    help="average the control over N coin-flip seeds (default 5)")
    a = ap.parse_args()
    since = date.fromisoformat(a.since)
    until = date.fromisoformat(a.until)
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    ivs = [i.strip() for i in a.intervals.split(",") if i.strip()]
    mode = "RANDOM-DIRECTION CONTROL" if a.control else "strategy"
    print(f"FVG comparison [{mode}] | {len(syms)} symbols | {since} -> {until}\n")
    for iv in ivs:
        # Real strategy: one deterministic run. Control: average PF/WR over
        # several coin-flip seeds so the number isn't a single lucky draw.
        if not a.control:
            trades = []
            for s in syms:
                trades += _run_pair(s, since, until, interval=iv)
            st = _stats(trades)
            if st:
                print(f"[{iv:4}] trades={st['n']:>5}  WR={st['wr']:.0f}%  PF={st['pf']:.2f}  "
                      f"exp={st['exp']:+.3f}%/trade  net={st['net']:+.2f}%")
            else:
                print(f"[{iv:4}] 0 trades — no {iv} candles cached for these symbols "
                      f"(run fetch_fvg_data.py first)")
            continue

        pfs, wrs, n_last = [], [], 0
        for seed in range(a.control_seeds):
            trades = []
            for s in syms:
                trades += _run_pair(s, since, until, interval=iv,
                                    control=True, seed=seed)
            st = _stats(trades)
            if st:
                pfs.append(st["pf"]); wrs.append(st["wr"]); n_last = st["n"]
        if pfs:
            mean_pf = sum(pfs) / len(pfs); mean_wr = sum(wrs) / len(wrs)
            print(f"[{iv:4}] trades={n_last:>5}  WR={mean_wr:.0f}%  "
                  f"PF={mean_pf:.2f} (mean of {len(pfs)} seeds; "
                  f"range {min(pfs):.2f}-{max(pfs):.2f})")
        else:
            print(f"[{iv:4}] 0 trades — no {iv} candles cached "
                  f"(run fetch_fvg_data.py first)")


if __name__ == "__main__":
    main()
