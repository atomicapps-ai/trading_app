"""find_pending_db.py — locate which SQLite file the pending queue actually lives in.

Symptom this solves: the dedupe script reports a clean DB, but the browser's
/pending queue still shows the same duplicate trades. That means the running app
is reading a *different* .db file than the script cleaned (a second checkout, a
git worktree, or a stray working directory — each has its own data/ folder).

This script does NOT modify anything. It:
  1. prints the absolute DB path the code resolves to (what the app + scripts use),
  2. scans for every *.db file under likely roots,
  3. for each, shows pending_approvals counts by status + the pending symbols,
so you can see exactly which file holds the phantom rows.

    python scripts/find_pending_db.py
    python scripts/find_pending_db.py --root C:\\Projects   # widen the search
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _inspect(db_path: Path) -> None:
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error as exc:  # locked / not a db
        print(f"    (could not open: {exc})")
        return
    try:
        cur = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='pending_approvals'")
        if cur.fetchone() is None:
            print("    no pending_approvals table")
            return
        cur = con.execute(
            "SELECT status, COUNT(*) FROM pending_approvals GROUP BY status ORDER BY status")
        by_status = cur.fetchall()
        if not by_status:
            print("    pending_approvals is empty")
            return
        print("    by status: " + ", ".join(f"{s}={n}" for s, n in by_status))
        cur = con.execute(
            "SELECT strategy, symbol, COUNT(*) c FROM pending_approvals "
            "WHERE status='pending' GROUP BY strategy, symbol ORDER BY c DESC, symbol")
        pend = cur.fetchall()
        if pend:
            print("    PENDING rows (what the queue shows):")
            for strat, sym, c in pend:
                flag = "  <-- DUP" if c > 1 else ""
                print(f"      {str(strat):18} {str(sym):8} x{c}{flag}")
        else:
            print("    0 pending rows")
    finally:
        con.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", action="append", default=None,
                    help="extra directory to scan (repeatable)")
    a = ap.parse_args()

    # Resolve the same path the app uses, WITHOUT importing the app (so this
    # diagnostic works even when deps aren't installed). Mirrors
    # services/settings_service.py: PROJECT_ROOT / "data" / "claude_trading_app.db".
    try:
        from services.settings_service import LOCAL_DB_PATH, PROJECT_ROOT
        resolved = Path(LOCAL_DB_PATH).resolve()
        project_root = Path(PROJECT_ROOT).resolve()
    except Exception as exc:  # deps missing, etc. — fall back to path arithmetic
        print(f"(note: could not import settings_service [{exc}]; using path arithmetic)")
        project_root = Path(__file__).resolve().parent.parent
        resolved = (project_root / "data" / "claude_trading_app.db").resolve()

    print("=" * 70)
    print(f"Code resolves the app/script DB to:\n    {resolved}")
    print(f"    exists: {resolved.exists()}")
    print(f"PROJECT_ROOT: {project_root}")
    print("=" * 70)

    roots = {project_root, Path.cwd().resolve()}
    # walk up a level so sibling checkouts / worktrees are covered
    roots.add(project_root.parent)
    for r in (a.root or []):
        roots.add(Path(r).resolve())

    seen: set[Path] = set()
    found: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for db in root.rglob("*.db"):
            rp = db.resolve()
            if rp in seen or ".venv" in rp.parts:
                continue
            seen.add(rp)
            found.append(rp)

    print(f"\nFound {len(found)} *.db file(s):\n")
    for db in sorted(found):
        marker = "  <== the one the code uses" if db == resolved else ""
        print(f"• {db}{marker}")
        _inspect(db)
        print()

    print("=" * 70)
    print("If a file OTHER than the marked one shows the pending dups, the app is")
    print("running from that directory. Launch the app from the same folder this")
    print("script reports as PROJECT_ROOT, or run dedupe against that DB.")


if __name__ == "__main__":
    main()
