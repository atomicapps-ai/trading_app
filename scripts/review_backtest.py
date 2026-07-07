"""scripts/review_backtest.py — review a cached backtest, trade by trade.

Reads the persisted backtest cache (data/backtest_cache.db, written by
scripts/score_universe.py) so you can review any strategy's simulated trades
and their indicator snapshots (entry / exit / worst-adverse candle) without
re-running the heavy backtest.

Usage
-----
    # Per-symbol score summary for a strategy:
    python -m scripts.review_backtest --strategy momentum_breakout

    # Every trade for one symbol, with key indicators at entry/exit:
    python -m scripts.review_backtest --strategy momentum_breakout --symbol NVDA

    # Export the full ledger (all indicators flattened) to CSV for Excel:
    python -m scripts.review_backtest --strategy momentum_breakout --csv nvda.csv --symbol NVDA
    python -m scripts.review_backtest --strategy momentum_breakout --csv all.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services import backtest_store as store  # noqa: E402

# The indicator fields surfaced in the console trade view (CSV gets them all).
_KEY = ["close", "rsi_14", "atr_14_pct", "adx_14", "macd_hist",
        "dist_sma_50_pct", "dist_sma_200_pct", "volume_ratio"]


def _fmt(v) -> str:
    return "—" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))


def main() -> int:
    ap = argparse.ArgumentParser(description="Review a cached backtest trade by trade.")
    ap.add_argument("--strategy", required=True)
    ap.add_argument("--symbol", help="Limit to one symbol")
    ap.add_argument("--verdict", choices=["KEEP", "DROP", "THIN"], help="Filter scores")
    ap.add_argument("--csv", help="Export the full trade ledger (all indicators) to this file")
    ap.add_argument("--limit", type=int, default=500)
    args = ap.parse_args()

    # Newest run for this strategy (any universe/window).
    cfg = store.config_hash(args.strategy)
    import sqlite3
    conn = sqlite3.connect(store.DB_PATH)
    conn.row_factory = sqlite3.Row
    r = conn.execute("SELECT * FROM backtest_runs WHERE strategy=? "
                     "ORDER BY created_at DESC LIMIT 1", (args.strategy,)).fetchone()
    conn.close()
    if not r:
        print(f"no cached run for {args.strategy}. Run scripts.score_universe first.")
        return 1
    run = dict(r)
    print(f"strategy {args.strategy} · run {run['run_id'][:8]} · {run['created_at'][:19]} · "
          f"{run['n_trades']} trades · config {'MATCH' if run['config_hash']==cfg else 'CHANGED (stale)'}")

    # ── Per-symbol score summary ──
    scores = store.get_scores(run["run_id"])
    if args.symbol:
        scores = [s for s in scores if s["symbol"] == args.symbol.upper()]
    if args.verdict:
        scores = [s for s in scores if s["verdict"] == args.verdict]
    if not args.symbol:
        print("-" * 78)
        print(f"{'SYM':<7}{'verdict':<8}{'IS n':>5}{'IS PF':>7}{'IS WR':>7}"
              f"{'IS avgR':>8}{'OOSn':>6}{'OOS PF':>8}")
        for s in scores:
            print(f"{s['symbol']:<7}{s['verdict']:<8}{s['is_n']:>5}{s['is_pf']:>7.2f}"
                  f"{s['is_wr']*100:>6.0f}%{s['is_avg_r']:>8.2f}{s['oos_n']:>6}{s['oos_pf']:>8.2f}")

    # ── Trade-by-trade (when a symbol is given, or with --csv) ──
    trades = store.get_trades(args.strategy, symbol=args.symbol,
                              run_id=run["run_id"], limit=args.limit)
    if args.symbol:
        print("-" * 100)
        print(f"{'entry':<11}{'exit':<11}{'win':>4}{'pnlR':>6}{'maeR':>6}{'mfeR':>6}"
              f"{'reason':<9} | entry: " + " ".join(k.split('_')[0][:4] for k in _KEY))
        for t in trades:
            ei = t["entry_ind"]
            vals = "  ".join(_fmt(ei.get(k)) for k in _KEY)
            print(f"{t['entry_date']:<11}{t['exit_date']:<11}{'Y' if t['win'] else 'n':>4}"
                  f"{t['pnl_r']:>6.2f}{t['mae_r']:>6.2f}{t['mfe_r']:>6.2f} {t['exit_reason']:<9}| {vals}")

    # ── CSV export: full ledger, indicators flattened (entry_/exit_/adverse_) ──
    if args.csv:
        base = ["symbol", "window", "signal_date", "entry_date", "exit_date", "direction",
                "entry", "stop", "tp1", "exit_px", "exit_reason", "pnl_pct", "pnl_r",
                "mfe_r", "mae_r", "win", "hold_days", "pqs"]
        ind_cols: list[str] = []
        for t in trades:
            for pfx in ("entry", "exit", "adverse"):
                for k in t.get(f"{pfx}_ind", {}):
                    col = f"{pfx}_{k}"
                    if col not in ind_cols:
                        ind_cols.append(col)
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(base + ind_cols)
            for t in trades:
                row = [t.get(c) for c in base]
                flat = {}
                for pfx in ("entry", "exit", "adverse"):
                    for k, v in t.get(f"{pfx}_ind", {}).items():
                        flat[f"{pfx}_{k}"] = v
                row += [flat.get(c) for c in ind_cols]
                w.writerow(row)
        print(f"wrote {len(trades)} trades × {len(base)+len(ind_cols)} cols → {args.csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
