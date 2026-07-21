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


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stale-days", type=int, default=None)
    a = ap.parse_args()
    from services import db_service
    await db_service.ensure_tables()          # applies the session_key/refreshed_at migration
    before = await db_service.get_pending_count("pending")
    kw = {} if a.stale_days is None else {"stale_days": a.stale_days}
    res = await db_service.dedupe_pending_plans(**kw)
    after = await db_service.get_pending_count("pending")
    print(f"pending before: {before}  ->  after: {after}")
    print(f"removed duplicates: {res['removed_dupes']}   removed stale: {res['removed_stale']}")


if __name__ == "__main__":
    asyncio.run(main())
