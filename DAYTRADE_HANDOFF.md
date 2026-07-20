# Day-trade research — HANDOFF (2026-07-08)

**To resume in a fresh session:** open this folder (`C:\Projects\trading_app`) and say
*"read DAYTRADE_HANDOFF.md and continue."* Everything below is committed to git; numbers cited are in
`data/research/strategy_results/*.json` (verify there, don't trust recall).

---

## TL;DR — the one real finding
After ~20 retail YouTube day-trade archetypes (all coin flips), the **only validated day-trade** is a
sourced academic strategy:

**Concretum "Beat the Market" Intraday Momentum** (Zarattini/Aziz/Barbon, SSRN 4824172) on SPY+QQQ 1-min.
- `scripts/bt_concretum_intraday_momentum.py` (spec in the file header). Run: `--vm 1.5 --tag concretum_vm15`.
- **VM=1.5 result** (`data/research/strategy_results/concretum_vm15.json`): 6,261 trades, gross PF 1.23,
  net PF 1.11; **net OOS PF 1.18 vs control 0.98**; windows: **5y 1.22 / 10y 1.20** / 20y 1.13. Clears the
  net-PF≥1.2 bar on the recent windows, beats control, regime-consistent, avgR>0.
- **Caveats (important, not hype):** the edge is THIN (avgR ~+0.005 = ~0.025%/trade net). It's a backtest,
  not live. Fills are modeled at the :00/:30 **bar close** — mildly optimistic.

### ⏭ NEXT ACTION (the pending robustness test)
Re-run Concretum entering at the **NEXT bar's open** instead of the signal-bar close (conservative fill).
If the edge survives → more trust; if it evaporates → it was a fill artifact. **Do this before promoting.**
(Add a `--fill next_open` option to `bt_concretum_intraday_momentum.py`.)

Then, if it survives: correlation gate vs the live book (`scripts/strategy_correlation_gate.py`) →
wire `active:false` for human review. Never trust a backtest alone.

---

## Methodology gates we adopted this session (apply going forward)
1. **Definitional completeness gate (BEFORE any backtest).** A strategy is only backtestable if entry,
   *setup-quality condition*, stop, target, exit are all unambiguous. Fully-mechanical (ORB, EMA cross) →
   verdict valid. Discretionary ("wait for a *good* setup / *proper* retest / right *location*") → the
   backtest tests OUR reconstruction, so a reject is inconclusive. The gate = "can this even be defined?"
   is a better filter than the popularity/praise gate we originally used.
2. **Judge on recent windows (5y), not the 20-year blob.** Regimes differ. The app + backtests now report
   5/10/20yr. Three-Line-Strike *decays* (20y flatters it); Concretum is consistent.
3. **Quality-filter, two-stage.** Mechanical trigger → quality filter (trend strength, level-freshness /
   "double-tap weak", vol regime, time-of-day) → score. We've only built stage 1. The winner/loser image
   galleries are the discovery tool for stage-2 filters.

## What was tested (all day-trades)
Rejected (verdicts VALID — fully mechanical): ORB cluster (`bt_orb_variants.py`, ~15 videos), Three-Line
Strike (`bt_three_line_strike.py`), 9-EMA cross + 9/20 cross (`bt_ema9.py`).
Rejected but INCONCLUSIVE (had discretion): One Box Scalper (`bt_one_box_scalper.py`) — **kept as EXCEPTION**
(operator saw a winner/loser pattern; selection-filter candidate; `research/video_library/day_intra/FEmD-hK1-yU/status.json`).
Closest-to-alive retail: ema9_20_cross (5y net 1.01). Full map: `research/video_library/day_intra/_PROCESSING.md`.

## Remaining plan legs (not yet done)
- **Robustness test on Concretum** (next-open fill) ← do first.
- Rescue candidates via stage-2 quality filters: ema9_20_cross + One Box (define the quality rule OURSELVES).
- Remaining YouTube archetypes (low priority — expect coin flips): break-and-retest (RAMgdqP4gr4),
  multi-model 5-min "330 backtests" (Bdgev1or-7M), indicator combos, generic-beginner. Transcripts already
  ingested in `research/video_library/day_intra/<id>/transcript.md`.
- Completeness re-triage of the 27 (grade each COMPLETE vs INCOMPLETE).

## Systems built (reusable)
- **Backtest images**: `scripts/render_backtest_images.py` — per-trade PNGs (candles + entry rectangle,
  EXIT ×, optional `--vwap`, trade-focused window), winners/ + losers/ + manifest.json + gallery.html,
  under `data/backtest_images/<strategy>/` (gitignored, regenerable). 5/15/30m/1d/1m supported.
- **App: Backtest Review** — `routers/backtest_review.py`, route `/backtest-review` (list) +
  `/backtest-review/<strategy>` (Winners/Losers tabs + per-trade metrics + 5/10/20yr window table).
  Images served via `/bt-images` mount (app.py). Sidebar link under Strategies. Start app: `python run.py dev`.
- **Swing ledgers**: `scripts/emit_swing_ledgers.py` (runs real detectors via replay_swing → ledgers).
- **YouTube pipeline** (style-laned): `video_discover.py --mode intraday`, `video_rank.py`
  (gates: subs≥10k + ≥3 VALIDATION comments = tested-and-works, 12mo recency preference),
  `video_ingest.py --no-frames --cookies data\yt_cookies.txt`. Lanes: `research/video_library/{swing,day_intra,scalp}/`.
  **scalp/ lane is empty — next sourcing pass.** Cookie at `data/yt_cookies.txt` (gitignored; ROTATE the
  Google session when done — tokens passed through chat).

## Background job
- **Alpha Vantage 20yr 1-min pull**: ~55/102 symbols done, watchdog `scripts/run_av_pull.ps1` auto-resumes.
  Data → `data/historical_1m/<SYM>.parquet`. When complete: `scripts/resample_1m.py --all` then re-run the
  day-trade backtests on the FULL universe (esp. single-stock overnight, `INTRADAY_STRATEGY_SPECS.md` Family A).

## Key docs
`strategies/strategy_docs/INTRADAY_STRATEGY_CATALOG.md` (all day-trades tested) ·
`INTRADAY_SOURCED.md` (Concretum specs) · `INTRADAY_STRATEGY_SPECS.md` (4 families + overnight) ·
`INTRADAY_FINDINGS.md` · `research/video_library/day_intra/_PROCESSING.md` (27-video map).

---

## ✅ RESOLVED (2026-07-20) — the pending next-open fill test PASSES

The blocking robustness test above ("re-run Concretum entering at the **next bar's open**")
has been run. Added `--fill {close,next_open}` to `scripts/bt_concretum_intraday_momentum.py`:
the signal still fires on the :00/:30 mark's close, but the order fills at the following
1-minute bar's open — what a real order sent on that signal would actually get.

**The edge is not a fill artifact.** VM=1.5, SPY+QQQ, n=6,261 (identical trade count):

| fill | gross PF | net PF | net OOS PF | 5y | 10y | 20y |
|---|--:|--:|--:|--:|--:|--:|
| close (original) | 1.23 | 1.11 | 1.18 | 1.22 | 1.20 | 1.13 |
| **next_open (conservative)** | **1.24** | **1.12** | **1.18** | **1.22** | **1.20** | **1.14** |

Every window is unchanged or marginally *better*. The one-bar fill delay costs nothing,
which makes sense mechanically: the strategy enters on a band breakout and holds for a
VWAP-trailing exit, so it is not harvesting the signal bar's own close.

**Parameter robustness** (next_open fill, net OOS PF / last-5y net PF):

| VM | 1.0 | 1.25 | 1.5 | 1.75 | 2.0 |
|---|--:|--:|--:|--:|--:|
| net OOS PF | 1.15 | 1.20 | **1.18** | 1.09 | 1.09 |
| last 5y net PF | 1.16 | 1.23 | 1.22 | 1.17 | 1.14 |

A plateau from VM 1.0-1.5 rather than a spike, and every setting is net-positive on the
recent window — this is not a tuned point. VM 1.25-1.5 is the sweet spot.

### Remaining caveats before promoting (unchanged in importance)
1. **The edge is still THIN** — avgR ~+0.005 (~0.025%/trade net). Fine as a portfolio
   component, fragile as a standalone.
2. **The control is an approximation.** `control_OOS` flips the sign of realised returns
   (`x * random.choice([1,-1])`) rather than re-simulating with a random direction. Because
   the exit is direction-dependent (VWAP trail), a sign-flip does not produce the trade the
   opposite call would actually have taken. Per `research/video_library/PROCESS_AUDIT.md`
   §D1 this is the exact defect class that invalidated the `false_break_fade` verdict —
   **rebuild this as a true re-simulation before promoting.** It is currently the weakest
   number in the result.
3. Then: correlation gate vs the live book → wire `active:false` for human review.

### ⏭ NEXT ACTION (replaces the fill test)
Rebuild `control_OOS` as a genuine direction-randomised re-simulation, then run the
correlation gate.
