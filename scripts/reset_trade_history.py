"""reset_trade_history.py — clean-slate the realized-P&L history.

The realized-P&L journal accumulated while the close-recording path was broken
(and while the IBKR balance was inflated), so those numbers are noise. This
clears the fake realized history:

  * trade_logs/*.jsonl          — the JSONL journal
  * trade_memory (SQLite)       — the ML pool

**Scan setups in ``pending_approvals`` are KEPT** — every setup the scanner
produced stays as a searchable, backtestable archive (see /signals). Pair this
with an IBKR paper reset to $1M for a true clean slate.

Options:
  --drop-plans   ALSO wipe every pending_approvals row (nuclear — you lose the
                 scan archive too). Off by default.

Safe by default: prints what it WOULD delete and exits. Pass --yes to do it.

    python -m scripts.reset_trade_history               # dry run (counts only)
    python -m scripts.reset_trade_history --yes          # clear realized P&L, keep setups
    python -m scripts.reset_trade_history --yes --drop-plans   # also wipe scan archive
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
    ap.add_argument("--drop-plans", action="store_true",
                    help="ALSO wipe every pending_approvals row (loses the scan archive)")
    args = ap.parse_args()

    await db_service.ensure_tables()

    n_files, n_lines = _jsonl_line_count()
    n_mem = len(await db_service.list_trade_memory(limit=1_000_000))
    n_plans = len(await db_service.get_pending_plans(status_filter=None, limit=1_000_000))

    print("Clean-slate the realized-P&L history:")
    print(f"  JSONL journal   : {n_lines} records across {n_files} file(s)  → CLEARED")
    print(f"  trade_memory    : {n_mem} rows  → CLEARED")
    if args.drop_plans:
        print(f"  scan setups     : {n_plans} rows  → DELETED (--drop-plans)")
    else:
        print(f"  scan setups     : {n_plans} rows  → KEPT (searchable archive at /signals)")

    if not args.yes:
        print("\nDry run — nothing deleted. Re-run with --yes to apply.")
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

    # 3) scan setups — kept unless explicitly dropped
    plans_deleted = await db_service.delete_all_plans() if args.drop_plans else 0

    print("\nDone.")
    print(f"  JSONL files removed : {removed_files}")
    print(f"  trade_memory rows   : {mem_deleted}")
    if args.drop_plans:
        print(f"  scan setups deleted : {plans_deleted}")
    else:
        print("  scan setups kept    : searchable + backtestable at /signals")
    print("\nRealized-P&L history is now empty. Reset the IBKR paper account to "
          "$1,000,000 in the Client Portal for the full clean slate.")


if __name__ == "__main__":
    asyncio.run(main())
