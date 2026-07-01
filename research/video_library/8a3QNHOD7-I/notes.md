# 8a3QNHOD7-I — Opening Range Sweep (session liquidity)

Source: <https://www.youtube.com/watch?v=8a3QNHOD7-I> · ~14 min, NAS100/NQ, 15m+5m. Intraday FX/futures regime.

## Rules → hypotheses
- Mark **Asia** and **London** session highs/lows. At the **New York open (9:30 ET)**, wait for price
  to **sweep** (take out) the London and/or Asia high or low, then **trade the opposing direction**,
  targeting the opposite session's liquidity — or a fixed **2:1 / 3:1** if already beyond it. → **H-SW1**
- **Entry trigger:** drop to 5m, take the **first 5-minute retrace candle that closes back** through
  the swept level (market order, not limit); stop beyond the sweep extreme. Raised his win rate
  ~35%→50%+ vs trading the level naked. → **H-SW2**
- Management: fixed 1.5–2.3R, or trail under each new 5m candle once structure clears.

## Notes
This is the **session-liquidity-sweep reversal** — a close cousin of the ORB (qcFpcTAzWXQ/I29peidTQxU)
but anchored to *session* extremes rather than the 30-min opening range. Native instrument is NQ;
on our 15m **stock** data we can only approximate (no clean Asia/London sessions for equities) — flag
the regime mismatch. The transferable, testable core is **H-SW2**: does a "sweep + first retrace-candle
close back inside" beat trading the raw level? That's the same retest-vs-chase lesson as the ORB.

## Status: queued. Best tested on intraday FX/futures; partial approximation on 15m stocks.
