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

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "research" / "video_library"

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


def known_ids() -> set[str]:
    if not LIB.exists():
        return set()
    return {p.name for p in LIB.iterdir() if p.is_dir()}


def search(query: str, n: int) -> list[dict]:
    cmd = ["yt-dlp", f"ytsearch{n}:{query}", "--flat-playlist",
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
    args = ap.parse_args()

    known = known_ids()
    seen: set[str] = set()
    rows: list[dict] = []
    for q in QUERIES:
        print(f"searching: {q}", file=sys.stderr)
        for d in search(q, args.per_query):
            vid = d.get("id")
            title = d.get("title") or ""
            if not vid or vid in seen or vid in known:
                continue
            if EXCLUDE.search(title) or not INCLUDE.search(title):
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
    out = LIB / "_candidates.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n{len(rows)} candidates -> {out.relative_to(ROOT)}")
    print("Next: review _candidates.md, then ingest the picks:")
    print('  python scripts/video_ingest.py --ingest "url1" "url2" ...')


if __name__ == "__main__":
    main()
