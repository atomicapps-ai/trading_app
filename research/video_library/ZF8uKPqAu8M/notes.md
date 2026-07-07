# ZF8uKPqAu8M — "I Backtested the ORB Breakout + Pullback Strategy" (Trading Steady)

Source: <https://www.youtube.com/watch?v=ZF8uKPqAu8M>

## Rules (as described)
- **Instrument:** S&P 500 (ES). **Timeframes:** 15-min opening range (first 3 candles on 5m), intraday.
- Mark the 9:30 ET 15-min opening range; wait for a breakout candle that closes outside; then wait for a **pullback** back to the range that closes back above it, enter on the break of the pullback candle's high; stop at range low (or pullback low); TP 1.5R (tested 2.5–4.5R and midpoint-entry variants too). No trades after 12:00; skip too-small/too-large ranges by ATR.

## Verdict: REJECT — intraday ORB, out of scope, and author-disconfirmed.
Intraday opening-range breakout on ES/S&P (15m/5m, NY open) — not daily US-stock swing trading. Moreover the creator's own 5-year backtest found it **unprofitable**: the pullback/continuation variants (and midpoint-entry / stop-order variants) all performed poorly, because waiting for a pullback filters out the strongest, highest-momentum breakouts. Both out of scope and empirically weak by the author's own testing.
Status: rejected
