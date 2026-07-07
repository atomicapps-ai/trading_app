# W8ENIXvcGlQ — Larry Connors RSI-pullback strategy ("88.89% win rate")

Source: <https://www.youtube.com/watch?v=W8ENIXvcGlQ>  (credits Larry Connors)

## Rules (mechanical) — long-only mean-reversion pullback
- **Trend filter:** price above its **200-day SMA** (else stay in cash).
- **Entry:** **RSI(10) < 30** → buy the next day's open (market order).
- **Exit:** **RSI(10) crosses above 40** → sell next open; OR a **10-trading-day time stop**.
- **No hard stop-loss** (pure mean reversion; the time stop caps duration).

## Backtest (strategy_suite rig, 955-symbol daily US-stock universe, per-symbol 200-SMA+RSI10, 10bps, IS/OOS, control)
No protective stop, so R is normalised to a fixed nominal 5%-of-price risk (constant), which
makes profit_factor and win% equal the true dollar figures:

| Segment | n | win% | PF | avg-R |
|---|---|---|---|---|
| in-sample | 9,179 | 69.7% | 1.59 | +0.140 |
| **out-sample** | 9,179 | **68.3%** | **1.31** | **+0.100** |
| random control | 18,358 | 48.3% | 0.90 | −0.037 |

Script: `scripts/bt_connors_pullback.py`; JSON: `data/research/strategy_results/connors_pullback_video.json`.

## Verdict: PASS
Clears every bar comfortably: OOS profit factor **1.31** (≥1.2), avg-R **+0.10** (>0), ~18k
trades (>>100), and it decisively beats its random-direction control (1.31 vs 0.90). The high
win rate is real — 68–70% — consistent with a shallow-pullback mean-reversion that exits on the
first RSI recovery (the video's "88.89%" is inflated but the *direction* is right). It holds out
of sample (IS 1.59 → OOS 1.31; both halves strongly positive).

Context: this is a textbook Connors pullback and it lands in the mean-reversion family alongside
the already-passed BB/RSI (pCmJ8wsAS_w) and BB-3SD-fade (FqxEKDxemtI) candidates and the live
`fear_dip_reversion`. Its distinguishing feature is the RSI(10)<30 / RSI(10)>40 trigger-and-exit
with **no hard stop** — higher win rate, smaller average win, different risk profile (tail risk
lives in the no-stop time exit). Validated **candidate only** — nothing goes live from this run;
adoption and correlation vs the existing mean-reversion strategies (they likely fire together in
selloffs) is a separate human decision.
Status: passed
