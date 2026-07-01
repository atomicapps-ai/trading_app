# I8Usc5lza_Y — "Volatility Contraction Pattern (VCP)" (Minervini-style swing channel)

Source: <https://www.youtube.com/watch?v=I8Usc5lza_Y> · ~11 min.

## Rules (mechanical)
- entry: in an established uptrend, after a series of progressively smaller pullbacks (each contraction shallower than the last, e.g. 11% → 6% → 4%), buy the breakout above the last/tightest contraction high on rising volume.
- exit/stop/target: stop at the low of the final contraction (small risk). Exit either at a fixed R-multiple (e.g. 3R) OR ride the trend until exhausted.
- filters/params: Minervini Trend Template gate — price > SMA50 > SMA150 > SMA200, SMA200 rising, price within ~25% of 52wk high and well above 52wk low, high relative strength. Daily (or weekly) bars, US stocks. Win rate modest; edge is high R:R.

## Verdict: 🟡 SHELVED-INTRADAY — overlaps deployed detectors; core is partly discretionary
Daily-testable in principle, but the defining "successively smaller contractions" requires discretionary swing/pivot counting, and the breakout-from-tightening-base mechanic is already covered by our deployed `volatility_squeeze` and `cup_and_handle` detectors plus the Momentum Breakout strategy. The one cleanly mechanical novel piece is the **Minervini Trend Template as a regime/quality gate** (price>SMA50>SMA150>SMA200, SMA200 rising 1mo, within 25% of 52wk high, >30% above 52wk low) — worth keeping as a screener filter to layer onto existing breakout strategies rather than a standalone backtest candidate.
Status: shelved-intraday (note: capture Trend-Template gate as a screener filter)
