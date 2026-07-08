# Intraday strategy specs — design for the 20-year deep-data validation (2026-07)

**Purpose.** We now have (pulling) ~20 years of 1-minute history (Alpha Vantage, `data/historical_1m/*.parquet`)
resampled to 5m/30m/daily. Prior intraday research (`INTRADAY_FINDINGS.md`) proved that *plain* mechanical
retail kernels (VWAP-revert, gap-fade, ORB) and the academic *Market Intraday Momentum* edge are **coin flips
on the shallow ~2021–2026 window we had**. Two hypotheses for why, both now testable:
1. **Data-depth** — the edges may have existed pre-2013 and decayed; we could not see the era they lived in.
2. **Conditioning** — a plain kernel is a coin flip *unconditionally*, but may have edge inside a regime subset.

This doc defines the **precise, mechanical** strategies we will test against the deep data. Every strategy is
specified to the point where a detector is unambiguous. Nothing here is "active" — this is the research spec that
feeds the backtest harnesses (`scripts/bt_intraday_*.py`) and, only for survivors, the wiring path
(detector → config → workflow → correlation gate → `active:false`).

## Rules of the rig (unchanged, apply to every strategy below)

- **Bars:** RTH-only (09:30–16:00 ET), resampled from the 1-min store. Session-grouped in ET; flat by the exit rule.
- **Cost:** per-symbol round-trip from `scripts/cost_model.py` (SPY/QQQ/mega-cap ≈ 1.5 bps; illiquid ≈ 12 bps).
  Auction-crossing strategies (overnight) add one extra half-spread each side — noted per strategy.
- **Scoring:** chronological **IS/OOS split** (first half / second half), **random-direction control**, gross PF
  (cost off) *and* net PF (fair cost). Report n, win%, avgR, PF for each.
- **PASS bar (to advance a strategy to wiring):** OOS **net** PF ≥ 1.2, avgR > 0, n ≥ ~100, and **beats its
  random-direction control**. A gross PF < 1.05 is dead on arrival (no edge to rescue with lower cost).
- **R normalization:** where there is a stop, R = risk-per-share to the stop. Where there is none (overnight,
  time-of-day holds), R = a fixed 5% nominal notional move, so avgR and PF are comparable across strategies.

---

## Family A — Overnight vs Intraday return split

**Rationale.** The most robust, widely-replicated equity anomaly in this space: for index ETFs and most large
caps, essentially *all* the long-run drift accrues **overnight** (prior close → next open), while the **intraday**
session (open → close) is flat-to-negative on average (Cliff–Cooper–Gulen 2008; Lachance 2021; Bogousslavsky 2021).
It is a *return-timing* effect, not a direction-prediction effect, which is exactly the kind of payoff-geometry edge
this project keeps finding to be real. It is also low-turnover (one decision/day), so cost is far less punishing than
the 30-min kernels.

| ID | Hypothesis | Entry | Exit | Filters | Cost note |
|---|---|---|---|---|---|
| **A1 overnight_hold** | Overnight drift is positive and material on ETFs/large-caps across 20y. | Buy at the close (last RTH bar, ~15:59). | Sell at next open (first RTH bar, 09:30). | None (baseline). | 1 round-trip/day, crosses close+open auctions: cost = per-symbol bps + 1 half-spread extra. |
| **A2 intraday_short** | The mirror: open→close is flat/negative; shorting it should be ≤0 (a *falsification* check on A1). | Short at open. | Cover at close. | None. | Same as A1. Expected to FAIL — it's the control for the split thesis. |
| **A3 overnight_conditional** | Overnight edge is *stronger* after specific prior-day states (down days, low VIX, non-Fridays). | Buy close only when prior RTH session return < 0 (buy-the-dip-overnight) **and** VIX < 25. | Next open. | prior_intraday_ret < 0; VIX < 25; skip Fri→Mon (weekend gap risk). | Same as A1; fewer trades. |
| **A4 overnight_minus_intraday (long/short pair)** | Long overnight + short intraday on the same name harvests both legs of the split. | At open: enter short for the day; at close: flip to long for the night. | Continuous flip open/close. | Optional trend gate (only when above 200-DMA). | 2 round-trips/day — highest cost; needs the split to be large. |

