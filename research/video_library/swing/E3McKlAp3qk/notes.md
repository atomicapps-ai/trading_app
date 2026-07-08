# E3McKlAp3qk — "Displacement ORB + Session Analysis" (Trade with Pat)

Source: <https://www.youtube.com/watch?v=E3McKlAp3qk> · ~12 min.

## Rules (mechanical)
- **Entry engine (Step 1 — Displacement ORB):** at the NY open, mark the 09:30–09:45 ET 15-min opening range. Drop to 5-min; wait for an impulsive candle that *closes* out of the range (displacement) and creates a demand zone / fair-value gap. Enter on the retrace to that zone (preferred trigger: bullish engulfing; usually just "zone holds" or re-break).
- **Stop:** below the demand zone (or FVG midline). **Target:** ~1.5–2.2R / swept opposing session-liquidity level.
- **Session filter (Step 2):** Asia ranges, London pushes, NY reverses — trade NY opposite the London push; if London sweeps both sides of the Asian range, expect continuation.
- Frames show **XAUUSD (gold)**; targets are gold/index-sized (~2%).

## Verdict: PASS — already mechanized and OOS-validated as the live `fvg_continuation`.
This video is the documented source of the live suite's **`fvg_continuation`** strategy. The repo's validated implementation (a faithful variant on FX majors, 30-minute bars) clears the bar: **profit factor ≈ 1.48, OOS ≈ 1.46** (see `strategies/strategy_docs/` + `CLAUDE.md` header). It is the FX-intraday member of the deployed book, so — unlike the daily-US-stock default scope — its home timeframe/instrument is an accepted exception already carried live.

Supersedes the earlier "shelved-intraday" note (written before intraday data was sourced). Open follow-up (deferred in CLAUDE.md, needs a local IB gateway): re-run the *faithful* 5-minute GOLD (XAUUSD) version and decide whether to keep the validated 30m-FX variant, adopt the 5m-gold original, or both. Tooling already built: `scripts/fetch_fx_history.py`, `scripts/compare_fvg_intervals.py`, `scripts/replay_fvg.py`.

Note: adoption is already done for the 30m-FX variant; nothing further goes live from this mining run. Recorded as PASS because its strategy survived real OOS backtesting and is in production.
Status: passed
