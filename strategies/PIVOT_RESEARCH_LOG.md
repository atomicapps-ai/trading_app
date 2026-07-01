# Pivot Strategy — Research Log

Living record of theories tested, methods, results, and verdicts. Every claim here is
backed by a backtest on local cached data (`data/historical/*.csv`), measured on
**expectancy (mean R per trade, after 10 bps round-trip cost)**, with a chronological
out-of-sample (OOS) second half and a random-direction control on identical triggers.

Rig: `scripts/strategy_lab.py` · loader `services/research_data.py` · pivots
`services/pivot_service.structural_pivots`. Runs offline in seconds.

Data: ~90 symbols, daily bars (mostly 2021→present), weekly resampled from daily.

---

## Iteration 1 — Naive weekly structural-pivot touch-reversal (2026-06-26)

**Strategy under test:** detect weekly structural swing pivots (Strength = left/right
bars). When daily price touches a confirmed support → go long; touches resistance →
go short (mean-reversion / fade). Stop just beyond the level, target = RR × risk.

**Configs run:** (strength 3, RR 2, stop 1.0%) · (strength 3, RR 1, stop 2.0%) ·
(strength 5, RR 2, stop 1.5%). ~10k–14k trades each.

### Result — the naive fade does NOT work
Expectancy (entry at level), OOS, vs the random-direction control:

| config | pivot-fade OOS | random OOS |
|---|---|---|
| str3, RR2, stop1.0% | **−0.179R** | −0.128R |
| str3, RR1, stop2.0% | **−0.176R** | −0.147R |
| str5, RR2, stop1.5% | **−0.086R** | −0.047R |

**In every configuration the fade is negative AND worse than a coin flip.** The gap is
statistically significant (n≈5–7k OOS). Major levels (strength 5) are the least-bad but
still lose to their own random control. **Verdict: REJECTED** as a standalone signal.

Interpretation: fading these levels underperforms random ⇒ at weekly structural levels,
price **continues / pierces** more often than it reverses. The mean-reversion assumption
is wrong at the moment of touch.

### T1 — which O/H/L/C sits closest to the level at the touch
| touch | O | H | L | C |
|---|---|---|---|---|
| support | 33.8% | 12.5% | **16.7%** | 39.0% |
| resistance | 32.0% | **14.2%** | 14.3% | 39.5% |

Counter-intuitive and useful: the **close/open** are most often nearest the level; the
wick extreme (Low at support, High at resistance) is *least* often nearest. Price tends
to **pierce** the level (the wick pushes through it) rather than tag-and-respect it —
consistent with the "continuation, not reversal" read above and with the operator's own
"levels weaken and break" intuition.

### T3 — "weakening" touch-count theory: INCONCLUSIVE (measurement bug)
The prior-touch counter currently counts the pivot's own formation, so the "fresh
(0 prior tests)" bucket is always empty and everything lands in 2nd/3rd+. Must fix the
counter to start *after* the level is confirmed before this theory can be judged.

### Known issues to fix next
1. Touch-counter includes formation bars → no "fresh" bucket. Fix: count touches only
   after `confirm_ts`.
2. Random and pivot are both negative ⇒ the trade *geometry* (tight stop, costs) loses on
   these triggers generally. The clean test is **fade vs continuation on the same
   geometry**, not just vs random.

### Queued experiments (data points here)
- **Iter 2 — Continuation/break:** flip the trade to trade the *break* of the level
  (long on resistance break, short on support break). The T1 + fade-loses evidence
  predicts this is where edge lives, if anywhere.
- **Iter 3 — Confluence filter:** require daily/4h structural pivots stacking at the
  weekly level; test whether confluence lifts expectancy.
- **Iter 4 — Fresh-level (fixed counter):** does a first/second touch behave differently
  from an exhausted level?
- **Iter 5 — Exit study:** vary stop distance, target, and time-stop to find the
  geometry that turns a real directional edge (if found) into positive expectancy.

**Net so far:** the rig is validated and fast; the *naive fade* is dead; the evidence
points toward continuation/breakout as the next hypothesis.

---

