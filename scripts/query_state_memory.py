"""scripts/query_state_memory.py — kNN against the bar-state matrix.

Two query modes:

  Latest bar mode:
    python scripts/query_state_memory.py --interval 30m --symbol NVDA

  Historical-as-of mode:
    python scripts/query_state_memory.py --interval 30m --symbol NVDA \
        --as-of "2024-09-15 13:30Z" --k 100

Prints:
  · the encoded query vector (raw + standardized)
  · the top-k nearest historical bars (symbol, ts, distance)
  · aggregate forward-return stats (mean / median / hit-rate at each horizon)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.state_memory import encoder, labeler  # noqa: E402
from services import state_memory_service  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", required=True, choices=["5m", "15m", "30m", "1h"])
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--as-of", default=None,
                    help="ISO timestamp; default = latest cached bar")
    ap.add_argument("--k", type=int, default=50)
    ap.add_argument("--top", type=int, default=15,
                    help="how many neighbor rows to print")
    args = ap.parse_args()

    sm = state_memory_service.load_index(args.interval)
    print(f"loaded index: {sm.size:,} vectors at {args.interval}\n")

    if args.as_of is None:
        # Use the most recent bar in the index for this symbol as anchor.
        meta = sm.metadata
        sym_rows = meta[meta["symbol"] == args.symbol.upper()]
        if sym_rows.empty:
            raise SystemExit(f"no rows in index for {args.symbol!r}; "
                             f"is it in the universe used at build time?")
        as_of_ts = pd.Timestamp(sym_rows["ts"].max())
    else:
        as_of_ts = pd.Timestamp(args.as_of)

    qvec = state_memory_service.encode_state_for(args.symbol, args.interval, as_of_ts)

    print(f"query: {args.symbol} @ {as_of_ts}")
    raw_str = " ".join(f"{name}={qvec[i]:+.3f}" for i, name in enumerate(encoder.FEATURE_NAMES))
    print(f"  raw features: {raw_str}\n")

    # Run the kNN query, ask for one extra so we can drop self-matches.
    neighbors = state_memory_service.query(sm, qvec, k=args.k + 1)
    self_mask = (
        (neighbors["symbol"] == args.symbol.upper())
        & (pd.to_datetime(neighbors["ts"], utc=True) == as_of_ts.tz_convert("UTC"))
    )
    if self_mask.any():
        neighbors = neighbors[~self_mask].reset_index(drop=True)
        neighbors["rank"] = range(len(neighbors))
    neighbors = neighbors.head(args.k).copy()

    print(f"top {min(args.top, len(neighbors))} neighbors:")
    print(neighbors.head(args.top).to_string(index=False, float_format=lambda x: f"{x:+.4f}"))
    print()

    print("aggregate forward-return stats across all k neighbors:")
    for h in labeler.HORIZONS:
        col = neighbors[h].dropna()
        if col.empty:
            print(f"  {h}: (no labeled neighbors)")
            continue
        mean = col.mean()
        median = col.median()
        hit_rate = (col > 0).mean()
        print(f"  {h}: mean={mean:+.3%}  median={median:+.3%}  "
              f"hit_rate={hit_rate:.1%}  n={len(col)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
