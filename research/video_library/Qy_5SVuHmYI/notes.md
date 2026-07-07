# Qy_5SVuHmYI — "The best way to use the ATR indicator"

Source: <https://www.youtube.com/watch?v=Qy_5SVuHmYI>

## Content — ATR explainer (volatility + stops + money management)
- ATR(14) measures volatility (average pips of last 14 candles); it does **not** give direction.
- "Strategy": find a relatively **low ATR** (contraction) → volatility will expand soon → a
  breakout is coming; then **predict the direction** and enter, using ATR to size the stop.
- Bonus: ATR-based stop-loss placement and a money-management rule.

## Verdict: REJECT — indicator tutorial, no complete/new mechanical edge
Two problems. First, the entry has no defined edge: the video explicitly says you must "predict
the direction" of the breakout yourself — that's discretionary, and ATR is direction-agnostic by
its own admission. Second, the mechanical part it *does* describe — low-ATR contraction → expect
an expansion breakout — is precisely the live `coil_breakout` kernel (ATR10<ATR50 contraction →
expansion thrust). ATR-based stop sizing is already used throughout the app's risk logic. So
there's no complete, testable strategy here that isn't already validated and live.
Status: rejected
