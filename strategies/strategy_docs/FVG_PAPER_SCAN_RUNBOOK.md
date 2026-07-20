# FVG-continuation (gold + FX) — paper-scan runbook

**Status:** setup is **code-complete**. The scan detects gold, builds a TradePlan,
runs both hard gates (compliance C1–C8 → risk R1–R9), and queues gated plans to
`/pending`. Gold (`XAUUSD`) is the first symbol scanned. Verified end-to-end on cached
data (a gold setup fires and reaches the gates; it only shows "unsized" here because the
sandbox has no account equity).

The scan is **broker-agnostic for detection** but needs two things from a live
connection to queue a *real* paper plan:
1. **Account equity** — position sizing needs an account with equity (your IBKR paper
   account). Without it every setup returns `unsized`.
2. **Fresh 30m bars** — the scan reads `data/historical/{SYM}_30m.csv`; a live run tops
   these up from IBKR so "today" sees the current NY session (else setups show `stale`).

Both are satisfied by connecting the **IBKR paper account** — nothing else to build.

## ▶ RUN THIS (on your machine, once IBKR Gateway/paper is up)

1. Start the app and confirm the broker dot is green:
   ```
   python run.py dev          # http://localhost:5000
   ```
   Broker page (`/broker`) → IBKR paper connected, equity showing.

2. Trigger the scan (either way):
   - **UI:** open `/strategies`, find **fvg_continuation**, click **▶ Run**.
   - **CLI:**
     ```
     curl -X POST "http://localhost:5000/api/strategies/fvg_continuation/run?mode=paper"
     ```

3. The scan evaluates the latest completed NY session for **XAUUSD + 9 FX majors**,
   refreshes their 30m bars from IBKR, runs the gates, and queues any fresh setup to
   **`/pending`**. Review/approve there (human-ack) exactly like the equity strategies.

## Notes
- It evaluates the **latest completed** session — during the NY window intraday it will
  show the prior session until the current one closes. Run it after ~16:00 ET, or on a
  schedule (below).
- `FRESHNESS_DAYS = 4`: a setup older than 4 days is shown as a stale preview, not queued
  — prevents a stale cache from queuing a week-old entry.
- **Optional auto-scan:** it currently runs on manual **▶ Run**. If you want it to fire
  automatically each session, say the word and I'll wire a dormant scheduler job
  (commented schedule) so it's one flip from auto — no live orders until you approve
  each plan in `/pending` regardless.

## What is NOT yet done (needs your go-ahead, live money)
- Auto-schedule (optional, above).
- Live (non-paper) trading — requires flipping mode to `live` + the standing human-ack
  gate on every order. Not in scope until you decide gold has paper-traded cleanly.
