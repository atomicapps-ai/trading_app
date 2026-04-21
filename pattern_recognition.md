# Pattern Recognition & Confluence Scoring
**Document type:** AI Training Reference  
**Version:** 1.0.0  
**Scope:** US Equities + ETFs | Top 9 High-Probability Patterns  
**Timeframe stack:** Daily → 4H → 1H → 15M (top-down confirmation)  
**Companion:** SKILL.md (Trading Architect), CLAUDE.md (app context)

---

## How to use this document

This document teaches an AI agent to:
1. **Identify** a pattern using precise, mathematical, unambiguous rules
2. **Score** pattern quality on a 0–100 scale
3. **Find confluence** across multiple timeframes to strengthen conviction
4. **Reject** weak or ambiguous setups before they become trade proposals

A pattern is never a trade signal on its own. It is an input to the
`analyst` agent's technical lens. The `portfolio_manager` combines
pattern scores with other lenses (fundamental, sentiment, macro) to
produce a `trade_plan`. A high-quality pattern with no other
confirmation is a watchlist item, not a trade.

---

## Core principle: mathematical pattern definition

Every pattern in this document is defined by conditions that can be
evaluated as TRUE or FALSE against price/volume data. There are no
subjective calls like "looks like a W" or "roughly symmetrical."
If the condition cannot be expressed as a comparison, ratio, or
threshold, it does not belong in the definition.

**Pattern quality score (PQS):** Each pattern has a base score and
modifier rules. The PQS feeds directly into `signal.strength` in the
`analyst` agent output (0.0–1.0, where PQS 100 = strength 1.0).

---

## Confluence scoring system

Confluence = multiple independent conditions confirming the same
directional bias at the same time. Each confirmed condition adds
to the total confluence score.

### Timeframe confluence (how to apply top-down)

The timeframe stack runs Daily → 4H → 1H → 15M.
A pattern on a lower timeframe is stronger when the higher timeframes
agree. Apply this rule for every pattern:

```
TIMEFRAME CONFLUENCE SCORE:

Pattern detected on 1H:
  + Daily trend agrees (price above/below 20 SMA in pattern direction): +20 pts
  + 4H trend agrees (price above/below VWAP or 20 SMA): +15 pts
  + 15M shows no counter-pattern forming: +10 pts
  Maximum timeframe confluence bonus: 45 pts

Pattern detected on Daily:
  + Weekly trend agrees (price above/below 20 SMA weekly): +20 pts
  + 4H shows constructive price action (no distribution): +15 pts
  Maximum timeframe confluence bonus: 35 pts

Pattern detected on 15M only (no higher TF confirmation):
  Timeframe confluence bonus: 0 pts
  NOTE: 15M-only patterns are valid for intraday setups but
  conviction ceiling is capped at 0.65 regardless of other factors.
```

### Indicator confluence modifiers (apply to any pattern)

These are universal modifiers that add to any pattern's base score:

```
VOLUME CONFIRMATION:
  Breakout/trigger candle volume > 1.5× 20-period avg volume: +10 pts
  Breakout/trigger candle volume > 2.0× 20-period avg volume: +15 pts
  (Use the higher value, not both)

RSI ALIGNMENT:
  RSI_14 trending in pattern direction (rising for long, falling for short): +8 pts
  RSI_14 not overbought for long (< 70) / not oversold for short (> 30): +5 pts

MOVING AVERAGE ALIGNMENT:
  Price above 50 SMA (long) / below 50 SMA (short) on trigger timeframe: +8 pts
  50 SMA above 200 SMA (long) / below (short) on trigger timeframe: +7 pts

VWAP ALIGNMENT (intraday patterns only, 1H and below):
  Price above VWAP for long setup / below VWAP for short setup: +8 pts

MARKET STRUCTURE:
  Setup is at a historically significant S/R level: +10 pts
  Setup is NOT near a major earnings date (within 7 days): +5 pts
  VIX below 25 (low fear regime, trends more reliable): +5 pts

SECTOR ALIGNMENT:
  Sector ETF (XLK, XLF, etc.) trending same direction as trade: +7 pts
  SPY trending same direction as trade on daily: +5 pts
```

### Confluence score interpretation

```
0–39:   REJECT — do not generate trade_plan
40–54:  WATCHLIST — monitor, wait for score to improve
55–69:  WEAK SIGNAL — generate signal with strength 0.55–0.69,
        requires 2+ other lenses to agree before trade_plan
70–84:  STRONG SIGNAL — generate signal with strength 0.70–0.84,
        requires 1 other lens to agree
85–100: HIGH CONVICTION — generate signal with strength 0.85–1.0,
        portfolio_manager may act with single-lens confirmation
        if fundamental backdrop is neutral or better
```

---

## Pattern 1: Bull Flag / Bear Flag

**Category:** Continuation  
**Best timeframes:** 1H (primary), Daily (swing), 15M (intraday)  
**Typical holding:** Intraday to 5 days  
**Base PQS:** 55

### What it is
A sharp impulsive move (the flagpole) followed by a controlled
pullback or sideways consolidation (the flag) on declining volume,
then a breakout resuming the original direction. Represents a
brief pause before continuation — the market is absorbing gains
before the next leg.

### Mathematical definition (bull flag)

```
FLAGPOLE CONDITIONS (all must be TRUE):
  P1. Flagpole height ≥ 3× ATR_14 on trigger timeframe
  P2. Flagpole formed in ≤ 10 candles
  P3. Flagpole volume: at least 3 of the flagpole candles have
      volume > 1.2× 20-period avg volume

FLAG CONDITIONS (all must be TRUE):
  F1. Price retraces 30–60% of flagpole height (Fibonacci zone)
      Retracement > 60%: flag is too deep, pattern invalid
      Retracement < 15%: not enough consolidation, too soon
  F2. Flag duration: 3–20 candles on trigger timeframe
      < 3 candles: too brief, likely just noise
      > 20 candles: flag is stale, momentum lost
  F3. Flag volume: average volume during flag < 70% of flagpole
      average volume (declining volume = healthy consolidation)
  F4. Flag forms as parallel channel (highs and lows both declining
      at similar angle) OR sideways channel (highs and lows flat)
      A widening channel (highs expanding) invalidates the pattern
  F5. Price stays above the 20 SMA on the trigger timeframe
      during the flag (bull flags should not lose this level)

TRIGGER (breakout entry):
  T1. Price closes above the upper trendline of the flag
  T2. Trigger candle volume > 1.5× 20-period avg volume
  T3. Entry: limit order 0.1% above the flag high
      (avoids false breakouts and spread games)

INVALIDATION:
  I1. Price closes below the low of the flag on volume
      > 1.2× avg volume
  I2. Flag duration exceeds 20 candles without breakout
  I3. Volume expands on a down day inside the flag (distribution)
```

