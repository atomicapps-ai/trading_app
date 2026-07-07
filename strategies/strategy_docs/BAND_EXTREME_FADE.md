# Band Extreme Fade — `band_extreme_fade`

**Family:** mean-reversion · **Source video:** FqxEKDxemtI · **Status:** `active: false` (validated
candidate, pending human review of in-app re-validation) · **Direction:** long-only.

## Thesis
A rubber-band snap-back. When price stretches 3 standard deviations below its 20-day mean it is
at a statistical extreme; wait for it to close back inside the 2-sigma band (the reversion has
started) and fade toward the basis. More selective than a plain 2-sigma or ATR-stretch dip.

## Rules (mechanical)
- A bar within the last `arm_lookback` (10) bars closed **below the 3-sigma lower band**.
  (3-sigma is derived from the standard 2-sigma columns: `std = (bb_upper_20 − sma_20)/2`,
  `lower_3sigma = sma_20 − 3·std`.)
- **Confirmation:** the current bar closes back **above the 2-sigma lower band** (`bb_lower_20`)
  and still **below the basis** (`sma_20`).
- **Entry:** next open. **Stop:** recent 5-bar swing low − 0.1×ATR. **Target:** the basis (SMA20).
- **Time cap:** 30 bars. Detector: `agents/detectors/band_extreme_fade.py`; exit branch
  `band_extreme_fade` in `scripts/replay_swing.py::_simulate` (`TARGET`/`STOP`/`TIME`).

## Backtest — standalone rig (daily US universe, 10 bps, IS/OOS, random control)
| Variant | n | IS PF | OOS PF | OOS avg-R | Control PF |
|---|---|---|---|---|---|
| target = basis (SMA20) | 9,805 | 1.34 | **1.22** | +0.137 | 0.78 |
| target = opposite 2-sigma band | 9,736 | 1.70 | **1.40** | +0.276 | 0.82 |

Script: `scripts/bt_bb3sd_fade.py`. **Equities only** — the same rule on FX intraday fails hard
(OOS PF 0.03–0.07; price "hugs" the band in strong FX trends, as the source author warns).

## Correlation gate — DIVERSIFIER
Max correlation to the live book = **0.54** (vs Fear-Dip Reversion). Crucially only **0.22**
correlated with the other new mean-rev sleeve (RSI Pullback), so the two are near-independent.
Method + matrix: `scripts/strategy_correlation_gate.py`.

## In-app re-validation
Confirmation sample (30 symbols, 2019–2026, `scripts/revalidate_new_strategies.py`): n=322,
**OOS PF 1.14** (IS PF **1.63**), +0.069R, 44% win, control 1.14. **Marginal on this small,
recent-only sample** — it ties its control and sits under 1.2 out of sample, though IS is strong
and avg-R is positive. This is weaker than the standalone (1.22–1.40 on full history/955 names),
so a **full-universe / full-history in-app re-validation is required before activation** — do not
flip `active: true` on this sample alone.

## Caveats
0.54 correlation to Fear-Dip is the highest of the three promoted diversifiers (still under the
0.60 gate). If deploying alongside Fear-Dip, watch for co-firing in deep selloffs; the 3-sigma
trigger is rarer/more selective, which partly mitigates.
