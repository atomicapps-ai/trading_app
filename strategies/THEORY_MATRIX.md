# Theory Matrix — Pivot / Price-Action Strategy Research

The master registry of every theory we test, its hypothesis, status, and verdict. This
is the human-readable index; the machine-readable run-by-run metrics accumulate in
`data/research/results_matrix.csv` (appended automatically by `scripts/strategy_lab.py`).
Full write-ups live in `strategies/PIVOT_RESEARCH_LOG.md`.

**Method (constant across all theories):** expectancy = mean R per trade after 10 bps
round-trip cost · chronological out-of-sample (OOS) second half · random-direction
control on identical triggers · ~90 symbols of local daily/intraday data.

**Verdict scale:** ✅ validated (positive OOS, beats control) · ⚠️ marginal/inconclusive
· ❌ rejected · 🐛 measurement bug · ⏳ queued · 🔬 in progress.

---

## A. Level interaction (how price behaves AT a structural level)

| ID | Hypothesis | Status | Result / note |
|----|-----------|--------|---------------|
| T1 | At a touch, a specific O/H/L/C sits closest to the level | ✅ measured | close/open nearest (~33–39%); wick extreme (L@support, H@resistance) *least* (13–17%) → price pierces, not taps |
| T2 | Entry reference (level vs close vs next-open) changes expectancy | ✅ measured | level best of the three, but **all negative** |
| T4 | **Continuation (trade the break) beats reversal (fade) at the level** | ⏳ next | evidence (T1 + fade<random) points here |
| T5 | "Close-beyond" confirmation (enter only on a confirmed break) | ⏳ queued | — |
| T6 | Pierce depth predicts reversal vs continuation | ⏳ queued | — |
| T7 | First touch behaves differently from later retests | ⏳ queued | needs T3 fix |

## B. Freshness / exhaustion (the "weakening" theory)

| ID | Hypothesis | Status | Result / note |
|----|-----------|--------|---------------|
| T3 | Expectancy decays as a zone is retested | 🐛 bug | counter includes formation bars → no "fresh" bucket; fix to count after confirm |
| T8 | Older (longer-standing) levels behave differently | ⏳ queued | — |
| T9 | Pivot Strength (left/right bars) changes reliability | ⚠️ partial | strength 5 least-bad but still <random |

## C. Multi-timeframe confluence

| ID | Hypothesis | Status | Result / note |
|----|-----------|--------|---------------|
| T10 | Weekly+Daily confluence beats single timeframe | ⏳ queued | — |
| T11 | Tri-confluence (W+D+4h) is the strongest setup | ⏳ queued | needs 4h (resample 1h) |
| T12 | Round-number confluence adds edge | ⏳ queued | — |

## D. Indicator confluence (other indicators, as you asked)

| ID | Hypothesis | Status | Result / note |
|----|-----------|--------|---------------|
| T13 | RSI oversold@support / overbought@resistance gates better trades | ⏳ queued | reuse indicator_service |
| T14 | RSI divergence at the level | ⏳ queued | — |
| T15 | MACD cross / histogram turn at the level | ⏳ queued | — |
| T16 | Stochastic confirmation at the level | ⏳ queued | — |
| T17 | 50/200 SMA sitting near the level (MA confluence) | ⏳ queued | — |
| T18 | Bollinger-band extreme + level | ⏳ queued | — |

## E. Volume

| ID | Hypothesis | Status | Result / note |
|----|-----------|--------|---------------|
| T19 | Volume spike on the touch (climax) marks reversals | ⏳ queued | — |
| T20 | Volume dry-up into the level | ⏳ queued | — |
| T21 | Relative volume vs 20-day average as a filter | ⏳ queued | — |

## F. Volatility / regime

| ID | Hypothesis | Status | Result / note |
|----|-----------|--------|---------------|
| T22 | ATR-based stop beats fixed-% stop | ⏳ queued | — |
| T23 | Fade only in range (low ADX); break only in trend (high ADX) | ⏳ queued | likely high-value given T4 |
| T24 | Market regime (SPY trend) gates direction | ⏳ queued | — |

