# FVG Continuation — Manual Trading Playbook (FX)

One-page daily routine to trade the validated FVG displacement-continuation by hand,
until the OANDA integration is live. Backtest: PF ~1.48, 49–53% win at 2–3R, clean
control, OOS-robust across 9 pairs (see FVG_CONTINUATION.md).

## One-time setup
- Chart: any FX pair, **5-min or 30-min**, **timezone = New York (ET)**.
- Add indicator: **scripts/pine/fvg.pine** ("TradeAgent FVG") in TradingView.
  Settings: Displacement ≥1.0–1.5× avg body, Min gap 2 pips, session filter optional.
- Pairs to watch: EURUSD, GBPUSD, AUDUSD, USDJPY, EURJPY, GBPJPY, AUDJPY, EURAUD, EURCAD.
- Risk: fixed % of account per trade (e.g. 0.5–1%). Position size = risk$ ÷ (stop distance in pips × pip value).

## Daily routine (per pair)
1. **Mark the Asian range** (19:00–00:00 ET prior evening): high + low.
2. **Watch the London session** (02:00–07:00 ET): which way did it push, and did it
   sweep the Asia high or low?
3. **Set the NY bias** (the directional filter — this is the edge):
   - London pushed **up / swept Asia high** → NY bias = **SHORT**.
   - London pushed **down / swept Asia low** → NY bias = **LONG**.
   - London swept **BOTH** Asia high and low → **continuation** (bias = London's direction).
4. **Mark the NY opening range** (09:30–09:45 ET): ORB high + low.
5. **Wait for a displacement FVG in the bias direction**, after 09:45 ET:
   - A strong candle (the indicator flags the gap) that **closes beyond the ORB** in the
     bias direction and leaves a fair-value gap.
6. **ENTER AT MARKET on the next candle's open** — in the displacement direction.
   *Do NOT wait for a pullback into the gap (that's the version that loses).*
7. **Stop:** the far edge of the FVG (gap bottom for longs, gap top for shorts).
8. **Target:** 2R or 3R (both tested positive). Exit at the NY close (16:00 ET) if neither hits.
9. **One trade per pair per day.** Skip the day if no qualifying displacement-FVG appears.

## Checklist before clicking
- [ ] NY bias set from Asia→London→NY (not guessed)
- [ ] FVG is in the **bias direction**
- [ ] Displacement candle **closed beyond the ORB**
- [ ] Entering **at market**, next candle (no limit, no waiting for retrace)
- [ ] Stop at the **far gap edge**; target 2–3R; size = fixed-% risk
- [ ] It's within the NY window (09:45–16:00 ET); flat by the close

## What NOT to do (tested, loses)
- ❌ Don't place a limit at the gap edge and wait for price to retrace into it — that
  version loses at realistic fills (adverse selection). The edge is the **continuation**, entered at market.
- ❌ Don't trade against the session bias. Don't hold past the NY close.
