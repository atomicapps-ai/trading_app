# Tomorrow's Trading Prep — 2026-04-30

Read order: **CLAUDE.md** → **HANDOFF.md** → this file.

This is a focused operational doc for getting the DL strategy ready for
tomorrow's 10:00 ET scout + 10:30 ET fire. **Not a code roadmap.**

---

## Reality check first

VIX as of 2026-04-29 close: **18.81** (regime gate floor: 20.0).

Unless VIX **closes ≥ 20 today** (after-hours moves push it on Globex),
DL will **correctly fire 0 signals tomorrow**. The strategy is designed
to sit on its hands in low-vol regimes — not a bug. Replay validation
this session: 80% WR / +5.52% across March-April when VIX cleared 20.

What you'll most likely see tomorrow:
- ✅ 10:00 ET — Lock 1 scout fires, scans, writes 0 `lock1_scouted`
  rows because the regime check fails.
- ✅ 10:30 ET — DL workflow fires, 5-symbol shortlist runs through the
  intraday analyst, 0 signals (VIX < 20 → regime gate blocks).
- 🔕 Phone — quiet (no push because no alerts written).
- 📊 Dashboard — alerts banner stays empty.

That's the right outcome. The thing to verify is that **everything is
wired to fire if the regime were to clear**, not that something fires
today.

---

## Tonight (before bed)

### 1. Cancel the lingering paper order from today's smoke
[scripts/smoke_alpaca_order_roundtrip.py](scripts/smoke_alpaca_order_roundtrip.py)
placed a BUY 1 SPY market order during this session that didn't fill
(market was closed). Clean it up so tomorrow's account starts neutral.

```
.venv\Scripts\python.exe -c "import asyncio; from brokers.alpaca import AlpacaAdapter; a=AlpacaAdapter(paper=True); asyncio.run((async lambda: (await a.connect(), await a.cancel_all_orders()))())"
```

Or just hit the **HALT** button on `/broker` (it calls cancel_all_orders).
Verify on the Broker page → Open orders panel is empty.

### 2. Subscribe to ntfy on your phone (if not done already)
- Install **ntfy** (binwiederhier) from App Store / Play Store.
- Tap **+** → topic `trading-agent-julius` → server `https://ntfy.sh`.
- Test from PowerShell:
  ```
  Invoke-RestMethod -Method POST http://127.0.0.1:5000/api/alerts/test
  ```
- Tap the notification → it should deep-link to the app's pending page.

### 3. Start the server in prod mode + leave it running
```
.venv\Scripts\python.exe run.py prod
```
Or for phone access on your local Tailnet (note: cellular/away-from-home
deferred to a future session):
```
.venv\Scripts\python.exe run.py prod --host 0.0.0.0
```
**Don't let the machine sleep.** Open Settings → Power & sleep → Screen:
Never / Sleep: Never (or at least until 11:00 ET tomorrow).

### 4. Pre-flight check — `/system-health`
Open `http://localhost:5000/system-health` and confirm:
- Top banner = green **OK**
- Scheduler = running, job_count ≥ 6 (workflows + DL Lock 1 scout + ct_poll
  + senate_daily_diff)
- Broker = `alpaca_paper` connected, equity ≈ $99,999.96
- Data freshness — both SPY + AAPL on 30m + 1d, ages < 50h. **If anything
  is stale, the data_service cache needs a refresh.**
- Errors panel = 0

### 5. Confirm tomorrow's crons are scheduled
On `/jobs`, find these two rows and verify their **next-run-time is
2026-04-30**:
- `dl_lock1_scout` — should show `0 10 * * 1-5` (10:00 ET Mon-Fri)
- `wf_double_lock_1030` — should show `30 10 * * 1-5` (10:30 ET Mon-Fri)

If either is missing or shows a stale next-run, the scheduler hasn't
picked up its config. Restart the server.

---

## Tomorrow morning (before 9:55 ET)

### 1. Reopen the dashboard
Confirm the server is still running (browser reaches it; account values
populate). If the machine slept overnight, the scheduler may have missed
the registration window — restart and re-check `/jobs`.

### 2. Open `/today`
This page is the trading cockpit. You'll see:
- **DL gate banner** at the top — should reflect today's VIX
- Pending approvals — empty
- Open positions — should be empty (assuming you canceled last night's
  smoke order)
- Jobs firing today — should list both `dl_lock1_scout` and
  `wf_double_lock_1030` with their next-fire times

