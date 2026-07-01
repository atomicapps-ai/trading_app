"""cleanup_app — trim the app down to the two live strategies.

KEEPS: momentum_breakout + fear_dip_reversion (configs + scan workflows) and the
core_universe_100 screener. REMOVES: the other strategy configs, their workflows,
and all other screeners. Detector code + the entire video pipeline are left
untouched (the two strategies use a detector whitelist, so old detectors never fire).

Stdlib-only (uses built-in sqlite3) so it runs under any Python — no venv needed.
Dry-run by default; pass --yes to apply. Git-tracked, so reversible with
`git checkout -- strategy_configs workflows`.

    python scripts/cleanup_app.py          # preview
    python scripts/cleanup_app.py --yes     # apply
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "claude_trading_app.db"
SCREENERS_YAML = ROOT / "universe_screeners.yaml"
KEEP_SCREENER = "core_universe_100"
STRATEGY_FILES = ["double_lock.yaml", "swing_momentum.yaml", "video_daily.yaml"]
WORKFLOW_FILES = [
    "double_lock_1030.yaml", "evening_run.yaml", "morning_run.yaml",
    "research_run.yaml", "video_daily_scan.yaml",
]


def main() -> None:
    do = "--yes" in sys.argv
    verb = "DELETING" if do else "would delete"

    print(f"== Files ({verb}) ==")
    targets = ([ROOT / "strategy_configs" / f for f in STRATEGY_FILES]
               + [ROOT / "workflows" / f for f in WORKFLOW_FILES])
    for p in targets:
        if not p.exists():
            print(f"  (missing)  {p.relative_to(ROOT)}")
            continue
        print(f"  {verb}  {p.relative_to(ROOT)}")
        if do:
            p.unlink()

    print(f"\n== Screeners ({verb}; keeping {KEEP_SCREENER}) ==")
    if not DB.exists():
        print(f"  DB not found at {DB} — skipping screener cleanup")
    else:
        con = sqlite3.connect(str(DB))
        try:
            names = [r[0] for r in con.execute("SELECT name FROM universe_presets")]
            for n in names:
                if n == KEEP_SCREENER:
                    print(f"  KEEP  {n}")
                    continue
                print(f"  {verb}  {n}")
                if do:
                    con.execute("DELETE FROM universe_presets WHERE name = ?", (n,))
            if do:
                con.commit()
        except sqlite3.Error as e:
            print(f"  screener cleanup failed: {e}")
        finally:
            con.close()

    # Prune the YAML backup too (optional; harmless if it can't).
    if do and SCREENERS_YAML.exists():
        try:
            import yaml
            d = yaml.safe_load(SCREENERS_YAML.read_text(encoding="utf-8")) or {}
            d["screeners"] = [s for s in d.get("screeners", [])
                              if s.get("name") == KEEP_SCREENER]
            SCREENERS_YAML.write_text(yaml.safe_dump(d, sort_keys=False), encoding="utf-8")
            print("  pruned universe_screeners.yaml backup")
        except Exception as e:                                    # noqa: BLE001
            print(f"  (could not prune YAML backup: {e}; harmless)")

    print("\nDone — restart the app so the scheduler drops the removed workflows."
          if do else "\nPreview only — re-run with --yes to apply.")


if __name__ == "__main__":
    main()
