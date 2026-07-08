# APSkB4hP73M — "Best Bollinger Bands strategy" (Bollinger squeeze breakout)

Source: <https://www.youtube.com/watch?v=APSkB4hP73M>

## Rules — daily/intraday
- Bollinger Bands = 20-SMA middle (trend direction) + 2·SD bands (volatility).
- Do **not** fade the bands (overbought/oversold is a trap in a trend).
- The actual strategy is the **Bollinger Band Squeeze breakout**:
  1. Find a low-volatility range — flat 20-SMA and narrow bands (low BBW / bands contracted).
  2. Wait for the bands to **expand** (BBW rising) = volatility picking up → breakout likely.
  3. Pick direction from price action: candles closing outside the upper band → long;
     closing outside the lower band → short.

## Verdict: REJECT — duplicate of the live `coil_breakout` strategy
This is exactly the volatility-contraction → expansion-breakout kernel that already cleared
this pipeline and is **live**: `coil_breakout` (from video YWBLKRLnrZ0, OOS PF 2.13 —
"range/coil contraction → volume breakout"). The BB-squeeze is the same idea expressed with
Bollinger-band width instead of ATR10<ATR50: flat/narrow → expansion thrust → trade the
break. Consistent with prior handling in this run (e.g. 6XtBCqBhQ-k rejected because its daily
analog is Coil-Breakout). No new mechanical edge to validate — the squeeze-breakout family is
already represented in the live suite.
Status: rejected
