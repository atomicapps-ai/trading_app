"""reset_trade_history.py — purge closed/historical trades, keep the live book.

The closed-trade journal accumulated while the close-recording path was broken,
so those rows are noise and skew the /trades summary + strategy ranking. This
clears the closed history everywhere it lives:

  * trade_logs/*.jsonl          — the JSONL journal
  * trade_memory (SQLite)       — the ML pool
  * pending_approvals status='closed'

**Open / executed / approved plans are LEFT INTACT** — they are your active
trades and the only valid history going forward.

Safe by default: prints what it WOULD delete and exits. Pass --yes to do it.

    python -m scripts.reset_trade_history          # dry run (counts only)
    python -m scripts.reset_trade_history --yes     # actually delete
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow running by path as well as -m.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import db_service  # noqa: E402
from services.settings_service import TRADE_LOG_DIR  # noqa: E402


def _jsonl_line_count() -> tuple[int, int]:
    """(files, total non-blank lines) currently in the JSONL journal."""
    files = list(TRADE_LOG_DIR.glob("*.jsonl")) if TRADE_LOG_DIR.exists() else []
    lines = 0
    for p in files:
        try:
            lines += sum(1 for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip())
        except Exception:  # noqa: BLE001
            pass
    return len(files), lines


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="actually delete (default: dry run)")
    args = ap.parse_args()

    await db_service.ensure_tables()

    n_files, n_lines = _jsonl_line_count()
    n_mem = len(await db_service.list_trade_memory(limit=1_000_000))
    n_closed = await db_service.count_closed_plans()

    print("Closed/historical trades to remove (open trades are kept):")
    print(f"  JSONL journal   : {n_lines} records across {n_files} file(s)")
    print(f"  trade_memory    : {n_mem} rows")
    print(f"  closed plans    : {n_closed} rows (pending_approvals status='closed')")

    if not args.yes:
        print("\nDry run — nothing deleted. Re-run with --yes to purge.")
        return

    # 1) JSONL journal — remove the monthly files (keep the dir + .gitkeep).
    removed_files = 0
    if TRADE_LOG_DIR.exists():
        for p in TRADE_LOG_DIR.glob("*.jsonl"):
            try:
                p.unlink()
                removed_files += 1
            except Exception as e:  # noqa: BLE001
                print(f"  ! could not delete {p.name}: {e}")

    # 2) trade_memory table
    mem_deleted = await db_service.clear_trade_memory()

    # 3) closed pending_approvals rows
    plans_deleted = await db_service.delete_closed_plans()

    print("\nDone.")
    print(f"  JSONL files removed : {removed_files}")
    print(f"  trade_memory rows   : {mem_deleted}")
    print(f"  closed plans        : {plans_deleted}")
    print("\nOpen/executed/approved plans were left intact. /trades now reflects "
          "only your active book (closed history starts fresh).")


if __name__ == "__main__":
    asyncio.run(main())
