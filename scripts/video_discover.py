"""video_discover — farm candidate trading-strategy videos via yt-dlp (no API).

Searches YouTube across our criteria queries, pulls engagement (views), filters to
DAILY US-STOCK systematic prospects (excludes forex/crypto/options/ICT/scalping),
dedupes against the existing library, ranks by views, and writes a candidate
shortlist to research/video_library/_candidates.md.

You run this (it needs YouTube access). Then we ingest the promising ones with
`video_ingest.py --ingest` and I assess the transcripts for real fit.

    python scripts/video_discover.py
    python scripts/video_discover.py --per-query 30 --top 50
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import os
ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "research" / "video_library"
LIB = BASE / os.environ.get("VIDEO_STYLE", "day_intra")   # per-style lane (swing|day_intra|scalp)

# Queries aimed at mechanical/systematic STOCK and FOREX strategies.
QUERIES = [
    # --- stocks ---
    "mechanical swing trading strategy stocks backtested rules",
    "stock breakout trading strategy backtest daily chart",
    "mean reversion stock strategy rules daily chart backtest",
    "momentum stock trading system entry exit stop backtest",
    "moving average pullback stock strategy backtested win rate",
    "best systematic stock trading strategy backtest results",
    "gap and go stock strategy rules backtest",
    "VCP volatility contraction breakout stock strategy",
    "RSI 2 mean reversion stock strategy backtest",
    "trend following stock strategy rules backtest",
    # --- forex (added per operator request) ---
    "forex swing trading strategy backtest rules win rate",
    "forex breakout trading strategy daily chart entry exit stop",
    "mechanical forex trading strategy backtested results",
    "forex trend following strategy rules backtest",
    "forex mean reversion strategy backtest daily chart",
    "best forex trading strategy backtest proven results",
]

# Forex is now in-scope; still drop crypto/options/futures and pure day-scalp noise.
EXCLUDE = re.compile(r"crypto|bitcoin|ethereum|\boption|\bfutures\b|"
                     r"prop firm|funded account|1 ?min scalp|5 ?min scalp", re.I)
INCLUDE = re.compile(r"stock|forex|currenc|fx\b|swing|breakout|revers|momentum|"
                     r"backtest|strateg|setup|rules|system|pair|trend", re.I)

# --- INTRADAY / day-trade mode (--mode intraday) ---
# Aimed ONLY at same-day / intraday mechanical setups on stocks & index ETFs.
QUERIES_INTRADAY = [
    "opening range breakout day trading strategy backtest stocks",
    "VWAP day trading strategy rules backtest",
    "intraday momentum day trading strategy stocks backtest",
    "5 minute opening range breakout strategy rules stocks",
    "gap and go day trading strategy rules backtest",
    "ORB opening range breakout strategy backtest SPY QQQ",
    "day trading strategy backtested rules intraday stocks",
    "5 minute scalping strategy backtest rules stocks",
    "1 minute scalping strategy backtested rules",
    "intraday mean reversion VWAP strategy rules stocks",
    "momentum day trading strategy entry exit stop intraday",
    "reversal day trading strategy intraday rules stocks",
    "supply and demand intraday day trading strategy rules",
    "breakout retest intraday day trading strategy rules",
    "premarket gap day trading strategy rules backtest",
    "opening range breakout backtest results win rate",
    "day trading momentum stocks in play relative volume",
    "9 30 open range breakout stock strategy rules",
]
# Day-trade mode: keep scalping/ORB/VWAP (the whole point); drop only truly off-scope noise.
EXCLUDE_INTRADAY = re.compile(r"crypto|bitcoin|ethereum|\boption(s)?\b|forex|"
                              r"currenc|\bfx\b|invest(ing|ment)|long term|buy and hold|"
                              r"swing trad", re.I)
INCLUDE_INTRADAY = re.compile(r"day ?trad|intraday|scalp|opening range|\borb\b|vwap|"
                              r"gap|premarket|pre-market|momentum|breakout|revers|"
                              r"9 ?30|open|strateg|rules|backtest|setup|system|"
                              r"stock|spy|qqq|nasdaq|index", re.I)

# --- STRINGENT INTRADAY mode (--mode intraday_strict) ---
# See research/video_library/DAY_TRADE_MINING_WORKFLOW.md. Fishes for RIGOR + NOVEL
# mechanism, and title-level drops everything we've already backtested to death.
QUERIES_INTRADAY_STRICT = [
    "intraday trading strategy 1000 trades backtest results python",
    "day trading strategy positive expectancy backtested proof",
    "relative volume RVOL intraday momentum strategy rules backtest",
    "intraday trend continuation strategy R multiple let winners run backtest",
    "quant intraday trading strategy backtest sharpe out of sample",
    "day trading strategy walk forward backtest out of sample results",
    "volatility expansion intraday breakout continuation strategy backtest",
    "order flow imbalance intraday strategy rules backtest",
    "statistical edge intraday strategy backtest expectancy stocks",
    "mechanical day trading system backtest 500 trades win rate",
    "intraday strategy backtest realistic slippage commission results",
    "futures intraday strategy backtest NQ ES rules statistical edge",
]
# Deny-list: drop the mechanisms proven to fail (ORB/VWAP/first-candle/gap/EMA-cross/
# SMC/ICT/simple-scalp) + promo/beginner fluff, at the title level, before ingest.
EXCLUDE_INTRADAY_STRICT = re.compile(
    r"crypto|bitcoin|ethereum|\boption(s)?\b|"
    r"opening range|\borb\b|9 ?30|first candle|vwap|"
    r"gap ?(and|&)? ?go|gap fill|ema cross|moving average cross|"
    r"\bict\b|smart money|\bsmc\b|liquidity sweep|"
    r"prop ?firm|funded account|for beginners|beginner|simple|easy|"
    r"get rich|\$\d|made \$|per day|a day\b", re.I)
INCLUDE_INTRADAY_STRICT = re.compile(
    r"backtest|expectancy|edge|rules|system|mechanical|quant|"
    r"walk ?forward|out of sample|R multiple|profit factor|sharpe|"
    r"day ?trad|intraday|continuation|momentum|relative volume|rvol|order flow", re.I)


def known_ids() -> set[str]:
    """Dedupe across ALL lanes (swing/day_intra/scalp) so a video is never re-farmed."""
    ids: set[str] = set()
    if not BASE.exists():
        return ids
    for lane in ("swing", "day_intra", "scalp"):
        d = BASE / lane
        if d.exists():
            ids |= {p.name for p in d.iterdir() if p.is_dir()}
    # also count any already in global history
    hist = BASE / "_history.json"
    if hist.exists():
        try:
            import json as _j
            ids |= set(_j.loads(hist.read_text()).keys())
        except Exception:
            pass
    return ids


def search(query: str, n: int) -> list[dict]:
    cmd = [sys.executable, "-m", "yt_dlp", f"ytsearch{n}:{query}", "--flat-playlist",
           "--dump-json", "--no-warnings", "--remote-components", "ejs:github"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        print(f"  (timeout) {query}", file=sys.stderr)
        return []
    rows = []
    for line in out.stdout.splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:  # noqa: BLE001
            continue
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-query", type=int, default=25)
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--mode", choices=["daily", "intraday", "intraday_strict"],
                    default="daily")
    args = ap.parse_args()

    if args.mode == "intraday_strict":
        queries, exclude, include = (QUERIES_INTRADAY_STRICT,
                                     EXCLUDE_INTRADAY_STRICT, INCLUDE_INTRADAY_STRICT)
    elif args.mode == "intraday":
        queries, exclude, include = QUERIES_INTRADAY, EXCLUDE_INTRADAY, INCLUDE_INTRADAY
    else:
        queries, exclude, include = QUERIES, EXCLUDE, INCLUDE

    known = known_ids()
    seen: set[str] = set()
    rows: list[dict] = []
    for q in queries:
        print(f"searching: {q}", file=sys.stderr)
        for d in search(q, args.per_query):
            vid = d.get("id")
            title = d.get("title") or ""
            if not vid or vid in seen or vid in known:
                continue
            if exclude.search(title) or not include.search(title):
                continue
            seen.add(vid)
            rows.append({
                "id": vid, "title": title,
                "channel": d.get("channel") or d.get("uploader") or "",
                "duration": d.get("duration") or 0,
                "views": d.get("view_count") or 0,
                "url": f"https://www.youtube.com/watch?v={vid}",
            })

    rows.sort(key=lambda r: r["views"], reverse=True)
    top = rows[:args.top]
    lines = ["# Candidate videos (yt-dlp farm)", "",
             f"{len(rows)} unique candidates after filtering; top {len(top)} by views.",
             "Dedupe vs library applied. Engagement is a WEAK proxy — backtest verifies.", "",
             "| views | min | channel | title | url |", "|---|---|---|---|---|"]
    for r in top:
        lines.append(f"| {r['views']:,} | {round(r['duration']/60)} | "
                     f"{r['channel'][:24]} | {r['title'][:70]} | {r['url']} |")
    out = LIB / "_candidates.md"   # LIB already points at the per-style lane (VIDEO_STYLE)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n{len(rows)} candidates -> {out.relative_to(ROOT)}")
    print("Next: review _candidates.md, then ingest the picks:")
    print('  python scripts/video_ingest.py --ingest "url1" "url2" ...')


if __name__ == "__main__":
    main()
