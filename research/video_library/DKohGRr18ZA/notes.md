# DKohGRr18ZA — "Simple breakout strategy (avoid false breakouts)"

Source: <https://www.youtube.com/watch?v=DKohGRr18ZA>

## Rules — S/R breakout with momentum confirmation
- Skip named patterns (wedge/pennant/triangle) — they don't look like the textbook on real charts.
- When price consolidates, draw a key level (support/resistance / connect the lower-highs).
- ~80% of raw breakouts are false, so don't enter on the break itself: **require a momentum
  candle at the breakout** (one big candle or several medium candles) to confirm.
- Then either enter, or wait for a **retest** of the broken level before entering.

## Verdict: REJECT — duplicate of the live breakout family; levels are discretionary
The mechanical kernel is "range breakout confirmed by an expansion/momentum candle (optionally
a retest)." That is exactly what the live daily strategies already encode: `momentum_breakout`
(126-day high breakout + **volume confirm**) and `coil_breakout` (contraction → **expansion
thrust** breakout of a range). The only thing this video adds is drawing the consolidation level
by eye, which is discretionary and not mechanizable faithfully. No new, testable edge beyond the
breakout-plus-confirmation kernel already validated and live.
Status: rejected
