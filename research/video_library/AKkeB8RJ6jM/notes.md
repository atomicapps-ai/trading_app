# AKkeB8RJ6jM — "Buying Pullbacks in Strong Stocks" (swing/Minervini-style)

Source: <https://www.youtube.com/watch?v=AKkeB8RJ6jM> · ~12 min.

## Rules (mechanical)
- entry: Buy a pullback in an uptrending stock. Two mechanizable entry triggers: (A) upside-reversal day — a day that opens weak but closes strong (close in upper part of range) on increased volume, occurring while price is near the 21-day EMA or 50-day MA; or (B) confirmed bounce — price touches the 21-EMA / 50-DMA and the next day closes back above it.
- exit/stop/target: Stop = just below the low of the reversal day (method A) or a decisive close below the support MA (method B). No fixed target; the video shows R-multiple management (examples cite ~1:4 R:R, exit discretionary on the way up). For a testable spec, exit on a trailing stop or a decisive close below the 21-EMA.
- filters/params: Stock in uptrend = higher highs/higher lows + rising 50-day MA. Pullback depth ~10–20% off recent high. General market in uptrend (10/20 EMA bull regime). Risk 1–2% per trade. MAs cited: 10-day, 21-day EMA ("sweet spot"), 50-day.

## Backtest result: ❌ REJECT — no edge in the entry
Tested two stops: (a) trigger-day low → OOS PF 0.10, exp −6.1R (razor-thin stop = every wiggle is many R);
(b) entry−1.5×ATR + 3R target → OOS PF 1.07, exp +0.027R, barely above its 0.88 control. Fixing the stop
geometry did NOT rescue it — the pullback-to-21EMA entry itself has no directional edge on daily US stocks.
Status: rejected, not deployed.

## Original triage verdict (superseded by backtest)
🔬 BACKTEST-CANDIDATE — daily-bar, fully mechanizable pullback-to-MA-in-uptrend with a reversal-candle trigger; distinct from our deployed strategies.
This is a trend-continuation pullback buy, not a counter-trend fade like Fear-Dip; it requires an intact uptrend (rising SMA50, price 10–20% off highs) plus a confirmation candle, which our current book lacks.
Exact daily spec: Universe in confirmed uptrend (close>SMA50 AND SMA50 rising over 20d AND price within 10–25% below its 50-day high). ENTRY: on a day where low ≤ 21-EMA (or 50-DMA) and close ≥ open and close in top 40% of the day's range and volume ≥ 20-day avg vol — buy next open. STOP: low of the trigger day. EXIT: trailing stop or first daily close below the 21-EMA. Regime: SPY 10>20 EMA bull filter. Params: SMA50, EMA21, vol-20.
Status: candidate, pending backtest
