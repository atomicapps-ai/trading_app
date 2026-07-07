# Tm0dkf8_giA — "How to Trade Breakouts with the Volatility Contraction Pattern" (TraderLion)

Source: <https://www.youtube.com/watch?v=Tm0dkf8_giA>

## Rules (mechanical) — daily/weekly US stocks
- **VCP base:** consolidation tightening left-to-right under a prior high, ≥2 successive contractions each shallower than the last, volume drying up into a tight final contraction (<~10%), preceded by a strong uptrend / relative strength.
- **Entry:** breakout through the pivot (prior resistance) on above-average volume.
- **Stop:** low of the last contraction (or low of day). Move to break-even quickly; you're right fast or out for a small loss.

## Verdict: REJECT — duplicate family / needs a custom detector.
This is the same **volatility-contraction-then-breakout** thesis already assessed for video I8Usc5lza_Y and already **deployed live as `coil_breakout`** (ATR10<ATR50 contraction → expansion breakout, uptrend), validated at **OOS PF 2.13 / +0.42R**. A faithful Minervini VCP (detecting successive decreasing-depth contractions + pivot) needs a dedicated detector — `agents/detectors/vcp_absorption.py` exists but isn't wired into the live registry (`ALL_DETECTORS`) and replay_swing has no exit branch for it, so it can't be scored without new code. Recorded as duplicate — the vol-contraction-breakout edge is already on the books as a pass (coil_breakout); a distinct faithful VCP would need a custom detector not built here.
Status: rejected