Auto-refreshes every 30s. Leave it open through the 9:30-10:30 ET window.

### 3. At 10:00 ET — verify the scout fires
On the dev server log (or in `/jobs/dl_lock1_scout` → Logs tab) you
should see lines like:
```
Lock1 scout: 5 symbols, 0 candidates (VIX 18.81 < 20 — regime block)
```
Or, if VIX cleared 20:
```
Lock1 scout: 5 symbols, 2 candidates  (VIX 21.4)
  AAPL LONG c1=BULL.STR.HPRS.HVOL ...
```

### 4. At 10:30 ET — verify the fire
Watch the log + `/jobs/wf_double_lock_1030`. Expected lines:
```
Scheduled workflow run: double_lock_1030
analyze: dispatching to intraday analyst (strategy=double_lock)
analyze: 5 symbols scanned, 0 symbols emitted signals (0 total)
plan: no signals from analyze step — nothing to do
Workflow double_lock_1030 complete: ok
```
The "dispatching to intraday analyst" line is the proof the integration
fix from this session is taking effect.

### 5. If a signal DOES fire (regime cleared)
- Phone push arrives within ~2s — title like "AAPL LONG — double_lock
  ARMED", deep-links to `/pending/{plan_id}`.
- Banner appears on dashboard with the alert.
- Open the pending page on the phone or desktop.
- Review the trade plan: entry / stop / TPs / sizing / regime evidence.
- Click **Approve** → executioner places a real Alpaca paper order →
  `close_at_time` schedules the 15:00 ET exit job.
- Watch Today / Broker pages for the fill.

### 6. End of day verification
Even if no trades fired:
- `/system-health` still green
- `dl_alerts` table has 0 new rows (or some if regime cleared)
- `pipeline_runs` has rows for today's `wf_double_lock_1030` (status=ok)

---

## What to flag back to me when I'm next on

- Did the scout fire on time?
- Did the workflow run produce a clean log line saying
  `dispatching to intraday analyst`?
- Did anything break that needed a manual intervention?
- If a signal fired: did the full ack → fill → close cycle work?
- What's the remaining concern for the Phase 5 backtest engine work?

---

## Known deferred items (do NOT block tomorrow)

| Item | Status | Why deferred |
|---|---|---|
| Phone access over the public internet | Tailscale Funnel / Cloudflare Tunnel — not yet wired | User shelved tonight |
| Multi-account paper UI | Single Alpaca key pair only | 1-2 day build, not urgent |
| Hard-delete 9 swing detectors + swing_momentum.yaml | They sit in `In Progress` bucket on `/strategies/in-progress` | Slice C, separate session |
| Pine codegen from YAML | Strategy `Pine` tab is placeholder | Bigger spec, separate session |
| Console / SSE log stream | Sidebar entry removed; server logs viewable via `/jobs/{id}` Logs tab | Phase 7 |
| Favorites independent watchlist | `/favorites` is a placeholder | Wireframed only |
| Strategy detail page (per-strategy `/strategies/{name}`) | Not built; cards on bucket page show summary | Not yet specified |

---

## If something breaks tomorrow

| Symptom | Likely cause | Fix |
|---|---|---|
| `/today` 500s | Worktree DB path or .env mismatch | Restart server in main repo |
| Scheduler not running on `/system-health` | Lifespan startup failed | Check stdout for `Scheduler failed to start`; restart |
| Alpaca shows disconnected | `.env` not loaded | Confirm running from `C:\Projects\trading_app\` not a worktree |
| Phone push doesn't arrive when it should | ntfy enabled flag off, or topic mismatch | Hit `POST /api/alerts/test` and check server log for `ntfy push sent` |
| 10:30 ET fires but `dispatching to daily analyst` shows | YAML flag not honored | Already fixed this session; if happens, check `services/workflow_engine.py::_run_analyze` lines around 348 |
| Detector raises `Invalid comparison ... datetime64[us, UTC]` | tz fix regressed | Check `agents/detectors/double_lock_filtered.py` line 193 — must use `daily.index.date < today` |

---

## Tonight's send-off

1. Cancel the smoke order (step 1 above).
2. Subscribe ntfy if not done (step 2).
3. Start `python run.py prod` (step 3).
4. `/system-health` green (step 4).
5. `/jobs` shows both DL crons with tomorrow's date (step 5).
6. Disable Windows sleep until 11:00 ET tomorrow.

If 1-6 all check, you're set.
