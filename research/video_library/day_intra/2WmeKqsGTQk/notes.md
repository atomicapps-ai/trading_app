# 2WmeKqsGTQk — false_break_fade

## Backtest result (scripts/backtest_fade_candidates.py)
- False-break fade (first 4h range; 5m body closes outside then back inside -> fade to opposite edge, 2R). Backtested FX 5m + gold, 2015-2025, net: pooled OOS net PF 0.96 (NY) / 0.95 (London) — beats the fade control (0.80) and EURUSD is net-positive (1.08), but ~breakeven-negative pooled and never clears the 1.3 bar. Closest of the whole day-trade pass, but not a pass. Reject.
- Verdict: REJECTED (informative — backtested, below bar).

## Fidelity re-test — the "closest lead" has no edge at any anchor (2026-07-20)

The original verdict called this "the closest of the whole day-trade pass" because it
"beat the fade control 0.80". That comparison was invalid: `control_fade` trades **1:1**
while this strategy trades **2R**, so it compared two different payoff geometries.

Re-run against a control that holds timing, stop distance and target geometry fixed and
randomises only **direction** (`python -m scripts.bt_fbf_faithful --variants all`), with
the five ways the detector diverged from the video corrected — the creator's actual 4-hour
NY range (00:00–04:00 ET, where the old harness used a 13:00-UTC block that defined the
"range" over the London/NY overlap and then faded breaks of it in the quiet afternoon,
inverting the premise); every re-entry per session instead of one; entry at the next bar's
open; his explicit ">1% beyond the range → stop fading, go with it" rule; and a cap on
impractically wide stops:

| variant | OOS PF | matched control | edge |
|---|--:|--:|---|
| original 13:00-UTC anchor, 1 trade/day | 0.818 | 0.828 | none |
| faithful 4h NY range, every re-entry | 0.778 | 0.787 | none |
| + the >1% no-fade rule | 0.778 | 0.774 | none |
| + capped stop distance | 0.783 | 0.781 | none |
| London anchor | 0.802 | 0.797 | none |
| **SPY/QQQ/IWM/DIA RTH, 21y, n=40,483** | **0.750** | **0.751** | none |

The equity-native test the original write-up asked for has now been run (21 years, 40k
trades) and it fails there too. **The setup sits exactly on its coin-flip baseline in
every configuration and on both asset classes** — the apparent result is entirely payoff
geometry. Making the implementation faithful moved the numbers and changed nothing.

Verdict unchanged: **REJECTED** — but now on valid grounds. See `PROCESS_AUDIT.md`.
