# rf_EQvubKlk — "High win-rate MACD Strategy" (MACD + 200-MA)

Source: <https://www.youtube.com/watch?v=rf_EQvubKlk>

## Rules (mechanical) — daily
- **Entry (long):** MACD line (12/26) crosses **up through the signal line while both are below the zero line**, AND price is above the **200-day MA** (uptrend filter). Short = mirror (cross down above zero, price below 200-MA).
- **Stop:** below the 200-day MA. **Target:** 1.5R.
- **Enhancement:** add a support/resistance bounce as confluence to avoid sideways false signals.

## Verdict: PASS — matches the live, validated `macd_run` strategy.
This is exactly the deployed **`macd_run`** strategy in the live suite: *MACD crosses up through signal below zero, 200-MA uptrend*. That strategy is already OOS-validated — config/CLAUDE.md record **OOS PF ~1.52, +0.27R**, and a fresh `score_universe --strategy macd_run` over the ~500-symbol universe confirms a strong in-sample edge (IS PF 5.07 pre-trim, avg-R +0.28, n≈6,700; 185 KEEP symbols). The video's only deviation is a fixed 1.5R target vs. macd_run's cross-back-down exit, but the validated core (MACD-below-zero cross + 200-MA filter) is identical and already in production.

Recorded as PASS because the strategy is already mechanized, OOS-validated, and live as `macd_run`. Nothing further goes live from this run.
Status: passed
