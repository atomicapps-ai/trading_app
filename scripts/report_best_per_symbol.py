"""Report current best_per_symbol from the optimizer DB."""
from __future__ import annotations

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
    rows = optimization_db.fetch_best_per_symbol_table()
    if not rows:
        print("no best_per_symbol rows yet — run scripts/optimize_strategies.py first")
        return 0
    print("=" * 100)
    print(f"{'strategy':<28} {'sym':<5} {'score':>6} {'PF':>5} "
          f"{'WR%':>5} {'N':>4} {'net$':>9}  params")
    print("-" * 100)
    for r in rows:
        print(f"{r['strategy_slug']:<28} {r['symbol']:<5} "
              f"{r['score']:>6.2f} {r['profit_factor']:>5.2f} "
              f"{r['wr_pct']:>5.1f} {r['n_trades']:>4d} "
              f"{r['net_pnl_usd']:>9.0f}  {r['params_json']}")
    print("-" * 100)
    print()
    for r in rows:
        print(f"  {r['strategy_slug']}/{r['symbol']}: {r['selection_rationale']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
