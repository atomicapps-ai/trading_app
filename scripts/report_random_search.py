"""Report top trials + distribution from random_search_trials."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")                            # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services import optimization_db


def main() -> int:
    optimization_db.ensure_schema()
    db = optimization_db.DB_PATH
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        # Total
        n_total = c.execute("SELECT COUNT(*) FROM random_search_trials").fetchone()[0]
        n_eligible = c.execute(
            "SELECT COUNT(*) FROM random_search_trials "
            "WHERE n_trades >= 30 AND profit_factor > 1.0"
        ).fetchone()[0]
        n_oos_robust = c.execute(
            "SELECT COUNT(*) FROM random_search_trials "
            "WHERE n_trades >= 30 AND profit_factor > 1.0 "
            "AND oos_score > 0 AND ABS(is_oos_gap_pct) <= 0.5"
        ).fetchone()[0]

        print(f"random_search_trials: {n_total:,} total, "
              f"{n_eligible:,} eligible (PF>1, N>=30), "
              f"{n_oos_robust:,} OOS-robust")
        print()

        # Per-symbol counts
        print("Per-symbol coverage:")
        rows = c.execute("""
            SELECT symbol, COUNT(*) AS n,
                   ROUND(AVG(score), 2) AS avg_score,
                   ROUND(MAX(score), 2) AS max_score
            FROM random_search_trials GROUP BY symbol ORDER BY symbol
        """).fetchall()
        for r in rows:
            print(f"  {r['symbol']:5s}  n={r['n']:>5d}  "
                  f"avg_score={r['avg_score']:>5}  max={r['max_score']:>5}")
        print()

        # Top 15 by OOS score
        print("Top 15 OOS-robust trials (PF>1.5, N>=30, oos_score>0, gap<=50%):")
        rows = c.execute("""
            SELECT symbol, entry_primitive, stop_type, tp_type,
                   regime_filter_count, uses_volume_filter,
                   n_trades, wr_pct, profit_factor, net_pnl_usd,
                   score, is_score, oos_score, is_oos_gap_pct,
                   meta_config_json
            FROM random_search_trials
            WHERE n_trades >= 30 AND profit_factor > 1.5
              AND oos_score > 0
              AND ABS(is_oos_gap_pct) <= 0.5
            ORDER BY oos_score DESC LIMIT 15
        """).fetchall()
        if not rows:
            print("  (none yet)")
        for r in rows:
            print(f"  {r['symbol']:5s}  e={r['entry_primitive']:<15s} "
                  f"stop={r['stop_type']:<13s} tp={r['tp_type']:<18s} "
                  f"rf={r['regime_filter_count']} v={r['uses_volume_filter']} "
                  f"N={r['n_trades']:>3d}  WR={r['wr_pct']:>5.1f}  "
                  f"PF={r['profit_factor']:>5.2f}  "
                  f"IS={r['is_score']:>5.2f} OOS={r['oos_score']:>5.2f}")
        print()

        # Entry primitive ranking
        print("Mean / median score by entry primitive (eligible trials only):")
        rows = c.execute("""
            SELECT entry_primitive, COUNT(*) AS n,
                   ROUND(AVG(score), 3) AS avg_score,
                   ROUND(AVG(profit_factor), 2) AS avg_pf
            FROM random_search_trials
            WHERE n_trades >= 30
            GROUP BY entry_primitive ORDER BY avg_score DESC
        """).fetchall()
        for r in rows:
            print(f"  {r['entry_primitive']:<18s}  n={r['n']:>4d}  "
                  f"avg_score={r['avg_score']:>5}  avg_PF={r['avg_pf']:>5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