## G. Candle confirmation

| ID | Hypothesis | Status | Result / note |
|----|-----------|--------|---------------|
| T25 | Engulfing / pin-bar at the level confirms | ⏳ queued | — |
| T26 | Wick-rejection size predicts the bounce | ⏳ queued | — |

## H. Exit mechanics

| ID | Hypothesis | Status | Result / note |
|----|-----------|--------|---------------|
| T27 | Target = next opposing pivot beats fixed R | ⏳ queued | — |
| T28 | Trailing stop vs fixed target | ⏳ queued | — |
| T29 | Time-stop length optimization | ⏳ queued | — |

## I. Context gates

| ID | Hypothesis | Status | Result / note |
|----|-----------|--------|---------------|
| T30 | Earnings-proximity gate (skip near earnings) | ⏳ queued | needs events MCP/data |
| T31 | Sector/peer confluence | ⏳ queued | — |
| T32 | Day-of-week / seasonality | ⏳ queued | — |

## J. Video-mined hypotheses (ICT/SMC + ORB — see `research/video_library/`)

Mined from 4 YouTube strategies. Method note: these are **intraday** ideas; our test cache is
15m stock bars (their native habitat is 1m forex/futures @ NY open), so results approximate.
Common finding: **the directional triggers are coin-flips; the edge is payoff geometry.**

| ID | Hypothesis | Status | Result / note |
|----|-----------|--------|---------------|
| ORB1 | 30m opening-range break + retest has positive expectancy | ✅ first-pass | 15m, 6 sym: retest OOS +0.102R, win 26.6% |
| ORB2 | Retest entry beats chasing the breakout close | ✅ first-pass | retest +0.102R vs chase +0.004R OOS |
| ORB3 | VWAP / 8–21 EMA confluence at the retest improves it | ⏳ queued | — |
| H-ICT1 | CHoCH/BOS (close beyond pivot) predicts continuation | ❌ rejected | 23k trades: 49.3% win, −0.013R = random |
| H-ICT2 | CHoCH + structural stop + asymmetric TP is net positive | ✅ first-pass (thin) | 1:4 → +0.066R OOS (21% win); 1:2 → +0.027R (34%) |
| H-ICT3 | FVG acts as S/R (continuation after retest) | ⚠️ marginal | direction-only +0.007R ≈ random |
| H-ICT4 | "Don't-take" filters (weak close, chop, news) lift expectancy | ⏳ queued | — |
| H-ICT5 | Confluence (CHoCH+0.618 fib+FVG+inflection) beats CHoCH alone | ⏳ queued | the key untested claim; needs 1m data |
| H-ICT6 | Targeting 15m FVG midpoints captures the move | ⏳ queued | — |
| H-ICT8 | CCT: consecutive strong same-dir candles → continuation | ⏳ queued | only novel piece of Cj09mzu5_oU |
| H-ICT9 | Wick-rejection (fail to close beyond level) → reversal | ⏳ queued | overlaps T26; wick = non-confirmation |
| H-ICT10 | Earlier entry = higher R:R, lower win rate | ✅ consistent | our 1:2→1:4 sweep confirms (34%→21% win, exp ↑) |

**Cross-link:** H-ICT1/H-ICT2 corroborate **T4** (continuation > fade) and **T5** (close-beyond
confirmation) — the break carries no *directional* edge, but *trading* the break with a structural
stop and a runner is mildly positive. Reinforces **T22** (ATR/structural stop) and **T23** (regime).

## K. Video batch 2 hypotheses (queued for the backtest series)

7 more videos mined (`0L6Rcgp6j7Y, 8a3QNHOD7-I, I29peidTQxU, e-QmGJU1XYc, j8Q3MIwGYOk, k-X0164r66U`,
+ the ORB Short). **Several fit our daily-stock data directly** — those are prioritized. None tested yet.

