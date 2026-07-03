#!/usr/bin/env bash
# setup.sh — one-command bootstrap for a fresh machine (macOS/Linux).
# Creates the venv, installs ALL deps into it, seeds .env, verifies core imports.
#
#   ./setup.sh
#   .venv/bin/python run.py dev
set -euo pipefail
cd "$(dirname "$0")"

echo "== TradeAgent setup =="

# 1. venv — create if missing
if [ ! -x .venv/bin/python ]; then
  echo "Creating .venv ..."
  python3 -m venv .venv
fi
PY=.venv/bin/python
"$PY" --version

# 2. dependencies — into the venv
echo "Installing dependencies ..."
"$PY" -m pip install --upgrade pip >/dev/null
"$PY" -m pip install -r requirements.txt

# 3. .env — seed from example if absent (never overwrite an existing one)
if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env
  echo "Created .env from .env.example — EDIT IT with your creds/ports."
fi

# 4. verify the imports that break a half-set-up environment
"$PY" -c "import aiosqlite, fastapi, uvicorn, pandas, pyarrow, ib_insync; print('core imports OK')"

echo ""
echo "Setup complete."
echo "Start the app:   .venv/bin/python run.py dev"
echo "FVG data (once): .venv/bin/python -m scripts.fetch_fvg_data"