**What would make A1 real:** net OOS PF ≥ 1.2 on the ETF set with avgR > 0; A2 net ≤ ~1.0. If A1 passes but A4
doesn't, the intraday-short leg is the cost drag — keep A1/A3 only. This family is the single most likely survivor.

---

## Family B — Regime-conditioned kernels

**Rationale.** A kernel that is a coin flip *unconditionally* can still have edge inside a regime. We take the three
kernels that failed unconditionally and gate each by the regime where its mechanism *should* work. Same ent/exit as
the original kernels (`bt_intraday_research.py`), only the **admission filter** changes. If none clear, the honest
conclusion is "no conditional edge either" — which is itself worth banking on 20y of data.

| ID | Base kernel | Regime gate (only trade when…) | Mechanism logic |
|---|---|---|---|
| **B1 gapfade_highvol** | gap_fade 1–3% | VIX ≥ 22 **and** gap is *counter*-trend (gap down while price > 200-DMA, or gap up while < 200-DMA). | Mean-reversion pays in high-vol; counter-trend gaps over-extend and snap back. |
| **B2 orb_trend_hvol** | ORB-30 breakout | SPY > 200-DMA (risk-on) **and** opening 30-min volume ≥ its 20-day median for that slot. | Breakouts continue only with market tailwind + real participation. |
| **B3 vwap_revert_range** | vwap_revert (wide stop, time-gated) | Day's ATR%≥ 60th pct **and** SPY within ±1% of 20-DMA (rangey, not trending). | Reversion to VWAP works in choppy/range regimes, fails in trends. |
| **B4 gapfade_monday** | gap_fade 0.5–2% | Weekday = Monday (documented weekend-overreaction reversal). | Calendar-conditioned reversion. |

**PASS = a gated variant's OOS net PF ≥ 1.2 AND materially above the *ungated* kernel's PF** (so the regime, not
luck, is doing the work). We also report the gate's trade-count cost — a gate that leaves n < 100 is too thin.

---

## Family C — Opening-range / first-hour

**Rationale.** The project's own Opening-Candle research found the **30-min first candle predicts day *direction*
~83%** (strong-body + close-in-range + high-volume), but intraday **TP/SL fails because MAE is too large** — so the
correct mechanic is **direction + EOD exit, no profit target** (the Double-Lock lesson: cut at structure/EOD, don't
cap the winner). We re-test that on 20y, plus the classic ORB variants defined with fair cost.

| ID | Hypothesis | Entry | Exit | Filters |
|---|---|---|---|---|
| **C1 opening_conviction** | A strong directional first 30-min candle predicts the day; ride it to the close. | At 10:00 (close of first 30-min bar): go long if the bar is BULL + body ≥ 50% of range + close in top 40% of range + volume ≥ 20-day slot median; short the mirror. | EOD close (15:59); catastrophic 3% stop only. | SPY-agnostic first pass; then add SPY>200-DMA for longs. |
| **C2 opening_double_lock** | Two consecutive same-direction conviction candles (10:00 + 10:30) → higher-confidence day. | At 10:30, enter in the shared direction if both 30-min bars were conviction candles (as C1) same sign. | EOD close; 3% stop. | This is the honest re-test of the removed `double_lock` on 20y + fair cost. |
| **C3 orb_breakout** | Break of the first 30-min range continues to a range-height target. | Stop-entry at first-30 high (long) / low (short) when broken after 10:00. | Target = 1× range height; ATR-scaled stop at opposite range edge; EOD backup. | Long-only in SPY>200-DMA on second pass. |
| **C4 orb_fade** | A *failed* breakout (pokes the range edge then closes back inside) fades to the far edge / VWAP. | On first 30-min-range break that reverses back inside within N bars, enter counter. | Target VWAP or opposite edge; stop beyond the failed extreme; EOD. | Works better in range regime (pair with B3 gate later). |

