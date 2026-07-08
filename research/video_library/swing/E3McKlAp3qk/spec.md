# E3McKlAp3qk — "Displacement ORB + Session Analysis" — FAITHFUL SPEC

Source: transcript (324 lines) + 8 frames. Channel: day-trader ("Trade with Pat" robot).
Claimed: 79.45% win rate over "1,000 backtests" (unverified marketing claim).
Purpose of this doc: an EXPLICIT, reviewable rule set BEFORE coding, so a backtest "fail"
is a fail of the real strategy — not of my interpretation. Ambiguous knobs are flagged ⚠️.

## Instrument (fidelity catch)
- Frames show **XAUUSD (gold)** on his screen; targets quoted as **~2–2.2%** moves — gold/index-sized,
  NOT FX-major-sized (majors move ~0.5–0.8%/session). Testing this on EURUSD is NOT faithful.
  → Faithful test needs **gold (XAUUSD) and/or index** intraday data (HistData FX won't cover it;
    Dukascopy does). We can ALSO run it on majors but must report instrument separately.
- Timezone: **New York time (UTC-5/-4)**. ORB window **9:30–9:45 ET** (first NY 15m candle).

## The two steps (creator's own words)

### STEP 1 — Displacement ORB (the entry engine)
1. **Opening range** = the first **15-minute candle** of the NYSE open (09:30–09:45 ET).
   Mark its high and low → the session range.
2. Drop to **5-minute** chart. Wait for an **impulsive move out of the top or bottom** of the
   range — "big strong candles" that create *displacement*.
   - ⚠️ "big/strong/displacement" threshold is undefined. Candidate: breakout leg ≥ N×ATR, or
     ≥3–4 consecutive same-color candles, or breakout-bar body ≥ k× median body. **SWEEP this.**
   - **Candle must CLOSE** beyond the range — a wick-out that doesn't close does NOT count.
3. The displacement must create an **entry zone**, one of:
   - **Demand zone / order block** = the last red (down) candle *before* the big push up
     (mirror for shorts). Drawn as a box [low, high] of that candle.
   - **Fair Value Gap (FVG)** — see definition below.
   - ⚠️ He often also wants "recent structure broken" (the push takes out a prior swing high).
     Treat as an optional confluence to sweep on/off.
4. **Entry trigger**: price retraces back to the zone and reacts. Preferred trigger = **bullish
   engulfing** candle close at the zone; BUT he explicitly says engulfing is *rare* and he usually
   just enters **when the zone holds** (wicks respecting it) or **when price breaks back out** of
   the zone. ⚠️ Three possible triggers → SWEEP: (a) engulfing close, (b) zone-touch-and-hold,
   (c) re-break of zone.
5. **Stop loss**: below the demand zone (for FVG entries: the FVG midline OR below the FVG). ⚠️ sweep.
6. **Target**: 1.5–1.6R quoted once, ~2–2.2% quoted elsewhere, and "the swept liquidity level
   (Asian high/low) / previous level price reached." ⚠️ Three target definitions → SWEEP:
   (a) fixed 1.5R, (b) fixed % move, (c) opposite swept-liquidity level. He scales out at liquidity.

### STEP 2 — Session Analysis (the DIRECTIONAL FILTER — "how I avoid dumb losses")
This is the bias gate that supposedly lifts win rate toward ~79%. WITHOUT it, step 1 is just ORB.
1. **Asian session ranges** (low volume) → defines an Asian range high/low = liquidity pools.
2. **London session pushes** one direction, typically **sweeping** the Asian high or low.
3. **New York session reverses** → trade NY in the **OPPOSITE** direction to the London push.
   - If London pushed **down** (swept Asian low) → NY bias = **LONG**.
   - If London pushed **up** (swept Asian high) → NY bias = **SHORT**.
4. **Exception (continuation)**: if London sweeps **BOTH** the Asian high AND low → expect NY
   **continuation** (same direction as London), not reversal.
5. Step-1 entries are only taken **in the NY-bias direction**. Targets = the unswept Asian liquidity.
   - ⚠️ Session clock (UTC): Asia ≈ 00–07, London ≈ 07–12, NY ≈ 12–21 (his "NY open" = 13:30/14:30 UTC
     depending on DST since ORB is 9:30 ET). Need DST-correct ET conversion, NOT a fixed UTC hour.

## Fair Value Gap — exact definition (to be VISUALLY VERIFIED)
Standard 3-candle imbalance:
- **Bullish FVG**: over 3 consecutive candles, `candle1.high < candle3.low`. The gap zone is
  **[candle1.high, candle3.low]**, left by a large middle (displacement) candle2.
- **Bearish FVG**: `candle1.low > candle3.high`; gap zone **[candle3.high, candle1.low]**.
- Entry: price retraces back INTO the gap (creator: "respecting that fair value gap"); enter on the
  reaction. Stop = FVG midline or beyond it.
- ⚠️ Ambiguous knobs: minimum gap size (filter noise), which FVG if several, retrace depth that
  triggers (touch edge / 50% / full fill), invalidation once filled. **SWEEP these.**

→ **VISUAL VERIFICATION PENDING**: confirm against (a) the creator's frames and (b) the user's
  screenshot that this 3-candle zone is what he marks as the FVG, before trusting any result.

## Verification protocol (before any verdict)
1. ✅/⬜ Visually confirm the FVG definition vs creator frames + user screenshot.
2. ⬜ Reproduce ONE example trade the creator walks through (instrument+date+levels) as a unit test:
   encoded entry/stop/target must match what he shows. If not → my code is wrong, not the strategy.
3. ⬜ Parameter-sweep every ⚠️ knob; a verdict that flips on one guess is not a verdict.
4. ⬜ Test on the RIGHT instrument (gold/indices), report majors separately.
5. ⬜ Only then record pass/fail.

## VERDICT (2026-06-30): ❌ REJECT — fill-fragile, loses under realistic execution
Backtested on 5–6 FX majors, 30m, full history (~2,800 trades), DST-correct ET sessions:
- **Idealized fill (enter at exact FVG edge):** 72% win, PF 2.62, OOS PF 2.93, random-control 0.99.
  Looked like a home run — clean control, holds OOS, consistent across 6 pairs.
- **Realistic fill (enter next-bar open, 3-pip cost):** 39% win, PF **0.58**, OOS 0.59 — LOSES,
  and falls BELOW the 0.99 random control (limit fills are adversely selected — you get filled
  right before price runs to the stop).
- **Independent confirmation:** TradingView Strategy Tester (honest fills) showed ~20–30% win,
  PF <0.2 on the same window. Three engines now agree once fills are realistic.

The entire apparent edge lived in the assumption of perfect limit fills at the gap edge. It is NOT
a deployable strategy. The "79% win rate" claim is consistent only with an unrealistic fill model.

**Methodology upgrade banked:** a *fill-robustness / next-bar-open* stress test is now mandatory for
ANY limit-entry strategy — the random-direction control and OOS split do NOT catch fill optimism,
because they vary direction/period, not execution quality. This caught a 2.62-PF phantom.

## Irreducible-discretion notes
"You're almost never going to have every single one of these confluences line up" + "market
structure and common sense" → he discretionarily relaxes triggers. Our encoding is an APPROXIMATION;
state that with the result. The session-bias gate (step 2) is the most mechanical part and the
biggest claimed edge — that is the piece most worth testing cleanly.
