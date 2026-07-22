# Handoff: kill the duplicate pending trades — for real this time

You have **full local access** to `C:\Projects\trading_app` (repo
`atomicapps-ai/trading_app`). A previous session (remote sandbox, no access to my
machine's DB) tried to fix this five times and couldn't close it out because it
could never see my actual database. That's your advantage — **you can.** Don't
trust any prior conclusion; verify everything against the live DB on disk.

## The symptom (still happening right now)

The `/pending` queue in the browser shows **9 duplicate trades**: HON, FCX, GM —
each `macd_run`, each appearing **3 times**. Every time I hit "refresh"/run a scan,
the same setups pile up again. I want: if a setup already exists and is still
valid, just update its refresh timestamp; if it's stale, remove it; never insert a
duplicate.

## What's already been built (on `main`, verify it's actually present)

The dedup logic already exists and looks correct in isolation:

- `services/db_service.py`:
  - `upsert_pending_plan(...)` dedups on a fingerprint `setup_fp` = `"{SYMBOL}|{direction}"`
    (one live row per strategy+symbol+direction, ignoring per-scan entry-price drift),
    scoped by status. Stale+pending → delete; valid existing → update `refreshed_at`;
    new+stale → skip; else insert.
  - `dedupe_pending_plans(stale_days=2, statuses=("pending","rejected","blocked"))`
    collapses existing dups, keeps newest, backfills legacy `setup_fp`/`session_key`.
  - `STALE_PENDING_DAYS = 2`; `_setup_fp(plan)` returns `f"{SYMBOL}|{direction}"`.
- `scripts/dedupe_pending.py` — one-off cleanup. `--show` lists all rows by
  `(status, strategy, fingerprint)` with a DUP flag. `--stale-days N`.
- `scripts/find_pending_db.py` — read-only diagnostic (pure stdlib): prints the DB
  path the code resolves to and scans every `*.db` under PROJECT_ROOT / its parent /
  cwd, showing pending rows per file.
- Scans call `dedupe_pending_plans()` as a final stage in
  `services/refresh_scan_service.py` and `services/fvg_scan_service.py`.

## The leading hypothesis — TEST IT FIRST

When I ran `.\.venv\Scripts\python.exe -m scripts.dedupe_pending --show`, the DB the
**script** sees had **zero pending rows** and its `macd_run` rows were for entirely
different symbols (KMI/PSX/XOM/AKAM/SO) — **no HON/FCX/GM anywhere**. Yet the browser
still shows 9 HON/FCX/GM pending. That mismatch means **the running app is reading a
different `.db` file than the dedupe script cleaned** — most likely the app is being
launched from a **git worktree or a second checkout**, each with its own
`data/claude_trading_app.db`.

**Step 1 — prove which file the app actually uses.** Don't reason about it, observe it:

```powershell
cd C:\Projects\trading_app
.\.venv\Scripts\python.exe -m scripts.find_pending_db
```

Find the `.db` whose PENDING rows list `HON/FCX/GM macd_run`. That file is where the
running app lives. Cross-check: look at how I'm actually starting the server (which
folder, is it a `git worktree list` entry?), and confirm its working directory
resolves `PROJECT_ROOT/data/claude_trading_app.db` to that same file.

Also confirm the process is even restarted after code changes — a long-running
`python run.py` won't pick up new dedup code until relaunched.

## If the hypothesis is wrong

If `find_pending_db` shows the dups ARE in the same DB the code resolves to, then the
dedup path has a real bug that only reproduces against my data. In that case:

1. Reproduce directly: run the scan that regenerates these (`refresh_scan_service` /
   the `/pending` refresh endpoint) against the live DB and watch row count.
2. Instrument `upsert_pending_plan` — log the computed `setup_fp`, the lookup query,
   and which branch (insert/update/delete) it takes for HON/FCX/GM. Likely suspects:
   `setup_fp` computed differently at write vs. lookup (direction casing, missing
   column on an un-migrated DB so `setup_fp` is NULL), the migration not having run
   on this DB, or the 3 rows differing in `status` so they're never collapsed.
3. Check the `/pending` template/route isn't rendering rows the query wouldn't (e.g.
   showing `rejected`/`blocked` in the "pending" tab).

Please use `systematic-debugging`: reproduce → confirm the exact row state in SQLite
(`SELECT plan_id, strategy, symbol, status, setup_fp, session_key, refreshed_at,
ts_created FROM pending_approvals WHERE symbol IN ('HON','FCX','GM')`) → form one
hypothesis → fix → re-run the scan twice and prove the count stays flat → clean up
existing dups with `dedupe_pending`.

## Definition of done

- After running a scan **twice in a row**, HON/FCX/GM show **one row each** (3 total,
  not 9), and existing dups are cleaned.
- The `refreshed_at` on a still-valid setup updates in place on re-scan; a stale one
  (past its `entry.valid_until`/`time_stop.deadline`, or older than
  `STALE_PENDING_DAYS`) is removed.
- The browser `/pending` queue matches the DB (hard-refresh, correct DB, app
  restarted).

## Working agreements (please follow)

- Edit directly in the repo root so I can test before any branch. Only branch/commit/
  push when I say so. Branch names: feature-tied (`fix/pending-dup-db-path`), not
  auto-generated. All updates land on `main`; delete the branch after merge.
- Never commit secrets (`.env`, `settings.yaml`, `config.enc`, `~/.cloudflared/*`).
- App base URL is `https://app.tindex.ai` (Cloudflare tunnel); `http://localhost:5000`
  on the box. `python -m scripts.app_url` prints whichever is reachable.
- Read `CLAUDE.md` first, then `HANDOFF.md`. IBKR paper is the broker; the app runs
  on Python 3.14 via `.\run dev`.

Start with `find_pending_db`. The answer is almost certainly "the app is running out
of a different folder than the one I've been cleaning." Prove it, fix the launch (or
the bug), and make a double-scan leave 3 rows.
