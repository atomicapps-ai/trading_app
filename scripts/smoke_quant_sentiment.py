"""smoke_quant_sentiment.py — minimal offline smoke test for the alpha stack.

Exercises the pure-function pieces of the quant + sentiment stack
without hitting yfinance, Alpaca, or FRED:

* ``news_sentiment_engine.classify_tags`` — regex tag classification.
* ``news_sentiment_engine.derive_multiplier`` — sentiment math.
* ``volume_profile_service.compute_volume_profile`` — POC / value area.
* ``relative_strength_service.detect_vcp`` — VCP detection on a synthetic frame.
* ``economic_calendar_service.events_within`` — recurring event window.
* Alpha-score scoring helpers — ``intermarket_score_0_100``, etc.

Exit code 0 on full pass, 1 on any failure. Used in CI / pre-commit.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.alpha_score import MacroPulse, RelativeStrength, SentimentMultiplier  # noqa: E402
from services.economic_calendar_service import events_within, in_event_blackout   # noqa: E402
from services.macro_pulse_service import intermarket_score_0_100                  # noqa: E402
from services.news_sentiment_engine import (                                      # noqa: E402
    aggregate_tags, classify_tags, derive_multiplier, score_text_with_tags,
    sentiment_score_0_100,
)
from services.relative_strength_service import (                                  # noqa: E402
    detect_vcp, price_action_score_0_100,
)
from services.volume_profile_service import (                                     # noqa: E402
    build_profile, compute_volume_profile, volume_profile_score_0_100,
)


FAILED = []


def check(name: str, ok: bool, detail: str = "") -> None:
    status = "OK " if ok else "FAIL"
    print(f"[{status}] {name}: {detail}")
    if not ok:
        FAILED.append(name)


def smoke_classify_tags() -> None:
    headlines = {
        "earnings_beat":       "ACME beats analyst estimates as Q2 revenue tops consensus",
        "earnings_miss":       "ACME misses consensus, falls short of analyst expectations",
        "regulatory_headwind": "ACME faces antitrust probe; SEC charges executives in lawsuit",
        "share_buyback":       "ACME announces $5B share buyback program",
        "ai_integration":      "ACME unveils generative AI integration powered by Nvidia GPUs",
        "analyst_upgrade":     "Goldman upgrades ACME to Buy with raised price target",
    }
    for expected, hl in headlines.items():
        tags = classify_tags(hl)
        check(f"classify_tags::{expected}", expected in tags, f"got {tags}")


def smoke_derive_multiplier() -> None:
    m, _ = derive_multiplier(0.6, {"earnings_beat": 1, "share_buyback": 1})
    check("derive_multiplier::positive", m > 1.3, f"got {m}")
    m, _ = derive_multiplier(-0.4, {"regulatory_headwind": 2})
    check("derive_multiplier::negative", m < 0.7, f"got {m}")
    m, _ = derive_multiplier(0.0, {})
    check("derive_multiplier::neutral", abs(m - 1.0) < 1e-6, f"got {m}")


def smoke_sentiment_score_0_100() -> None:
    pos = SentimentMultiplier(symbol="X", as_of_ts=datetime.now(timezone.utc),
                              avg_compound=0.5, n_articles=12, multiplier=1.4)
    s = sentiment_score_0_100(pos)
    check("sentiment_score::strong_positive", s > 80, f"got {s}")

    neg = SentimentMultiplier(symbol="X", as_of_ts=datetime.now(timezone.utc),
                              avg_compound=-0.5, n_articles=12, multiplier=0.6)
    s = sentiment_score_0_100(neg)
    check("sentiment_score::strong_negative", s < 20, f"got {s}")


def smoke_score_text_with_tags() -> None:
    # VADER scores some financial idioms ("crushes") as negative, so use neutral
    # vocabulary; we're checking that the tag classifier picks up both signals.
    res = score_text_with_tags(
        "Company beats analyst estimates strongly and announces share buyback program"
    )
    check("score_text_with_tags::has_tags",
          "earnings_beat" in res["tags"] and "share_buyback" in res["tags"],
          f"got {res['tags']}")
    check("score_text_with_tags::positive_compound", res["compound"] > 0, f"got {res['compound']}")


def smoke_volume_profile() -> None:
    rng = np.random.default_rng(42)
    n = 60
    base = 100 + np.cumsum(rng.normal(0, 0.5, n))
    df = pd.DataFrame({
        "open": base,
        "high": base + 1,
        "low": base - 1,
        "close": base + rng.normal(0, 0.2, n),
        "volume": rng.integers(1_000_000, 5_000_000, n),
    })
    res = compute_volume_profile(df, bins=30)
    check("vp::poc_in_range", df["low"].min() <= res["poc_price"] <= df["high"].max())
    check("vp::vah_above_val", res["value_area_high"] > res["value_area_low"])
    check("vp::poc_inside_va",
          res["value_area_low"] <= res["poc_price"] <= res["value_area_high"])

    profile = build_profile("FAKE", df, bins=30)
    score, rationale = volume_profile_score_0_100(profile)
    check("vp::score_in_range", 0 <= score <= 100, f"score={score} rationale={rationale}")


def smoke_vcp_detection() -> None:
    rng = np.random.default_rng(0)
    bars: list[dict] = []
    base = 100.0
    # Three contracting slices: ranges 8%, 4%, 1.5%.
    for i in range(10):
        h, l = base + 4, base - 4
        bars.append({"open": base, "high": h, "low": l, "close": base, "volume": 1_000_000})
        base += rng.normal(0, 0.5)
    for i in range(10):
        h, l = base + 2, base - 2
        bars.append({"open": base, "high": h, "low": l, "close": base, "volume": 1_000_000})
        base += rng.normal(0, 0.3)
    for i in range(10):
        h, l = base + 0.75, base - 0.75
        bars.append({"open": base, "high": h, "low": l, "close": base, "volume": 1_000_000})
        base += rng.normal(0, 0.1)
    df = pd.DataFrame(bars)
    res = detect_vcp(df)
    check("vcp::qualified_on_contracting_synth", res["qualified"], f"got {res}")

    # Now an expanding pattern → must not qualify.
    bars2: list[dict] = []
    base = 100.0
    for slice_range in (1.0, 2.0, 4.0):
        for _ in range(10):
            h, l = base + slice_range, base - slice_range
            bars2.append({"open": base, "high": h, "low": l, "close": base, "volume": 1_000_000})
    df2 = pd.DataFrame(bars2)
    res2 = detect_vcp(df2)
    check("vcp::not_qualified_on_expanding", not res2["qualified"], f"got {res2}")


def smoke_economic_calendar() -> None:
    now = datetime(2026, 5, 7, tzinfo=timezone.utc)
    events = events_within(now, hours_before=24 * 90, hours_after=2)
    have_fomc = any(e.category == "FOMC" for e in events)
    have_cpi = any(e.category == "CPI" for e in events)
    have_nfp = any(e.category == "NFP" for e in events)
    check("calendar::contains_fomc", have_fomc, f"events={[e.name for e in events][:5]}")
    check("calendar::contains_cpi", have_cpi)
    check("calendar::contains_nfp", have_nfp)

    in_blackout, _ = in_event_blackout(now, hours_before=24 * 60)
    check("calendar::blackout_within_60d", in_blackout)


def smoke_intermarket_score() -> None:
    pulse = MacroPulse(
        as_of_ts=datetime.now(timezone.utc),
        yield_2y=4.2, yield_10y=4.5, yield_curve_2s10s=0.3,
        yield_curve_regime="normal",
        yield_curve_change_5d=0.05,
        dxy_level=118.0, dxy_change_5d=-0.5, dxy_regime="neutral",
        nikkei_overnight_pct=0.7, dax_overnight_pct=0.4,
        spy_gap_risk="bullish",
    )
    score, rationale = intermarket_score_0_100(pulse)
    check("intermarket::bullish_macro_high_score", score >= 70, f"score={score}, {rationale}")

    bearish = MacroPulse(
        as_of_ts=datetime.now(timezone.utc),
        yield_curve_2s10s=-0.7, yield_curve_regime="inverted_deep",
        dxy_level=130.0, dxy_change_5d=2.0, dxy_regime="strong",
        nikkei_overnight_pct=-1.5, dax_overnight_pct=-1.0,
        spy_gap_risk="bearish",
    )
    score2, _ = intermarket_score_0_100(bearish)
    check("intermarket::bearish_macro_low_score", score2 < 30, f"score={score2}")


def smoke_price_action_score() -> None:
    rs = RelativeStrength(
        symbol="X", benchmark="SPY",
        rs_20d=4.0, rs_60d=8.0,
        benchmark_pulling_back=True, vcp_qualified=True,
        contraction_count=2, latest_range_pct=1.2,
    )
    score, rationale = price_action_score_0_100(rs)
    check("price_action::leadership_score", score >= 90, f"score={score}, {rationale}")

    rs_weak = RelativeStrength(symbol="X", rs_20d=-3.0, rs_60d=-5.0)
    score2, _ = price_action_score_0_100(rs_weak)
    check("price_action::lagger_score", score2 < 40, f"score={score2}")


def main() -> int:
    print("Running quant + sentiment smoke tests…\n")
    smoke_classify_tags()
    smoke_derive_multiplier()
    smoke_sentiment_score_0_100()
    smoke_score_text_with_tags()
    smoke_volume_profile()
    smoke_vcp_detection()
    smoke_economic_calendar()
    smoke_intermarket_score()
    smoke_price_action_score()

    print()
    if FAILED:
        print(f"FAILED: {len(FAILED)} tests")
        for name in FAILED:
            print(f"  - {name}")
        return 1
    print("All smoke tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
