# S4 — Supply/Demand Zone Retest (+ R:R filter)

**Source video:** e-QmGJU1XYc ("3-step formula: structure + supply/demand + R:R").
**Family:** structure + zone retest. **Data fit:** daily stocks ✅.
**Verdict: ❌ as taught (loses money); ⚠️ MARGINAL once the R:R≥2.5 filter is added.**

## The strategy (plain rules)
1. Define trend with a strict "valid-low" rule (a low is only valid once the prior high breaks).
2. Trade **with** the trend off zones: in an uptrend buy a **demand zone** (the consolidation candle
   before an impulse up); stop below the zone, target the recent high.
3. Only take setups whose reward:risk ≥ **2.5:1**.

## Precise definitions (as backtested)
- **Trend filter:** close > **SMA200** → longs only.
- **Demand zone:** a candle whose next 3 bars gain ≥ **1.5×ATR(14)**; zone = that candle's [low, high].
- **Entry:** later **retrace into the zone** (zone-high touched) → zone high. **Stop:** zone low − 0.1×ATR.
- **Target:** prior 20-bar swing high. **Variant:** require reward:risk ≥ 2.5 (H-RR1).

## Backtest configuration
Universe 90 daily stocks · 2006–2026 · daily bars · chronological IS/OOS · 10 bps cost in R ·
random-direction control. Two runs: unfiltered, and with the R:R≥2.5 floor.

## Results (net of costs)
**Unfiltered (as taught):**
| Window | n | win% | expectancy | PF |
|---|---|---|---|---|
| All | 15,395 | 44.5% | **−0.068R** | 0.88 |
| OOS | 7,698 | 44.4% | −0.054R | 0.91 |
| Random control | 15,395 | 48.0% | −0.117R | 0.80 |

**With R:R ≥ 2.5 filter (H-RR1):**
| Window | n | win% | expectancy | PF |
|---|---|---|---|---|
| All | 4,338 | 24.1% | **+0.038R** | 1.05 |
| In-sample | 2,169 | 23.4% | +0.042R | 1.05 |
| Out-of-sample | 2,169 | 24.8% | +0.034R | 1.04 |
| Random control | 4,338 | 49.3% | −0.103R | 0.88 |

## Reading the result
- **As taught, it loses** (−0.068R) — only slightly less bad than random, i.e. the demand-zone
  retest itself carries little edge. This contradicts the video's "profitable every month" claim.
- **The R:R≥2.5 filter is the active ingredient (H-RR1):** it flips the strategy positive (+0.038R)
  by discarding low-payoff setups and keeping only high-reward ones (avg win +3.7R at 24% win). The
  edge is payoff geometry, not the zone — the same recurring lesson as the ICT/ORB work.
- Even filtered, the edge is thin and barely above breakeven after costs.

## Caveats / next steps
- The "valid-low" structural trend definition (H-SD2) was approximated with an SMA200 gate; test the
  precise swing-structure version. Sweep the R:R floor (2.0 / 2.5 / 3.0) and the impulse threshold.
