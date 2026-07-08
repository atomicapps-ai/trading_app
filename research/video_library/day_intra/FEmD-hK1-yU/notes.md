> ⭐ **STATUS: EXCEPTION — RETAINED (not rejected).** The unfiltered strategy is a coin flip on 20yr
> SPY/QQQ (33% win, gross PF 0.97, net-losing). BUT the operator identified a **clear visual pattern
> separating winners from losers** in the trade gallery, so this is kept as a **selection-filter
> candidate**: the hypothesis is that a filter on the winning setups converts the coin flip into an edge.
> Do NOT retire/delete. Next step: quantify that winner/loser feature and re-backtest the filtered subset
> against the PASS bar (OOS PF ≥ 1.2, beats control). Marked exception 2026-07-08.

# One Box Scalper (First Candle) — mechanical spec
Source: Scarface Trades, "My Simple 5 Minute 'First Candle' Scalping Strategy" (FEmD-hK1-yU).
Extracted from transcript + chart frames (00120 box, 00300 confirmation patterns, 00435 retest, 00795 daily boxes).
Creator's claim (2-month backtest): 29 trades, **69% win, 2.58 profit factor, 90% daily-win**, +$10,490. One trade/day.

## Instruments / bars
- Liquid index ETFs / stocks (video shows SPY, SNDK). We test on 1-minute bars (SPY/QQQ deep-history first).
- **Box** built from the first **5-minute** candle; **execution on 1-minute** bars.

## Rules (mechanical)
1. **Box** = high (H0) and low (L0) of the first 5 minutes of the session (09:30–09:35 ET = the opening 5-min candle).
   Inside the box is a no-trade "restriction" zone.
2. **Trading window**: first 90 minutes (09:35–11:00 ET). **One trade per day** (first valid confirmed entry only).
3. **Breakout (sets direction)**: the first 1-min candle (≥09:35) that **closes above H0** → *bullish bias*; that
   **closes below L0** → *bearish bias*. Close must be beyond the box, not just a wick.
4. **Retest**: after the breakout, price returns to the broken edge — bearish: a later candle's **high ≥ L0**
   (back up to the box low); bullish: a later candle's **low ≤ H0** (back down to the box high).
5. **Confirmation candle** at the retest (this is the discretionary part in the video → encoded explicitly):
   - **Bearish**: (a) *shooting star / inverted hammer* — upper wick ≥ 2× body, body in lower third, OR
     (b) *bearish engulfing* — red candle whose body engulfs the prior candle's body.
   - **Bullish**: (a) *hammer* — lower wick ≥ 2× body, body in upper third, OR (b) *bullish engulfing*.
6. **Entry**: at the open of the bar **after** the confirmation candle, in the breakout direction.
7. **Stop**: bearish → just above the confirmation candle's **high**; bullish → just below its **low**.
   R = |entry − stop|.
8. **Target**: fixed **2R** (bearish entry − 2R; bullish entry + 2R).
9. **Exit**: target (+2R win) or stop (−1R loss); else flat at the end of the session (recorded at realized R).

## Assumptions flagged (undeterminable from video → explicit defaults, will sensitivity-test)
- Retest = touch of the broken box edge (exact "how far into the box" is discretionary in the video).
- Confirmation thresholds: wick ≥ 2× body, body-in-third for star/hammer; standard body-engulf for engulfing.
  The video's "weak/strong price action" is inherently discretionary — these are reasonable mechanizations.
- Breakout = first 1-min CLOSE beyond the box (transcript: "the candle closes below or above the box").
- 90-minute window + one-trade-per-day (both stated explicitly).

## Backtest plan
- `scripts/bt_one_box_scalper.py` on 1-min bars, fair per-symbol cost, IS/OOS split, random-direction control.
- Then `scripts/trade_gallery.py` renders every detected trade (box + entry/stop/target + confirmation candle)
  to an HTML gallery for **visual confirmation** that the code fires where the strategy actually sets up,
  alongside this video's reference frames. Only if the visuals match do we trust the numbers.