| ID | Hypothesis | Source | Data fit | Status |
|----|-----------|--------|----------|--------|
| H-PA1 | Big-body, no-wick candle marks a level that holds on retest | 0L6Rcgp6j7Y | daily stocks ✅ | ⏳ |
| H-PA2 | Price reverts to the 50-MA when stretched far from it | 0L6Rcgp6j7Y | daily ✅ | ⏳ |
| H-PA3 | Accelerating momentum → continuation after shallow pause | 0L6Rcgp6j7Y | daily/15m | ⏳ |
| H-PA4 | Shallow pullback (holds >0.382 fib) → continuation; deep → reversal | 0L6Rcgp6j7Y | daily ✅ | ⏳ |
| H-SW1 | NY-open sweep of Asia/London extreme → reverse to opposite session | 8a3QNHOD7-I | FX/futures 1–15m ⚠️ | ⏳ |
| H-SW2 | "First 5m retrace-candle close back" beats trading the level naked | 8a3QNHOD7-I | intraday ⚠️ | ⏳ |
| H-SD1 | Demand/supply-zone retest, trend-aligned, continues | e-QmGJU1XYc | daily ✅ | ⏳ |
| H-SD2 | Strict "valid-low" BOS (low valid only after prior high breaks) defines trend | e-QmGJU1XYc | daily ✅ | ⏳ |
| H-RR1 | An R:R ≥ 2.5 floor lifts net expectancy (vs survivorship) | e-QmGJU1XYc | any ✅ | ⏳ |
| H-MAC1 | Presidential cycle: buy ~2y pre-election, sell election year | j8Q3MIwGYOk | index daily ✅ | ⏳ |
| H-BOS-CC | BOS body-close (not wick) confirmation lifts the break edge | j8Q3MIwGYOk | daily/15m ✅ | ⏳ |
| H-FIB1 | Fib golden-zone (0.618–0.79) + same-dir FVG reversal | j8Q3MIwGYOk | 15m/daily | ⏳ |
| H-MR1 | Buy "right side of the V" after capitulation, trail daily-bar lows | k-X0164r66U | daily ✅ | ⏳ |
| H-MR3 | Volume-climax filter improves capitulation-reversal entries | k-X0164r66U | daily ✅ | ⏳ |
| H-CONT1 | Multi-month breakout (in-play + catalyst) continues | k-X0164r66U | daily ✅ | ⏳ |
| H-CONT2 | 20-MA / prior-daily-bar-low trailing stop vs fixed target | k-X0164r66U | daily ✅ | ⏳ |

**Series priority (best data fit first):** H-MR1/H-CONT1/H-CONT2 (Lance, daily), H-SD1/H-SD2/H-RR1
(structure+zones, daily), H-PA1/H-PA2/H-PA4 (price-action, daily), H-MAC1 (index seasonality),
H-BOS-CC (sharpens our close-confirm test). Intraday-only (H-SW1/H-SW2, H-FIB1) flagged for the
regime caveat / future FX data.

---

## Standings

- **Tested:** T1 (✅ measured), T2 (✅ measured), T3 (🐛), T9 (⚠️), ORB1/ORB2 (✅ first-pass), H-ICT1 (❌), H-ICT2/H-ICT10 (✅ first-pass), H-ICT3 (⚠️).
- **Rejected so far:** naive fade-at-level (all entry refs, all configs) — see PIVOT_RESEARCH_LOG.md Iteration 1; **CHoCH/FVG as directional predictors** (coin-flips — see video_library).
- **Recurring lesson (3 independent sources now):** edge comes from **payoff geometry** (structural stop + let winners run), not from setup prediction. ORB retest, CHoCH-with-stop, and the pivot break all converge on this.
- **Next up:** **T4 (continuation vs reversal)** — the decisive fork the data is pointing at — then T3 fix, T23 (regime gate), and the indicator-confluence block (T13–T18).
- **Confluence inputs to add to the lab:** indicator_service (RSI/MACD/ATR/SMA/volume), multi-TF pivots, and optionally an events/sentiment MCP.
