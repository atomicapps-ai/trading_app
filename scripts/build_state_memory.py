"""scripts/build_state_memory.py — build a FAISS index over cached bars.

Iterates every {SYM}_{INTERVAL}.csv in data/historical/, encodes per-bar
8-dim feature vectors, computes 1h/4h/1d/5d forward-return labels, and
writes a FAISS IndexFlatL2 + parquet sidecar + scaler to
data/state_memory/{INTERVAL}/.

Run separately per interval:
    python scripts/build_state_memory.py --interval 30m
    python scripts/build_state_memory.py --interval 15m

Optional --screener limits to a named screener's tickers (otherwise
every cached CSV at that interval is included).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services import state_memory_service, universe_service  # noqa: E402


async def _resolve_symbols(screener: str | None) -> list[str] | None:
    if screener is None:
        return None
    preset = await universe_service.get_preset_db(screener)
    if preset is None:
        raise SystemExit(f"screener {screener!r} not found")
    tickers = preset.get("tickers") or []
    if not tickers:
        raise SystemExit(f"screener {screener!r} has no tickers")
    return list(tickers)


async def main_async() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", required=True, choices=["5m", "15m", "30m", "1h"])
    ap.add_argument("--screener", default=None,
                    help="optional screener name; defaults to all CSVs at this interval")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    symbols = await _resolve_symbols(args.screener)

    t0 = time.time()
    sm = state_memory_service.build_index(args.interval, symbols=symbols)
    elapsed = time.time() - t0

    print(f"\nDONE — {sm.size:,} vectors, {len(sm.metadata):,} sidecar rows "
          f"in {elapsed:.1f}s")
    print(f"  index:    {state_memory_service.interval_dir(args.interval) / 'index.faiss'}")
    print(f"  metadata: {state_memory_service.interval_dir(args.interval) / 'metadata.parquet'}")
    print(f"  scaler:   {state_memory_service.interval_dir(args.interval) / 'scaler.npz'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
