# Strategy Backtest Report — Video-Mined Strategies

**Generated:** 2026-06-28 · **Harness:** `scripts/strategy_suite.py` · **Per-strategy docs:** this folder.

11 YouTube strategy videos were cataloged (`research/video_library/`), deduplicated into **9 unique
strategies**, and run through one standardized rig so the numbers are directly comparable.

## Method (identical for every strategy)
- **Universe:** 90 daily US stocks (2006–2026, ~20y) for daily strategies; 6–10 symbols of 15-minute
  bars for intraday strategies.
- **Out-of-sample:** chronological split — metrics reported for the full set, in-sample (first half)
  and out-of-sample (second half) by trade time. We trust a result only if **OOS holds up**.
- **Costs:** 10 bps round-trip, charged per trade in R via each trade's own risk fraction.
- **Control:** the same trades with **coin-flipped direction** — answers "is the signal better than
  random timing?" A strategy that doesn't beat its control has no directional edge.
- **Metric:** expectancy = mean **R-multiple** per trade (R = entry-to-stop risk), net of costs.

## Leaderboard (by out-of-sample expectancy, net of costs)
| # | Strategy | Data | n | win% | OOS exp | vs control | Verdict |
|---|----------|------|---|------|---------|-----------|---------|
| S7 | Multi-month breakout continuation | daily ✅ | 4,990 | 28% | **+0.452R** | +0.05R | ✅ validated |
| S5 | Mean-reversion to 50-MA | daily ✅ | 9,133 | 30% | **+0.238R** | −0.05R | ✅ validated |
| S1 | Opening-range breakout + retest | 15m ⚠️ | 5,384 | 27% | +0.102R | — | ✅ first-pass |
| S3 | CHoCH/BOS + FVG (1:4 payoff) | 15m ⚠️ | 23,247 | 21% | +0.087R | coin-flip dir. | ⚠️ thin |
| S6 | Capitulation "V" reversal | daily ✅ | 1,157 | 36% | +0.046R | −0.07R | ⚠️ marginal |
| S4 | Supply/demand + R:R≥2.5 filter | daily ✅ | 4,338 | 25% | +0.034R | −0.10R | ⚠️ marginal |
| S4₀ | Supply/demand (as taught, no filter) | daily ✅ | 15,395 | 44% | −0.054R | −0.12R | ❌ loses |
| S8 | Presidential-cycle seasonality | index ✅ | — | — | n too small | — | ❌ unsupported |
| S2 | Session liquidity sweep | FX ⚠️ | — | — | not run | — | ⏳ needs FX data |
| S9 | Fib golden-zone + FVG confluence | 15m/FX | — | — | not run | — | ⏳ queued |

## What actually works (and the one recurring lesson)
1. **Trend-following on daily stocks is the real edge.** S7 (breakout continuation, +0.45R OOS) and
   S5 (mean-reversion to the mean, +0.24R OOS) are the two genuine winners — both OOS-robust, both
   beating their controls, both classic "low win rate / large winners" profiles. These fit our data
   natively, so we trust them most.
2. **Edge = payoff geometry, not setup prediction.** This recurred across *every* family:
   - S3 (ICT): the CHoCH/FVG triggers are coin-flips directionally; only the structural-stop +
     let-it-run management makes them positive.
   - S1 (ORB): retest entry beats chasing — same payoff lesson.
   - S4: the demand zone alone loses; the **R:R≥2.5 filter** is what flips it positive.
   The thing that pays is *cut losers at structure, let winners run* — not predicting direction.
3. **Several famous claims don't survive contact with data.** "Supply/demand as taught" loses;
   "presidential cycle" wasn't supported in-sample (pre-election 2-yr windows averaged +26% vs +64%
   for all windows). YouTube confidence ≠ edge — which is the entire point of this rig.

## Trust & caveats
- **Daily strategies (S4–S8)** are the trustworthy block — native regime, 20 years, thousands of
  trades, OOS split, controls. **Intraday strategies (S1, S3)** are first-pass approximations on
  stock 15m data; their native habitat is FX/futures, so treat them as directional leads, not proof.
- **Survivorship:** the 90-symbol universe is today's survivors — re-test promising strategies (S7,
  S5) on a point-in-time universe before risking capital.
- **Not modeled:** slippage beyond 10 bps, partial fills, borrow for shorts, overnight gaps on the
  daily holds. Drawdowns (S5/S7 exceed −150R cumulative) imply position sizing/correlation limits
  matter a lot live.

## Recommended next steps
1. **Harden S7 and S5** (the winners): add a market-regime gate (SPY>200MA), parameter sweeps
   (lookback, ATR-stop, MA-trail), and a point-in-time universe.
2. **Load intraday FX/futures data** to test S2, S9, and properly re-test S1/S3 in their native regime
   — and finally test the ICT **confluence** claim (does fib+FVG stacking beat the base?).
3. **Wire the validated winners** (S7 first) into the `/pending` paper pipeline behind the existing
   compliance + risk gates, for forward (out-of-sample by construction) paper validation.

*All per-strategy detail (rules, exact config, full IS/OOS/control tables) is in the `S#_*.md` files
in this folder. Machine-readable results: `data/research/strategy_results/*.json`.*
