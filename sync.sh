#!/usr/bin/env bash
# sync.sh — bring this machine up to date with origin/main and make it runnable.
# Keep in the repo root, run:  ./sync.sh
# Leaves .env / settings.yaml / data caches untouched (gitignored) — only code + deps.
set -euo pipefail
cd "$(dirname "$0")"

echo "== Syncing to origin/main =="

# 1. Fetch latest
git fetch origin --prune

# 2. Stash local tracked changes so the switch/pull can't be blocked
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "Stashing local tracked changes (restore later: git stash pop)"
  git stash push -m "sync.sh auto-stash"
fi

# 3. Move to main and fast-forward to origin/main
git checkout main 2>/dev/null || git checkout -b main --track origin/main
git pull --ff-only origin main

# 4. Ensure a venv, then refresh dependencies
PY=.venv/bin/python
if [ ! -x "$PY" ]; then
  echo "Creating .venv ..."
  python3 -m venv .venv
fi
"$PY" -m pip install --upgrade pip >/dev/null
"$PY" -m pip install -r requirements.txt

# 5. Seed .env on a fresh machine (never overwrites an existing one)
if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env
  echo "Created .env from example - set BROKER_PROVIDER=ibkr and IBKR_PORT=4002."
fi

# 6. Verify + show where we landed
"$PY" -c "import aiosqlite, fastapi, uvicorn, pandas, pyarrow, ib_insync; print('core imports OK')"
echo -n "Now at: "; git log --oneline -1

echo ""
echo "Synced. Start the app:  .venv/bin/python run.py dev"
