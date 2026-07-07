# 8vufTzGZqiI — "Opening Range Reversal (ORE)" (Doug)

Source: <https://www.youtube.com/watch?v=8vufTzGZqiI>

## Rules (as described)
- **Bias (daily chart):** asset above its 50-day SMA = "strong" (buy dips); below = "weak" (sell rallies).
- **Trigger (intraday, sub-1h, he uses 5m):** at the open, an opening-range move against the daily bias that exceeds ~20% of the daily ATR is treated as a "manipulation / liquidity sweep."
- **Entry:** counter to the intraday move / with the daily bias — buy when a 5-min candle takes out the prior candle's high (reversal confirmation). **Stop:** low of day. **Target:** 50% of the opening move (up to the full retrace).

## Verdict: REJECT — intraday execution, out of scope.
The daily chart is only a bias filter; the actual entry/stop/target all live on a sub-hour intraday chart (opening-range extension, intraday candle break, "low of day" stop). That's an intraday reversal scalp, not a daily-bar swing setup, and it's pitched as multi-asset (stocks/gold/oil/crypto/futures). The daily-timeframe kernel — "buy stretched dips on assets above their 50-MA" — is already implemented in the live suite as `fear_dip_reversion` (≥3×ATR below the 50-SMA, uptrend). No new daily-testable edge here.
Status: rejected
