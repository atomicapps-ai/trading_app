"""dedupe_pending.py — one-off cleanup of duplicate / stale pending trade setups.

The old scan inserted a fresh row for the same setup on every refresh (plan_id was
a new uuid each run), so the pending queue piled up identical trades. The scan path
is now dedup-aware; run this once to clean the rows already in the DB.

    python scripts/dedupe_pending.py            # collapse dups + remove stale
    python scripts/dedupe_pending.py --stale-days 1
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow `python scripts/dedupe_pending.py` (not just `python -m scripts.dedupe_pending`)
# by putting the project root on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def _show(db_service) -> None:
    """Print every pending row's setup identity so duplicates are visible."""
    from services import db as _dbmod
    import json
    async with _dbmod.connect() as db:
        import aiosqlite
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT plan_id, strategy, symbol, direction, status, setup_fp, "
            "ts_created, plan_json FROM pending_approvals WHERE status='pending' "
            "ORDER BY strategy, setup_fp, ts_created")
        rows = await cur.fetchall()
    print(f"{len(rows)} pending rows:\n")
    print(f"{'strategy':22} {'fingerprint (symbol|dir|entry|stop|target)':46} {'created':20}")
    for r in rows:
        fp = r["setup_fp"] or db_service._setup_fp(json.loads(r["plan_json"] or "{}"))
        print(f"{r['strategy'][:22]:22} {fp[:46]:46} {str(r['ts_created'])[:19]}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stale-days", type=int, default=None)
    ap.add_argument("--show", action="store_true", help="list pending setups, don't modify")
    a = ap.parse_args()
    from services import db_service
    await db_service.ensure_tables()          # applies the setup_fp/refreshed_at migration
    if a.show:
        await _show(db_service)
        return
    before = await db_service.get_pending_count("pending")
    kw = {} if a.stale_days is None else {"stale_days": a.stale_days}
    res = await db_service.dedupe_pending_plans(**kw)
    after = await db_service.get_pending_count("pending")
    print(f"pending before: {before}  ->  after: {after}")
    print(f"removed duplicates: {res['removed_dupes']}   removed stale: {res['removed_stale']}")


if __name__ == "__main__":
    asyncio.run(main())