### Target and stop calculation

```
MEASURED MOVE TARGET:
  TP1 = entry + (flagpole height × 0.75)  [conservative target]
  TP2 = entry + (flagpole height × 1.00)  [full measured move]
  TP3 = entry + (flagpole height × 1.50)  [extended target, trail to here]

STOP PLACEMENT:
  Initial stop = low of the flag - (0.1 × ATR_14)
  Rationale: a close below the flag low means the pattern failed
```

### Bear flag (mirror rules)
All conditions reversed: flagpole is a sharp drop, flag is a 
controlled bounce on declining volume, breakout is a close below
the flag low with volume. Entry is a limit short 0.1% below flag low.

### PQS modifiers specific to this pattern

```
+ Flagpole formed on a catalyst (earnings beat, upgrade,
  news event with novelty > 0.70): +12 pts
+ Flag is a perfect parallel channel (R² of trendlines > 0.85): +8 pts
+ Trigger candle volume > 2.5× avg: +8 pts (already counted in
  universal modifier, so add 8 - 15 = no extra if already claimed)
+ Flag retracement is 38.2–50% of flagpole (ideal Fibonacci zone): +7 pts
- Flag retracement > 50% (deeper, less reliable): -8 pts
- Flagpole formed in only 1–2 candles (spike, not a pole): -10 pts
```

### Timeframe confluence example (bull flag)

```
Setup: Bull flag identified on 1H chart

Condition                                          Points
─────────────────────────────────────────────────────────
Base PQS (pattern valid)                              55
Daily trend up (price > 20 SMA daily)                +20
4H price above VWAP                                  +15
15M no counter pattern                               +10
Trigger volume > 2.0× avg                            +15
RSI_14 trending up, not overbought                   +13
Price above 50 SMA on 1H                             +8
50 SMA > 200 SMA on 1H                               +7
Flag retracement 42% (ideal zone)                    +7
SPY trending up on daily                             +5
─────────────────────────────────────────────────────────
TOTAL PQS                                            155
Capped at 100 → PQS: 100
Signal strength: 1.0 (HIGH CONVICTION)
```

---

## Pattern 2: Double Bottom / Double Top

**Category:** Reversal  
**Best timeframes:** Daily (primary), 4H (confirmation), 1H (entry timing)  
**Typical holding:** 5–20 days (swing)  
**Base PQS:** 58

### What it is
Two distinct lows (double bottom) or highs (double top) at
approximately the same price level, separated by a meaningful
bounce, signaling exhaustion of the prior trend. The "neckline"
(the high between the two lows, or low between the two highs)
is the critical breakout level. Breaking the neckline confirms
the reversal.

### Mathematical definition (double bottom)

```
FIRST LOW CONDITIONS:
  L1. First low forms after a downtrend of at least 15% from
      a prior swing high (measured on daily chart)
  L2. First low is a clearly defined swing low: at least 3 candles
      with both neighboring candles having higher lows
  L3. Volume on the move into first low: elevated
      (volume > 1.2× 20-day avg on the decline candles)

BOUNCE CONDITIONS:
  B1. Bounce from first low retraces 38–65% of the prior
      downtrend (creates the neckline)
  B2. Bounce duration: minimum 5 candles on trigger timeframe
  B3. Neckline level = high of the bounce (must be a clearly
      defined swing high, not just the highest close)

SECOND LOW CONDITIONS:
  S1. Second low within ±3% of first low price level
      (exactly equal is suspicious — slight variation is healthy)
  S2. Second low does NOT close below first low by more than
      0.5% (a decisive new low invalidates the pattern)
  S3. Volume on move into second low: LESS than volume on move
      into first low (declining selling pressure = key confirmation)
  S4. RSI at second low is HIGHER than RSI at first low
      (bullish divergence — this is the most important confirmation)
      RSI divergence absent: pattern still valid but -15 pts PQS
  S5. Time between first low and second low: minimum 10 candles,
      maximum 60 candles on trigger timeframe
      < 10 candles: too fast, likely same selling wave
      > 60 candles: pattern too spread out, context has changed

NECKLINE BREAKOUT (trigger):
  N1. Price closes above neckline level on daily chart
  N2. Breakout candle volume > 1.5× 20-day avg volume
  N3. Entry: limit buy at neckline + 0.25% (above the breakout level)
  N4. Wait for candle close — do not enter on an intracandle touch

INVALIDATION:
  I1. Price closes below the lower of the two lows by > 1%
  I2. Neckline breakout fails (price closes back below neckline
      on volume > 1.2× avg within 3 candles of breakout)
```

### Target and stop calculation

```
MEASURED MOVE TARGET:
  Pattern height = neckline price - average of two lows
  TP1 = neckline + (pattern height × 0.75)
  TP2 = neckline + (pattern height × 1.00)
  TP3 = neckline + (pattern height × 1.50) [extended]

STOP PLACEMENT:
  Initial stop = lower of the two lows - (0.15 × ATR_14)
  Rationale: both lows must hold for the pattern to remain valid
```

### Double top (mirror rules)
All conditions reversed. Two highs within ±3% of each other.
Neckline is the low between them. Breakout is a close below
neckline with volume. RSI confirmation: RSI at second high
LOWER than RSI at first high (bearish divergence).

### PQS modifiers specific to this pattern

```
+ RSI divergence confirmed at second low/high: +15 pts
+ Volume on second low/high visibly less than first: +10 pts
+ Second low/high within ±1% of first (very precise): +8 pts
+ Neckline is also a prior significant S/R level: +10 pts
+ Pattern forms after a prolonged trend (> 30% move): +7 pts
- RSI divergence absent: -15 pts
- Second low slightly undercuts first (false breakdown): -10 pts
  (still valid if recovery is immediate, but reduce conviction)
- Volume on breakout candle < 1.2× avg: -12 pts
- Breakout occurs in last 30 minutes of session: -8 pts
  (late-day breakouts fail more often — thin volume)
```

---

## Pattern 3: RSI Divergence (Bullish and Bearish)

**Category:** Reversal / Momentum shift  
**Best timeframes:** 1H (primary), Daily (higher weight), 15M (entry timing)  
**Typical holding:** 1–10 days  
**Base PQS:** 52

