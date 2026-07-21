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
    """Print every pending_approvals row (ALL statuses) by status + fingerprint,
    so duplicates are visible wherever they live."""
    from services import db as _dbmod
    from collections import Counter
    import aiosqlite, json
    async with _dbmod.connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT strategy, symbol, status, setup_fp, ts_created, plan_json "
            "FROM pending_approvals ORDER BY status, strategy, setup_fp, ts_created")
        rows = await cur.fetchall()
    by_status = Counter(r["status"] for r in rows)
    print(f"{len(rows)} total rows in pending_approvals — by status: {dict(by_status)}\n")
    # count duplicates per (status, strategy, fingerprint)
    keyed = Counter()
    for r in rows:
        fp = r["setup_fp"] or db_service._setup_fp(json.loads(r["plan_json"] or "{}"))
        keyed[(r["status"], r["strategy"], fp)] += 1
    print(f"{'status':10} {'strategy':20} {'fingerprint':40} {'count':>5}")
    for (st, strat, fp), n in sorted(keyed.items(), key=lambda x: -x[1]):
        flag = "  <-- DUP" if n > 1 else ""
        print(f"{st[:10]:10} {strat[:20]:20} {fp[:40]:40} {n:>5}{flag}")


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
