# Process audit — the day-trade mining funnel, its detectors, and its verdicts

**Auditor:** trader/quant onboarding pass, 2026-07-20.
**Scope:** the ~250-video day-trade mining program — the funnel in
`DAY_TRADE_MINING_WORKFLOW.md`, the six backtested detectors, the PASS bar, the
`/backtest-review` verification loop, and the 173 tombstones in `_history.json`.

**Bottom line:** the *strategies* really are dead — I re-tested the three most promising
rejections faithfully, on the right instrument, with a proper control, and none of them
has any directional edge. But **four of the six process defects below were real, and two
of them individually invalidated a verdict.** The program reached a correct conclusion
through a partly broken instrument. Fix the instrument before mining another 250 videos,
because the next candidate that matters would be missed the same way.

---

## 1. Defects found (ordered by how much damage each did)

### D1 — The control did not match the strategy's payoff geometry ❌ invalidated a verdict

`scripts/backtest_fade_candidates.py::control_fade` opens at `entry ± rng` with target
`entry ∓ rng` — a **1:1** trade. Both strategies it was benchmarking against
(`false_break_fade`, `opening_range_fade`) run a **2R** target. Comparing a 2R strategy to
a 1:1 control compares two different payoff geometries and tells you nothing about
directional skill; PF at 1:1 and PF at 2:1 are not commensurable numbers.

This is what produced `FADE_CANDIDATES_BACKTEST.md`'s headline claim that
`false_break_fade` "beats the fade control 0.80" and is "the closest of the entire
day-trade pass". It doesn't beat anything. Holding timing, stop distance and target
geometry fixed and randomising only the **direction** — the only control that isolates
predictive skill — gives:

| false_break_fade variant | OOS PF | matched control PF | edge |
|---|--:|--:|---|
| original 13:00-UTC anchor, 1 trade/day | 0.818 | 0.828 | **none** |
| faithful 4h NY range, every re-entry | 0.778 | 0.787 | **none** |
| + creator's >1% no-fade rule | 0.778 | 0.774 | **none** |
| + capped stop distance | 0.783 | 0.781 | **none** |
| London anchor | 0.802 | 0.797 | **none** |
| **equities (SPY/QQQ/IWM/DIA, 21y, n=40,483)** | **0.762** | **0.751** | **none** |

The strategy sits exactly on its coin-flip baseline in every configuration, on both asset
classes, across 21 years. `fvg_continuation` is the project's own proof that a real edge
looks different: PF 1.24 against a control of 0.78.

**Fix:** every control must be the *same strategy with the direction randomised*, averaged
over seeds. `scripts/bt_equity_open_setups.py::randomize` and
`scripts/bt_fbf_faithful.py` do this. The `control_with_trend` in `backtest_prospects.py`
has the same flaw (fixed 10/20-pip geometry vs. detectors using ATR stops).

### D2 — "We have no 5m equity data" is false, and it misdirected the whole intraday pass ❌ invalidated a verdict

`PROSPECT_BACKTEST.md`, `7teij9jI7mg/notes.md`, and `TRADER_SESSION_ONBOARDING.md` all
state the project has no cached 5-minute equity bars, so equity-native setups were run on
FX "as a stand-in" and `orb_retest` was parked **pending** a faithful re-test.

There are **522 `*_5m.csv` files on disk**, including 21 years of RTH bars for the exact
instruments those setups are native to:

| symbol | 5m bars | coverage |
|---|--:|---|
| SPY | 421,687 | 2005-01-03 → 2026-07-07 |
| QQQ | 421,464 | 2005-01-03 → 2026-07-07 |
| IWM | 421,219 | 2005-01-03 → 2026-07-07 |
| DIA | 420,993 | 2005-01-03 → 2026-07-07 |

13 of the 17 "out of scope" tombstones were intraday/futures setups rejected partly on
this belief. The data gap was the stated reason `orb_retest` never got a verdict.

