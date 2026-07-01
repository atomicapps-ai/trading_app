# S6 — Capitulation "V" Mean-Reversion

**Source video:** k-X0164r66U (Lance) — mean-reversion half. **Family:** mean reversion / exhaustion.
**Data fit:** daily stocks ✅. **Verdict: ⚠️ MARGINAL** — positive and beats control, but thin edge.

## The strategy (plain rules)
After a sharp, extended, accelerating sell-off on **massive volume** (capitulation / emotional
exhaustion), don't catch the knife — wait for the **down-trend to break** and buy the "right side of
the V." Initial stop at the low, then trail prior daily-bar lows.

## Precise definitions (as backtested — H-MR1 + H-MR3)
- **Capitulation flag:** 10-day return ≤ **−10%** AND today's volume ≥ **2× the 20-day average**
  AND today is a down day.
- **Entry:** first **close above the prior day's high** within 8 bars of the flag (trend break) → next open.
- **Stop:** the **5-day low**. **Exit:** trail the prior-bar low, else 40-bar time stop. Long only.

## Backtest configuration
Universe 90 daily stocks · 2006–2026 · daily bars · chronological IS/OOS · 10 bps cost in R ·
random-direction control · R = entry − 5-day low.

## Results (net of costs)
| Window | n | win% | expectancy | profit factor | avg win / loss | max DD (R) |
|---|---|---|---|---|---|---|
| **All** | 1,157 | 33.2% | **+0.031R** | 1.13 | +0.80 / −0.35 | −31 |
| In-sample | 578 | 30.4% | +0.016R | 1.07 | +0.81 / −0.33 | −31 |
| Out-of-sample | 579 | 35.9% | +0.046R | 1.19 | +0.80 / −0.38 | −24 |
| Random control | 1,157 | 44.0% | **−0.071R** | 0.75 | +0.48 / −0.50 | −87 |

## Reading the result
- Positive and **OOS ≥ IS**, and the control is clearly negative, so the setup beats random. But the
  per-trade edge (**+0.03R**) is thin and the trailing-prior-bar-low exit cuts winners early
  (avg win only +0.80R) — it protects capital but caps the upside the video promises.
- Smaller, shallower drawdown than the trend strategies — capitulation reversals are quick.

## Caveats / next steps
- The thin edge likely lives in the *exit*. Test: hold to a fixed target (2R/3R) instead of trailing
  prior-bar lows; vary the capitulation thresholds (−8/−12%, 1.5×/3× volume); add a regime gate.
- Lance's real edge was discretionary (reading the specific tape); the mechanical proxy is a floor,
  not a ceiling.
