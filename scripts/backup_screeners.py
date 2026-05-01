"""scripts/backup_screeners.py — manual screener backup.

Dumps every screener row from SQLite to ``universe_screeners.yaml``
(the git-tracked source of truth for the screener registry).

Normally you don't need to run this — every CRUD mutation on the
screener API auto-exports. Use this only when:
  - You suspect the YAML and DB drifted (e.g. someone hand-edited the
    DB outside the app)
  - You want to confirm the YAML is current before committing

Usage:
    .venv\\Scripts\\python.exe -m scripts.backup_screeners

The companion restore path runs automatically on app startup —
``services.universe_service.import_screeners_from_yaml()`` is called
from the FastAPI lifespan and recreates rows present in the YAML but
missing from the DB. Restore is additive only; it never overwrites.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main() -> None:
    from services import universe_service
    n = await universe_service.export_screeners_to_yaml()
    print(f"Exported {n} screener(s) to {universe_service.SCREENERS_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
