# UXN50MOGDmA — "London Breakout Strategy x100 backtest" (Trading Strategy Tester)

Source: <https://www.youtube.com/watch?v=UXN50MOGDmA>

## Rules (as described)
- **Instrument:** forex (EUR/USD, GBP/USD). **Timeframes:** 1h/30m, session-based.
- Mark the range of the last 4 hours of the Asian session before the London open; at the London open, enter on a 30-min candle close above/below the range. Range width = L; TP at 3L, stop at 2L (2:3 R:R).

## Verdict: REJECT — forex, intraday session breakout, out of scope.
A London-breakout day-trading method on forex pairs, keyed to intraday session timing (Asian range → London open) on 1h/30m bars — not daily US stocks. Depends on session-marker indicators and broker server-time. Not representable in the daily rig. (The channel's own backtest was only marginally positive: +181 on $1,000, 68% win but the author notes it fails in sideways markets.)
Status: rejected
