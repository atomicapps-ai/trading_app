# Empirical Breakout Precursor — Detector Spec

**Implementation:** [`agents/detectors/breakout_empirical.py`](../../agents/detectors/breakout_empirical.py)
**Status:** v1, calibrated against 502 labeled winners across 62 diverse symbols.

This detector is *empirically derived*. Every threshold is a
percentile of the distribution of measured features across actual
successful breakouts — not a number picked from a book. If you want
to change a threshold, re-run the analysis pipeline (see below) and
let the new distribution dictate the change.

---

## Why this detector exists (and what it replaces)

The strict "Absorption at Resistance" / VCP detectors that preceded
this one (see `vcp_absorption.md` — historical notes) were optimized
to match Minervini's **textbook** description. When we measured what
real successful breakouts actually looked like across 20 years of
cached daily history, we found:

| Assumption the VCP detector encoded | Empirical reality |
|---|---|
| 3+ touches at a flat resistance | 50% of winners had 0 touches within 2% of anchor |
| Volume dry-up (< 60% of prior) | Median winner had 95% of prior volume — no dry-up |
| Strict monotonic tightening | Median compression was 0.905 — barely tightening |
| Minervini Trend Template (SMA50>150>200) | 10% of winners violated this stack |
| Within 25% of 52w high | 10% of winners broke out from 41% of 52w high |
| Anchor day volume spike | Median anchor volume was 90% of avg — below normal |

Conclusion: the VCP/absorption rubric is **one specific** winner shape,
not the general case. Most breakouts don't form that exact structure.

---

## Data pipeline that produced the thresholds

Four scripts, run in order, all local:

```
scripts/label_breakouts.py       → tags every bar that preceded a
                                    ≥50% gain within 120 bars and
                                    was at/near a recent high
scripts/dedup_breakouts.py       → collapses consecutive labels into
                                    discrete events (one anchor per
                                    setup)
scripts/measure_setup_structure.py → for each anchor, rewinds and
                                    computes 28 structural features
                                    across a fixed 180-bar lookback
scripts/distribution_analysis.py → computes P10/P25/P50/P75/P90 per
                                    feature across all anchors →
                                    produces the spec this detector
                                    literally imports its numbers from
```

Total labeled-winner pool used for calibration:
- **502 events**, 56 symbols
- Criteria: anchor bar ≥ 98% of 60-day max; next 120 bars contain a
  close ≥ 1.5× anchor close
- Cover 2005 – 2026 across mega-cap tech, semis, AI, critical
  minerals, oil, robotics, quantum, defense, and sector ETFs

---

## Detector logic

### Hard gates (event is REJECTED if any fails)

Each gate's boundary is the P10 or P90 of the winner distribution —
i.e. "reject anything WORSE than the 10th percentile of real winners":

```
close / SMA50          ≥ 1.010       (winner P10)
RSI(14)                ∈ [50.97, 67.22]  (winner P10–P90)
max_drawdown_in_base   ≤ 0.25        (winner P90; boundary of 25% base def)
base_len_25pct         ∈ [24, 180]    (winner P10–P90)
n_contraction_pairs    ≥ 5           (winner P10)
```

### Score (0-100) for events that pass all gates

A weighted average of per-feature scores. Each feature's score is 100
at the winner MEDIAN, falls to 50 at P10/P90, and 0 at double-distance
outside the band.

Weights (sum to ~1.0):

| Weight | Feature | Why weighted here |
|---|---|---|
| 0.15 | `close_vs_sma50` | Tightest winner cluster |
| 0.15 | `rsi_14` | Tight [51, 67] band, very predictive |
| 0.12 | `max_dd_base` | Recent-consolidation defining feature |
| 0.10 | `base_len_25pct` | Ensures a base actually formed |
| 0.08 | `n_contraction_pairs` | Base has structure |
| 0.05 | `first_depth_pct` | Contraction character |
| 0.05 | `final_depth_pct` | Contraction character |
| 0.05 | `compression` | How much the base tightened |
| 0.05 | `vol_ratio_30_180` | Soft volume check |
| 0.05 | `anchor_vol_vs_avg` | Breakout-day activity |
| 0.05 | `close_vs_sma200` | Longer-term trend |
| 0.05 | `pct_of_52w_high` | 52w-high positioning |
| 0.05 | `run_up_60` | Short-term momentum |

