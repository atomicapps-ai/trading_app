# Intraday / Day-Trade Lane — scaffold

This documents the **day-trade lane**: strategies that open and close within the same session
(flat by the close). It's the intraday counterpart to the daily-swing detectors. A working,
**unvalidated** example ships with it — `intraday_reversion` — to prove the path end-to-end.

## What "day trade" means in the codebase (the DNA)

Style is structural, not a flag. A day-trade strategy differs from a swing one in three coupled places:

| | Swing | Day trade |
|---|---|---|
| Detector signature | `(daily, hourly, config, as_of_ts, macro)` → `ALL_DETECTORS` | `(bars_30m, daily, vix_prev_close, config, as_of_ts)` → `INTRADAY_DETECTORS` |
| Input bars | daily | 30-minute session bars (ET) + prior daily row for context |
| Exit | multi-session (`time_stop_sessions`, trail/target) | **same day** — `TimeStop.deadline` = today's close |
| Scan cadence | once post-close | during the session (in-session cron) |

## What's already wired (you don't have to build these)

- **Intraday analyst dispatch** — `agents/analyst.py::run_intraday_on_shortlist` / `analyst.run_intraday`
  feeds 30m bars + prior-session VIX to every detector in `INTRADAY_DETECTORS`.
- **Intraday workflow step** — a workflow `analyze` step with `params.intraday_30m: true` routes to
  the intraday runner (`services/workflow_engine.py`).
- **Same-day exit** — `agents/portfolio_manager.py` anchors the plan's `TimeStop.deadline` to
  today's session close when `holding_period == "intraday"` (configurable via
  `time_stop_close_et_hour/minute`); `agents/executioner.py::close_at_time` flattens the position
  at the deadline.
- **Enable switch** — the `/strategies` Enable/Disable toggle gates intraday scans too (the
  scheduler checks effective-active at fire-time; see `services/strategy_state.py`).
- **Data** — `data/historical/<SYM>_30m.csv` (plus 15m/5m) for ~940 US stocks (history ~5 years),
  kept fresh in-session by the candle-refresh job.
- **Backtest harness** — `scripts/bt_intraday.py` replays a real intraday detector session-by-session
  with the same-day exit and reports IS/OOS + control (it calls the actual detector, so its numbers
  are the in-app numbers).

## The example: `intraday_reversion` (SCAFFOLD — do not enable unvalidated)

Intraday VWAP mean-reversion snap-back: in a daily uptrend, buy a stretch below the session VWAP,
target the mean, flat by 15:00 ET. Files: `agents/detectors/intraday_reversion.py`,
`strategy_configs/intraday_reversion.yaml` (`active: false`, `style: day_trade`),
`workflows/intraday_reversion_scan.yaml`. It exists to exercise the plumbing, **not** as a proven
edge.

## Checklist to add a real day-trade strategy

1. **Design the mechanical spec** — kernel + intraday entry + hard stop + same-day exit. Mean-reversion
   snap-backs are the most promising base (best win rates in the swing work).
2. **Write the detector** in `agents/detectors/<name>.py` with the intraday signature; register it in
   `INTRADAY_DETECTORS`.
3. **Config** `strategy_configs/<name>.yaml`: `style: day_trade`, `holding_period: intraday`,
   `family: …`, `active: false`, `time_stop_close_et_hour: 15`.
4. **Workflow** `workflows/<name>_scan.yaml`: `analyze` step with `intraday_30m: true`; an in-session
   `schedule:` (gated by the enable toggle). **Add a per-symbol/per-day dedup guard** so repeated
   in-session scans don't re-enter the same setup.
5. **Validate** on `scripts/bt_intraday.py` — OOS PF ≥ ~1.2, avg-R > 0, ≥ ~100 trades, beats control.
6. **Correlation gate** vs the live book (`scripts/strategy_correlation_gate.py`) — intraday will
   likely be near-uncorrelated with the daily strategies (a genuine diversifier).
7. **Doc + `STRATEGY_GRID.md` row.** Enable from `/strategies` once it clears — no restart needed.

## Reality check

Same-day, high-probability edges are the hardest to find, and the video-mining run is the evidence:
opening-range breakouts, FVG/golden-pocket, liquidity sweeps, EMA+StochRSI scalps and the 4H-range
fade all lost or were marginal on real intraday data, and the removed `double_lock` "82% win" was
really ~53%. Also note intraday stock history is only ~5 years, so OOS confidence is lower than the
20-year daily rig. Budget for several failed candidates and treat "high win rate" claims skeptically.
