# Intraday (day-trade) research — findings, 2026-07

**Result: no deployable intraday stock day-trade edge found in this data. Nothing promoted.**

## What was tested

`scripts/bt_intraday_research.py` — a same-day rig on 30-minute US-stock bars (60–80 symbols,
~5 years, session-grouped in ET, flat by 15:00). Metrics: chronological IS/OOS, random-direction
control, **and gross PF (cost off)** to separate edge from cost. Kernels (long-biased):

- **VWAP reversion** — buy a % stretch below session VWAP in a daily uptrend; target VWAP.
  Stops: first a session-low stop (too tight — 24% win, PF ~0.3), then a wide daily-ATR-scaled
  stop + a 10:30–14:00 entry gate (46% win, PF ~0.53).
- **RSI(2) intraday bounce** — 30m RSI(2)<10 below VWAP; target VWAP.
- **Opening-range fade** — failed breakdown of the first-2-bar range back into it.
- **Opening-range breakout** — momentum contrast (break above the range, target = range height).
- **Gap fade** — fade a morning gap-down toward the prior close; several gap bands (0.5–5%),
  full vs half fill targets, ±trend filter.

## The numbers (80 symbols)

| Kernel | n | win% | OOS PF (net) | ctrl PF | **gross PF** |
|---|---|---|---|---|---|
| vwap_revert (wide stop, time-gated) | 4,759 | 46% | 0.54 | 0.54 | 0.98 |
| gap_fade 1–3% full fill | 2,960 | 50% | 0.81 | 0.69 | **1.07** |
| gap_fade 1–3% half fill | 2,960 | 55% | 0.71 | 0.57 | 1.03 |
| gap_fade 2–5% full fill | 1,387 | 45% | 0.87 | 0.76 | 0.97 |
| (RSI2, ORB fade/breakout) | — | 33–40% | 0.19–0.44 | ~control | <1 |

JSON: `data/research/strategy_results/intraday_research.json`.

## Interpretation

- **Even GROSS of costs, the best kernel is PF ~1.07** — essentially a coin flip. After realistic
  day-trade costs it's net-losing, and every kernel sits at/below its random-direction control.
  So there is no directional edge to deploy, and it isn't merely a cost problem — the edge isn't
  there gross either.
- The 10-bps round-trip cost is *heavy* at intraday stop sizes (~0.17R/trade), but even halving it
  wouldn't lift a ~1.0 gross PF over the 1.2 bar.
- **This matches the project's own history.** `double_lock` was removed because its real intraday
  edge was ~53% (see CLAUDE.md), and the Opening-Candle research found that day-DIRECTION signals
  (strong on the 30m first candle) do **not** survive intraday TP/SL because MAE is too large.
  Stock intraday history here is also only ~5 years, so OOS confidence is lower than the 20-yr daily rig.

## Update (2026-07) — fair-cost + finer-data re-test (Track A)

We suspected the null might be a data/cost artifact: the sweep above used **30-minute bars and a
flat 10-bps cost**, which is ~6.7× too high for liquid intraday names. So we (a) built a per-symbol
cost model (`scripts/cost_model.py`; SPY/QQQ/AAPL/NVDA ≈ **1.5 bps** round-trip, not 10), (b) fetched
**5-minute** bars, and re-ran the kernels (`scripts/bt_intraday_fair.py`, 60 symbols).

| Kernel | GROSS PF (5m) | NET fair (~1.5bps) | NET old (10bps) |
|---|---|---|---|
| vwap_revert | 0.96 | 0.67 | 0.50 |
| gap_fade 1–3% full | 0.86 | 0.66 | 0.57 |
| gap_fade 0.5–2% half | 0.93 | 0.61 | 0.44 |

Two honest takeaways:
1. **Fair cost matters** — net PF rises materially (0.44–0.57 → 0.58–0.67), confirming the flat 10-bps
   was unfairly punitive. The process critique was right; the infrastructure is now fair.
2. **But it's NOT a cost/data artifact.** Even **gross of cost, on finer 5m bars, every kernel is
   < 1.0** — *worse* than at 30m — because finer bars add noise/whipsaw to these mean-reversion/gap
   kernels. Fair cost + finer data did not reveal a hidden edge; it confirmed the absence of one for
   these standard retail kernels.

Conclusion: stop tuning the standard kernels. The now-fair rig (per-symbol cost + 1m/5m data) is
ready, and the value is in sourcing **novel, less-crowded** intraday edges (academic microstructure,
futures, quant-community code) rather than re-testing crowded classics.

## Recommendation

Do **not** promote any intraday stock day-trade from this pass. The scaffold (`intraday_reversion`
+ `bt_intraday.py` harness + the day-trade lane) stays in place, ready for a real edge. Honest
paths that could change the answer (none guaranteed):

1. **Ultra-liquid subset + realistic low cost** — on SPY/QQQ/mega-caps a ~2-bps round trip is real;
   gap_fade (gross ~1.07) *might* net-clear there, but 1.07 gross is not a robust edge — treat any
   such result with heavy skepticism and large OOS samples.
2. **FX intraday** — the existing `fvg_continuation` (FX) already validated (PF ~1.48); the FX
   session structure may hold more intraday edge than US stock intraday. Revisit once the IBKR FX
   broker is live.
3. **Event-driven intraday** (earnings/news gaps) rather than purely mechanical — different data.

Bottom line: the data says mechanical same-day stock edges aren't here. Better to know that than
to ship a coin flip that loses after costs.
