# Video-Mining Run — Status (2026-07-07)

## Progress: 61 / 100 assessed
- **PASSED: 8**
- **REJECTED: 53**

### The 8 passes (validated candidates — nothing auto-adopted)
| video | strategy | result |
|---|---|---|
| 2ElrQnn2cZE | Turtle / Donchian 55-high/20-low breakout + 200-MA + 2N stop | OOS PF **1.40**, avg-R +0.26, n≈26k |
| g-PLctW8aU0 | DEMA(200) + SuperTrend(12,3) trend follower | OOS PF **1.38**, avg-R +0.16, n≈27k |
| qpkCxEUdoMo | "4 consecutive red candles" mean reversion (MA/time exit) | OOS PF **1.39–1.42**, avg-R +0.09/+0.14 |
| pCmJ8wsAS_w | Bollinger(30,2) + RSI(13) mean reversion (+ squeeze skip) | OOS PF **1.25–1.28**, avg-R +0.12 |
| KuXV0LRfJx8 | Turnaround-Tuesday seasonal (borderline) | OOS PF **1.20** (thin, at threshold) |
| E3McKlAp3qk | Displacement ORB + FVG | = live `fvg_continuation` (OOS PF ~1.46) |
| rf_EQvubKlk | MACD cross below zero + 200-MA | = live `macd_run` (OOS PF ~1.52) |
| YWBLKRLnrZ0 | Range/coil contraction → volume breakout | = live `coil_breakout` (OOS PF ~2.13) |

New standalone passes worth a human look: **Turtle/Donchian**, **DEMA+SuperTrend**, **4-down-days mean-rev**, **BB+RSI mean-rev** (all clear OOS PF ≥1.2, beat controls). The other 3 map to already-live strategies; turnaround-Tuesday is a thin borderline.

### Backtest harnesses built this run (in scripts/)
bt_turtle, bt_supertrend, bt_4candles, bt_bbrsi (the passes) + bt_liqgrab, bt_pullback, bt_fibdiscount, bt_rsi2, bt_qs, bt_sma825 (rejects, with numbers). All use scripts/strategy_suite.py (10bps cost, IS/OOS split, random-direction control) on the 955-symbol daily cache. Raw JSON in data/research/strategy_results/.

## Why not 100 yet: acquisition is YouTube-IP-blocked
All usable pending videos have been assessed (queue: pending 0). The remaining ~39 need lane-A acquisition (discover/rank/ingest), which hits **YouTube transcript IP-blocking** ("IpBlocked") — triggered by the burst of ingest requests. It clears with time (usually hours); re-hammering prolongs it. 20 videos are ingested-but-empty (no transcript/frames) and are checkpointed to re-ingest cleanly later.

## To resume (once the block clears)
```
# refill the empty/blocked shells + top up:
python scripts/video_ingest.py --ingest <urls from research/video_library/_candidates_ranked.md not in library> --interval 90
python scripts/video_discover.py --per-query 30 --top 120   # more candidates if needed
python scripts/video_rank.py --stage2 60 --pick 100
# then continue the loop:
python -m scripts.video_queue --next   # → read transcript+frames → spec → backtest → notes.md → video_retire
```
The loop is fully resumable from _history.json — finished videos are never re-processed.
