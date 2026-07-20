# 6WfTIyJ-YzQ — opening_range_fade

## Backtest result (scripts/backtest_fade_candidates.py)
- Opening-range exhaustion fade (first 15m range >= 20% daily ATR -> fade opening candle to opposite OR edge). Backtested FX 5m + gold, 2015-2025, net of spread: pooled OOS net PF 0.78 (NY) / 0.88 (London), avg-R negative — a net LOSER, worse than the fade control on most symbols. Only EURUSD gross-positive. Reject.
- Verdict: REJECTED (informative — backtested, below bar).

## Re-test — the original number was a harness artifact (2026-07-20)

The reported PF (0.78 FX / 0.365 on my first equity run) was not a fair test. The
mechanisation places the stop **on** the opening-range extreme while entering right next
to it, giving a **median risk of ~6 bps on SPY**. Against a 2bp round-turn cost that is
**34% of every risk unit** — a trade no discretionary trader would take, and the source
video sizes stops off ATR, not off the bare extreme.

With a tradeable stop (`scripts/bt_equity_open_setups.py`, SPY/QQQ/IWM/DIA, 21y):

| stop buffer | min risk | N | OOS PF | median risk | matched control |
|---|--:|--:|--:|--:|--:|
| none (as originally tested) | — | 8,101 | **0.365** | 8.2 bps | 0.351 |
| 0.10 × ATR | — | 8,346 | 0.844 | 21.7 bps | 0.843 |
| none | 20 bps | 1,363 | 0.963 | 28.5 bps | 0.939 |
| 0.25 × ATR | 25 bps | 7,168 | 0.890 | 46.0 bps | 0.877 |

**Verdict unchanged — REJECTED** (every row still equals its control, so there is no
directional edge) — **but the recorded number was ~2.5× too harsh and was never a fair
test.** Note also that the mechanisation replaces the video's two-reversal-candle trigger
with an immediate fade at the OR close; of the six backtested detectors this is the one
furthest from what the creator actually teaches. See `PROCESS_AUDIT.md` §D3.
