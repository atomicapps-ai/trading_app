# Gap day-trade backtest — no edge (definitive, huge sample)

Tested the standout day-trade lead from the backlog — **qkChxbuUqvU "Gap Trading
Prints You Money (Gap Up/Down/Fill)"** — directly, without needing the transcript.
Gap trades are a same-session open→close day trade, so they evaluate faithfully on
daily bars: enter at the open, use the day's High/Low to detect whether the gap-fill
target (prior close) or the stop was touched intraday, else exit at the close.

Script: `scripts/backtest_gap.py`. **595 US equities · ~20y (2006-2026) · OOS ≥ 2018 ·
5 bps round-turn cost.** Up to 564k trades per config — this is definitive, not noise.

## Result — every config is net-negative

| model | gap≥ | stop | N (OOS) | WR% | PF gross | PF net | avg-R |
|---|--:|--:|--:|--:|--:|--:|--:|
| fade | 2.0% | 3% | 87,623 | 47.6 | 0.965 | **0.922** | −0.01 |
| go | 1.0% | 2% | 265,145 | 42.5 | 0.970 | 0.914 | −0.01 |
| go | 0.5% | 2% | 564,208 | 44.2 | 0.974 | 0.908 | −0.01 |
| … | | | | | | | |
| fade | 0.5% | 1% | 564,208 | 40.6 | 0.725 | 0.654 | −0.15 |

- **Best config: net PF 0.92** (gross 0.97). Nothing clears 1.0 net; nothing clears
  0.98 even gross. The PF ≥ 1.3 bar isn't remotely in reach.
- **Gap-FADE** (bet the gap fills): high win rate (up to 59%) but the losses when a
  gap keeps running are fat — strongly negative avg-R. A classic "win often, lose big"
  trap. Net loser at every threshold/stop.
- **Gap-GO** (bet the gap continues): roughly flat gross (~0.94–0.98), tips net-negative
  once costs are in.

## Verdict

**No edge.** The "gap fill prints money" claim is decisively false on 20 years of US
equities — gaps continue about as often as they fill, and neither side pays after a
tiny 5 bps cost. This is the highest-conviction rejection of the whole exercise (the
sample is enormous). Lead **qkChxbuUqvU → rejected**.

## Caveats (don't over-read)
- Both-touched days resolve to the stop (conservative). Intraday path within the day
  isn't modeled beyond H/L; a finer test (1h/5m equity bars) would refine exits but is
  very unlikely to flip a 0.92 into a 1.3.
- No earnings/news filter — the biggest gaps are often earnings, which are exactly the
  ones that run. A news-gated variant is possible but is a different (harder) strategy.

## Standing conclusion for day-trade mining
Across the full pass — 30 `day_intra` videos, the 4 mechanical prospects, the ORB
parameter hunt, and now gap trading on 20y of equities — **no mechanical retail
day-trade setup from YouTube has cleared PF ≥ 1.3 net.** The book's one validated
intraday edge remains `fvg_continuation` (FX NY-session FVG, OOS PF ~1.46). The
higher-EV path is deepening that, not mining more retail day-trade clones.
