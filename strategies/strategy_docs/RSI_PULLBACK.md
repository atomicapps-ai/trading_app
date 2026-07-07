# RSI Pullback (Connors) — `rsi_pullback`

**Family:** mean-reversion · **Source video:** W8ENIXvcGlQ · **Status:** `active: false` (validated
candidate, pending human review of in-app re-validation) · **Direction:** long-only.

## Thesis
The market's long-term drift is up, but it doesn't go up in a straight line — fear and profit-
taking create shallow oversold dips inside otherwise healthy uptrends. Buy the dip, exit on the
first sign the bounce has started. High win rate, small average win; the edge is the fast
recovery exit, **not** a fixed target.

## Rules (mechanical)
- **Trend filter:** close > SMA200 (uptrend only; otherwise stay flat).
- **Entry:** RSI(10) < 30 → buy next open.
- **Exit:** RSI(10) crosses back above 40 → sell next open; **or** a 10-bar time stop.
- **Protective stop only:** entry − 3×ATR14 (disaster stop; no fixed profit target).
- Detector: `agents/detectors/rsi_pullback.py`. Exit branch: `scripts/replay_swing.py::_simulate`
  (`RSI_EXIT` / `TIME` / `STOP`). Config: `strategy_configs/rsi_pullback.yaml`.

## Backtest — standalone rig (955-symbol daily US universe, 10 bps, IS/OOS, random control)
| Segment | n | win% | PF | avg-R |
|---|---|---|---|---|
| in-sample | 9,179 | 69.7% | 1.59 | +0.140 |
| **out-sample** | 9,179 | **68.3%** | **1.31** | **+0.100** |
| random control | 18,358 | 48.3% | 0.90 | −0.037 |

Script: `scripts/bt_connors_pullback.py`.

## Correlation gate — DIVERSIFIER
Max correlation to the live book = **0.40** (vs Fear-Dip Reversion); 0.15 vs MACD-run, 0.17 vs
Momentum Breakout. Distinct trigger from Fear-Dip (RSI(10)<30 + RSI-recovery exit vs ≥3×ATR
stretch below SMA50 targeting the mean). Only 0.22 correlated with the other new mean-rev sleeve
(Band Extreme Fade). Method + matrix: `scripts/strategy_correlation_gate.py`,
`data/research/strategy_results/correlation_gate.json`.

## In-app re-validation (real detector via `replay()`)
Confirmation sample (30 symbols, 2019–2026, `scripts/revalidate_new_strategies.py`): n=276,
**OOS PF 1.32**, +0.056R, 66.7% win (IS PF 1.14, control 1.19) — **matches the standalone 1.31**.
The detector reproduces the edge through the real pipeline. NOTE: a full-universe / full-history
in-app re-validation is still worth running (the per-bar detector is O(n²) per symbol, so the
big run is slow) before flipping `active: true`, and correlation vs the live Fear-Dip should be
reviewed in production.

## Caveats
No hard stop in the original method (the 3×ATR disaster stop is our addition for risk-gate
sizing); tail risk lives in the time-exit. High win rate but small average win — position sizing
and the fear-regime co-firing with Fear-Dip should be checked before activation.
