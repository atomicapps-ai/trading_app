"""scripts/score_universe.py — per-symbol suitability report for a strategy.

READ-ONLY. Replays the REAL detector for a strategy over every symbol in the
core universe, splits history into in-sample (IS) and out-of-sample (OOS)
windows, and reports each symbol's trade metrics so you can see which symbols
help the strategy and which drag it down — before anything changes live.

Classification per symbol (see strategies/UNIVERSE_SELECTION.md §4):
  KEEP  — enough trades and not a proven dragger
  DROP  — proven dragger: IS profit factor < --pf-drop AND OOS also weak
          (the only ones we'd remove; we drop draggers, never cherry-pick winners)
  THIN  — too few trades to judge (< --min-trades); kept by default, unproven

Usage
-----
    python -m scripts.score_universe --strategy momentum_breakout
    python -m scripts.score_universe --strategy fear_dip_reversion --min-trades 20
    python -m scripts.score_universe --strategy macd_run --md   # also write a report file

Nothing is written to the live universe. --md just saves a Markdown table.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)  # type: ignore[attr-defined]
except Exception:
    pass

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from scripts.replay_swing import replay  # noqa: E402
from services import universe_service  # noqa: E402


def _r_multiple(t) -> float | None:
    """R = reward/risk for one trade, sign-aware. None if risk is degenerate."""
    risk = abs(t.entry - t.stop)
    if risk <= 1e-9:
        return None
    if (t.direction or "long") == "long":
        return (t.exit_px - t.entry) / risk
    return (t.entry - t.exit_px) / risk


def _metrics(trades: list) -> dict:
    rs = [r for r in (_r_multiple(t) for t in trades) if r is not None]
    n = len(rs)
    if n == 0:
        return {"n": 0, "win_rate": 0.0, "pf": 0.0, "avg_r": 0.0, "total_r": 0.0}
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    pf = (gross_win / gross_loss) if gross_loss > 1e-9 else (99.0 if gross_win > 0 else 0.0)
    return {
        "n": n,
        "win_rate": len(wins) / n,
        "pf": pf,
        "avg_r": sum(rs) / n,
        "total_r": sum(rs),
    }


def _trade_dict(t, window: str) -> dict:
    return {"symbol": t.symbol, "window": window, "signal_date": t.date_str,
            "entry_date": t.entry_date, "exit_date": t.exit_date,
            "direction": t.direction, "entry": t.entry, "stop": t.stop, "tp1": t.tp,
            "exit_px": t.exit_px, "exit_reason": t.exit_reason,
            "pnl_pct": t.pnl_pct, "pnl_r": t.pnl_r, "mfe_r": t.mfe_r, "mae_r": t.mae_r,
            "win": t.win, "hold_days": t.hold_days, "pqs": t.pqs,
            "entry_ind": t.entry_ind, "exit_ind": t.exit_ind, "adverse_ind": t.adverse_ind}


def _persist(store, args, preset, cfg_hash, uni_hash, rows, is_trades, oos_trades) -> None:
    import uuid
    from datetime import datetime, timezone
    run_id = str(uuid.uuid4())
    created = datetime.now(timezone.utc).isoformat()
    trades = [_trade_dict(t, "IS") for t in is_trades] + \
             [_trade_dict(t, "OOS") for t in oos_trades]
    scores = [{"symbol": r["sym"],
               "is_n": r["is"]["n"], "is_pf": r["is"]["pf"], "is_wr": r["is"]["win_rate"],
               "is_avg_r": r["is"]["avg_r"], "is_total_r": r["is"]["total_r"],
               "oos_n": r["oos"]["n"], "oos_pf": r["oos"]["pf"], "oos_wr": r["oos"]["win_rate"],
               "oos_avg_r": r["oos"]["avg_r"], "verdict": r["verdict"]} for r in rows]
    agg = {"n_symbols": len(rows), "n_trades": len(trades),
           "is_pf": None, "is_avg_r": None, "oos_pf": None, "oos_avg_r": None}
    store.save_run(run_id=run_id, strategy=args.strategy, cfg_hash=cfg_hash,
                   universe_name=preset["name"], uni_hash=uni_hash,
                   is_since=args.is_since, split=args.split, until=args.until,
                   created_at=created, agg=agg, trades=trades, scores=scores)
    pruned = store.prune_old_runs(args.strategy, keep=args.keep)
    print(f"✓ persisted run {run_id[:8]}: {len(trades)} trades + {len(scores)} symbol "
          f"scores → data/backtest_cache.db"
          + (f" (pruned {pruned} old)" if pruned else ""), flush=True)


def _classify(is_m: dict, oos_m: dict, min_trades: int, pf_drop: float) -> str:
    if is_m["n"] < min_trades:
        return "THIN"
    # A dragger loses in-sample AND doesn't redeem itself out-of-sample.
    is_bad = is_m["pf"] < pf_drop or is_m["avg_r"] <= 0
    oos_bad = oos_m["pf"] < 1.0 or oos_m["avg_r"] <= 0
    if is_bad and oos_bad:
        return "DROP"
    return "KEEP"


async def main() -> int:
    ap = argparse.ArgumentParser(description="Per-symbol suitability report (read-only).")
    ap.add_argument("--strategy", default="momentum_breakout")
    ap.add_argument("--universe", help="Screener name (default: the core universe)")
    ap.add_argument("--is-since", default="2015-01-01", help="IS window start")
    ap.add_argument("--split", default="2023-01-01", help="IS/OOS boundary")
    ap.add_argument("--until", default=date.today().isoformat(), help="OOS window end")
    ap.add_argument("--min-trades", type=int, default=15,
                    help="Below this IS trade count a symbol is THIN/unproven")
    ap.add_argument("--pf-drop", type=float, default=1.0,
                    help="IS profit factor below this (and weak OOS) = dragger")
    ap.add_argument("--md", action="store_true", help="Also write a Markdown report")
    ap.add_argument("--force", action="store_true",
                    help="Re-run even if a cached run exists for this config")
    ap.add_argument("--max-age-days", type=float, default=30.0,
                    help="Reuse a cached run only if newer than this (default 30)")
    ap.add_argument("--keep", type=int, default=3,
                    help="Runs to keep per strategy before pruning older ones")
    args = ap.parse_args()

    # Self-apply the schema migration (rename core_universe_100 -> core_universe,
    # add is_core) so this works even if the app hasn't been restarted since the
    # upgrade. Idempotent; safe against a shared Turso DB.
    from services import db_service
    await db_service.ensure_tables()

    if args.universe:
        preset = await universe_service.get_preset_db(args.universe)
    else:
        preset = await universe_service.get_core_universe()
        # Fall back if no core is flagged yet (fresh/older DB).
        if not preset:
            for name in ("core_universe", "core_universe_100"):
                preset = await universe_service.get_preset_db(name)
                if preset:
                    break
        if not preset:
            active = [p for p in await universe_service.list_presets_db() if p.get("is_active")]
            preset = active[0] if active else None
    if not preset:
        print("no universe found (need a core universe or --universe NAME)")
        return 1
    symbols = [str(s).upper() for s in (preset.get("tickers") or [])]
    print(f"strategy: {args.strategy}   universe: {preset['name']} ({len(symbols)} symbols)")
    print(f"IS {args.is_since}→{args.split}   OOS {args.split}→{args.until}   "
          f"min_trades={args.min_trades}  pf_drop={args.pf_drop}")

    from services import backtest_store as store
    cfg_hash = store.config_hash(args.strategy)
    uni_hash = store.universe_hash(symbols)

    # ── Cache: reuse a stored run unless the strategy config or universe
    # changed (hashes differ) or --force. Heavy backtests run once. ──
    rows: list = []
    cached_at = None
    if not args.force:
        cr = store.find_cached_run(args.strategy, cfg_hash, uni_hash, args.max_age_days)
        if cr:
            cached_at = cr["created_at"]
            for s in store.get_scores(cr["run_id"]):
                rows.append({"sym": s["symbol"],
                             "is": {"n": s["is_n"], "pf": s["is_pf"], "win_rate": s["is_wr"],
                                    "avg_r": s["is_avg_r"], "total_r": s["is_total_r"]},
                             "oos": {"n": s["oos_n"], "pf": s["oos_pf"], "win_rate": s["oos_wr"],
                                     "avg_r": s["oos_avg_r"], "total_r": 0.0},
                             "verdict": s["verdict"]})
            print(f"✓ cached run {cr['run_id'][:8]} from {cached_at[:19]} — "
                  f"{cr['n_trades']} trades (use --force to re-run)", flush=True)

    if not rows:
        print(f"replaying real detector over {len(symbols)} symbols "
              f"(cache miss — this is the heavy run)…", flush=True)

        def _prog(i, tot, sym):
            if i % 25 == 0 or i == tot:
                print(f"  … {i}/{tot} symbols", flush=True)

        is_trades = await replay(symbols, args.is_since, args.split, args.strategy, progress=_prog)
        print("  IS window done; running OOS…", flush=True)
        oos_trades = await replay(symbols, args.split, args.until, args.strategy, progress=_prog)

        by_sym_is: dict[str, list] = {}
        by_sym_oos: dict[str, list] = {}
        for t in is_trades:
            by_sym_is.setdefault(t.symbol, []).append(t)
        for t in oos_trades:
            by_sym_oos.setdefault(t.symbol, []).append(t)

        for sym in symbols:
            is_m = _metrics(by_sym_is.get(sym, []))
            oos_m = _metrics(by_sym_oos.get(sym, []))
            if is_m["n"] == 0 and oos_m["n"] == 0:
                continue
            verdict = _classify(is_m, oos_m, args.min_trades, args.pf_drop)
            rows.append({"sym": sym, "is": is_m, "oos": oos_m, "verdict": verdict})

        # Persist the run: every trade (with indicator snapshots) + per-symbol
        # scores, keyed by config/universe hash so we never re-run needlessly.
        _persist(store, args, preset, cfg_hash, uni_hash, rows, is_trades, oos_trades)

    rows.sort(key=lambda r: (r["verdict"] != "DROP", -r["is"]["total_r"]))
    kept = [r for r in rows if r["verdict"] in ("KEEP", "THIN")]
    dropped = [r for r in rows if r["verdict"] == "DROP"]

    def _agg_rows(rs: list) -> dict:
        # Summary IS aggregate across per-symbol rows. PF is approximated from
        # each symbol's net total_R (winners' R vs losers' R) — enough to show
        # whether trimming draggers lifts the aggregate.
        n = sum(r["is"]["n"] for r in rs)
        tot = sum(r["is"]["total_r"] for r in rs)
        pos = sum(r["is"]["total_r"] for r in rs if r["is"]["total_r"] > 0)
        neg = abs(sum(r["is"]["total_r"] for r in rs if r["is"]["total_r"] < 0))
        pf = pos / neg if neg > 1e-9 else (99.0 if pos > 0 else 0.0)
        return {"pf": pf, "avg_r": (tot / n if n else 0.0), "total_r": tot, "n": int(n)}

    before = _agg_rows(rows)
    after = _agg_rows(kept)

    print("-" * 92)
    print(f"{'SYM':<7}{'verdict':<8}{'IS n':>5}{'IS PF':>7}{'IS WR':>7}{'IS avgR':>8}"
          f"{'IS totR':>8}   {'OOSn':>5}{'OOS PF':>7}{'OOS avgR':>9}")
    print("-" * 92)
    for r in rows:
        i, o = r["is"], r["oos"]
        print(f"{r['sym']:<7}{r['verdict']:<8}{i['n']:>5}{i['pf']:>7.2f}{i['win_rate']*100:>6.0f}%"
              f"{i['avg_r']:>8.2f}{i['total_r']:>8.1f}   "
              f"{o['n']:>5}{o['pf']:>7.2f}{o['avg_r']:>9.2f}")
    print("-" * 92)
    print(f"symbols traded: {len(rows)}   KEEP {len([r for r in rows if r['verdict']=='KEEP'])} "
          f"· THIN {len([r for r in rows if r['verdict']=='THIN'])} · DROP {len(dropped)}")
    print(f"IS aggregate  BEFORE trim: PF {before['pf']:.2f}  avgR {before['avg_r']:.2f}  "
          f"totR {before['total_r']:.0f}  (n={before['n']})")
    print(f"IS aggregate  AFTER  trim: PF {after['pf']:.2f}  avgR {after['avg_r']:.2f}  "
          f"totR {after['total_r']:.0f}  (n={after['n']})")
    if dropped:
        print(f"draggers to drop: {', '.join(r['sym'] for r in dropped)}")

    if args.md:
        out = ROOT / "strategies" / f"UNIVERSE_SCORES_{args.strategy}.md"
        lines = [f"# Universe scores — {args.strategy}", "",
                 f"Universe: {preset['name']} ({len(symbols)}) · "
                 f"IS {args.is_since}→{args.split} · OOS {args.split}→{args.until}", "",
                 f"BEFORE trim IS PF {before['pf']:.2f} / avgR {before['avg_r']:.2f} → "
                 f"AFTER PF {after['pf']:.2f} / avgR {after['avg_r']:.2f}", "",
                 "| symbol | verdict | IS n | IS PF | IS WR | IS avgR | OOS n | OOS PF |",
                 "|---|---|--:|--:|--:|--:|--:|--:|"]
        for r in rows:
            i, o = r["is"], r["oos"]
            lines.append(f"| {r['sym']} | {r['verdict']} | {i['n']} | {i['pf']:.2f} | "
                         f"{i['win_rate']*100:.0f}% | {i['avg_r']:.2f} | {o['n']} | {o['pf']:.2f} |")
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {out}")

    return 0


def _install_sigint_handler() -> None:
    import os
    import signal

    def _die(*_a):
        print("\n^C — stopping.", flush=True)
        os._exit(130)

    for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGBREAK", None)):
        if sig is not None:
            try:
                signal.signal(sig, _die)
            except (ValueError, OSError):
                pass


if __name__ == "__main__":
    _install_sigint_handler()
    raise SystemExit(asyncio.run(main()))