**Now re-tested properly** (`scripts/bt_equity_open_setups.py` — 09:30 ET anchor, entry at
the next bar's open, flat 15:55 ET, 2bp round-turn, stop resolved first on both-touched
bars):

| detector | N | WR% | OOS PF | control PF | verdict |
|---|--:|--:|--:|--:|---|
| orb_retest | 14,664 | 42.7 | 0.984 | 0.986 | no edge — dead on its native instrument |
| false_break_fade | 40,483 | 36.8 | 0.750 | 0.751 | no edge |
| opening_range_fade (fair geometry) | 7,168 | 39.2 | 0.890 | 0.877 | no edge |

`orb_retest`'s per-year PF over 21 years never establishes a trend: 0.82, 0.98, 0.78,
1.18, 0.63, 0.98, 1.09, 0.88, 0.88, 0.80, 0.87, 0.84, 0.92, 0.93, 1.07, 0.99, 0.99, 1.08,
1.06, 0.98, 1.04, 0.94. It oscillates around its control. **The FX stand-in was not what
killed it.** That "pending" verdict can now be closed as a rejection with confidence.

### D3 — A rejection was manufactured by an untradeable stop distance ⚠️ unfair test

`opening_range_fade` was reported at OOS PF 0.78 on FX and scored **0.365** in my first
equity run — a number so bad it should have prompted a look at the trades. It did not,
because the trades were never rendered. The cause: the mechanisation places the stop
*on* the opening-range extreme while entering at the 09:45 open, which is usually right
next to it. Median risk came out at **5.9 bps on SPY**. Against a 2 bp round-turn cost,
transaction cost alone was **34% of every risk unit** — no discretionary trader would
take that trade, and the source video explicitly sizes stops off ATR.

Giving the stop a sane buffer and dropping setups too tight to trade:

| stop buffer | min risk | N | OOS PF | median risk | control |
|---|--:|--:|--:|--:|--:|
| none (as tested) | — | 8,101 | **0.365** | 8.2 bps | 0.351 |
| 0.10 × ATR | — | 8,346 | 0.844 | 21.7 bps | 0.843 |
| none | 20 bps | 1,363 | 0.963 | 28.5 bps | 0.939 |
| 0.25 × ATR | 25 bps | 7,168 | 0.890 | 46.0 bps | 0.877 |

The conclusion is unchanged — every row still equals its control, so the setup has no
edge — but **the number in the file was 2.5× too harsh and was never a fair test.** That
distinction matters: this time it didn't flip a verdict; next time it will.

**Fix:** any detector must report median risk-in-bps alongside PF, and reject its own
setups when cost exceeds ~10% of the risk unit rather than silently trading them.

### D4 — The "look at the trades" verification loop did not work ⚠️

The onboarding instruction is *don't trust a PF you haven't eyeballed trades for*. The
tooling could not deliver that for the candidates that mattered:

- **`scripts/build_candidate_review.py` crashes as documented.** Its own docstring says
  `python scripts/build_candidate_review.py --only false_break_fade`; that raises
  `ModuleNotFoundError: No module named 'agents'`. It must be run as `python -m
  scripts.build_candidate_review`. Nobody had run it for `false_break_fade` — there were
  no images for the "closest lead" of the entire program.
- **`r_net` is a copy of `r_gross`.** `build_candidate_review.py:78` sets
  `"r_net": round(t.pnl_r, 2)` — the same value as `r_gross`. So the "net PF" column that
  `/backtest-review` displays is gross PF for all six candidates, and the UI's headline
  cost-adjusted number is not cost-adjusted.
- **The chart window is hardcoded to equity RTH.** `render_backtest_images.py::_window`
  clips intraday charts to `between_time(09:30, 16:00)`. FX candidates anchored at
  13:00 UTC build their range from 08:00 ET, so the range formation — the thing you need
  to see to verify a *range* strategy — is cropped off every chart.
