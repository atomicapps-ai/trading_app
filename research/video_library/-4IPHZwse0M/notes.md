# -4IPHZwse0M — Craig Percoco "Range → Change → Execution"

Source: <https://www.youtube.com/watch?v=-4IPHZwse0M> · day trading (forex/futures, 1-min @ NY open), ~28 min.
This is the **clearest articulation of the engine shared by all three ICT videos**, so it's the
reference write-up; the other two cross-link here.

## The strategy (as stated)
A 3-step filtration:
1. **Range** — on 15m, map structure: break-of-structure (BOS) = higher-high past prior high
   (uptrend) / lower-low past prior low (downtrend). Decide who's in control. Mark fair value
   gaps (FVG = 3-bar gap, wick of candle 1 doesn't overlap wick of candle 3) as draw-to targets.
2. **Change** — drop to 1m; wait for a **change of character (CHoCH)** = a candle CLOSE beyond
   the last swing pivot, flipping control. This is the trigger.
3. **Execution** — enter at the **midpoint of the FVG** produced by the CHoCH, stop just beyond
   the liquidity-inflection level (structure), start at a fixed **1:4**, move to break-even on the
   next BOS, then trail to the next FVG. Low win rate, winners run (he states 21%-ish, 6R+ runners).
   *Don't take* when: high-impact news at entry, weak/no close through the CHoCH, sideways chop.

## Testable hypotheses
- **H-ICT1** A candle close beyond a swing pivot (CHoCH/BOS) predicts continuation. ❌ killed (no directional edge)
- **H-ICT2** With a structural stop + asymmetric target, CHoCH entries are net positive. ✅ first-pass (thin)
- **H-ICT3** FVG midpoint acts as support/resistance (price continues after retest). ⏳ partially (no standalone edge)
- **H-ICT4** "Don't-take" filters (weak close, chop, news) raise expectancy. ⏳ untested

## Backtest (10 symbols, 15m, ATR-normalized; approximates the 1m engine on the data we have)
**Direction-only (8-bar forward continuation, R=ATR):**
| signal | n | win% | mean |
|---|---|---|---|
| CHoCH/BOS | 23,332 | 49.3% | −0.013R |
| FVG | 76,724 | 49.7% | +0.007R |
| RANDOM control | 2,999 | 49.3% | −0.070R |
→ **As a directional predictor, CHoCH and FVG are indistinguishable from a coin flip.**

**Asymmetric payoff (CHoCH entry, stop at structure, fixed TP):**
| rule | n | win% | exp | OOS exp |
|---|---|---|---|---|
| 1:2 | 23,274 | 34.2% | +0.027R | +0.025R |
| 1:4 | 23,247 | 21.3% | +0.066R | +0.087R |
→ **The edge is entirely in the payoff geometry** (cut at structure, let winners run), not
prediction — same finding as the ORB retest video. Positive and OOS-stable, but **thin** (costs
/ slippage not modeled; 21% win is brutal; chase entry, no retest/FVG/fib filter applied yet).

## Verdict
The "Range/Change/Execution" model reduces to: **break of structure + asymmetric trade management.**
Real but small edge from the management half; the FVG/CHoCH/fib vocabulary is interchangeable
dressing on the structural-break-and-run mechanic we already isolated in the pivot work. Worth
carrying forward to test the *filtered* version (retest entry + FVG confluence + don't-take rules).
Data limit: their actual edge is 1-min forex/futures at NY open — untestable on our 15m stock cache.