### What it is
Price makes a new low (bullish divergence) or new high (bearish
divergence) while RSI fails to confirm, making a higher low or
lower high respectively. This disconnect reveals that the momentum
behind the move is weakening — the trend is running out of fuel.
RSI divergence is both a standalone pattern AND the most important
confluence modifier for every other pattern in this document.

### Mathematical definition (bullish divergence)

```
PRICE CONDITION:
  P1. Price Low 2 < Price Low 1 (price makes a lower low)
  P2. Price Low 1 and Price Low 2 are both clearly defined
      swing lows (at least 2 candles on each side with higher lows)
  P3. Distance between Low 1 and Low 2: minimum 5 candles,
      maximum 50 candles on trigger timeframe
  P4. The overall context is a downtrend on this timeframe
      (price below 20 SMA, or in a defined downtrend channel)

RSI CONDITION:
  R1. RSI at Low 2 > RSI at Low 1 (RSI makes a higher low)
      The RSI difference must be ≥ 3 points to be significant
      (RSI Low 2 = 32, RSI Low 1 = 28 → difference = 4 → valid)
      (RSI Low 2 = 29, RSI Low 1 = 28 → difference = 1 → invalid)
  R2. RSI at Low 1 ≤ 40 (divergence in oversold territory
      is more powerful than divergence at RSI 55)
      RSI at Low 1 between 30–40: normal divergence
      RSI at Low 1 ≤ 30: strong divergence (+10 pts bonus)
      RSI at Low 1 > 40: weak divergence (-10 pts)
  R3. Use RSI period 14 as the standard
      Confirm on one timeframe above (e.g. if found on 1H,
      check that 4H RSI is also not making new lows)

TRIGGER:
  T1. Price closes above the most recent swing high between
      Low 1 and Low 2 (the "confirmation high")
  T2. Entry: limit buy at confirmation high + 0.15%
  T3. Alternative entry: aggressive entry on a bullish candle
      at Low 2 if RSI is ≤ 30 and volume is declining
      (reduced R but higher conviction in extreme oversold)

INVALIDATION:
  I1. Price closes below Low 2 (new lower low = divergence failed)
  I2. RSI drops below its level at Low 1 (RSI confirms new low)
  I3. 15 candles pass after Low 2 without trigger firing
```

### Target and stop calculation

```
TARGETS:
  TP1 = High between Low 1 and Low 2 (the swing high = neckline)
  TP2 = Origin of the move (swing high that started the downtrend)
  TP3 = Fibonacci 1.272 extension of the Low 1 → swing high → Low 2 move

STOP PLACEMENT:
  Initial stop = Low 2 - (0.1 × ATR_14)
  If aggressive entry at Low 2: stop = Low 2 - (0.25 × ATR_14)
```

### Divergence classes (strength ranking)

```
CLASS A (strongest): Price makes lower low, RSI makes higher low,
  AND RSI at Low 2 is in oversold territory (≤ 30)
  PQS bonus: +18 pts

CLASS B (standard): Price makes lower low, RSI makes higher low,
  RSI at Low 2 between 30–40
  PQS bonus: 0 pts (this is the base case)

CLASS C (weakest): Price makes lower low, RSI makes higher low,
  RSI at Low 2 above 40
  PQS penalty: -10 pts
  Note: Class C divergence requires additional confirmation from
  at least 2 other indicators before a trade_plan is generated

HIDDEN DIVERGENCE (trend continuation, not reversal):
  Bullish hidden: price makes higher low, RSI makes lower low
  → confirms uptrend continuation, use as flag/pullback entry signal
  Bearish hidden: price makes lower high, RSI makes higher high
  → confirms downtrend continuation
  Hidden divergence base PQS: 48 (lower than regular divergence)
```

### Bearish divergence (mirror rules)
Price makes higher high, RSI makes lower high. RSI at High 2
must be ≥ 60 for standard divergence, ≥ 70 for strong divergence.
Trigger: price closes below the most recent swing low between
High 1 and High 2.

### PQS modifiers specific to this pattern

```
+ Class A divergence (RSI ≤ 30 at second low): +18 pts
+ Divergence confirmed on timeframe above: +15 pts
  (found on 1H AND visible on 4H): +15 pts
+ MACD histogram also diverging in same direction: +10 pts
+ Volume declining into second low (less selling pressure): +8 pts
+ Second low forms at a major support level: +10 pts
- Class C divergence (RSI > 40 at low): -10 pts
- Only visible on trigger timeframe, not confirmed above: -8 pts
- Trigger candle has low volume: -10 pts
```

---

## Pattern 4: Ascending / Descending Triangle

**Category:** Continuation (primary) / Reversal (secondary)  
**Best timeframes:** Daily (primary), 4H, 1H  
**Typical holding:** 3–15 days  
**Base PQS:** 60

### What it is
An ascending triangle has a flat resistance line at the top and
rising lows — buyers are getting more aggressive each time price
dips, while sellers hold a fixed level. Eventually buyers overwhelm
sellers and price breaks out above resistance. A descending
triangle is the mirror: flat support, declining highs.

### Mathematical definition (ascending triangle)

```
RESISTANCE LINE CONDITIONS:
  R1. Minimum 2 touches of the resistance level (price touches,
      then pulls back — each touch is a rejection)
      Optimal: 3–4 touches (more touches = stronger resistance = 
      more powerful when it finally breaks)
  R2. Resistance touches within ±0.5% of each other
      (a sloping resistance line is not an ascending triangle —
      it is a rising wedge, a different and typically bearish pattern)
  R3. Each resistance touch should be a clearly defined swing high
      (at least 2 candles on each side with lower highs)

RISING LOWS CONDITIONS:
  L1. Minimum 2 rising swing lows (each subsequent low is higher
      than the prior low)
  L2. Lows form a clearly rising trendline
      Linear regression slope of the lows > 0
      Slope should be measurable — lows rising < 0.1% per candle
      on daily is too flat (essentially horizontal = symmetrical
      triangle, different pattern)
  L3. Each low should be a defined swing low (same rule as R3)

TRIANGLE STRUCTURE:
  T1. Pattern duration: minimum 10 candles, maximum 60 candles
      on trigger timeframe
  T2. As triangle progresses, the range between resistance and
      the rising lows NARROWS by at least 30% from the first
      touch to the last touch before breakout
      (this is the "coiling" — price is compressing)
  T3. Volume during triangle formation: generally declining
      as the triangle develops (the market is undecided,
      volume reflects uncertainty)

BREAKOUT TRIGGER:
  B1. Price closes above the resistance level
  B2. Breakout candle volume > 1.5× 20-period avg volume
  B3. Entry: limit buy at resistance + 0.2%
  B4. If breakout occurs in the first 25% of the triangle's
      expected lifespan (too early): reduce PQS by 15 pts
      (early breakouts from triangles fail more often)
  B5. Ideal breakout zone: 50–75% through the triangle's apex
      (the point where resistance and support lines converge)

INVALIDATION:
  I1. Price closes below the most recent rising low by > 1%
  I2. Resistance line is broken to the downside (breakdown —
      pattern becomes bearish, consider short on retest)
  I3. Triangle reaches apex (lines converge) without breakout:
      pattern expires — momentum is gone
```

