# Fade candidates backtest — the 2 that survived transcript assessment

The gated + hardened-gate + ingest round surfaced 17 videos; transcript assessment
(deny-list + mechanical test) rejected 15 and kept **2 novel, mechanical range-FADE
setups**. Both were backtested on FX 5m + gold (2015-2025, net of per-asset spread,
IS/OOS split 2022) via `scripts/backtest_fade_candidates.py`.

## Result — neither clears PF ≥ 1.3

| strategy | source | pooled OOS net PF | vs control | verdict |
|---|---|--:|--|---|
| false_break_fade | 2WmeKqsGTQk | **0.96** (NY) / 0.95 (London) | beats control 0.80 ✓ | ❌ reject (below bar) |
| opening_range_fade | 6WfTIyJ-YzQ | 0.78 (NY) / 0.88 (London) | loses to control | ❌ reject |
| _control_ (fade every open) | — | 0.80 | baseline | — |

- **false_break_fade** (4h range → 5m body closes outside then back inside → fade to
  opposite edge, 2R) is the **closest of the entire day-trade pass**: it consistently
  beats the fade control, and **EURUSD is net-positive** (OOS gross 1.23 / net 1.08,
  N=354). But pooled it's ~breakeven-negative and never reaches 1.3.
- **opening_range_fade** (first 15m range ≥ 20% daily ATR → fade the opening candle) is
  a net loser, worse than the control.

## CORRECTION (2026-07-20) — "beats the control" was an artifact; there is no faint signal

The control on this page (`control_fade`) trades a **1:1** payoff while both strategies
trade **2R**. PF at 1:1 and PF at 2:1 are not comparable, so "beats the fade control 0.80"
compared two different geometries and said nothing about directional skill.

Re-tested against a control that holds timing, stop distance and target geometry fixed and
randomises only **direction** (`scripts/bt_fbf_faithful.py`, `scripts/bt_equity_open_setups.py`),
and with the five ways the detector diverged from the video corrected — the creator's
actual 4-hour NY range anchor (00:00–04:00 ET, not the 13:00-UTC London/NY-overlap block),
every re-entry per session rather than one, entry at the next bar's open, his explicit
">1% beyond the range → stop fading" rule, and a stop-distance cap:

| variant | OOS PF | matched control | edge |
|---|--:|--:|---|
| original 13:00-UTC anchor, 1 trade/day | 0.818 | 0.828 | none |
| faithful 4h NY range, every re-entry | 0.778 | 0.787 | none |
| + the >1% no-fade rule | 0.778 | 0.774 | none |
| + capped stop distance | 0.783 | 0.781 | none |
| London anchor | 0.802 | 0.797 | none |
| **SPY/QQQ/IWM/DIA RTH, 21y, n=40,483** | **0.750** | **0.751** | none |

`false_break_fade` sits **exactly on its coin-flip baseline** in every configuration, on
both asset classes, across 21 years. It is not "the closest lead" — it has no directional
content at all. The equity-native test this page called for has now been run and it fails
there too.

`opening_range_fade`'s reported PF was also unfair rather than merely bad: the
mechanisation put the stop on the opening-range extreme while entering next to it, giving
a median risk of ~6 bps against a 2 bp cost (34% of the risk unit). With a tradeable stop
it scores 0.89 vs a 0.88 control — still no edge, but the original 0.35/0.78 numbers were
never a fair test. See `PROCESS_AUDIT.md` §D1, §D3.

**Reproducibility note:** re-running the original command today gives pooled OOS net PF
0.922 for `false_break_fade` vs 0.963 for `control_fade` — i.e. it now *loses* to the
control it was said to beat, and EURUSD OOS N is 533 vs the 354 recorded here. The FX
cache has grown to 2026-07-20; results were never pinned to a data snapshot.

## Standing conclusion
Across the full day-trade mining program — ~250 videos triaged, 38 mechanised and
backtested — **no retail YouTube day-trade setup has cleared PF ≥ 1.3 net**, and the three
leads that looked closest have now been re-tested faithfully, on their native instruments,
against matched controls, and show **zero** directional edge. The one validated intraday
edge remains `fvg_continuation` (FX + gold, OOS PF ~1.2–1.36 against a 0.78–0.84 control).

Reproduce:
```bash
python -m scripts.backtest_fade_candidates --since 2015-01-01 --oos 2022-01-01   # original
python -m scripts.bt_fbf_faithful --variants all                                  # fidelity sweep
python -m scripts.bt_equity_open_setups --symbols SPY,QQQ,IWM,DIA --since 2005-01-01
```
