# Universe & Per-Strategy Sub-Universe Selection

**Status:** design agreed 2026-07-06, implementation pending approval of the
per-strategy structural rules (see §6). Supersedes the "one shared
`liquid_momentum_core` screener for every strategy" arrangement, which
silently gated out valid setups (a momentum screen applied to a
mean-reversion strategy — see §2).

---

## 1. Terminology

| Term | Meaning |
|---|---|
| **Universe (core)** | The master list of symbols *approved for trading* — broad, liquid, real companies. Filtered for **tradeability only** (liquidity, quality, established), never for directional bias. Every strategy sees this by default. |
| **Sub-universe** (a strategy's "galaxy") | The subset of the core a single strategy actually scans. Default = the whole core. Narrowed only when it's *proven* to make that strategy more consistent / profitable. |
| **List** | Any saved symbol collection. Many may exist; exactly **one is flagged the core** (the master pool everything filters from). Others are watchlists, candidate sets, etc. |

### Rename
`core_universe_100` → **`core_universe`**. The `100` is misleading (it holds
~503). Going forward:
- **Multiple lists may exist**; a single `is_core` flag designates the master.
- `is_core` is distinct from `is_active` (which screener the UI is editing).

---

## 2. Why the old setup was wrong

All four daily strategies pointed at `liquid_momentum_core`, whose criteria
require price **above** SMA20/50/200, RSI 50–80, and +3%/month. That is a
*momentum* screen. Applied to every strategy it:

- fit `momentum_breakout` (wants momentum) ✅
- gated `macd_run` pullbacks (a pullback dips below SMA20 / RSI<50) ⚠️
- **structurally excluded** `fear_dip_reversion`, which requires price **below**
  SMA50 by ≥3 ATR — the exact opposite. It could essentially never fire. ❌

**Lesson:** a screener must filter for *tradeability*; a *strategy's* own
detector filters for the *setup*. Don't bake one strategy's directional bias
into the shared universe.

---

## 3. The three-layer selection model

For each strategy, membership is recomputed **every scan**:

```
sub-universe =
    ( core
      ─ STRUCTURAL rules    (the strategy's own design preconditions; live)
      ─ EMPIRICAL draggers   (symbols proven to hurt metrics over IS+OOS; static) )
    + MANUAL includes        (cherry-picked / override → bypass structural + empirical)
    ─ MANUAL excludes        (force out; always)

precedence:  manual override  >  structural / empirical
```

### Layer A — Structural rules (a priori, from the detector)
What we *know* from the strategy's design. Cheap, deterministic, evaluated live
each scan. Also pre-trims the pool before the expensive backtest scoring.

> **Safety invariant (non-negotiable):** a strategy's structural filter must be
> a **subset of** that strategy's detector conditions — never stricter. The
> detector is the source of truth and does the final gate; the pre-filter only
> removes symbols the detector would have rejected anyway. If unsure, keep it
> looser. Violating this re-introduces the silent-gating bug of §2.

### Layer B — Empirical draggers (data-driven)
What we *don't* know a priori: which specific symbols drag a strategy's
aggregate metrics down. Found by replaying the real detector per symbol over
history (§5). We **drop proven draggers**, we do **not** "keep only the
winners" (that is curve-fitting — see §4).

### Layer C — Manual overrides
`manual_includes` (force in, bypassing structural + empirical) and
`manual_excludes` (force out). The only way a symbol violates a structural rule
is an explicit user override.

### Provenance
Every symbol in a strategy's universe carries a reason:
`structural-pass` · `dragger-dropped` · `thin-unproven` ·
`manual-include (overrode <rule>)` · `manual-exclude`. This is the audit trail
that makes "prove it helps" real and prevents silent gating.

---

## 4. Overfitting guardrails (read before trusting any subset)

Per-symbol selection on history is precisely how this project once fooled
itself: `double_lock` showed an 82% win rate on a cherry-picked 16-name
universe (n=17), then delivered **53%** out-of-sample. Non-negotiable rules:

1. **Select on in-sample, validate on out-of-sample.** Keep a symbol only if
   the strategy works IS **and** holds OOS.
2. **Minimum sample size** (~15–20 trades/symbol) or the number is noise.
3. **Remove proven draggers, don't cherry-pick winners.** Dropping symbols with
   PF < 1 (with enough trades) that also fail OOS is defensible. Keeping only
   the top decile is curve-fitting — the future winners are a different set.
4. **Walk-forward re-score** (~monthly). Suitability drifts.
5. **Keep the core broad.** The subset is a light trim, not an aggressive prune.

---

## 5. The per-strategy workflow

```
1. Structural rules   → define from the detector (Layer A). Confirm ⊆ detector.
2. Backtest           → replay the real detector over the structural survivors
                        (scripts/replay_swing.replay) across the core.
3. Score symbol-by-symbol → per-symbol {n, win_rate, profit_factor, avg_R}
                        on IS and OOS windows.
4. Build the subset   → structural survivors − proven draggers
                        + manual includes − manual excludes.
5. Metrics & scoring  → the subset's aggregate metrics define the strategy's
                        quality; each symbol's historical trade record scores
                        future trades on that symbol (feeds probability_service).
```

---

## 6. Worked example — `momentum_breakout` (recommended pilot)

Chosen because its structural precondition is the most self-evident and it's
the least confounded (it already aligns with a momentum universe, so it cleanly
validates the pipeline).

**Detector (`s7_breakout_continuation`) conditions:**
- close > prior 126-day high (breakout trigger)
- breakout volume ≥ 1.5× (confirmation)
- price above SMA200, sweet spot 5–15% above (trend zone)
- SPY>200MA = regime *modifier* (scored, not a hard gate)

**Layer A — structural rule (⊆ detector):** `price > SMA200` + tradeability
(liquid, mid+ cap). *Not* "above SMA20 / RSI 50–80 / +3%month" — those are
stricter than the detector and would drop valid breakouts. Just the uptrend +
tradeability.

**Layers B/C:** replay over the core, drop symbols where the breakout strategy
is a proven dragger (PF<1, n≥15, fails OOS); keep the rest; honor manual
overrides.

**Result:** `momentum_breakout`'s defined sub-universe, its aggregate metrics,
and per-symbol trade histories that score future signals.

### Structural rules for the other three (to confirm before wiring)
| Strategy | Structural rule (⊆ detector) | Notes |
|---|---|---|
| `momentum_breakout` | price > SMA200 | uptrend continuation |
| `macd_run` | price > SMA200 | pullback-in-uptrend; **no** short-term-momentum gate |
| `coil_breakout` | price > SMA200 | coil is often flat — don't require +month/RSI |
| `fear_dip_reversion` | price < SMA50 | **opposite** of the others — oversold mean reversion |

---

## 7. Data model changes

- `universe_presets`: add `is_core` (bool), `manual_includes_json`,
  `manual_excludes_json`. Rename row `core_universe_100` → `core_universe`.
- Per-strategy **structural rules** live in each `strategy_configs/<name>.yaml`
  (a `universe_rules` block), derived from the detector — not in one shared
  screener.
- Per-symbol scores → `optimization_db.best_per_symbol` (exists) + an as-of /
  IS-OOS window and the keep/drop/thin classification.

---

## 8. Implementation phases

1. **Rename + core flag** — `core_universe`, `is_core`, multi-list support.
2. **Structural rules per strategy** — written from each detector, confirmed
   ⊆ detector (the correctness-critical step; §6 table).
3. **Scorer + read-only report** — replay over structural survivors, per-symbol
   IS/OOS metrics, dragger classification. *No live change yet* — see the data
   first, confirm thresholds, prove the trim helps.
4. **Manual includes/excludes + provenance UI**, then wire the subset into the
   scans.
5. **Walk-forward re-score job** (monthly).
