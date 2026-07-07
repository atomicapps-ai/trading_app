# FjxG1-dGzyU — "The magical trendline break strategy"

Source: <https://www.youtube.com/watch?v=FjxG1-dGzyU>

## Rules — trendline break + confirmation
- Draw a trendline connecting higher-lows (uptrend) or lower-highs (downtrend); needs **≥3
  touches** to be "valid."
- Wait for price to **break** the trendline — but don't enter on the break itself.
- Wait for confirmation (a retest / continuation past the break, "Point C"), then enter; scale
  out ("close half of the trade").

## Verdict: REJECT — trendline drawing is inherently discretionary
The entire setup is anchored on a hand-drawn trendline: which swings to connect, how many
touches "count," and what slope is valid are all subjective, and no two chartists draw the same
line. Without a deterministic line there is no deterministic break, entry, stop, or target, so
the strategy can't be coded faithfully. This is the discretionary trend-line family (same class
as the fakeout/trendline videos in this run). The one mechanizable cousin — a break of a
rolling swing structure — is already covered by the live `momentum_breakout` / `coil_breakout`.
Status: rejected