Default minimum score to emit: **50** (configurable via
`config['pattern_thresholds']['breakout_empirical']['min_score']`).

### What we deliberately do NOT gate on

These features are computed and scored but **are not hard gates** —
because their winner distributions are too wide to meaningfully
reject bars:

- `touches_within_2pct` (median 0 across winners)
- `compression` (median 0.905, near 1)
- `vol_ratio_*` (medians near 1.0)
- `sma50_vs_sma200` (Stage 2 violated by 10% of winners)
- `pct_of_52w_high` (spans 0.41 – 0.96 across winners)
- `run_up_180` (P10 = 0.71, i.e. −29% run-up is still winner territory)

---

## Validation

Run `scripts/validate_empirical.py` to measure the detector's
**lift** — how much more often it fires on true-positive anchor
bars vs random baseline bars. Target ≥2× for usable, ≥3× for strong.

### Last measured performance (v1 post-tz-fix)

| Metric | Value |
|---|---|
| Anchor events tested | 527 (gain≥50% in 120 bars) |
| Random baseline bars | 16,800 (300 per symbol × 56 symbols) |
| Winner capture rate | **58.44%** (308 / 527) |
| Random fire rate | **9.46%** (1,589 / 16,800) |
| **Lift** | **6.18×** — STRONG |
| Median score, anchor fires | 76.2 |
| Median score, random fires | 73.9 |

The score discrimination is currently weak — anchors and random fires
have nearly the same median score. The hard gates do almost all the
filtering. Scoring-layer improvements are v2 work.

### Known blind spots

Tickers with <30% anchor capture: ARQQ, QUBT, QBTS, RGTI, SYM, UUUU,
ASTS. These are mostly post-2020 IPOs with short history and atypical
momentum profiles — the winner distribution we calibrated against
doesn't represent their pattern shape. Random fire rates on these
names are also near-zero, so the detector is silent rather than wrong.

The validation script writes `data/validation_results.csv` with
every event's fire/no-fire and score. Inspect the fires to find
canonical and outlier examples.

---

## Trade plan emitted on detection

| Field | Value |
|---|---|
| Entry | current close |
| Stop | max(recent base low − 0.5·ATR, close × 0.90) |
| TP1 | entry + 2R |
| TP2 | entry + 4R |
| Invalidation | daily close below stop |

The stop caps at −10% below entry — this limits risk when the recent
base low is very deep (happens in post-drawdown recovery setups).

---

## Updating the detector

Every threshold in the code comes from the distribution analysis.
**Do not hand-edit them.** To recalibrate:

1. Change the labeling criteria in `label_breakouts.py` if needed
   (e.g. different gain threshold, different forward window).
2. Re-run the 4-step pipeline.
3. Copy the numbers from `data/threshold_spec.md` into the detector's
   `GATES` and `WINNER_MEDIANS` dicts.
4. Re-validate and compare lift to the previous version.

A threshold change without a corresponding distribution-analysis
re-run means we went back to guessing.

---

## Known limitations (v1 → v2 backlog)

- **No debounce.** Fires on every qualifying bar in a cluster (median
  cluster is 6 bars). Production needs one signal per setup.
- **Daily-only.** Weekly variants would have different percentiles;
  needs separate calibration run on weekly bars.
- **US equities only.** Pool is 62 US-listed names; Indian/EU/Asian
  stocks likely need re-calibration.
- **No outcome segmentation.** Winners vary 50% – 500%. Detector can't
  distinguish "50% winner" from "500% winner" — cross-set deltas
  showed no structural feature predicts magnitude.
- **Breakout-day confirmation missing.** We detect the setup, not
  the breakout trigger. Entry is at current close; may be early by
  a few bars. Add explicit trigger condition in v2.
- **Elite vs broad collapsed into one model.** v2 could have separate
  detectors tuned on the 100%/120b and 100%/252b distributions for
  users who want tighter signals at the cost of fewer events.
