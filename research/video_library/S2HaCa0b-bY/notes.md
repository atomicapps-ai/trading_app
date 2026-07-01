# S2HaCa0b-bY — "MACD Money Map (3 systems)" (unknown channel)

Source: <https://www.youtube.com/watch?v=S2HaCa0b-bY> · ~15 min.

## Rules (mechanical)
- entry: Three overlapping "systems." (1) Trend: only long when MACD>0, only short when MACD<0; take crossover only when MACD is far from zero (>±0.5) and "wait 2-3 candles" to confirm. (2) Reversal: MACD/price divergence + histogram pattern (flip/shrinking/zero-bounce). (3) Confirmation: triple-timeframe stack (daily=bias, 4h=signal, 1h=trigger) must all agree, plus crossover must sit at a hand-drawn support/resistance level / candlestick.
- exit/stop/target: stop at recent swing high/low; target = 2R; scale half at target, move stop to breakeven, trail remainder with opposite MACD cross.
- filters/params: MACD (default), zero-line bias, ±0.5 distance gate, multi-timeframe alignment, key S/R confluence, hammer/candlestick confirm.

## Verdict: ❌ REJECT — irreducible discretion (multi-timeframe + hand-drawn S/R + divergence + candlestick confluence)
The core edge claims ("higher win rate at support/resistance," divergence, hammer confirmation, multi-timeframe agreement) are subjective and can't be mechanized cleanly on daily bars alone — entry requires 1h/4h/daily stacking we have no intraday data for, plus draw-by-hand level confluence. Even the daily-bar skeleton (MACD cross above 200-style bias + distance gate) is a weaker duplicate of nothing we run but is buried under non-testable discretion. Not extractable as a clean spec.
Status: rejected, not deployed
