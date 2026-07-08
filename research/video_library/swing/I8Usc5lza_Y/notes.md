# I8Usc5lza_Y — "Volatility Contraction Pattern (VCP)" (Minervini-style swing)

Source: <https://www.youtube.com/watch?v=I8Usc5lza_Y>

## Rules (mechanical) — daily US stocks
- **Trend template (prerequisite):** price above the 50/150/200-day MAs (properly stacked), near the 52-week high, strong relative strength.
- **VCP base:** a series of successive contractions where each pullback is *shallower* than the last (e.g. 25% → 9% → 3%), volume drying up into the final tight area near the highs.
- **Entry:** breakout above the last (tightest) contraction's high on expanding volume. **Stop:** low of that last contraction. **Exit:** fixed ~3R, or trail the trend for multi-baggers.

## Verdict: REJECT — duplicate family / promising but needs a custom detector.
This is a genuine, mechanical daily swing pattern — but its edge is the *volatility-contraction-then-breakout* thesis, which the project has already mined and **deployed live as `coil_breakout`** (ATR10<ATR50 contraction → expansion-thrust breakout of a 30-day range, uptrend), validated at **OOS PF 2.13 / 55% win / +0.42R** (sourced from the sibling video YWBLKRLnrZ0). A *faithful* Minervini VCP (detecting successive decreasing-depth contractions + the full trend template) would require a dedicated detector — `agents/detectors/vcp_absorption.py` exists but is not wired into the live registry (`ALL_DETECTORS`) and replay_swing has no exit branch for it, so it can't be scored without new code. Not building that now. Recorded as: promising, but the vol-contraction-breakout edge is already live (coil_breakout) and a distinct faithful VCP needs a custom detector.
Status: rejected
