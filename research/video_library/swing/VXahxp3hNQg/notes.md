# VXahxp3hNQg — "Momentum loss through candlestick shapes" (reversal at key levels)

Source: <https://www.youtube.com/watch?v=VXahxp3hNQg>

## Content — discretionary reversal at support/resistance
- Identify a key support/resistance level (where price previously reversed).
- As price re-approaches the level, look for **momentum loss**: candles getting smaller and
  smaller, then long-wick rejections and a **doji** → reversal → enter the bounce.

## Verdict: REJECT — discretionary S/R + fuzzy candle read
Both halves are discretionary. The anchor is a hand-picked key level (which prior swing counts
is a judgment call), and the trigger — "candles getting smaller," "multiple long wicks,"
"a doji" — is a qualitative read with no numeric definition (how much smaller, over how many
bars, wick length threshold). Can't be coded faithfully. The mechanizable cousin (mean-reversion
bounce from an extreme) is already validated/live via `fear_dip_reversion` and the passed BB/RSI
and BB-3SD mean-reversion candidates — this adds nothing testable beyond those.
Status: rejected
