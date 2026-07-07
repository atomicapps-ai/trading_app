# n-SEsjdZaMo — "Gap Up / Gap Down strategy" (Humble Trader)

Source: <https://www.youtube.com/watch?v=n-SEsjdZaMo>

## Rules (as described)
- **Universe:** large-cap US stocks that gapped overnight (pre-market scanner), driven by a fundamental catalyst (earnings beat/miss + guidance).
- **Gap-up long:** gap opens above a key daily resistance / 52-week high; buy the pullback to the level or the break of pre-market highs; **stop = 5-min VWAP**; target successive daily resistance / measured continuation; can replay for 2–3 days.
- **Gap-down short:** mirror — gap below support / 52-week low on bad earnings, short bounces toward VWAP.

## Verdict: REJECT — intraday + event-driven + discretionary, out of scope.
Although the universe is US stocks, execution is **intraday**: VWAP on 5-/2-minute charts for entries and stops, pre-market levels, "first five minutes of the day" scalps into resistance. The edge is explicitly an **earnings catalyst** (event-driven, not in the daily OHLCV rig) plus hand-drawn levels. A daily-only "earnings-gap continuation" would need an earnings-event feed and a custom gap detector — not a clean daily-bar setup and not built here. Not testable in the project's daily swing framework.
Status: rejected