### Target and stop calculation

```
MEASURED MOVE TARGET:
  Pattern height = resistance level - first low of the triangle
  TP1 = resistance + (pattern height × 0.75)
  TP2 = resistance + (pattern height × 1.00)
  TP3 = resistance + (pattern height × 1.50)

STOP PLACEMENT:
  Initial stop = most recent rising low - (0.1 × ATR_14)
  After breakout: trail stop below each new swing low
```

### Descending triangle (mirror rules)
Flat support, declining highs. Breakout is a close below support
with volume. Measured move target is below support.
Note: descending triangles in a broader uptrend sometimes resolve
upward — treat a bullish resolution as a high-conviction long signal
(unexpected breakout direction adds conviction).

### PQS modifiers specific to this pattern

```
+ 3 or more touches on resistance line: +10 pts
+ 4 or more touches on resistance line: +15 pts (use higher)
+ Breakout occurs in ideal 50-75% zone of triangle lifespan: +10 pts
+ Volume clearly declining through triangle formation: +8 pts
+ Prior trend before triangle is strong (> 20% move): +7 pts
+ Resistance level coincides with prior major S/R: +10 pts
- Breakout occurs in first 25% of triangle lifespan: -15 pts
- Only 2 touches on resistance (minimum): -8 pts
- Volume on breakout < 1.2× avg: -12 pts
- Resistance line has slope (not flat): -20 pts
  (this may be a rising wedge — re-classify)
```

---

## Pattern 5: Inside Bar / NR7 Compression

**Category:** Volatility compression breakout  
**Best timeframes:** Daily (primary), 4H  
**Typical holding:** 1–5 days  
**Base PQS:** 50

### What it is
An inside bar is a candle whose high and low are completely
contained within the prior candle's range — the market is
contracting, unable to make a new high or low. NR7 (Narrow Range 7)
is the candle with the smallest high-low range of the last 7 candles.
Both signal volatility compression — a spring coiling before release.
When these occur after a trend, they often precede continuation.
When clustered (multiple consecutive inside bars), the eventual
breakout is typically explosive.

### Mathematical definition

```
INSIDE BAR CONDITIONS:
  I1. Current candle high < prior candle high
  I2. Current candle low > prior candle low
  (Both conditions must be true — a candle that exceeds on one
  side but not the other is NOT an inside bar)
  I3. The "mother candle" (prior candle) should have a meaningful
      range: mother candle range ≥ 0.75 × ATR_14
      (an inside bar inside a doji is not meaningful)

NR7 CONDITIONS:
  N1. Current candle range (high - low) is the smallest of
      the last 7 candles (including current)
  N2. NR7 is more powerful when it is ALSO an inside bar
      (both conditions true simultaneously)
  N3. NR7 range should be ≤ 50% of the 14-period average
      range (ATR_14) — this confirms genuine compression

COMPRESSION CLUSTER (highest quality setup):
  C1. 2 consecutive inside bars: strong compression signal
  C2. 3+ consecutive inside bars: very strong compression signal
  C3. Each additional inside bar in sequence adds +8 pts to PQS
  C4. Volume should decline with each successive inside bar
      (the market is going quiet before the storm)

CONTEXT REQUIREMENT:
  X1. Pattern must occur in the context of a trend, not in
      choppy sideways action
      Prior trend: price moved > 10% in one direction over
      the last 20 candles before the compression
  X2. Inside bar / NR7 should occur near a key level
      (support in uptrend, resistance in downtrend) OR
      after a pullback to the 20 SMA in the trend direction
      (compression at a logical reaction level = high quality)

TRIGGER:
  T1. Long trigger: price trades above the mother candle high
      (or highest high of the compression cluster)
  T2. Short trigger: price trades below the mother candle low
  T3. Entry: buy stop 0.1% above the high (for long)
      or sell stop 0.1% below the low (for short)
      (use a stop order so you only enter if price actually breaks)
  T4. Direction bias: use the higher timeframe trend to decide
      which direction to take if both sides could trigger
      (in an uptrend: only take the long trigger)

INVALIDATION:
  I1. Price breaks the trigger level on one side, then
      immediately reverses through the other side: failed breakout
      Exit immediately — do not hold through a whipsaw
  I2. 5 candles pass without trigger firing: pattern is stale
```

### Target and stop calculation

```
TARGETS:
  TP1 = entry + (mother candle range × 1.5)
  TP2 = entry + (mother candle range × 2.5)
  TP3 = next major S/R level in breakout direction

STOP PLACEMENT:
  Long: stop = mother candle low - (0.1 × ATR_14)
  Short: stop = mother candle high + (0.1 × ATR_14)
  Tight stops are a feature of this pattern — the compression
  defines a precise "I was wrong" level
```

### PQS modifiers specific to this pattern

```
+ NR7 AND inside bar simultaneously: +12 pts
+ 2 consecutive inside bars (cluster): +8 pts
+ 3+ consecutive inside bars: +16 pts (use this, not the +8)
+ Volume declining each day in the compression: +10 pts
+ Compression occurs at 20 SMA in trend direction: +8 pts
+ Compression occurs at a prior major S/R level: +10 pts
+ ATR_14 has been declining for 5+ periods (volatility trend
  confirming the compression): +7 pts
- Mother candle is a doji (tiny range): -12 pts
- No clear trend context (choppy market): -15 pts
- Trigger fires on low volume (< 1.2× avg): -10 pts
```

---

## Pattern 6: Cup and Handle

**Category:** Continuation  
**Best timeframes:** Daily (primary), Weekly (confirmation)  
**Typical holding:** 10–40 days  
**Base PQS:** 62

### What it is
A rounding bottom (the cup) followed by a small consolidation
or slight pullback (the handle) before a breakout to new highs.
The cup shape reflects a gradual shift from selling pressure to
accumulation. Institutionally recognized and widely respected.
Works best on higher timeframes and in stocks with strong
fundamental backing.

### Mathematical definition

