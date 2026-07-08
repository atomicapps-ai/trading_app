# uQP2z4OXMRo — "Does trend following work?" (review of an RDB Computing study)

Source: <https://www.youtube.com/watch?v=uQP2z4OXMRo>

## Content — a walkthrough of a research study, not a strategy
- Reviews a long-only trend-following study (RDB Computing) over ~24,000 US stocks, 1983–2005
  (22 yrs), using an **ATR trailing-stop** exit (the study's focus vs a prior %-stop study).
- Conclusion-style content about whether momentum/trend capture beats buy-and-hold.

## Verdict: REJECT — study review; mechanical core already covered
This isn't a self-contained strategy — it's a summary of someone else's backtest, and it doesn't
even fully specify an *entry* (the study's variable of interest is the ATR trailing stop). The
mechanical idea it endorses — long-only trend following exited by an ATR trailing stop — is
already implemented and live: `momentum_breakout` (126-day-high breakout, ATR stop, 50-SMA
trail), and the trend-following payoff was just re-demonstrated by the MA-crossover test
(k_kSCjdf8D0). Corroborates existing findings; adds no new, separable, testable strategy.
Status: rejected