**Note on C1/C2 vs history:** the prior finding was 83% *directional* accuracy but a *losing* strategy when a tight
TP/SL was bolted on. The whole point of C1/C2 is to test whether **EOD-exit (payoff geometry fixed)** converts that
directional edge into positive expectancy net of cost — the single most important open question from the DL era.

---

## Family D — Time-of-day / last-hour structure

**Rationale.** Intraday returns are not uniform across the session — open and close carry most of the volume and
information; midday is quiet. These are microstructure/flow effects (index rebalancing, MOC auction imbalance,
option hedging) and are less crowded than ORB/VWAP retail setups.

| ID | Hypothesis | Entry | Exit | Filters |
|---|---|---|---|---|
| **D1 last_hour_momentum** | If the day is trending by 15:00, the last hour continues it (MOC imbalance + hedging flows). | At 15:00, go long if day return (open→15:00) > +X% (e.g. > +0.3%); short if < −X%. | Close (15:59). | Threshold X tuned on IS only; report OOS. |
| **D2 lunch_reversion** | The late-morning extreme (11:00–12:00) over-extends; fade it into the afternoon. | At 12:00, fade the sign of the 09:30→12:00 move if |move| > Y%. | 14:00, or VWAP touch, or EOD. | Range-regime gate optional. |
| **D3 first30_to_last30** | The Gao intraday-momentum re-test **on 20y** (first-30 return predicts last-30). | At 15:30, long/short by sign of first-30-min return. | Close. | This is the deep-data re-run of the null we found on 5y — the key "did depth change the answer" test. |
| **D4 power_hour_reversal** | The final 30 min *reverses* the day's move (profit-taking into close) on high-range days. | At 15:30, take the *opposite* of the 09:30→15:30 sign when |day move| is large (top tercile). | Close. | Direct contrast to D1/D3 — only one of {momentum, reversal} can dominate; 20y tells us which. |

**PASS bar identical.** D1 and D4 are deliberately opposed hypotheses on the same window; the deep data adjudicates.
D3 is the headline re-test: if 20y (incl. pre-2013) shows D3 net PF ≥ 1.2 in-era but ~1.0 recently, that *confirms*
post-publication decay rather than a broken rig — a valuable, publishable-quality finding either way.

---

## Execution plan

1. **Now (deep ETFs ready):** run all families on the 10 completed 20-year symbols
   (SPY, QQQ, IWM, DIA, XLE, XLF, XLI, XLK, XLV, AAPL). ETFs are the fairest test (lowest cost, cleanest overnight
   split). Rank by OOS net PF vs control. Record survivors + nulls in this doc.
2. **On full-pull completion (~102 symbols):** re-run breadth. A real edge should hold across many names, not 2.
3. **Survivors only:** wire detector → `strategy_configs/*.yaml` → `workflows/*_scan.yaml` → correlation gate
   (max|corr| < 0.60 to the live book) → ship `active:false` for human review. Same path as every other strategy.

---

## RESULTS — 20-year preliminary validation on 9 deep ETFs (2026-07-08)

Ran all 11 strategies pooled across **SPY, QQQ, IWM, DIA, XLK, XLF, XLE, XLV, XLI** — each with full
**2005→2026** 1-minute-derived history (~5,400 trading days / symbol). `intraday_families_deep_etfs.json`.