- **No opening-range box is emitted.** `build_candidate_review.py` never sets
  `box_high`/`box_low`, though `_draw` supports them. The rendered charts show entry,
  stop and target lines floating with no visible range, so a range-break setup cannot be
  confirmed or refuted by eye.

**Fix applied:** `scripts/build_equity_review.py` writes `entry_time`/`exit_time`, the
opening-range box, and a genuinely net `r_net`. I used it to verify the ORB re-test
visually before accepting its number (§2).

### D5 — Documented results no longer reproduce ⚠️

`FADE_CANDIDATES_BACKTEST.md` reports pooled OOS net PF **0.96** for `false_break_fade`
and **0.80** for the control. Re-running the identical command today gives **0.922** and
**0.963** — the strategy now *loses* to the control it was said to beat, and EURUSD OOS
N is 533 against the documented 354. The price cache has grown (FX now runs to
2026-07-20) and results were never pinned to a data snapshot or a commit.

**Fix:** every result table should record the data end-date and row counts per symbol, so
a future reader can tell a data refresh from a code regression.

### D6 — Entry-on-signal-bar-close throughout the shared rig ⚠️ minor here, dangerous generally

Every detector in `backtest_prospects.py` and `backtest_fade_candidates.py` sets
`entry_price = c[i]` — the close of the bar that produced the signal. You cannot know a
bar's close in time to trade it. `simulate_trades` does at least start exit checks at
`i+1`, so this is a one-bar optimistic fill rather than outright look-ahead, and on 5m FX
it is worth only a fraction of a pip. It is still the wrong default: on a setup whose
trigger *is* a sharp close (three-line strike, engulfing entries) it systematically
flatters the fill. My re-tests fill at the next bar's **open**.

---

## 2. Detector faithfulness — checked against transcripts and against trade charts

| detector | faithful to the video? | notes |
|---|---|---|
| `orb_retest` | **yes** (spec + visually verified) | Rendered SPY/QQQ trades: OR box drawn, break-then-retest visible, entry above/below the broken level, stop on the far side of the range, 2R target. Matches `7teij9jI7mg/spec.json`. Its rejection is a strategy verdict. |
| `false_break_fade` | **no** — five divergences, all now tested | Wrong range anchor (13:00 UTC block = the London/NY overlap, i.e. the range was defined over the *most* volatile hours and then faded in the quiet afternoon — inverting the premise); one trade/day vs. the creator's several; entry at close; no >1% escape hatch; no stop cap. **All five corrected — result unchanged, PF still equals control.** |
| `opening_range_fade` | **partly** | Geometry untradeable (D3). Also the video's trigger is two specific reversal candles, which the harness replaces with an immediate fade at the OR close — a real simplification. Even the fair-geometry version has no edge, but this one is closest to "not really tested". |
| `three_line_strike` | yes | Fixed 10/20-pip stop/target is the creator's own spec. WR 38% at 2:1 vs. the claimed 70-75%. |
| `amd_session_reversal` | reasonable proxy | Session windows in UTC, not DST-aware ET — a ~1h drift across the year on a session-timing strategy. Worth noting, though PF 0.87 net is far from the bar. |
| `ema_reclaim_pullback` | reasonable proxy | State machine is a defensible reading of a discretionary setup. |

**On the visual check I did run:** I rendered ORB-retest equity trades and inspected
winners and losers. The 2023-06-28 SPY long broke the 418.70–419.10 opening range, pulled
back to it, entered at 419.55 on the next bar's open with the stop at the far side of the
range and a 2R target — textbook execution of the written spec. The 2022-10-05 SPY short
did the mirror image and was stopped when price rallied straight back through the range.
The mechanics are right; the setup simply has no predictive content.

---

## 3. Is the funnel itself sound?

**Sound:** cheap filters first, expensive transcript/backtest last; the stage-4 rule
("reject only *exact* known-fail mechanisms") is the right correction to title-based
rejection; the two-tier purge with tombstones keeps the library lean without losing URLs.

**Not sound:**

