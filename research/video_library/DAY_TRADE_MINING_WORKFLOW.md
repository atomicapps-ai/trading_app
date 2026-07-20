# Day-trade video mining — stringent criteria + workflow

**Goal:** find *validated* intraday day-trade strategies (flat by EOD) that clear a
hard backtest bar — not another retail ORB/VWAP/EMA clone. Written after a full
day_intra pass where **0 of 30 videos + 4 mechanical prospects + an ORB param hunt +
gap-trading on 20y of equities cleared PF ≥ 1.3.** So the filter is deliberately harsh:
we spend assessment effort only on videos that could plausibly clear the bar.

---

## 1. What we've PROVEN fails — auto-reject on sight (the deny-list)

These mechanisms have been backtested to death and do not survive OOS + costs. A video
whose setup reduces to any of them is rejected at triage, before ingest:

- **Opening-Range Breakout (ORB)** and every variant — 15m/30m/5m range, break, retest.
- **VWAP + EMA** cross/reclaim day-trading.
- **First-candle / 9:30 / opening-candle** direction plays.
- **Moving-average crossover** (9-EMA, 20/50) as the entry.
- **Gap trading** — fade *or* go (tested on 595 equities × 20y; net PF ≤ 0.92).
- **Generic SMC / ICT / "smart money"** liquidity-sweep with discretionary levels.
- **"Simple scalping" 1-min checklists**, especially Heikin-Ashi (repaints → not fillable).
- **Session explainers** ("what is the London session"), **prop-firm promos**, funded-account
  ads, **"complete beginner" tutorial compilations**, indicator-reversal (RSI "premium").

## 2. Stringent INCLUDE criteria — a video must pass ALL to enter the queue

1. **Intraday & flat by EOD** — a same-session trade, not a multi-day swing.
2. **Exactly mechanical** — a rule you could code with no discretion: precise entry
   trigger, precise stop, precise exit/target. "Look for clean structure" fails this.
3. **Novel mechanism** — NOT on the deny-list above. It must bring an edge source we
   haven't already killed (e.g. order-flow/RVOL, volatility-regime, statistical
   continuation, a genuinely different trigger), not a repackaged ORB.
4. **Asymmetric payoff geometry** — a defined stop *and* a ≥2R target or a
   "let-winners-run" trail. Edge is payoff geometry, not hit-rate; flat 1:1 scalps
   almost never net out after cost.
5. **Evidence of rigor** — the creator shows a real backtest (≈100+ trades) or a
   multi-month track, and names instrument + timeframe + session. "I made $4k today"
   and n=17 hindsight do NOT count.
6. **Testable instrument** — FX majors/metals (deep 5m cache) or liquid US
   equities/ETFs (20y daily + ~2y 1h). Crypto/options-only → deprioritize (can't
   validate cleanly here).

## 3. The PASS bar (backtest gate) — unchanged, applied per candidate

- **PF ≥ 1.3 net of costs** (spread+commission modeled per instrument),
- **avg-R > 0**, **~100+ trades**,
- **beats a with-trend / random-direction control**,
- **stable across IS/OOS** — check per-year PF, reject regime artifacts
  (this is what killed the best ORB config: great 2022-25, losing 2015-21),
- **corr < 0.60** to the live book (`scripts/strategy_correlation_gate.py`).

Only survivors get wired `active:false` for human review.

---

## 4. The workflow (end to end)

```
[0] CRITERIA          this doc — the deny-list + INCLUDE gate + PASS bar
        │
[1] DISCOVER          operator machine (YouTube access):
        │             VIDEO_STYLE=day_intra python scripts/video_discover.py --mode intraday_strict
        │             → hardened queries fish for rigor+novelty; title deny-list pre-filters
        │             → writes research/video_library/day_intra/_candidates.md (ranked)
        │
[2] TRIAGE (me)       apply §2 to _candidates.md titles/channels → KEEP / SKIP + reason.
        │             Only KEEPs get ingested. (I can do this from candidate metadata.)
        │
[3] INGEST            operator machine: transcript-only is enough
        │             python scripts/video_ingest.py --ingest "<url>" ...   (push transcripts)
        │
[4] ASSESS (me)       read transcript → extract mechanical spec (instrument/TF/session/
        │             entry/filters/stop/target). Collapses to a deny-list mechanism or is
        │             discretionary → reject now (tier=noise). Else → spec.json.
        │
[5] BACKTEST GATE(me) build/run a mechanical backtest on cached data → §3 PASS bar.
        │             PASS → wire active:false + doc.   FAIL → reject (tier by §6).
        │
[6] RETIRE / PURGE    keep the library lean (see §6).
```

## 5. Division of labor (why some steps are "operator machine")

The sandbox's cloud IP is **blocked by YouTube** (`RequestBlocked`), so it can't
discover or ingest. Steps [1] and [3] run on the operator's residential IP (or the
`/mining` "Add a video" page). Everything analytical — triage, spec extraction,
backtesting, verdicts, purge — runs here on the pushed transcripts + cached price data.

## 6. Purge policy — two tiers, so rejects don't rot the library

Every reject is tagged a **tier** at assessment:

| Tier | When | What we keep | Command |
|---|---|---|---|
| **informative** | we backtested it, or it taught a transferable lesson (e.g. the ORB regime finding, the gap no-edge result) | `notes.md` verdict + `status.json` (heavy artifacts pruned) | `video_retire.py <id> --status rejected --tier informative --reason "..."` |
| **noise** | auto-rejected at triage/assess — promo, non-mechanical, redundant deny-list clone, duplicate | **nothing** — folder deleted; a one-line tombstone in `_history.json` (id, url, reason, tier) prevents re-ingest | `video_retire.py <id> --purge --reason "..."` |

- **Purge = "below the level."** Noise never reaches the Assess panels and consumes ~0
  disk. The tombstone keeps the URL, so the operator can always re-ingest from source if
  ever needed — purge is reversible off-sandbox, so it's safe.
- Batch prune: `video_retire.py --purge-noise` purges every history entry tagged
  `tier=noise`; `video_retire.py --all-rejected` still prunes heavy artifacts for all
  rejects (informative + noise) without deleting notes.
- **Never purge PASSED or informative rejects** — the "we tried this, here's the PF"
  record is the whole point of the library.

## 7. Quick commands
```bash
# operator machine (YouTube reachable):
VIDEO_STYLE=day_intra python scripts/video_discover.py --mode intraday_strict --per-query 30 --top 50
python scripts/video_ingest.py --ingest "<url1>" "<url2>"     # the KEEP picks, then git push

# here (analysis):  assess → backtest → verdict → purge
python scripts/video_retire.py <id> --purge --reason "redundant ORB clone"   # noise
python scripts/video_retire.py --purge-noise                                  # batch clean
```
