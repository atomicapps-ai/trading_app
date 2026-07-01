# Stage 3 — Deploying S7 + S5 to the /pending paper pipeline

Both hardened daily strategies are now wired into the live agent pipeline as their own book.
Verified end-to-end by dry-run (analyst → planner → compliance → risk) on cached data.

## What was built
| Piece | File | Purpose |
|---|---|---|
| S7 detector | `agents/detectors/s7_breakout_continuation.py` | 126-day-high breakout, 1×ATR stop, let-it-run targets |
| S5 detector | `agents/detectors/s5_mean_reversion.py` | buy ≥3×ATR below SMA50, target the mean; tp1 floored at 2.2R |
| Registration | `agents/detectors/__init__.py` | both added to `ALL_DETECTORS` |
| Detector whitelist | `agents/analyst.py` | `run_lens_technical` honors a strategy's `detectors:` list (new, backward-compatible) |
| Strategy config | `strategy_configs/video_daily.yaml` | scopes the book to s7+s5, lets high-quality singletons plan, conservative risk |
| Workflow | `workflows/video_daily_scan.yaml` | daily 16:15 ET post-close scan → plan → /pending (paper) |
| Separation | `strategy_configs/swing_momentum.yaml` | scoped to its original 9 detectors so s7/s5 don't double-fire |

## How a signal reaches /pending (existing pipeline, unchanged)
`video_daily_scan` → `filter_universe` (liquid_momentum_core) → `compute_macro` → `analyze`
(strategy=video_daily → runs ONLY s7+s5) → `plan` (PortfolioManager builds TradePlans) →
`pipeline_service` runs **ComplianceOfficer** then **RiskManager** on every plan → passing/resized
plans are written to `pending_approvals` as `status=pending` → they appear on **/pending** for your
approval. No auto-approve (video_daily has none), so every trade waits for a human ack.

## Dry-run verification (on cached 2006–2026 data)
Ran the real agent classes over NVDA/AAPL/MSFT/JPM/XOM/WMT:
- Whitelist correctly limited the technical lens to s7+s5 only.
- Position sizing = 0.5% equity risk (~$495 on $100k) — correct.
- **Compliance: approved** on all. **Risk: pass/resized** on S7 (R_tp1 3.0) and S5 after the tp1 fix
  (R_tp1 2.2–2.3, all clearing the 2.0 min-R:R gate). The S5 tp1<2.0 rejection bug was found and fixed here.

## To run it live (on your machine)
1. **Restart the app** so APScheduler registers `video_daily_scan` and the new detectors load.
2. **Confirm the universe** — make sure `liquid_momentum_core` (or the active screener) holds a liquid
   large-cap list similar to the ~90 names the strategies were validated on (not `bellwether_16`).
3. **Keep sizing conservative** — `settings.risk_defaults.max_risk_pct_per_trade` ≤ 0.5% (S7 has deep
   cumulative drawdowns; small per-trade risk + position caps matter).
4. **Wait for 16:15 ET** (weekdays) for the scan, or trigger now: `POST /api/workflows/video_daily_scan/run`.
5. Review and approve plans on **/pending**. Forward paper results = true out-of-sample validation.

## Honest expectations
- Win rates are LOW by design (S7 ~28%, S5 ~30%) — most trades are small losses; a minority of big
  winners carry the edge. Don't judge by hit rate; judge by expectancy over many trades.
- S7's edge is outlier-driven (a few explosive names) → results will be lumpy.
- The backtest universe is survivorship-biased; paper-forward sidesteps that, which is the whole point
  of this stage. Let it accumulate trades before drawing conclusions.
