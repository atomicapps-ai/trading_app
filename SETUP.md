# Fresh-machine setup

Getting the app running on a new machine from `main`. The recurring failures
(missing `aiosqlite`, wrong Python, `ib_insync` on 3.14, venv confusion) all
come from the **three things git does NOT carry**. This doc makes a fresh clone
turnkey and lists exactly what each machine has to provide itself.

## TL;DR

```powershell
# Windows
git clone <repo> ; cd trading_app
.\setup.ps1                      # venv + deps + .env seed + import check
# edit .env  (broker + ports)
.\.venv\Scripts\python.exe run.py dev
```

```bash
# macOS / Linux
git clone <repo> && cd trading_app
./setup.sh
# edit .env
.venv/bin/python run.py dev
```

Then open http://127.0.0.1:5000.

> **Always launch with the venv's Python** (`.\.venv\Scripts\python.exe` on
> Windows, `.venv/bin/python` elsewhere). Bare `python` resolves to system
> Python, which does not have the project's dependencies — that is the single
> most common "it worked on the other machine" failure.

## What git carries vs. what each machine provides

| Thing | In git? | How a fresh machine gets it |
|---|---|---|
| Source code | ✅ | `git clone` / `git pull` |
| `requirements.txt` | ✅ | `setup.ps1` / `setup.sh` installs it into `.venv` |
| **`.venv` + installed deps** | ❌ | created by the setup script (never commit a venv) |
| **`.env` (creds, ports, `BROKER_PROVIDER`)** | ❌ (`.env.example` is) | setup seeds it from `.env.example`; then you edit it |
| **SQLite DB** (`data/*.db`) | ❌ | auto-created on first startup; migrations run automatically |
| Active broker selection | ❌ (it's a DB row) | set `BROKER_PROVIDER=ibkr` in `.env` so it's the same on every machine without re-adding an account |
| Bar cache (`data/historical/`) | ❌ | regenerate: `python -m scripts.fetch_fvg_data` (FX/gold), or the app auto-downloads equity bars on first strategy run |
| FVG raw parquet (`data/fx_hist/`) | ❌ | `python -m scripts.fetch_fvg_data` |
| Trade logs (`trade_logs/`) | ❌ | copy across machines if you want to preserve the ML data pool |

## Python version

The app runs on **Python 3.14** (and 3.11/3.12). `ib_insync` needs an event
loop at import time, which 3.14 doesn't auto-create — `brokers/ibkr.py` handles
that, so no action needed. If `setup` picks a Python you don't want, create the
venv explicitly first: `py -3.14 -m venv .venv` (Windows) then re-run setup.

## Broker (IBKR) per machine

IBKR auth is the **local gateway login**, not API keys. On each machine:

1. Run **IB Gateway** (or TWS) and log in to the paper account.
2. In the Gateway: **Configure → Settings → API → Settings**:
   - ✅ Enable ActiveX and Socket Clients
   - Socket port = **4002** (paper Gateway; 4001 live, 7497/7496 for TWS)
   - Add **127.0.0.1** to Trusted IPs (so it doesn't prompt to accept each connection)
   - Read-Only API **off** (to place orders)
3. Set in `.env`: `BROKER_PROVIDER=ibkr`, `IBKR_PORT=4002`, `IBKR_CLIENT_ID=7`.
4. Verify before launching the app:
   ```
   .\.venv\Scripts\python.exe -m scripts.smoke_ibkr
   ```
   Expect `✓ connected`, an account snapshot, and quotes for AAPL / EURUSD / XAUUSD.

## Sanity check that setup worked

```
.\.venv\Scripts\python.exe -c "import aiosqlite, fastapi, uvicorn, pandas, pyarrow, ib_insync; print('OK')"
```
If that prints `OK`, the environment is complete.
