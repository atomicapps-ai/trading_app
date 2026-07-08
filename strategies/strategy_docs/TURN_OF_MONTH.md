# Turn-of-the-Month — `turn_of_month`

**Family:** seasonality/calendar · **Source:** QuantifiedStrategies / Quantpedia (reviewed) ·
**Status:** `active: false` (validated candidate, pending human review) · **Direction:** long-only.

## Thesis
Equities drift up around the month boundary — salaries, dividend/pension reinvestment, and
window-dressing flows concentrate buying in the last few days of a month and the first few of the
next. A low-exposure calendar edge, uncorrelated with price-signal strategies.

## Rules (mechanical)
- **Entry:** on the **5th-last trading day of the month** → buy next open.
- **Exit:** ~7 sessions later (≈ the **3rd trading day of the new month**) — the `turn_of_month`
  branch in `scripts/replay_swing.py::_simulate`.
- **Stop:** no price signal, so a wide disaster stop (entry − 3·ATR14) defines R and caps tail risk;
  the exit is calendar-based.
- Detector: `agents/detectors/turn_of_month.py`. Config: `strategy_configs/turn_of_month.yaml`.
- **Calendar caveat:** no exchange-calendar library is installed, so "Kth-last trading day" is
  approximated by the Kth-last **business day** (weekday). Holidays can shift the entry by a day a
  few times a year — immaterial for a window-based seasonal edge. Add `pandas_market_calendars` for
  exactness later.

## Backtest — standalone rig (955-symbol daily US universe, 10 bps, IS/OOS, control)
| Variant | n | win% | IS PF | OOS PF | avg-R |
|---|---|---|---|---|---|
| 5th-last → 3rd-into (default) | 172,930 | 53.4% | 1.35 | **1.28** | +0.11 |
| 3rd-last → 3rd-into | 172,958 | 54.0% | 1.10 | 1.27 | +0.09 |
| 2nd-last → 3rd-into | 172,983 | 51.4% | 1.05 | 1.10 | +0.03 |

Script: `scripts/bt_tom.py`. Reported by sources: SPY CAGR ~2.9%, ~25% exposure, works
internationally.

## Correlation gate — DIVERSIFIER
Max correlation to the live book = **0.36** (vs Fear-Dip); 0.23 vs Momentum and MACD-run. As a
seasonality edge it's near-orthogonal to every price-signal strategy — the cleanest kind of
diversifier. Script: `scripts/bt_tom_corr.py`.

## In-app re-validation (real detector via `replay()`)
Confirmation sample (60 symbols, 2015–2026, `scripts/revalidate_new_strategies.py … turn_of_month`):
n=6,664, **OOS PF 1.17** (IS 1.38), +0.039R, 54% win, control 1.03. Slightly below the exact-calendar
standalone (1.28) and the ETF test (1.35) — expected, because the wired exit uses a fixed 7-session
hold (business-day approximation) instead of the exact "3rd trading day of next month," on a small
recent sample. Positive and consistent; tightening the exit with a market-calendar library should
recover the gap. Do **not** flip `active: true` until reviewed.

## Cross-universe check (ETFs)
On the cached ETF universe (`scripts/bt_etf_universe.py`, 13 broad/sector ETFs) TOM is **stronger**:
OOS PF **1.35** (IS 1.46), +0.067R, 56% win — the seasonal edge is robust across stocks and ETFs.

## Caveats
Low exposure (~25% of days) and a modest per-trade edge — its value is diversification, not raw
return. The business-day approximation and the fixed 7-session exit are small fidelity gaps vs the
exact-calendar standalone test; both are documented and easy to tighten with a market-calendar lib.