```
CUP CONDITIONS:
  C1. Prior uptrend before the cup: price must have risen at
      least 30% from a prior base before forming the cup
  C2. Cup depth: retracement of 15–50% from the high that
      starts the cup to the low of the cup
      > 50% depth: too deep, pattern less reliable
      < 15% depth: too shallow, not enough base building
  C3. Cup shape: the decline into the low and the recovery
      from the low should be roughly symmetrical and gradual
      (U-shape, not V-shape)
      Quantify: the left side decline should take at least
      as many candles as the right side recovery
      A V-bottom (recovery in < 50% of the decline candles)
      is not a cup — it's a different pattern
  C4. Cup duration: minimum 7 weeks on daily chart,
      maximum 65 weeks
      < 7 weeks: not enough base building
      > 65 weeks: pattern is too old, context has changed
  C5. Volume during the cup formation: should be highest
      on the left side (the decline), lowest at the bottom
      of the cup (accumulation is quiet), and should begin
      to increase on the right side of the cup as price
      recovers (buyers returning)
  C6. Right side of cup should recover to within 5% of
      the original high (the "pivot point")
      Recovering to only 80% of the prior high = weak cup

HANDLE CONDITIONS:
  H1. Handle forms as a small pullback or sideways drift
      after the right side of the cup reaches near the prior high
  H2. Handle depth: retracement of 8–20% of the cup's
      right side rally (from pivot point)
      > 20%: handle too deep, pattern stressed
      < 5%: barely any handle — still valid but -8 pts
  H3. Handle duration: 1–8 weeks on daily chart
  H4. Handle should drift downward or sideways, NOT upward
      (an upward-drifting handle is a warning sign)
  H5. Handle volume: should decline during the handle
      (shakeout of weak holders on low volume)
  H6. Handle should form in the upper half of the cup
      (if handle forms below the midpoint of the cup depth,
      the pattern is compromised)

BREAKOUT TRIGGER:
  B1. Price closes above the pivot point (the high that started
      the cup) on the daily chart
  B2. Breakout volume: must be > 1.5× 40-day avg volume
      (this is a significant breakout — it needs institutional
      participation, not just retail)
  B3. Entry: limit buy at pivot point + 0.5%
      (slightly above to confirm the breakout is real)

INVALIDATION:
  I1. Handle depth exceeds 20% of the cup's right side rally
  I2. Price closes below the lowest point of the handle
  I3. Breakout volume is below avg (fakeout risk — wait for
      re-test with volume before entering)
```

### Target and stop calculation

```
MEASURED MOVE TARGET:
  Cup depth = pivot point price - cup low price
  TP1 = pivot point + (cup depth × 0.75)
  TP2 = pivot point + (cup depth × 1.00)
  TP3 = pivot point + (cup depth × 1.50)

STOP PLACEMENT:
  Initial stop = lowest point of the handle - (0.1 × ATR_14)
  This is typically a tight stop relative to the target — the
  risk/reward on cup and handle is usually excellent
```

### PQS modifiers specific to this pattern

```
+ Prior uptrend > 50% before cup: +10 pts
+ Cup duration 7–26 weeks (ideal time): +8 pts
+ Right side volume increasing as cup recovers: +10 pts
+ Handle volume clearly declining: +8 pts
+ Pivot point coincides with prior major resistance
  (the breakout is also a multi-year high): +12 pts
+ Fundamental backing: EPS growing, strong revenue: +10 pts
  (cup and handle is most reliable in fundamentally strong names)
- Cup depth > 40% (too deep): -10 pts
- V-shaped cup bottom: -15 pts
- Handle forms in lower half of cup: -12 pts
- Breakout volume below 1.2× avg: -15 pts
  (low-volume breakout from C&H is a common trap)
```

---

## Pattern 7: Volatility Squeeze (TTM Squeeze)

**Category:** Volatility compression → explosive breakout  
**Best timeframes:** Daily (primary), 4H, 1H  
**Typical holding:** 3–15 days (can be intraday on 1H squeeze)  
**Base PQS:** 65

### What it is
The most powerful compression pattern in this document.
When Bollinger Bands (measuring price volatility) contract
INSIDE Keltner Channels (measuring average true range volatility),
the market is in a state of extreme compression — lower volatility
than is typical for the current ATR environment.
This condition (the "squeeze") historically precedes explosive
directional moves. The momentum histogram (typically a MACD-derived
oscillator) reveals which direction the explosion is likely to go.

### Indicator setup (required)

```
BOLLINGER BANDS:
  Period: 20
  Multiplier: 2.0 standard deviations
  Upper BB = 20 SMA + (2.0 × 20-period std dev)
  Lower BB = 20 SMA - (2.0 × 20-period std dev)

KELTNER CHANNELS:
  Period: 20
  Multiplier: 1.5 × ATR (some implementations use 2.0 —
  use 1.5 for a more sensitive squeeze detection)
  Upper KC = 20 EMA + (1.5 × ATR_20)
  Lower KC = 20 EMA - (1.5 × ATR_20)

SQUEEZE CONDITION:
  Upper BB < Upper KC AND Lower BB > Lower KC
  (Bollinger Bands are completely inside the Keltner Channels)
  When this is true: SQUEEZE IS ON (the coil is loaded)
  When this turns false (BBs expand outside KCs): SQUEEZE FIRES

MOMENTUM HISTOGRAM:
  Momentum = closing price - midpoint of (highest high + lowest low
             over 20 periods + 20-period SMA) / 2
  (This is the TTM Squeeze momentum oscillator)
  Histogram above zero and rising: bullish momentum building
  Histogram below zero and falling: bearish momentum building
  Histogram crossing zero upward: potential long trigger
  Histogram crossing zero downward: potential short trigger
```

### Mathematical definition

