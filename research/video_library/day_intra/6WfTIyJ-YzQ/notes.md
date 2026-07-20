# 6WfTIyJ-YzQ — opening_range_fade

## Backtest result (scripts/backtest_fade_candidates.py)
- Opening-range exhaustion fade (first 15m range >= 20% daily ATR -> fade opening candle to opposite OR edge). Backtested FX 5m + gold, 2015-2025, net of spread: pooled OOS net PF 0.78 (NY) / 0.88 (London), avg-R negative — a net LOSER, worse than the fade control on most symbols. Only EURUSD gross-positive. Reject.
- Verdict: REJECTED (informative — backtested, below bar).