| Strategy | n | gross PF | net PF | **OOS net PF** | OOS avgR | ctrl PF | verdict |
|---|---|---|---|---|---|---|---|
| **A1 overnight_hold** | 48,681 | **1.17** | 1.01 | 1.02 | +0.001 | 1.02 | real gross, **washes to ~1.0 net** |
| A2 intraday_short | 48,681 | 0.98 | 0.88 | 0.85 | −0.012 | 1.01 | negative (confirms the split) |
| A3 overnight_conditional | 10,966 | 1.23 | 1.00 | 0.97 | −0.001 | 1.00 | passed on SPY alone (OOS 1.25) but **washes pooled** |
| B1 gapfade_highvol | 2,057 | 0.90 | 0.86 | 0.89 | −0.042 | 1.01 | dead |
| B2 orb_trend_hvol | 11,715 | 0.89 | 0.78 | 0.83 | −0.064 | 0.95 | dead |
| C1 opening_conviction | 11,491 | 1.14 | 1.06 | 0.95 | −0.006 | 0.99 | gross edge, **decays OOS net** |
| C2 opening_double_lock | 4,912 | 1.05 | 0.96 | 0.94 | −0.006 | 1.03 | dead net (DL removal vindicated on 20y) |
| C3 orb_breakout | 48,059 | 1.02 | 0.90 | 0.91 | −0.036 | 0.99 | dead |
| D1 last_hour_momentum | 32,406 | 1.11 | 0.95 | 0.91 | −0.003 | 1.00 | gross edge, net coin-flip |
| D3 first30_to_last30 | 48,041 | 1.11 | 0.88 | 0.75 | −0.006 | 1.01 | **Gao decay re-confirmed on 20y** |
| D4 power_hour_reversal | 16,492 | 0.86 | 0.74 | 0.81 | −0.006 | 1.04 | dead |

**Headline findings:**

1. **The overnight/intraday split is REAL and confirmed on 20 years.** Raw means (per day): overnight
   +0.03–0.05% vs intraday +0.00–0.02% for every ETF; **IWM intraday is negative** (−0.005%). A1 gross PF
   1.17 across 48,681 symbol-days is exactly this anomaly. A2 (short the intraday leg) is correctly negative.
   This is a genuine, replicated structural fact — not a fluke of the recent window.

2. **But it does not net-clear cost at daily ETF frequency.** The per-night edge (~0.004 R) is only
   marginally above the auction-crossing round-trip (~0.0045 R), so A1/A3 wash to **net PF ≈ 1.0**. Real gross,
   uncapturable cheaply *as a daily ETF strategy*. A3 passed on SPY alone (OOS 1.25) but that was small-sample /
   idiosyncratic — it washes out pooled, so it does **not** clear the PASS bar honestly.

3. **No crowded kernel survives — even on 20 years, even regime-conditioned.** B/C/D are all net < 1.0 OOS and
   at/below their random controls. Depth did **not** rescue them → the earlier ~5-year null was not a data
   artifact for these setups. Notably **D3 (Gao intraday-momentum) got *worse* OOS on the deep data (0.75)**,
   and **C1/C2 (conviction + EOD-exit) decay OOS net** — so fixing payoff geometry did *not* convert the 83%
   directional signal into money. Both long-standing project questions are now answered: the academic edge is
   decayed, and the opening-conviction signal isn't tradeable net. The `double_lock` removal is vindicated on 20y.

**Nothing clears the PASS bar → nothing to wire yet.** This is a valuable negative result on the fairest
possible data.

**The one live lead → single-stock overnight (pending full pull).** The split is *largest* on IWM (small-caps)
and the overnight effect is documented to be far stronger on individual small/mid-cap stocks than on mega-cap
ETFs — where a bigger gross edge could clear the same cost. So the key follow-up when the 100-symbol universe
finishes is **A1/A3 run per-stock (and on lower-priced, higher-overnight-drift names)**, plus **selective
overnight** (hold only the highest-conviction nights: post-large-down-day, pre-month-end, earnings-adjacent) so
fewer round-trips carry more edge each. That is the version with a real shot at net > 1.2.

## Priors (what we expect, stated up front so we can be wrong)

- **Most likely to pass:** A1/A3 (overnight) — robust, low-turnover, mechanism well-established.
- **Coin-flip risk:** C3/C4 (ORB) and B-series — crowded; conditioning may or may not rescue them.
- **Headline science:** D3 (intraday-momentum depth re-test) and C1/C2 (conviction + EOD-exit) — these answer the
  two questions the project has been unable to close: did the academic edge decay, and does fixing payoff geometry
  turn the 83% directional signal into money.
