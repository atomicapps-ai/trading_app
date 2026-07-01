# qcFpcTAzWXQ — 30-min Opening Range Breakout + Retest

Source: <https://www.youtube.com/watch?v=qcFpcTAzWXQ> · day-trading (NQ futures), ~9 min.

## The strategy (as stated)
1. Mark the high/low of the first 30 min (9:30–10:00 ET) = opening range.
2. Wait for a **5-min candle to CLOSE outside** the range (not a wick) → direction.
3. **Don't chase.** Wait for price to **retest** the broken level (ORH as support for
   longs / ORL as resistance for shorts); enter on the **first touch** that holds.
4. Stop just beyond the level (tight); let winners run; big R:R. Trade 9:30–11:00 ET only.

Echoes our own pivot findings: body-close confirmation (our F1) + first-touch (freshness).

## Testable hypotheses
- **H-ORB1** ORB break-and-retest has positive expectancy. ✅ first-pass
- **H-ORB2** Retest entry beats chasing the breakout close. ✅ first-pass
- **H-ORB3** Confluence (VWAP / 8–21 EMA at the retest) improves it. ⏳

## First-pass result (6 symbols, 15m, stop 0.2×OR, exit EOD)
| entry | n | win% | exp | OOS exp |
|---|---|---|---|---|
| retest | 5384 | 26.6% | +0.167R | **+0.102R** |
| chase  | 6472 | 32.8% | +0.047R | +0.004R |

**Verdict:** retest > chase confirmed; ORB shows positive OOS expectancy. BUT win rate is
~27% (trend-day profile), and this is only 6 stocks with assumed stop/exit. Needs:
breadth, stop/exit sweep, random-direction control, and ideally test on NQ/ES/QQQ.

Frames: `frames/` at 134/180/240/300/372s (range, break, retest, short eg, long eg).
