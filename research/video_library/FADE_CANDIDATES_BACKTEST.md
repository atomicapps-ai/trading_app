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

## Standing conclusion
Across the full day-trade mining program — 30 original videos + 17 gated/ingested + the
4 mechanical prospects + the ORB param hunt + gap trading on 20y equities — **no retail
YouTube day-trade setup has cleared PF ≥ 1.3 net.** The false-break fade is a genuine
faint reversion signal (beats control) and the only lead that's even close; it could be
revisited with an equity/index-native test (SPY/QQQ intraday) where "false breakout of
the opening range" is more native than on FX. The one validated intraday edge remains
`fvg_continuation` (FX + gold, OOS PF ~1.5).

Reproduce: `python -m scripts.backtest_fade_candidates --since 2015-01-01 --oos 2022-01-01`