```
SQUEEZE SETUP CONDITIONS:
  S1. Squeeze ON for minimum 6 consecutive candles on trigger TF
      (a squeeze that fires after only 2-3 bars is often noise)
      Optimal squeeze duration: 8–20 candles
      > 30 candles: very long squeeze, very powerful when it fires
      Each candle of squeeze duration beyond 8: +1 pt (max +20 pts)

  S2. Bollinger Band width at its minimum in the last 52 periods
      (the bands are narrower than they've been in a year)
      Confirms this is genuine multi-period compression

  S3. ATR_14 is declining or flat during the squeeze
      (actual volatility is contracting, not just the bands)

  S4. Volume declining during the squeeze
      (market participants are waiting — nobody is committing)

DIRECTION DETERMINATION:
  D1. Momentum histogram is the primary directional signal
      Histogram rising above zero for 2+ bars: long bias
      Histogram falling below zero for 2+ bars: short bias
  D2. Price position relative to 20 SMA:
      Price above 20 SMA: supports long bias
      Price below 20 SMA: supports short bias
  D3. Higher timeframe trend alignment:
      Daily squeeze, weekly trend up: strong long bias
      Daily squeeze, weekly trend down: strong short bias
  D4. If D1, D2, and D3 all agree: HIGH CONVICTION direction
      If D1 and D2 agree but D3 does not: MODERATE conviction
      If only D1 is clear: LOW conviction — wait for more bars

TRIGGER:
  T1. Squeeze fires: Upper BB expands above Upper KC
      OR Lower BB expands below Lower KC (BBs exit the KCs)
  T2. Momentum histogram is clearly directional (not near zero)
  T3. Entry on the candle that fires the squeeze, or the next
      candle open (do not chase more than 1.5% from squeeze fire)
  T4. Volume on the fire candle should be increasing
      (the market is waking up — volume confirms the move)

INVALIDATION:
  I1. Squeeze fires but momentum histogram is near zero
      (no directional conviction) — WAIT, do not enter
  I2. Price moves against the momentum direction on the fire bar
      (histogram says long, price drops) — do not enter long
  I3. Squeeze fires but volume is below average
      (compression released without participation — false fire)
      Wait for next day's volume confirmation
```

### Target and stop calculation

```
TARGETS:
  The squeeze does not have a standard measured move target.
  Use the nearest significant S/R levels in the momentum direction.
  TP1 = next resistance level (long) / support level (short)
  TP2 = second resistance / support level
  TP3 = trail with structural trailing stop (below swing lows for long)

STOP PLACEMENT:
  Long: stop = low of the squeeze candle (the tightest candle
        in the squeeze) - (0.15 × ATR_14)
  Short: stop = high of the squeeze candle + (0.15 × ATR_14)
  The squeeze's narrowest candle defines the invalidation level
```

### Multi-timeframe squeeze (highest conviction setup)

```
DUAL SQUEEZE:
  Squeeze firing on 1H AND squeeze active (not yet fired) on Daily:
  → The daily squeeze provides the big picture compression
  → The 1H squeeze provides the precise entry timing
  → PQS bonus: +20 pts
  → This is one of the highest-quality mechanical setups in equities

TRIPLE SQUEEZE:
  Squeeze conditions present on Daily + 4H + 1H simultaneously:
  → Extremely rare
  → PQS bonus: +30 pts (cap at 100)
  → Treat as highest conviction possible on the technical lens
```

### PQS modifiers specific to this pattern

```
+ Squeeze lasted 12+ candles (long coil): +12 pts
+ Squeeze lasted 20+ candles (very long coil): +20 pts (use this)
+ BB width at 52-period minimum: +10 pts
+ Dual timeframe squeeze (1H firing, Daily still on): +20 pts
+ Triple timeframe squeeze: +30 pts (use this, not dual)
+ All 3 direction signals agree (D1 + D2 + D3): +15 pts
+ Volume declining through squeeze, spikes on fire: +10 pts
- Squeeze lasted < 6 candles (too short): -20 pts
- Momentum near zero on fire candle: -15 pts
- Volume on fire candle < avg: -12 pts
- Higher timeframe trend opposes direction: -10 pts
```

---

## Pattern 8: VWAP Reclaim

**Category:** Intraday trend continuation / reversal  
**Best timeframes:** 1H (primary), 15M (entry timing)  
**Typical holding:** Intraday to 2 days  
**Base PQS:** 50

### What it is
VWAP (Volume Weighted Average Price) is the single most important
intraday reference level used by institutional traders. It represents
the average price paid by all participants weighted by volume for
the session. Price above VWAP = buyers in control. Price below
VWAP = sellers in control. A VWAP reclaim occurs when price breaks
below VWAP, consolidates, then recaptures it with volume — signaling
that institutional buyers are re-entering. The reclaim candle and
the volume behind it tell the story.

### Mathematical definition

```
SETUP CONDITIONS:
  V1. Price was above VWAP for a sustained period (minimum 
      60 minutes of trading above VWAP) — establishing that
      VWAP was a support level, not just a random cross
  V2. Price breaks below VWAP on a selloff:
      Selloff candle closes below VWAP by at least 0.3%
      (a brief wick below VWAP does not count — needs a close)
  V3. Price consolidates below VWAP for 2–8 candles on 15M
      (the holding pattern — sellers test whether the level is lost)
  V4. Volume during the consolidation below VWAP:
      should be below the session's average volume per bar
      (declining volume = sellers are exhausting)

RECLAIM TRIGGER:
  R1. Price closes back above VWAP
  R2. Reclaim candle body (open to close) must cross VWAP
      (a wick above VWAP without a close above does not trigger)
  R3. Reclaim candle volume: > 1.5× session avg volume per bar
      (institutional buying is visible in the volume)
  R4. Reclaim candle is preferably bullish (close > open)
      A bearish reclaim candle (close < open but still above VWAP)
      is valid but weaker (-8 pts)
  R5. Entry: limit buy at VWAP + 0.15% on the close of
      the reclaim candle, OR on the next candle open

QUALITY HIERARCHY:
  TIER 1 (best): First VWAP reclaim of the session after a
    clean break below
  TIER 2: Second VWAP reclaim (first reclaim failed and price
    went back below, then reclaimed again)
    → -15 pts PQS (second reclaims fail more often)
  TIER 3: Third+ VWAP reclaim → do not trade
    (VWAP has lost its significance as a level)

CONTEXT REQUIREMENTS:
  X1. Only trade VWAP reclaims in the direction of the
      daily trend (if daily is up: long VWAP reclaims only)
  X2. Do not trade VWAP reclaims in the first 15 minutes
      of the session (VWAP is not yet meaningful)
  X3. Do not trade VWAP reclaims in the last 30 minutes
      (closing auction dynamics distort the signal)
  X4. SPY should not be in a sharply declining trend at
      the moment of the reclaim (market-wide selling
      overwhelms individual stock VWAP signals)

INVALIDATION:
  I1. Price closes back below VWAP after the reclaim candle
      (immediate failure — exit on the close)
  I2. Reclaim volume was below avg (weak hands, not institutions)
  I3. SPY drops more than 0.5% during the reclaim setup
```

### Target and stop calculation

```
TARGETS:
  TP1 = prior session high or next intraday resistance level
  TP2 = daily open price (if above VWAP reclaim)
  TP3 = daily high (trailing stop target)

STOP PLACEMENT:
  Stop = low of the consolidation below VWAP - (0.1 × ATR on 15M)
  This is the level where "sellers are back in control" — if
  price goes there after a VWAP reclaim, the setup has failed
  
TIME STOP: Exit by 15:30 ET regardless of position
  (never hold a VWAP reclaim into the closing auction)
```