## Iteration 2 — Continuation vs reversal + regime gate (2026-06-26)

**Goal:** find whether a *base directional edge* exists at structural levels before
adding any indicators. Tested fade vs break, gated by ADX (trend/range) and trend
direction. 11,625 touch events, 90 symbols, str3 / RR2 / stop1% / hold25.

### Result — continuation wins, and we found a real edge
OOS expectancy (after 10 bps cost):

| strategy | OOS exp | n(OOS) |
|---|---|---|
| fade_all | −0.179R | 5813 |
| break_all | **−0.081R** | 5813 |
| fade_range (ADX<20) | −0.193R | 2574 |
| break_trend (ADX>25) | −0.089R | 1947 |
| **break_aligned** (break with trend) | **−0.014R** | 2882 |
| random control | −0.128R | 5813 |

### Verdicts
- **T4 ✅ CONTINUATION beats reversal.** Break (−0.081) ≫ fade (−0.179). Fade rejected
  for good; price continues through weekly structural levels more than it reverses.
- **T23/T24 ⚠️→ trend-alignment validated, range-fade rejected.** `break_aligned`
  (long breakouts in uptrends / short breakdowns in downtrends) beats random by ~6σ —
  the first statistically real directional edge in the project. But "fade in a range"
  is *worse* than random, so that half of the regime idea is dead.
- **Still net-negative (−0.014R).** A real *directional* edge that current mechanics
  (1% stop / 2R / 25-bar) leak away via stops + costs. Edge exists; geometry must catch it.

### Open question for Iter 3 (must answer before celebrating)
Does the *level break* add edge over plain trend-following? `break_aligned` mixes "with
the trend" + "at a level." Need a **trend-only control** (trend-aligned entries at random
bars, same geometry) — if break_aligned doesn't beat that, the edge is just momentum and
the pivot adds nothing.

### Queued — Iter 3: convert the directional edge to positive expectancy
1. **Isolate the level's contribution** (trend-only control) — is the pivot real?
2. **Exit/stop optimization on `break_aligned`:** ATR stop (T22), target=next opposing
   pivot (T27), hold length (T29), stop distance sweep. Goal: push −0.014R → positive.
3. Only then layer indicator confluence (T13–T21) to filter further.

**Net so far:** fade is dead; **trend-aligned breakout of structural levels is a real
directional signal (beats random ~6σ)** but not yet net-positive. Next: prove the level
matters vs pure momentum, then fix the geometry.

---

## Iteration 3 — Level vs trend-only control + exit optimization (2026-06-26)

**Goal:** (1) prove the structural level adds edge over pure trend-following; (2) tune
exits to convert the directional edge to positive expectancy. 90 symbols, str3, weekly
pivots, trend-aligned breaks only.

### Result — the level matters, and exits make it pay
OOS expectancy (after 10 bps cost):

| strategy | exp (all) | OOS exp | OOS n |
|---|---|---|---|
| **trend_only control** (trend, NO level) | −0.201R | **−0.182R** | 3523 |
| break_aligned base (1%/2R/25) | −0.028R | +0.006R | 1984 |
| break_aligned **ATR1.5 / 2R** | +0.059R | **+0.117R** | 1984 |
| break_aligned **ATR1.5 / 3R** | +0.091R | **+0.150R** | 1984 |
| break_aligned next-pivot target | +0.150R | +0.229R | 1984 |

### Verdicts
- **✅✅ THE LEVEL IS THE EDGE (control passed decisively).** Pure trend-following LOSES
  (−0.182R OOS). The *same* trend-aligned trade, taken at a structural-level break, is
  **positive** — a ~0.19R swing that comes entirely from the level. The pivot is not
  decoration; it is where the edge lives.
