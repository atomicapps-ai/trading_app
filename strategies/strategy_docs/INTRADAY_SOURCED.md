# Intraday day-trades — sourced from a reliable, tested source (2026-07-08)

**Why this doc exists.** The ~20 intraday strategies in `INTRADAY_STRATEGY_CATALOG.md` were mostly homemade
kernels (VWAP/gap/ORB) plus one academic paper — weak provenance. These are **fresh, sourced from published,
net-of-cost, rigorously-backtested research** and specified precisely enough to reimplement. Each still must
pass our own rig (OOS net PF ≥ 1.2, avg-R > 0, n ≥ ~100, beats control) before it's wired.

## Source: Concretum Research (Zarattini · Aziz · Barbon), SSRN
A quant research group (ex-BlackRock quant + St.Gallen finance prof + pro day-trading fund). Their day-trade
papers are SSRN-published, **net of realistic commission + slippage**, survivorship-bias-free, and explicitly
"based on economic rationale rather than retrospective optimization." Reference Python/Matlab implementations
exist. This is about as credible as retail-accessible day-trade research gets. Full paper list:
`https://concretumgroup.com/papers/`.

---

## CANDIDATE S-I1 — "Stocks in Play" 5-minute ORB  ★ flagship
Source: *A Profitable Day Trading Strategy for the U.S. Equity Market* (SSRN 4729284, 2024).
Reported: 2016–2023, top-20 Stocks-in-Play, **+1,637% net / Sharpe 2.81 / alpha 36% / beta ~0 / MDD 12% /
hit 48.4%**. Base version (no relative-volume filter) is poor (Sharpe 0.48) — **the edge is entirely in the
selection filter**, which is exactly the "trade where the volume/participation is abnormal" thesis.

**Universe filters (each day, per stock):**
- open price > **$5**
- avg daily volume over prior **14 days ≥ 1,000,000 shares**
- **ATR(14) > $0.50**
- **Relative Volume ≥ 100%**, where `RelVol = (first-5min volume today) / mean(first-5min volume over prior 14 days)`
- **trade only the TOP 20 stocks by RelVol** that day

**Trade definition:**
- Look at the first 5-min candle (09:30–09:35 ET). If **bullish** (close>open) → place a **stop-BUY at the 5-min high**, long only. If **bearish** → **stop-SELL at the 5-min low**, short only. Doji (open=close) → no trade.
- **Stop loss = 10% × ATR(14)** from the entry price.
- **Exit at EOD (16:00)** if the stop isn't hit first. No profit target.
- **Sizing:** risk **1%** of capital per trade (position sized so a stop = −1%); **max 4× leverage**.
- Costs used: **$0.0035/share** commission.
- Timeframe note: 5-min ORB dominates; 15/30/60-min much weaker (Sharpe 1.43/0.21/0.40).

**Testable now?** Partially. Needs **5-min bars on a broad universe** and, ideally, **delisted names**
(survivorship-free). Our liquid-100 is survivor-biased (over-states results) but is a valid first pass once the
pull lands. The RelVol filter + top-20 selection is the core and is fully implementable.

---

## CANDIDATE S-I2 — "Beat the Market" Intraday Momentum (SPY)  ★ flagship · testable NOW
Source: *Beat the Market: An Effective Intraday Momentum Strategy for SPY* (SSRN 4824172, 2024/25).
Reported: 2007–2024, final version **+1,985% net / 19.6% ann. / Sharpe 1.33 / MDD 25% / alpha 19.6% / beta ≈ −0.07**,
~1.8 trades/day. **Only needs SPY — which we already have at full 20-year 1-minute depth. Immediately testable.**

**Bars/timing:** 1-min data, but **decisions only at :00 and :30** each hour (ET). First entry 10:00. Always flat by 16:00.

