"""inspect_top_archetype.py — re-run the #1 OOS-robust trial and inspect
its actual trade ledger (long/short split, MFE/MAE, etc.).

Pulls the top OOS row from random_search_trials, re-builds the same config,
re-runs the meta_strategy detector and trade simulator, and prints a
detailed breakdown.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")                            # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from agents.detectors.external import meta_strategy
from agents.detectors.external._base import simulate_trades
from services import optimization_db


def load_bars(symbol: str, interval: str = "1d") -> pd.DataFrame:
    p = ROOT / "data" / "historical" / f"{symbol}_{interval}.csv"
    df = pd.read_csv(p, index_col=0, parse_dates=True)
    df.columns = [c.strip().lower() for c in df.columns]
    if "adj_close" in df.columns and "close" in df.columns:
        df["close"] = df["adj_close"]
    df = df[[c for c in ["open","high","low","close","volume"] if c in df.columns]].dropna()
    df.index = pd.to_datetime(df.index, utc=True)
    return df.sort_index()


def main() -> int:
    optimization_db.ensure_schema()
    with sqlite3.connect(optimization_db.DB_PATH) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute("""
            SELECT * FROM random_search_trials
            WHERE n_trades >= 30 AND profit_factor > 1.5
              AND oos_score > 0 AND ABS(is_oos_gap_pct) <= 0.5
            ORDER BY oos_score DESC LIMIT 5
        """).fetchall()
    if not rows:
        print("no eligible rows yet")
        return 0
    for rank, r in enumerate(rows, 1):
        cfg = json.loads(r["meta_config_json"])
        sym = r["symbol"]
        print(f"\n{'=' * 78}")
        print(f"#{rank} ARCHETYPE — {sym} · OOS={r['oos_score']:.2f} IS={r['is_score']:.2f}")
        print(f"  entry={cfg['entry_primitive']}  stop={cfg['stop_type']}  tp={cfg['tp_type']}")
        print(f"  regime_filters={cfg['regime_filters']}  vol={cfg['use_volume_filter']}  "
              f"long_only={cfg.get('long_only', False)}")
        print(f"{'-' * 78}")

        bars = load_bars(sym)
        sigs = meta_strategy.detect(bars, cfg)
        trades = simulate_trades(bars, sigs)
        if not trades:
            print("  (no trades after re-run)")
            continue

        n = len(trades)
        longs = [t for t in trades if t.direction == "long"]
        shorts = [t for t in trades if t.direction == "short"]
        wins = [t for t in trades if t.win]
        losses = [t for t in trades if not t.win]
        win_long = len([t for t in longs if t.win])
        win_short = len([t for t in shorts if t.win])
        exit_reasons = Counter(t.exit_reason for t in trades)

        print(f"  total trades: {n}")
        print(f"    LONG : {len(longs):>3d}  ({win_long}/{len(longs)} wins, "
              f"{100*win_long/max(len(longs),1):.0f}% WR)")
        print(f"    SHORT: {len(shorts):>3d}  ({win_short}/{len(shorts)} wins, "
              f"{100*win_short/max(len(shorts),1):.0f}% WR)")
        print(f"  exit reasons: {dict(exit_reasons)}")
        avg_w = sum(t.pnl_pct for t in wins) / max(len(wins), 1) * 100
        avg_l = sum(t.pnl_pct for t in losses) / max(len(losses), 1) * 100
        print(f"  avg win:  {avg_w:+.2f}%   avg loss: {avg_l:+.2f}%")
        print(f"  avg bars held: {sum(t.bars_held for t in trades) / n:.1f}")

        # First 3 + last 3 trades for sanity
        print(f"  first 3 trades:")
        for t in trades[:3]:
            print(f"    {t.entry_ts.strftime('%Y-%m-%d')} {t.direction:>5s} "
                  f"entry={t.entry_price:.2f} stop={t.stop_price:.2f} "
                  f"exit={t.exit_price:.2f} pnl={t.pnl_pct*100:+.2f}% ({t.exit_reason})")
        print(f"  last 3 trades:")
        for t in trades[-3:]:
            print(f"    {t.entry_ts.strftime('%Y-%m-%d')} {t.direction:>5s} "
                  f"entry={t.entry_price:.2f} stop={t.stop_price:.2f} "
                  f"exit={t.exit_price:.2f} pnl={t.pnl_pct*100:+.2f}% ({t.exit_reason})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