- **✅ First validated POSITIVE out-of-sample strategy in the project.** ATR-based stops
  (respecting each symbol's volatility instead of a fixed 1%) turn the leaking base into
  **+0.117R (2R) / +0.150R (3R) OOS** — clean, look-ahead-free, ~5–8σ significant over
  1984 OOS trades. The fixed-% stop was the leak.
- **⚠️ next-pivot target (+0.229R) NOT YET TRUSTED — possible look-ahead.** The target is
  picked from the full pivot set, which may include levels confirmed *after* entry. Must
  restrict targets to pre-entry-confirmed levels before believing this number.

### The validated strategy (clean version)
> **Long the breakout of a weekly structural resistance in an uptrend (price>rising SMA50);
> short the breakdown of weekly support in a downtrend. Stop = 1.5×ATR beyond the level;
> target = 3R. → +0.150R OOS / trade across 90 symbols.**

### Caveats before any real conviction
- One dataset (90 US equities, ~2021–2026). Needs: per-symbol robustness, regime split
  (does it survive 2022's bear?), transaction-cost sensitivity, a true untouched hold-out.
- Light parameter sweep ⇒ guard against overfitting; the *mechanism* (vol-scaled stop,
  run with the trend) is sound, not a magic number, which is reassuring.

### Queued — Iter 4+
1. Robustness harden the ATR/3R strategy (per-symbol, regime, cost, hold-out).
2. Fix + re-test the next-pivot target (remove look-ahead).
3. **Now** layer indicator confluence (T13–T21) onto this real base edge to push it higher.
4. Then wire it into the app as a mechanical strategy for paper trading.

**Net so far:** 🎯 first real, positive, out-of-sample edge — *trend-aligned weekly
structural breakout with an ATR stop*. The level is proven to carry the edge. Harden it,
then sharpen with confluence.

---

## Iteration 4 — Robustness hardening (2026-06-26)

**Goal:** stress the validated ATR1.5/3R breakout across regimes, symbols, and costs;
fix the next-pivot look-ahead. **Data turns out to span 2006–2026 (20 yrs), 3,967 trades.**

### [A] Regime survival (net @10bps, by year)
Positive in **14 / 21 years**, incl. **+0.176R in 2008**. Negative in choppy/range years:
2011 (−0.28), 2015–16, 2019, 2022 (−0.14), 2026-partial (−0.41, n=83). Classic
trend-following signature: pays in trends, bleeds in whipsaw.

### [B] Breadth
**58 / 89 symbols (65%) individually positive**, median +0.116R. Edge is broad, not a
few names.

### [C] Cost sensitivity (overall mean net R)
0bps +0.152 · 5bps +0.122 · 10bps +0.091 · 20bps +0.031 · 30bps −0.030. **Break-even
≈28 bps** ⇒ survives realistic costs on **liquid** names; dies on high slippage.

### [D] Next-pivot target, look-ahead FIXED
+0.037R (win 52.9%) — far below the buggy +0.229R. Caution vindicated; **keep the fixed
3R target** (it's better at +0.091R).

### VERDICT — ✅ VALIDATED, ROBUST EDGE
> **Trend-aligned weekly structural breakout · 1.5×ATR stop · 3R target → +0.091R/trade
> net of 10 bps · 2006–2026 · 3,967 trades · 65% of symbols positive.**

Profile: trend-following (~35–40% win rate, big winners, losing chop years), liquid-name
only, cost-sensitive. Real positive expectancy that survives 20 years and broad symbols.

### Known weaknesses → Iter 5+ targets
1. **Choppy-year drawdowns** (2011/2022). Add a range filter (only trade when ADX
   trending / market in a trend) to cut whipsaw losses — likely the highest-value refine.
2. **35% of symbols negative** — a universe/quality filter could lift the aggregate.
3. **Cost/liquidity** — restrict to liquid names; model slippage in execution.
4. Layer indicator confluence (T13–T21) onto this base to raise expectancy / win rate.
5. Then implement as a mechanical app strategy → paper trade.

**Net so far:** ✅ a 20-year-validated, broad, cost-aware trend-following breakout edge
off structural levels. From two dead ideas (Kronos, fade) to one real strategy — the
right way. Next: cut the chop-year losses with a regime filter, then sharpen + deploy.

---

## Iteration 5 — Forensic: dissecting winners vs losers (2026-06-26)

**Scope:** validated ATR1.5/3R breakout, **2017–present (~9 yrs)**, net@10bps. Deep-dive
on **3,041 trades (1,078 win / 1,963 lose)** at strength 3, tagging each by pivot/context.

### Findings (with sample sizes)
- **F1 — CLOSE-beyond confirmation is decisive.** Closed beyond the level: **+0.326R,
  41.8% win (n=1,630)**. Wick-only (closed back inside): **−0.159R, 28.1% (n=1,411)**.
  Mechanism = wick = false break / rejection; close = commitment. Biggest lever found.
- **F2 — moderate strength > major levels.** str2 +0.129R · str3 +0.101 · str4 +0.099 ·
  str5 +0.053 (~3k trades each). Sweet spot **strength 2–3**; the most-major levels are
  over-anticipated.
- **F3 — avoid worn-out levels.** 1 prior test **+0.308R (n=521)** vs 2+ tests +0.057R
  (n=2,385); fresh(0) +0.078 (n=135). Losers averaged 12.6 prior touches vs 9.8 for
  winners. The "weakening" theory holds for 2+ retests. Prefer **≤1 prior retest**.
- **F4 — ADX is a weak filter (regime hypothesis mostly wrong).** Winner avg ADX 23.5 ≈
  loser 23.6 — no separation. Only ADX>35 helps (+0.244R, n=360). Confirmation >> regime.

### Caveat
F1 was *tagged* but trades still entered at the level intrabar. A real close-confirmation
enters at **next-bar open** (worse price) → re-test needed before trusting +0.326R.

### Implied refined strategy → Iter 6 test
> Trend-aligned weekly structural breakout, **strength 2–3**, **only if the bar closes
> beyond the level** (enter next-bar open), **≤1 prior retest**, 1.5×ATR stop, 3R target.

Re-test this combined rule OOS with realistic next-open entry; expect materially higher
expectancy than the +0.091R base. Then layer indicator confluence; then deploy to paper.

---

## Iteration 6 — Realistic-entry validation (2026-06-26) — REALITY CHECK

**Goal:** re-test the forensic refinements with realistic **next-bar-open** entry,
isolating each. 2017+, net@10bps.

### Result (strength 3, OOS = recent half)
| variant | exp | OOS | breadth |
|---|---|---|---|
| V0 enter at level | +0.101 | +0.013 | 61/90 |
| V1 next-open | +0.001 | −0.079 | 43/90 |
| V2 +close-confirm | +0.052 | −0.027 | 46/88 |
| V3 +close+fresh | +0.232 | +0.172 | 23/30 (n=342) |

(Strength 2 similar; V2 recovers to only +0.036 OOS.)

### Honest verdicts
- **❌ Close-confirmation does NOT survive realistic entry.** The forensic +0.326R was an
  artifact of optimistic intrabar fill + selection. With next-open entry it's ≈0/negative
  OOS. Caution vindicated.
- **⚠️ The edge lives entirely in filling AT the level** (stop-entry order), not in chasing
  a confirmed close. Moving entry to next-open kills +0.10 → ~0.
- **⚠️ V3 (freshness) looks strong (+0.172 OOS) but n=342 / 30 symbols — under-powered, not
  trustworthy.** Same small-sample trap as Kronos-AAPL.
- **🚩 Recent-window edge is thin.** Base V0 over 2017+ OOS = +0.013–0.030R, **not
  statistically > 0** (~0.5σ). The strong +0.091R was the *full 20-yr* figure; the last
  ~4.5 yrs are weak (trend-following regime dependence, but a real flag).

### Reframed status
A **real but thin, execution-fragile, regime-dependent trend-following edge.** Strong over
20 yrs, weak recently, and dependent on stop-entry fills at the level. NOT the robust
machine Iter 5 implied. Refinements (close-confirm) rejected; freshness unproven.

### Critical next test (Iter 7)
**Realistic execution modeling:** stop-entry at the level *with slippage/gap modeling* —
because the entire edge hinges on fill quality. If slippage on breakouts erases +0.09 →
the strategy is marginal at best. Also: re-confirm freshness on a bigger sample; consider
whether this is a *combine-with-others* signal rather than standalone.
