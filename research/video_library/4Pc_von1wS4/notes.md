# 4Pc_von1wS4 — "How to Read Candlestick Charts" (Ross Cameron / Warrior Trading style)

Source: <https://www.youtube.com/watch?v=4Pc_von1wS4> · ~48 min.

## Rules (mechanical)
- entry: intraday momentum-continuation day trade. Scan for stock with high relative volume (>=5x 50-day avg), price up >=10% on the day (gap >2%), a news catalyst, price between $2 and $20. Wait for first up-wave, then first pullback; buy when the first candle makes a new high after the pullback. Confirm with: price above VWAP, MACD above signal line ("open"), price holding 9/20 EMA, high green volume on the up-candles, "green on the tape" (level 2 order flow).
- exit/stop/target: stop at the low of the entry candle (~10c risk for ~2:1 RR target). Scale out half on strength; exit fully on first candle making a new low / red on tape / momentum stall. Aims ~2:1 RR at ~68% win rate.
- filters/params: relvol>=5x, up>=10%, price $2-$20, news catalyst, above VWAP, MACD>signal, 9/20/200 EMA.

## Verdict: ❌ REJECT — intraday momentum scalp requiring real-time level-2 tape reading, news-catalyst discretion, and the "first candle to make a new high" timing on minute bars — none of which is daily-bar testable, and the core (intraday gappers/tape) is a different bucket than our daily swing pipeline.
The entry/exit hinge on intraday order flow ("green on the tape"), minute-candle wave timing, and a live news catalyst; the only daily-bar-mappable pieces (price>VWAP, MACD>signal, above SMA200) are already covered by our deployed MACD-run and momentum strategies. No novel daily-testable core.
Status: rejected
