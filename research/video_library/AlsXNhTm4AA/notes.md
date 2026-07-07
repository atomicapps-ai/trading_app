# AlsXNhTm4AA — "1-minute Fibonacci scalping (gold zone)"

Source: <https://www.youtube.com/watch?v=AlsXNhTm4AA>

## Rules — 1-min FX scalp
- Identify a short-term trend (lower highs in a downtrend / higher lows in an uptrend).
- Wait for a **break of structure** (BOS), then a pullback into the **0.5–0.618 "gold zone"**
  Fibonacci retracement, enter in the trend direction; targets at the −0.5 / −1 extensions.

## Verdict: REJECT — duplicate of an already-tested no-edge kernel
This is the identical kernel to video 2GAAK_JhNW0 (Fib golden-pocket continuation after a
break of structure), which I backtested this same session on 11 years of FX data
(`scripts/bt_fib_goldenpocket.py`): the mechanical 0.5–0.618 continuation entry won only
11–18% of the time with OOS profit factor 0.02–0.09 — *at or below its random-direction
control*, i.e. no demonstrable edge, and negative after costs. The frame confirms the same
setup (EURUSD 1-min, BOS label, 0.618 entry, −0.5/−1 extension targets). Nothing new to test;
the golden-pocket-continuation idea does not clear the bar.
Status: rejected
