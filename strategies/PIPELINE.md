# Strategy Research Pipeline — the repeatable playbook

This is the standard, repeatable process for turning a trading-strategy video (or any
idea) into a validated, parameterized strategy with comparable results. Every strategy
goes through the same six stages so results are consistent and the master grid is honest.

## The six stages

1. **Catalog** — `scripts/video_ingest.py --ingest "<url>..."` saves transcript + frames to
   `research/video_library/<id>/`. Dedupes against `_history.json`. (`--backfill` fills any
   video missing frames.) A video is a *source of hypotheses, not facts*.

2. **Spec & name** — read the transcript (frames to disambiguate). Produce a structured spec in
   `strategies/registry/<name>.spec.yaml`: name, source video, family, instrument/timeframe,
   entry / exit / stop / target, filters, and **data_fit**. Ambiguous rules become
   **clarifying questions for the operator** — the human-in-the-loop review gate.

3. **Register** — add the testable hypotheses to `strategies/THEORY_MATRIX.md` with IDs.

4. **Backtest** (the rig) — run `scripts/strategy_suite.py` style battery on the spec:
   - baseline expectancy (mean R per trade, net 10 bps cost)
   - chronological **out-of-sample** split (trust only if OOS holds)
   - **random-direction control** (does the signal beat a coin flip?)
   - benchmark (SPY buy-&-hold)
   Then, for anything with an edge:
   - **attribution** (`scripts/strategy_filters.py`) — find filters that lift expectancy OOS
   - **hardening** (`scripts/strategy_harden.py`) — parameter sweep (plateau, not a spike),
     walk-forward (persists across eras), breadth (broad, not 1-2 names)
   → lands on the **proper tuned parameters**.

5. **Document** — `strategies/strategy_docs/<NAME>.md`: rules, exact config, results
   (IS / OOS / control / benchmark), robustness, verdict + confidence + caveats.

6. **Compare** — append to **`strategies/STRATEGY_GRID.md`** (+ `data/research/strategy_grid.csv`):
   every strategy ranked by OOS expectancy / profit factor / win-rate at its tuned params,
   with the common benchmark and a data-fit flag. This is the single source of truth.

## Triage rule (don't waste effort)
Spec + quick baseline backtest for ALL strategies. Only run the full attribution + hardening
battery on the ones that show an edge OOS and beat the control. The rest are documented with a
"rejected / not-supported" verdict (which is itself a valuable result) or shelved as
"needs intraday FX data".

## Honesty rules (constant)
- Trust **out-of-sample**, not in-sample. Watch trade count — a filter leaving <100 trades proved
  nothing. Beware multiple-comparisons: the more filters tested, the more flukes; require a mechanism.
- **Edge = payoff geometry + selection**, rarely raw direction. Recurring finding across every video
  family: the triggers are near coin-flips; the money is in the stop/target geometry and skipping
  junk setups — not prediction.
- Win-rate ↔ reward:risk is a seesaw. High win rate by itself is not the goal; **expectancy** is.

## Outputs / structure
```
strategies/
  registry/<name>.spec.yaml      one structured spec per strategy
  THEORY_MATRIX.md               hypothesis registry (IDs, status, verdict)
  strategy_docs/<NAME>.md        per-strategy write-up
  STRATEGY_GRID.md               the master comparison grid (source of truth)
data/research/strategy_grid.csv  machine-readable results
research/video_library/<id>/     transcript + frames + notes per video
scripts/
  video_ingest.py                catalog (transcript + frames, dedupe, backfill)
  strategy_suite.py              standardized backtest harness
  strategy_filters.py            conditional feature attribution (find filters)
  strategy_harden.py             param sweep / walk-forward / breadth
  strategy_pipeline.py           driver: run the battery on a spec -> grid (to build)
```

## Validated → deployed
A strategy that clears the battery (positive OOS, beats control, robust) gets:
- a detector in `agents/detectors/` (pure fn of bars + as_of_ts, with strength-rated evidence),
- a `strategy_configs/<name>.yaml` (whitelisted to its detector) + a scan workflow,
- exposure in the `/strategies` Configure panel + the History backtest view.
(Reference implementations: `momentum_breakout`, `fear_dip_reversion`.)