### PQS modifiers specific to this pattern

```
+ First reclaim of the session: +10 pts
+ Reclaim volume > 2.0× session avg: +12 pts
+ Daily trend aligned with reclaim direction: +15 pts
+ Reclaim candle is a strong bullish engulfing: +8 pts
+ SPY also above its VWAP at moment of reclaim: +8 pts
+ Prior consolidation below VWAP lasted 3–6 candles
  (enough time but not too long): +7 pts
- Second reclaim attempt: -15 pts
- Bearish reclaim candle (close < open): -8 pts
- Volume on reclaim < 1.2× avg: -12 pts
- SPY declining more than 0.3% at moment of reclaim: -10 pts
- Reclaim attempted in first 15 or last 30 min: -20 pts
```

---

## Pattern 9: Wyckoff Accumulation / Distribution

**Category:** Institutional positioning / reversal  
**Best timeframes:** Daily (primary), Weekly (context)  
**Typical holding:** 15–60 days (position trade)  
**Base PQS:** 60

### What it is
Wyckoff describes the process by which institutional "smart money"
(the Composite Man) quietly accumulates stock at low prices before
a major uptrend (accumulation) or distributes stock at high prices
before a major downtrend (distribution). The pattern appears as a
period of sideways range-bound trading where price oscillates between
defined support (the creek) and resistance (the resistance line)
while the institutional player absorbs all available supply
(accumulation) or sells into all available demand (distribution).
Understanding Wyckoff explains WHY volatility squeezes happen —
the accumulation IS the compression.

### Phase structure (accumulation — memorize these labels)

```
PHASE A — Stopping the downtrend:
  PS  (Preliminary Support): First sign of demand after downtrend.
      Large volume, price bounces but quickly fails.
      NOT the bottom — just the first warning the trend may end.
  SC  (Selling Climax): The actual bottom. Volume extreme
      (highest in the entire decline or close to it). Panic selling.
      Price closes well off the low of the candle (buyers absorb).
  AR  (Automatic Rally): Sharp bounce from SC on decreasing volume.
      Sets the top of the range. Price will oscillate between
      AR high and SC low for the accumulation phase.
  ST  (Secondary Test): Price returns to test the SC area.
      Volume MUST be lower than SC (less selling pressure).
      Price may undercut SC slightly — this is a SPRING (see below).

PHASE B — Building the cause:
  The bulk of the accumulation time. Price oscillates in the
  trading range between AR high and SC low.
  Key events to identify:
    - Multiple tests of resistance (AR high): each test on
      declining volume = supply being absorbed
    - Multiple tests of support (SC low): each test on
      declining volume = demand holding
    - Upthrust (UT): price briefly breaks above AR high,
      then falls back. Tests supply. On low volume = bullish.
      On high volume = more supply to absorb.

PHASE C — The test (most important phase):
  SPRING: Price briefly breaks BELOW the SC low (the "creek"),
    appearing to fail — triggering stop losses of weak hands —
    then immediately reverses back above the range.
    Volume on the spring: LOW (no real selling — it's a shakeout).
    Volume on the recovery: increasing (institutions buying).
    The spring is the single most reliable Wyckoff entry signal.
    
  SPRING QUALITY:
    Type 1 (best): Barely undercuts SC low, immediate recovery,
      low volume on the undercut, high volume on recovery
    Type 2: Undercuts SC low by 1-3%, recovers within 2 candles
    Type 3 (weakest): Larger undercut, slower recovery
    
  LPS (Last Point of Support): After a spring, price rallies and
    then pulls back on LOW volume — the final shakeout before
    the uptrend. Ideal entry point.

PHASE D — Markup begins:
  SOS (Sign of Strength): Strong rally above the AR high on
    HIGH volume. Confirms accumulation is complete.
    This is the breakout — institutions have accumulated their
    full position and are now letting price run.
  BU (Back Up): Price pulls back to test the top of the
    trading range (now support). Low volume on the pullback.
    Secondary entry opportunity.

PHASE E — Trending:
  Price trends higher outside the trading range. The cause
  built during accumulation is now the effect.
```

### Mathematical definition

```
RANGE IDENTIFICATION:
  R1. Identify SC: candle with highest volume in the decline
      AND lower wick significantly longer than body (buying)
      Volume at SC must be ≥ 2× average volume of the prior
      20 sessions (climactic volume is the signature)
  R2. Identify AR: highest closing price within 10 sessions
      of SC
  R3. Trading range = SC low to AR high
  R4. Range duration must be ≥ 6 weeks on daily chart
      (< 6 weeks: not enough cause built for a meaningful move)
      Optimal: 3–6 months
      > 12 months: very powerful base, expect a large move

SPRING IDENTIFICATION:
  SP1. Price closes below SC low by 0.1–5%
       (> 5% undercut: may be a genuine breakdown, not a spring)
  SP2. Volume on the spring candle: < 75% of SC volume
       (ideally < 50% of SC volume — low volume spring = best quality)
  SP3. Price closes back above SC low within 1–3 candles
       of the spring candle
  SP4. The candle that recovers above SC low should have
       increasing volume vs the spring candle

LPS ENTRY (preferred entry):
  L1. After a spring and initial rally, price pulls back
  L2. Pullback stops at or above SC low (the range holds)
  L3. Volume on LPS pullback: declining (no distribution)
  L4. Entry: limit buy as price turns up from LPS
  L5. Confirmation: next candle closes above LPS high

SOS BREAKOUT ENTRY (alternative entry):
  S1. Price closes above AR high (the top of the range)
  S2. Volume: > 1.5× 40-session average (institutional participation)
  S3. Entry: limit buy at AR high + 0.5%

INVALIDATION:
  I1. Spring is followed by a close below the spring low
      (genuine breakdown — the range has failed)
  I2. SOS breakout fails (price closes back inside range
      within 3 sessions of the breakout — distribution)
  I3. Volume during Phase B is consistently HIGH on down days
      and LOW on up days (distribution disguised as accumulation)
      If this pattern is present: re-classify as distribution
```

### Target calculation

```
WYCKOFF POINT AND FIGURE TARGET METHOD:
  Count the horizontal width of the trading range
  Multiply by the box size and count
  This gives the minimum expected move (the "cause")
  
  SIMPLIFIED METHOD:
  Range height = AR high - SC low
  TP1 = AR high + (range height × 1.0)  [minimum target]
  TP2 = AR high + (range height × 2.0)  [full measured move]
  TP3 = AR high + (range height × 3.0)  [extended (powerful bases)]

STOP PLACEMENT:
  Spring entry: stop = spring low - (0.1 × ATR_14)
  LPS entry: stop = LPS low - (0.1 × ATR_14)
  SOS entry: stop = AR high - (0.5 × ATR_14)
```