**Noise-area boundaries** (anchored to today's open, gap-adjusted, recomputed every HH:MM):
```
move_{t-i, 9:30→HH:MM} = | Close_{t-i,HH:MM} / Open_{t-i,9:30} − 1 |      # i = 1..14
σ_{t,HH:MM}            = mean of those 14 absolute moves   (a MEAN of |returns|, NOT a stdev)
Upper_{t,HH:MM} = max(Open_t, PrevClose_{t-1}) × (1 + VM · σ_{t,HH:MM})
Lower_{t,HH:MM} = min(Open_t, PrevClose_{t-1}) × (1 − VM · σ_{t,HH:MM})
VM (volatility multiplier) = 1   # paper's headline; ~1.5 gave best risk-adj
```
**Entry:** at a :00/:30 mark, **long if price > Upper**, **short if price < Lower**. One position at a time; if
price crosses to the opposite band, **reverse** (close + open opposite). Multiple trades/day allowed.

**Exit / trailing stop (dynamic, final version):** close long when price crosses **below `max(Upper, VWAP)`**;
close short when above `min(Lower, VWAP)` (VWAP = session-anchored, RTH only — the *tighter* reference).
Also flat at 16:00. No profit target.

**Sizing (vol-targeting):**
```
σ_target = 2% daily
σ_SPY,t  = sample stdev of last 14 daily returns (÷13, i.e. n−1)
Shares_t = floor( AUM × min(4, σ_target / σ_SPY,t) / Open_t )     # leverage cap 4×
```
**Costs:** $0.0035/share commission + $0.001/share slippage.
**Documented conditioners (not gates):** edge rises with VIX; Wednesday strongest (FOMC/opex); best on NR4/NR7
days, none on trend days; low prior 5-day RSI predicts higher returns (β −3.25).

---

## Queue — rest of the Concretum day-trade catalog (specs to extract next)
| # | Candidate | Source (SSRN) | Reported | Notes |
|---|---|---|---|---|
| S-I3 | **VWAP day-trading system (QQQ/TQQQ)** | 4631351 | $25k→$192k (QQQ) / $2.08M (TQQQ), 2018–2023 | VWAP-anchored intraday; needs QQQ/TQQQ 1-min (have QQQ). |
| S-I4 | **ORB on QQQ/TQQQ** ("Can Day Trading Really Be Profitable?") | 4416622 | +1,484% (TQQQ) vs 169% QQQ, 2016–2023 | The single-ETF precursor to S-I1; directly testable on QQQ. |
| S-I5 | **Power of Price Action Reading** (gap&go / PEAD, discretionary+systematic) | 4879527 | discretionary overlay lifts a systematic gap strategy | event/gap-driven; needs news/earnings flags. |
| S-I6 | **Fast Alphas overlay** (intraday trend + 5-min mean-rev execution overlay) | 6391638 | mean-rev signal unprofitable alone but improves net trend CAGR/Sharpe | an *execution* overlay, not a standalone edge. |

## How these differ from our dead kernels (why they might survive where ours didn't)
1. **Selection, not just trigger.** S-I1's edge is *which stocks* (top-20 abnormal RelVol / news catalysts), not the ORB mechanic — our ORB kernels traded everything and died. Matches the "trade where participation is abnormal" thesis.
2. **Anchored, adaptive bands.** S-I2's boundaries scale with each day's own realized intraday move and time-of-day — adaptive, not a fixed threshold.
3. **Let winners run + trail.** Both use EOD/trailing exits with **no profit target** — the payoff-geometry lesson this project keeps re-learning.
4. **Honest costs already baked in** at the source, and they still clear — so we're validating a *live* claim, not reviving a decayed one.

## Test plan
- **Now:** implement S-I2 on our 20-yr SPY (fully specified, single symbol) → run in the rig with fair cost + IS/OOS + control. This is the highest-value immediate test — a credible, still-live claim on data we already have.
- **On full pull:** implement S-I1 (RelVol top-20 ORB) on the liquid-100 5-min set (survivor-biased first pass), and S-I4 on QQQ. Flag the survivorship caveat.
- Survivors → correlation gate vs the live book → wire `active:false`.
