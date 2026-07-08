# R3T1zRyZdMc — "How to backtest the right way" (Artie / The Moving Average)

Source: <https://www.youtube.com/watch?v=R3T1zRyZdMc>

## Content — backtesting methodology, not a strategy
- Argues most people backtest wrong: they start from "today" and eyeball every signal
  (e.g. a 21/200 MA crossover), which biases results.
- The video is about *how to backtest* (avoiding hindsight bias, sampling, walk-forward-ish
  discipline) using EURUSD as the walkthrough example.

## Verdict: REJECT — no tradeable strategy to mine
There is no strategy specification here — no entry/stop/target rule set of its own. It's a
process/education piece about backtesting technique (its only concrete example, a 21/200 MA
crossover, is used to illustrate *method*, not proposed as an edge). Nothing mechanical to
translate into the strategy_suite. Out of scope for the mining loop.
Status: rejected