### Distribution (mirror structure)
All phases are the mirror image. PSY (Preliminary Supply) instead
of PS. BC (Buying Climax) instead of SC. UTAD (Upthrust After
Distribution) instead of Spring — price briefly breaks ABOVE
resistance before collapsing. LPS becomes LPSY (Last Point of
Supply). Signs of Weakness (SOW) instead of SOS.

### PQS modifiers specific to this pattern

```
+ Spring is Type 1 (low volume undercut, immediate recovery): +20 pts
+ Range duration 3–6 months (ideal cause building): +12 pts
+ Range duration > 6 months (powerful base): +18 pts (use this)
+ Volume clearly higher on up days than down days in Phase B: +12 pts
+ Spring volume < 50% of SC volume (very low = very bullish): +10 pts
+ Fundamental improvement during the accumulation phase
  (earnings growth, margin expansion visible in filings): +15 pts
+ SOS breakout volume > 2× avg: +10 pts
- Range duration < 6 weeks (insufficient cause): -20 pts
- Spring volume > 75% of SC volume (too much selling): -15 pts
- Phase B shows distribution characteristics: -25 pts
  (re-evaluate as distribution, not accumulation)
- No clear SC identifiable (ambiguous starting point): -12 pts
```

---

## Confluence combinations (most powerful multi-pattern setups)

When multiple patterns from this document occur simultaneously
on the same symbol, the combined signal quality exceeds the
sum of the parts. These are the highest-conviction setups.

### Combination 1: Wyckoff spring + Volatility squeeze
**Interpretation:** The accumulation range IS the compression.
When the spring fires and the squeeze also fires on the daily
chart at the same time, institutions are finishing their
accumulation exactly as volatility releases.
**PQS:** Take the higher of the two individual PQS scores + 25 pts
**Signal strength:** Floor of 0.85

### Combination 2: Ascending triangle + RSI divergence on pullback
**Interpretation:** The triangle's rising lows are confirmed by
RSI making higher lows — double confirmation that selling
pressure is genuinely exhausting.
**PQS:** Average of the two PQS scores + 15 pts

### Combination 3: Bull flag + VWAP reclaim
**Interpretation:** The flag is forming above VWAP, and the
reclaim of VWAP on the pullback within the flag gives a precise
intraday entry into the larger flag setup.
**PQS:** Higher of the two PQS scores + 12 pts

### Combination 4: Cup and handle + Volume squeeze in the handle
**Interpretation:** The handle compression is confirmed by a
volatility squeeze — the handle is not just consolidation but
active coiling. The breakout from the handle will be explosive.
**PQS:** Average of the two PQS scores + 18 pts

### Combination 5: Double bottom + Class A RSI divergence
**Interpretation:** The two lows of the double bottom are confirmed
by RSI divergence — the textbook highest-quality reversal setup.
Both patterns are independently identifying the same turning point.
**PQS:** Average of the two PQS scores + 20 pts
**Signal strength:** Floor of 0.80

---

## Agent implementation notes

### How `analyst.py` should use this document

```python
# Pseudocode for pattern detection flow

def run_technical_lens(symbol: str, ohlcv: DataFrame,
                       timeframe: str) -> list[Signal]:
    signals = []
    
    # 1. Run each pattern detector
    detectors = [
        detect_bull_bear_flag,
        detect_double_bottom_top,
        detect_rsi_divergence,
        detect_ascending_descending_triangle,
        detect_inside_bar_nr7,
        detect_cup_and_handle,
        detect_volatility_squeeze,
        detect_vwap_reclaim,
        detect_wyckoff_accumulation,
    ]
    
    pattern_results = []
    for detector in detectors:
        result = detector(ohlcv, timeframe)
        if result.detected:
            pattern_results.append(result)
    
    # 2. Check for confluence combinations
    combination_bonus = check_combination_bonuses(pattern_results)
    
    # 3. Apply universal confluence modifiers
    for result in pattern_results:
        result.pqs += apply_universal_modifiers(result, ohlcv, timeframe)
        result.pqs += apply_timeframe_confluence(result, symbol, timeframe)
        result.pqs += combination_bonus.get(result.pattern_name, 0)
        result.pqs = min(result.pqs, 100)  # cap at 100
    
    # 4. Filter by minimum score
    qualifying = [r for r in pattern_results if r.pqs >= 55]
    
    # 5. Convert to Signal objects
    for result in qualifying:
        signal = Signal(
            symbol=symbol,
            lens="technical",
            direction=result.direction,
            strength=result.pqs / 100,
            timeframe=timeframe,
            key_levels={
                "entry": result.entry_price,
                "stop": result.stop_price,
                "tp1": result.tp1,
                "tp2": result.tp2,
                "invalidation": result.invalidation_level
            },
            evidence=[
                {"type": "pattern", "ref": result.pattern_name},
                {"type": "pqs", "ref": f"PQS={result.pqs}"},
                *result.evidence_items
            ],
            invalidation_condition=result.invalidation_condition
        )
        signals.append(signal)
    
    return signals
```

### Key rules for pattern detection code

1. Every pattern detector returns a typed result object, never
   a dict or bool. The result must include: `detected`, `direction`,
   `pqs_base`, `entry_price`, `stop_price`, `tp1`, `tp2`,
   `invalidation_level`, `invalidation_condition`, `evidence_items`.

2. Pattern detectors receive OHLCV data for the trigger timeframe
   PLUS the timeframe above it for confluence checks. They do not
   fetch their own data.

3. PQS is computed inside the detector (base + pattern-specific
   modifiers). Universal modifiers are applied by the caller
   (`run_technical_lens`) after all detectors have run.

4. A detector that finds a partial pattern (some conditions met
   but not all) should return `detected=False` with a
   `watchlist_candidate=True` flag and the conditions that are
   not yet met. This feeds the watchlist feature.

5. All numeric thresholds in this document are defaults.
   They are loaded from the strategy config YAML at runtime
   so they can be tuned without changing code.
   Example: `squeeze_min_duration: 6` in the YAML overrides
   the hardcoded 6 in the detector.

---

*End of Pattern Recognition Document — Version 1.0.0*  
*Next: Universe Filter Presets YAML files*  
*Next: Phase 3 build prompt (broker layer)*
