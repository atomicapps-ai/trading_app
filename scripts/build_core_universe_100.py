"""scripts/build_core_universe_100.py — build the core_universe_100 screener.

Two-stage pipeline:

Stage 1 (Finviz, server-side): liquidity + price + cap + country + 5 fundamental filters
Stage 2 (local, computed):     ATR(14)/price ∈ [1.5%, 4%]  +  Price > SMA50 AND Price > SMA200

Run order:
1. Upsert screener config to SQLite
2. Scrape Finviz with Stage 1 filters
3. Ensure daily bars cached for each Stage-1 ticker (local HF parquet shards)
4. Compute ATR%, SMA50, SMA200 from bars; apply Stage-2 filter
5. Save final ticker list back to screener (`tickers` field)
6. Print full funnel + final list + a per-ticker rejection ledger
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")                            # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import numpy as np
import pandas as pd

from services import hf_data_service, universe_service


SCREENER_NAME = "core_universe_100"
SCREENER_TITLE = "Core Universe 100 (Quality + Trending + Goldilocks Vol)"
SCREENER_DESC = (
    "Two-stage screener for the price_action_pattern_recog_matrix system. "
    "Stage 1 (Finviz): mid+ cap US-listed stocks, ADV>2M, price>$15, "
    "5-yr profitable, op margin positive, trading above SMA50 and SMA200. "
    "Stage 2 (local): ATR(14)/price between 1.5%-4% to exclude dead names "
    "and meme-style hyper-volatile stocks. Target ~100 names — quality, "
    "liquid, in-trend, with normalized volatility."
)
SCREENER_NOTES = (
    "Stage 1 produced via Finviz scrape. Stage 2 computed locally from cached "
    "daily bars. Re-run weekly to refresh — universe drifts as names cross "
    "above/below the SMA50/200 trend gates and as ATR contracts/expands. "
    "v4 (2026-05-09): re-added strict fundamentals (fa_curratio>1, fa_debteq<1, "
    "fa_eps5years>0) now that max_pages=50 captures the full ~500-ticker "
    "candidate set. Mag-7 names that fail strict balance-sheet filters "
    "(e.g. AAPL D/E>1 from buybacks) are FORCE-INCLUDED via the override list "
    "below, but still subject to Stage 2 (ATR%/SMA) — so a Mag-7 in downtrend "
    "is correctly excluded."
)

STAGE1_FILTERS = {
    # liquidity / price
    "sh_price": "o15",                # > $15
    "sh_avgvol": "o2000",             # > 2M shares/day
    # quality / size / location
    "cap": "midover",                 # Mid+ ($2B and up — large + mega included)
    "geo": "usa",                     # US listing
    # fundamentals (strict — back from v3)
    "fa_pe": "profitable",            # positive earnings
    "fa_opermargin": "pos",           # operating margin positive
    "fa_eps5years": "pos",            # 5-yr EPS growth positive
    "fa_curratio": "o1",              # current ratio > 1 (short-term solvent)
    "fa_debteq": "u1",                # debt/equity < 1 (conservative leverage)
    # trend (Finviz checks current price vs SMAs)
    "ta_sma50_pa": "pa",              # price above SMA50
    "ta_sma200_pa": "pa",             # price above SMA200
}

# Force-include list — names that may fail individual fundamental filters
# (e.g. AAPL D/E > 1 from buybacks) but are obviously high-quality tradeable
# vehicles. Still subject to Stage 2 (ATR% band + SMA50/200 trend).
FORCE_INCLUDE = [
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN",   # mega-cap tech
    "NVDA", "META", "TSLA",                     # rest of Mag 7
    "AVGO", "ORCL",                             # next-tier mega-cap tech
    "JPM", "BAC", "GS",                         # mega-cap financial
    "JNJ", "UNH", "LLY",                        # mega-cap healthcare
    "WMT", "COST",                              # mega-cap retail
    "XOM", "CVX",                               # mega-cap energy
    "PG", "KO", "PEP",                          # mega-cap consumer staples
]

# Stage 2 thresholds (% of current close)
ATR_PCT_MIN = 0.015                    # 1.5%
ATR_PCT_MAX = 0.05                     # 5.0%  (widened from 4% per A3)


def load_bars(symbol: str) -> pd.DataFrame | None:
    p = ROOT / "data" / "historical" / f"{symbol}_1d.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, index_col=0, parse_dates=True)
    df.columns = [c.strip().lower() for c in df.columns]
    if "adj_close" in df.columns and "close" in df.columns:
        df["close"] = df["adj_close"]
    cols = ["open", "high", "low", "close", "volume"]
    df = df[[c for c in cols if c in df.columns]].dropna()
    if df.empty:
        return None
    df.index = pd.to_datetime(df.index, utc=True)
    return df.sort_index()


def compute_atr_pct_and_smas(df: pd.DataFrame) -> tuple[float, float, float, float] | None:
    """Returns (atr_pct, close, sma50, sma200) or None if insufficient data."""
    if len(df) < 200:
        return None
    high = df["high"]; low = df["low"]; close = df["close"]
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / 14, adjust=False).mean()
    last_close = float(close.iloc[-1])
    last_atr = float(atr.iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1])
    sma200 = float(close.rolling(200).mean().iloc[-1])
    if last_close <= 0 or np.isnan(last_atr) or np.isnan(sma50) or np.isnan(sma200):
        return None
    return last_atr / last_close, last_close, sma50, sma200


async def main() -> int:
    # 1. Upsert screener
    existing = await universe_service.get_preset_db(SCREENER_NAME)
    if existing:
        print(f"updating screener: {SCREENER_NAME}")
        await universe_service.update_preset_db(
            SCREENER_NAME,
            title=SCREENER_TITLE, description=SCREENER_DESC,
            notes=SCREENER_NOTES, filters=STAGE1_FILTERS,
            output_tags=["core_universe", "quality", "trending", "tradeable"],
        )
    else:
        print(f"creating screener: {SCREENER_NAME}")
        await universe_service.create_preset_db(
            name=SCREENER_NAME, title=SCREENER_TITLE,
            description=SCREENER_DESC, notes=SCREENER_NOTES,
            filters=STAGE1_FILTERS,
            output_tags=["core_universe", "quality", "trending", "tradeable"],
        )

    # 2. Stage 1 — Finviz scrape
    print(f"\n--- STAGE 1 (Finviz) ---")
    print(f"filters: {STAGE1_FILTERS}")
    t0 = time.time()
    # max_pages=50 = up to 1000 tickers, plenty of headroom. Earlier 15 cap
    # was excluding N-Z range alphabetically (NVDA, MSFT, META, TSLA all cut).
    stage1_tickers, truncated = await asyncio.to_thread(
        lambda: universe_service.scrape_finviz_filters(STAGE1_FILTERS, max_pages=50),
    )
    print(f"scraped {len(stage1_tickers)} tickers in {time.time() - t0:.1f}s "
          f"(truncated={truncated})")

    # Merge in force-included names (deduplicated)
    stage1_set = set(stage1_tickers)
    forced_added = [t for t in FORCE_INCLUDE if t not in stage1_set]
    stage1_tickers = list(stage1_tickers) + forced_added
    if forced_added:
        print(f"force-included (failed strict Stage 1 filters but bypass list): "
              f"{forced_added}")

    if truncated:
        print("⚠️  hit max_pages — there are MORE Stage 1 matches than returned. "
              "If Stage 2 doesn't narrow enough, tighten Stage 1 filters.")

    if not stage1_tickers:
        print("⚠️  no tickers from Stage 1 — nothing to do")
        return 1

    # 3. Ensure daily bars cached for each Stage-1 ticker — and refresh via
    #    yfinance so today's close is available for the SMA verification.
    #    (HF stocks dataset stops at 2026-04-06; yfinance is current.)
    print(f"\n--- BAR FETCH + yfinance freshness pass ---")
    hist_dir = ROOT / "data" / "historical"
    hist_dir.mkdir(parents=True, exist_ok=True)

    # First, ensure HF backfill for any uncached symbol
    needed = []
    for sym in stage1_tickers:
        p = hist_dir / f"{sym.upper()}_1d.csv"
        if not p.exists():
            needed.append(sym)
    print(f"HF backfill — already cached: {len(stage1_tickers) - len(needed)}  "
          f"to fetch: {len(needed)}")
    if needed:
        t0 = time.time()
        for i, sym in enumerate(needed, 1):
            r = await hf_data_service.fetch_and_save(
                sym, source="auto", start="2010-01-01", interval="1d",
            )
            if i % 20 == 0 or i == len(needed):
                status = "ok" if r["ok"] else "FAIL"
                print(f"  [{i}/{len(needed)}] last={sym} {status}")
        print(f"HF backfill done in {time.time() - t0:.1f}s")

    # Now force a yfinance refresh for ALL Stage 1 tickers — gets today's close.
    # yfinance is fast (~0.5-1.5s/symbol) and current. This eliminates the
    # "stale local data vs live Finviz" SMA mismatch.
    print(f"yfinance freshness refresh — {len(stage1_tickers)} tickers")
    t0 = time.time()
    refresh_ok = 0
    refresh_fail = 0
    for i, sym in enumerate(stage1_tickers, 1):
        r = await hf_data_service.fetch_and_save(
            sym, source="yfinance", start="2010-01-01", interval="1d",
        )
        if r["ok"]:
            refresh_ok += 1
        else:
            refresh_fail += 1
        if i % 20 == 0 or i == len(stage1_tickers):
            print(f"  [{i}/{len(stage1_tickers)}] last={sym} "
                  f"({refresh_ok} ok / {refresh_fail} fail)")
    print(f"yfinance refresh done in {time.time() - t0:.1f}s "
          f"({refresh_ok} ok, {refresh_fail} failed)")

    # 4. Stage 2 — local ATR%/SMA filter
    print(f"\n--- STAGE 2 (local ATR% + SMA verification) ---")
    accepted: list[dict] = []
    rejected: list[dict] = []
    no_bars = 0
    insufficient = 0
    for sym in stage1_tickers:
        df = load_bars(sym)
        if df is None:
            no_bars += 1
            rejected.append({"sym": sym, "reason": "no bars"})
            continue
        out = compute_atr_pct_and_smas(df)
        if out is None:
            insufficient += 1
            rejected.append({"sym": sym, "reason": "insufficient bar history (<200d)"})
            continue
        atr_pct, close, sma50, sma200 = out

        if not (ATR_PCT_MIN <= atr_pct <= ATR_PCT_MAX):
            rejected.append({
                "sym": sym, "reason": f"ATR%={atr_pct:.3%} (need {ATR_PCT_MIN:.1%}-{ATR_PCT_MAX:.1%})",
                "atr_pct": atr_pct, "close": close,
            })
            continue
        if not (close > sma50 and close > sma200):
            rejected.append({
                "sym": sym, "reason": "P below SMA50 or SMA200 (Finviz stale or just crossed under)",
                "close": close, "sma50": sma50, "sma200": sma200,
            })
            continue

        accepted.append({
            "sym": sym, "close": round(close, 2),
            "atr_pct": round(atr_pct * 100, 2),
            "sma50_dist_pct": round((close / sma50 - 1) * 100, 2),
            "sma200_dist_pct": round((close / sma200 - 1) * 100, 2),
        })

    print(f"Stage 1 input:               {len(stage1_tickers)}")
    print(f"  - no bars (data missing):  {no_bars}")
    print(f"  - insufficient history:    {insufficient}")
    print(f"  - rejected by ATR% / SMA:  "
          f"{len(rejected) - no_bars - insufficient}")
    print(f"Stage 2 PASS:                {len(accepted)}  "
          f"({100 * len(accepted) / max(len(stage1_tickers), 1):.0f}% of Stage 1)")

    # 5. Save final list
    final_tickers = [r["sym"] for r in accepted]
    await universe_service.save_preset_tickers_db(
        SCREENER_NAME, final_tickers, source="finviz_plus_local_atr_sma",
    )
    print(f"\nsaved {len(final_tickers)} tickers to screener {SCREENER_NAME!r}")

    # 6. Report — tag force-included names
    forced_set = set(forced_added)
    for r in accepted:
        r["force_included"] = r["sym"] in forced_set
    accepted.sort(key=lambda r: r["atr_pct"], reverse=True)
    print(f"\n--- FINAL UNIVERSE: core_universe_100 ({len(accepted)} symbols) ---")
    n_forced = sum(1 for r in accepted if r["force_included"])
    print(f"  natural Stage 1 pass: {len(accepted) - n_forced}  "
          f"force-included (and survived Stage 2): {n_forced}")
    print(f"{'sym':<6} {'close':>10} {'atr%':>6} {'>SMA50%':>9} {'>SMA200%':>10} {'tag':>8}")
    for r in accepted:
        tag = "FORCED" if r["force_included"] else ""
        print(f"{r['sym']:<6} {r['close']:>10.2f} {r['atr_pct']:>5.1f}% "
              f"{r['sma50_dist_pct']:>+8.1f}% {r['sma200_dist_pct']:>+9.1f}% "
              f"{tag:>8}")

    # Also report force-includes that DID NOT pass Stage 2
    forced_passed = {r["sym"] for r in accepted if r["force_included"]}
    forced_dropped = sorted(set(forced_added) - forced_passed)
    if forced_dropped:
        print(f"\nForce-include names dropped at Stage 2 (out of trend or ATR% band):")
        for sym in forced_dropped:
            for rej in rejected:
                if rej["sym"] == sym:
                    print(f"  {sym}  -- {rej['reason']}")
                    break

    # Summary file for user review
    out_md = ROOT / "strategies" / "CORE_UNIVERSE_100.md"
    lines = [
        "# core_universe_100 — Universe Snapshot",
        "",
        f"Generated: {pd.Timestamp.now(tz='UTC').isoformat()}",
        "",
        "## Funnel",
        "",
        f"- Stage 1 (Finviz): **{len(stage1_tickers)}** tickers",
        f"- Stage 2 (local ATR% + SMA verify): **{len(accepted)}** tickers",
        f"- Rejected: **{len(rejected)}** (see below)",
        "",
        "## Stage 1 filters",
        "",
        "| Filter | Value | Meaning |",
        "|---|---|---|",
        "| `sh_price` | `o15` | Price > $15 |",
        "| `sh_avgvol` | `o2000` | ADV > 2M |",
        "| `cap` | `mid` | Mid+ market cap (~$2B+) |",
        "| `geo` | `usa` | US-listed |",
        "| `fa_pe` | `profitable` | Positive earnings |",
        "| `fa_eps5years` | `pos` | 5-yr EPS growth positive |",
        "| `fa_opermargin` | `pos` | Operating margin positive |",
        "| `fa_curratio` | `o1` | Current ratio > 1 |",
        "| `fa_debteq` | `u1` | Debt/Equity < 1 |",
        "| `ta_sma50_pa` | `pa` | Price above SMA50 |",
        "| `ta_sma200_pa` | `pa` | Price above SMA200 |",
        "",
        "## Stage 2 filters (local)",
        "",
        f"- ATR(14) / close ∈ [{ATR_PCT_MIN:.1%}, {ATR_PCT_MAX:.1%}]",
        "- Re-verify: close > SMA50 AND close > SMA200",
        "",
        f"## Final universe ({len(accepted)} symbols)",
        "",
        "| Symbol | Close | ATR% | dist >SMA50 | dist >SMA200 |",
        "|---|---:|---:|---:|---:|",
    ]
    for r in accepted:
        lines.append(f"| {r['sym']} | ${r['close']:.2f} | {r['atr_pct']:.1f}% | "
                     f"{r['sma50_dist_pct']:+.1f}% | {r['sma200_dist_pct']:+.1f}% |")
    lines += [
        "",
        f"## Rejected ({len(rejected)})",
        "",
        "First 30 rejection reasons:",
        "",
        "| Symbol | Reason |",
        "|---|---|",
    ]
    for r in rejected[:30]:
        lines.append(f"| {r['sym']} | {r['reason']} |")
    if len(rejected) > 30:
        lines.append(f"| ... | (and {len(rejected) - 30} more) |")
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nwritten to: {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
