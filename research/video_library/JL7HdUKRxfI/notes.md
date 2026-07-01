# JL7HdUKRxfI — "Trend Pullback to Fib Discount Zone" (swing trading)

Source: <https://www.youtube.com/watch?v=JL7HdUKRxfI> · ~19 min.

## Rules (mechanical)
- entry: Uptrend only — price above 50-EMA. Wait for a pullback of ≥3 consecutive sizeable
  red candles. Draw Fibonacci from the latest swing low to swing high; only enter when price
  retraces below the 50% ("discount") level. Enter on the close of the first green
  confirmation candle.
- exit/stop/target: Stop below the pullback low / nearest support; let it run, ~1% risk for
  ~3% target (≈3R).
- filters/params: "Look left" for a prior support/demand level near the entry (discretionary
  confluence); confirmation candle required.

## Backtest result: ❌ REJECT — no edge (≈ coin flip)
Tested: close>EMA50 + price below 50% Fib of a 20-bar swing + green day → next open; stop = 5-bar low; target
3R or close<EMA50. OOS PF 1.03, exp +0.016R, n=2249 — essentially break-even, and its control (0.76) shows the
geometry alone is negative. Converges to the earlier marginal Fib-50 pullback (bQP6vLB7ius, +0.06R). Not deployable.
Status: rejected, not deployed.

## Original triage verdict (superseded by backtest)
🔬 BACKTEST-CANDIDATE — the core (trend filter + measured pullback into Fib-50% discount + confirmation) is fully mechanizable on daily bars and is a pullback-continuation strategy, distinct from the deployed breakout/mean-reversion/MACD set.
Drop the discretionary "look left for support" overlay and the EMA/Fib/pullback rules become
objective. It's trend-following pullback entry (buy strength on a dip) rather than fading the
mean (Fear-Dip) — a genuinely different family.
Daily spec: long only when close > EMA50; after a swing high, require a pullback of ≥3 down
days; compute Fib of last swing-low→swing-high; arm when price trades below the 50%
retracement of that leg; enter at next daily close that is green (close>open); stop below the
pullback low; target 3R or trail by EMA50. Universe = liquid US equities.
Status: candidate, pending backtest
