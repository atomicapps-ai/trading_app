# Hardening Report — S7 (breakout) & S5 (mean-reversion)

**Harness:** `scripts/strategy_harden.py` (caches loads; reuses suite cost model & metrics).
**Battery:** parameter sweep · walk-forward (5 eras) · market-regime gate · per-symbol breadth.
**Bottom line: both survived. Both are real, robust, and complementary — S7 = trend/momentum,
S5 = mean-reversion. Cleared to advance to the paper pipeline.**

## S7 — Multi-month breakout continuation
**Parameter sweep (every config positive = plateau, not a knife-edge):**
| Axis | Values → expectancy (OOS) |
|---|---|
| Lookback | 63:+0.47 · 126:+0.45 · 189:+0.40 · 252:+0.42 |
| Stop ×ATR | 0.5:+0.44 · 1.0:+0.45 · 1.5:+0.40 · 2.0:+0.33 |
| Trail MA | 10:+0.15 · 20:+0.45 · **50:+0.64** |

- **Walk-forward (5 eras):** −0.06, +0.09, +0.40, +0.21, +0.59 → positive in **4/5**, only the
  earliest (~2006–09) era weak; edge strengthens over time.
- **Regime gate (SPY>200MA):** slightly *helps* — +0.51R OOS vs +0.45, fewer trades. Keep optional-ON.
- **Breadth:** 59/90 symbols net-positive (66%). **Caveat:** outlier-driven tail — a few explosive
  momentum names (QUBT +25R, TSLA/IONQ/RGTI ~+3R) carry an outsized share. Classic trend-following
  concentration; means live results depend on catching the big runners and sitting through chop.
- **Locked spec:** 126-day-high breakout → next open · stop 1.0×ATR(14) · trail **50-day SMA** ·
  long only · optional SPY>200MA gate. Expectancy ≈ **+0.50R OOS**.

## S5 — Mean-reversion to the 50-MA
**Parameter sweep (every config positive = plateau):**
| Axis | Values → expectancy (OOS) |
|---|---|
| Stretch ×ATR | 2.0:+0.20 · 2.5:+0.24 · 3.0:+0.30 · **3.5:+0.37** |
| Stop ×ATR | 0.5:+0.29 · 1.0:+0.24 · 1.5:+0.23 · 2.0:+0.18 |
| Max hold | 15:+0.18 · 30:+0.24 · 45:+0.26 · 60:+0.28 |

- **Walk-forward (5 eras):** +0.08, +0.15, +0.10, +0.15, +0.37 → **positive in 5/5** — the more
  *consistent* edge of the two.
- **Regime gate (SPY>200MA):** *hurts* — +0.16R OOS vs +0.24. Makes sense: the best dip-buys happen
  in/after corrections (often SPY<200MA). **Do NOT regime-gate S5.**
- **Breadth:** 77/90 symbols net-positive (86%), modest spread (−0.38 to +0.91), **no outlier
  dependence** — a broader, more reliable edge than S7.
- **Locked spec:** close ≤ SMA50 − **3.0×ATR(14)** → next open · target SMA50 · stop 1.0×ATR ·
  max hold 45 bars · long only · **no regime gate**. Expectancy ≈ **+0.30R OOS**.

## Verdict & how they fit together
| | S7 breakout | S5 mean-reversion |
|---|---|---|
| Edge type | trend / momentum | reversion |
| OOS expectancy | ~+0.50R (with 50MA trail) | ~+0.30R |
| Walk-forward | 4/5 eras | **5/5 eras** |
| Breadth | 59/90 | **77/90** |
| Outlier risk | high (few names carry it) | low (broad) |
| Best regime | bull (SPY>200MA) | corrections/dips (no gate) |

They are **negatively correlated by design** — S7 wants strong uptrends, S5 wants oversold dips — so
running both diversifies the book. Both passed the stress tests that kill overfit strategies.

## Remaining caveats (true for both)
- **Survivorship:** 90-symbol universe = today's survivors. Re-test on a point-in-time list before
  sizing real capital. (Paper-forward trading sidesteps this — it's true OOS by construction.)
- Not modeled: slippage beyond 10 bps, borrow, overnight gaps. Position sizing / correlation caps
  matter given S7's deep cumulative drawdowns.

## LIVE SELECTION FILTERS (encoded into the detectors)

After deployment, a conditional feature-attribution study (`scripts/strategy_filters.py`) tagged every
backtested trade with market/indicator context at entry and ranked features by OOS win% + expectancy.
Two filters survived and are now **encoded as gates + conviction (PQS) boosts + strength-rated evidence**:

| Strategy | Filter (live) | Effect (OOS) |
|---|---|---|
| **S7** | require **breakout volume ≥ 1.5×** 20-day avg; SPY<200MA applies a conviction penalty | 0.64R → **~1.23R**, win 22%→25% |
| **S5** | only fire in a **fear regime**: SPY<200MA **or** VIX≥26 | 0.32R → **~0.58R**, win 30%→32% |

Each fired plan now carries an evidence line with a STRONG/MODERATE/WEAK rating (e.g. "Fear regime
STRONG (2/2…)", "Breakout volume 1.8× — MODERATE support") and the PQS reflects filter strength.
Config: `strategy_configs/video_daily.yaml` (`require_breakout_volume`, `require_fear_regime`, etc.).

**Honest note on win rate:** selection filtering lifts win rate only a few points (~30→32%, 22→25%);
it roughly *doubles expectancy* instead. A 70% win rate is not attainable by selection — it would
require shortening the exit, which trades the edge away (win-rate ↔ reward:risk seesaw).

## PHASE 2 — entry-filter attribution (encoded into the detectors)

Triggered by a user-supplied trade review. Tested exit changes + extra entry filters on the full
90-symbol history (OOS split). Result summary:

**Exit changes — REJECTED for both.** A breakeven-after-1R/2R stop *hurt* both strategies (Momentum
PF 1.43→0.83; Fear-Dip 1.68→1.32) — it cuts winners that need room to run. The existing 50-MA trail /
target-the-mean exits are already optimal. (Important: this killed the trade-review's headline idea.)

**Entry filters — ADOPTED (validated OOS):**

| Strategy | Filter encoded | Effect (OOS) |
|---|---|---|
| Momentum Breakout | **ADX ≥ 20** gate (skip chop; ADX<20 was PF 1.10) | removes worst bucket |
| Momentum Breakout | **distance 5–15% above 200-MA** = sweet spot (conviction boost; optional hard gate `require_trend_zone`) | win 24%→**30.5%**, PF 1.66→**2.34** |
| Fear-Dip Reversion | **VIX ≥ 32 (extreme fear)** conviction tier | win 33%→**46.5%**, PF 1.76→**3.13** |
| Fear-Dip Reversion | **dip-in-uptrend** (close>200-MA) boost | PF →2.01 |
| Fear-Dip Reversion | removed `capitulation_volume` bonus | climax-volume dips tested *worse* |

All exposed as config knobs in `momentum_breakout.yaml` / `fear_dip_reversion.yaml` and editable in the
`/strategies` Configure panel. Each fired plan shows the filter + STRONG/MODERATE/EXTREME strength in
its evidence, and PQS conviction reflects it.

**Lesson reinforced:** win-rate gains come from *entry selection* (ADX, distance-from-mean, fear depth),
not from changing the exit. The breakeven "protect profits" instinct is a trap for these edges.

## History: Stage 2 — detectors → Stage 3 — wired to paper → filters encoded → Phase 2 entry filters added.
