# k-X0164r66U — Lance: two swing strategies (mean-reversion + continuation)

Source: <https://www.youtube.com/watch?v=k-X0164r66U> · ~13 min. Ex-prop (Trillium) swing trader, **daily charts**.
**Best regime fit in the whole library** — explicitly daily-chart swing trading on liquid US stocks.

## Rules → hypotheses
1. **Mean reversion / capitulation V.** After a sharp, extended, *accelerating* move down on **massive
   volume** (capitulation), buy the **"right side of the V"** when the down-trend breaks; initial stop
   at the low, then **trail prior daily-bar lows**. → **H-MR1** (capitulation reversal entry),
   **H-MR3** (volume-climax filter — does requiring a volume spike improve it?)
2. **Continuation / breakout.** Multi-month breakout, ideally with a catalyst, in an "in-play" stock;
   buy the **breakout level**, initial stop = break back below resistance (or LOD), then **trail the
   20-period daily MA** (or prior daily-bar lows). → **H-CONT1** (multi-month breakout continuation),
   **H-CONT2** (20-MA trailing stop vs fixed target).
3. **Position sizing rule.** "If your stop is 3× wider, your size should be 3× smaller" — risk-based
   sizing tied to the daily-chart stop. → not a signal; a money-management principle (already in our
   portfolio_manager). Worth noting for any live wiring.

## Why this one matters
No FVG/ICT mysticism — concrete, daily-timeframe, volume + structure + trailing-stop rules that fit
our data exactly. **H-MR1, H-MR3, H-CONT1, H-CONT2 are the most directly backtestable hypotheses in
the library.** Strong candidates to anchor the overnight series.

## Status: queued. Prioritize for the daily-stock backtest run.
