# Basic-ORB hunt on gold/euro/FX — regime-dependent, no robust edge

Follow-up to PROSPECT_BACKTEST.md: swept a *basic* opening-range breakout (the
config the UFjajYgJBHg 10-yr study endorsed — no retest/FVG "secrets", R:R<2:1,
gold/euro) over open-anchor × range-size × R:R × entry on XAUUSD/EURUSD/GBPUSD/
AUDUSD 5m (2015-2025). Script: `scripts/hunt_orb.py`.

## Best config found
EURUSD · London open (07:00 UTC) · 30m range (6×5m) · R:R 1.5 · retest entry.
- OOS (2022-2025): **net PF 1.18** (gross 1.29), N=703, WR 47%.
- The whole EURUSD/London/30m cluster is robust across R:R and entry
  (net PF ~1.10-1.18) — so it's not a single lucky cell.

## Why it still fails the bar — per-year stability kills it
Net (0.7-pip) profit factor, EURUSD headline config, by year:

| 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 || 2022 | 2023 | 2024 | 2025 |
|--|--|--|--|--|--|--||--|--|--|--|
|1.03|0.92|0.94|**0.72**|**0.78**|0.94|1.04||1.18|1.12|1.14|1.61|

- **In-sample 2015-2021: net-LOSING most years** (2018-2019 badly).
- **Out-of-sample 2022-2025: positive.**
- The headline OOS PF 1.18 is a **regime artifact** of a favourable 2022-2025.
  Full-period net is ~breakeven-to-negative. Flip the IS/OOS split and this
  config would be rejected.

## Verdict
**No robust "great day trade" emerged.** Even the best opening-range config is
regime-dependent, not a stable edge, and never clears PF>=1.3 on the full sample.
Consistent with the whole intraday pass: mechanical ORB/EMA/VWAP scalps don't
hold up out-of-sample once costs are honest and you check regime stability.
Gold (XAUUSD) topped out at net PF ~1.06 — weaker than EURUSD.

## What would actually move the needle (not more ORB tuning)
- The book already has ONE validated intraday strategy: `fvg_continuation`
  (FX NY-session FVG, OOS PF ~1.46). Deepening that (the deferred 5m-gold
  faithful run) is a better bet than mining more YouTube ORB clones.
- A genuinely different intraday *mechanism* (order-flow/vol-regime/news-driven),
  not another moving-average-and-a-range retail setup.
