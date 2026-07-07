# Hidden Divergence — `hidden_divergence`

**Family:** trend-continuation · **Source video:** 9KVvwJHvcyE · **Status:** `active: false`
(validated candidate, pending human review of in-app re-validation) · **Direction:** long-only.

## Thesis
A *hidden* divergence is a continuation signal, not a reversal one. In an uptrend, a pullback
that makes a **higher low in price** but a **lower low in RSI** shows the dip was shallower than
momentum implies — the trend is likely to resume. Enter on confirmation and ride it.

## Rules (mechanical)
- **Trend filter:** close > 200-EMA.
- **Divergence:** two confirmed fractal swing lows (±`pivot_k`=3). The more recent low is
  **higher** than the prior (price higher-low) while **RSI(14) is lower** at the recent low
  (RSI lower-low), within `max_pivot_gap` (40) bars.
- **Confirmation:** Stochastic %K(14,3) < 45 at the recent low.
- **Entry:** the bar the recent pivot confirms → next open. **Stop:** recent swing low − 0.1×ATR.
- **Exit:** ride the trend — structural trailing stop up to the prior-bar low (no fixed target),
  60-bar time cap. Detector: `agents/detectors/hidden_divergence.py`; exit branch
  `hidden_divergence` in `scripts/replay_swing.py::_simulate` (`TRAIL`/`STOP`/`TIME`).

## Backtest — standalone rig (955-symbol daily US universe, 10 bps, IS/OOS, random control)
| Variant | n | IS PF | OOS PF | OOS avg-R | Control PF |
|---|---|---|---|---|---|
| trail + stochastic (full spec) | 14,770 | 1.10 | **1.21** | +0.059 | 0.73 |
| trail, no stoch | 38,335 | 1.03 | 1.08 | +0.023 | 0.67 |

Borderline pass (clears only in the full-spec form, like the earlier KuXV0LRfJx8). Script:
`scripts/bt_hidden_divergence.py`.

## Correlation gate — CLEANEST DIVERSIFIER
Max correlation to the live book = **0.24** (vs MACD-run); ≤0.16 vs Momentum Breakout and
Fear-Dip. The single most independent strategy in the book — near-uncorrelated with everything.
Method + matrix: `scripts/strategy_correlation_gate.py`.

## In-app re-validation
Confirmation sample (30 symbols, 2019–2026, `scripts/revalidate_new_strategies.py`): n=243,
**OOS PF 1.84**, +0.211R, 33% win (IS PF 1.17, control 0.96) — strong out of sample and beats the
control decisively. The low win rate / large average win is the trend-ride exit working as
designed. A full-universe run is still worth doing before activation, but this sample confirms the
edge reproduces (and then some) through the real detector.

## Caveats
Borderline standalone edge (OOS 1.21, thin) that depends on the full spec — the stochastic filter
and the trend-ride exit both matter; drop either and it slips toward a coin flip. Its exceptional
diversification (0.24) is the main reason to carry it despite the modest standalone PF.
