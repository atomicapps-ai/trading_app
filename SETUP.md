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
.\run dev                        # start the app
```

```bash
# macOS / Linux
git clone <repo> && cd trading_app
./setup.sh
# edit .env
./run dev
```

Then open http://127.0.0.1:5000.

> **You don't need to activate the venv or type its Python path.** The `run`
> launcher (`run.cmd` on Windows, `run` on macOS/Linux) always uses the
> project's venv Python. And even if you call `python run.py dev` directly with
> the wrong (system) Python, `run.py` re-execs itself under the venv
> automatically — so the old "it worked on the other machine" failure
> (missing `aiosqlite`, `ib_insync`, …) can't happen anymore.
>
> Commands:
> - Windows PowerShell: `.\run dev`   (the `.\` is required by PowerShell)
> - Windows cmd:        `run dev`
> - macOS / Linux:      `./run dev`
> - `prod` mode + flags pass straight through: `.\run prod --port 8080`

## Source-controlling the config (encrypted)

Instead of hand-editing `.env` on every machine, you can commit it **encrypted**
and decrypt it anywhere with one shared passphrase (kept in a password manager —
it's the only thing not in git):

```
# after editing .env (and/or settings.yaml), bundle + encrypt -> config.enc
python -m scripts.config_crypt encrypt        # then: git add config.enc && commit && push

# on any machine, after git pull:
python -m scripts.config_crypt decrypt         # recreates .env (+ settings.yaml)
```

- Only the encrypted `config.enc` is committed; the plaintext `.env` /
  `settings.yaml` stay gitignored.
- Passphrase comes from `--passphrase`, `$CONFIG_PASSPHRASE`, or a prompt.
- Crypto: Fernet (AES-128-CBC + HMAC) with a scrypt-derived key.
- Tradeoff: committing encrypted secrets means anyone with the repo **and** the
  passphrase can read them — use a strong passphrase, and rotate any credential
  if the passphrase is ever exposed. (For IBKR this is low-stakes: auth is the
  local gateway login, not API keys.)

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