1. **The PASS bar has no control term.** It says "beats a with-trend / random-direction
   control" but the implemented controls don't match strategy geometry (D1). PF ≥ 1.3
   against nothing is a number, not a test. The bar should read: **PF ≥ 1.3 net AND
   PF ≥ control + 0.25**, control = same strategy, direction randomised, ≥3 seeds.
2. **"Daily analog already exists" is not a valid rejection of an intraday setup.** At
   least 6 tombstones reject an intraday candidate because a daily cousin is live
   (`8vufTzGZqiI` → fear_dip_reversion, `6XtBCqBhQ-k` → coil_breakout, `9JEmsSItdt4` →
   Turtle). Intraday and daily versions of the same pattern are different trades with
   different costs, holding periods and correlation profiles — that is what the
   correlation gate is for. Judge them on measured correlation, not on family resemblance.
3. **"Out of scope: intraday/futures" rested on a false premise** (D2) and should be
   retired as a reason.
4. **30 of 173 tombstones carry no reason at all.** That is 17% of the corpus with no
   audit trail.
5. **Only 38 of 173 candidates (22%) were ever backtested.** 73 were rejected as
   discretionary/educational and 49 as duplicates. Those are mostly defensible calls on
   reading, but it means the "we tested ~250 strategies" framing overstates by ~5×. The
   honest statement is: **~250 videos triaged, 38 mechanised and backtested, 12 passed
   (all daily/swing), 0 intraday passed besides `fvg_continuation`.**

---

## 4. Recommended changes

1. Replace both geometry-mismatched controls with direction-randomised ones. (Done for
   the re-tests; `backtest_prospects.py` and `backtest_fade_candidates.py` still need it.)
2. Correct the "no 5m equity data" claim in `PROSPECT_BACKTEST.md`,
   `7teij9jI7mg/notes.md` and `TRADER_SESSION_ONBOARDING.md`. (Done.)
3. Make every detector report median risk-in-bps and refuse setups where cost > 10% of
   the risk unit.
4. Fix `build_candidate_review.py`: the docstring command, the fake `r_net`, the missing
   range box; and make `render_backtest_images._window` take the session window from the
   ledger instead of hardcoding equity RTH.
5. Amend the PASS bar to include the explicit control margin, and drop "daily analog
   exists" and "intraday is out of scope" as rejection reasons.
6. Stamp every result table with data end-date and per-symbol row counts.

---

## 5. Verdict on the operator's hypothesis

> *Were the failures the strategies, or our implementation of them?*

**The strategies — but the process was not entitled to that conclusion when it drew it.**

Of the three leads worth re-opening, the implementation was materially wrong in two cases
(`false_break_fade`'s session anchor and trade count; `opening_range_fade`'s untradeable
stop) and the headline lead was never tested on its native instrument at all
(`orb_retest`). Fixing every one of those changed the numbers and changed **none** of the
verdicts. Corrected, on the right instruments, with matched controls and 21 years of
data, all three sit on their coin-flip baseline:

| setup | best faithful config | OOS PF | matched control | sample |
|---|---|--:|--:|--:|
| orb_retest | SPY/QQQ/IWM/DIA RTH, 09:30 anchor | 0.98 | 0.99 | 14,664 |
| false_break_fade | 5 anchors × 2 asset classes | 0.76–0.82 | 0.75–0.83 | 40,483 (eq) |
| opening_range_fade | fair-geometry equity | 0.89 | 0.88 | 7,168 |

These are not near-misses that better coding would rescue. They are setups with **no
directional information**, whose apparent results are entirely payoff geometry — which is
precisely why a geometry-matched control was the one thing the rig most needed and did
not have.

The one caveat worth stating plainly: two of the six detectors were unfaithful enough
that had they contained an edge, this program would have missed it. The conclusion is
right; the method that produced it got there partly by luck. Fix the six defects before
the next pass, because the process as it stands cannot reliably tell a dead strategy from
a mis-coded one — and that is the exact question the program exists to answer.
