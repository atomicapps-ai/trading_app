"""Phase 4 Step 1-3 smoke test.

Verifies:
  1. services/data_service.py       — get_bars(SPY, '1d') works; as_of_ts slice is honored
  2. services/indicator_service.py  — add_indicators() appends the full column set
  3. services/news_service.py       — module imports cleanly (no live API call here —
                                      that requires an Alpaca key which the user sets later)

Run:  .venv\\Scripts\\python.exe -m scripts.smoke_phase4_step1
"""
from __future__ import annotations

import asyncio
import logging
import sys

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


async def main() -> int:
    print("=" * 70)
    print("Phase 4 Step 1-3 smoke test")
    print("=" * 70)

    # ---- 1. data_service --------------------------------------------------
    print("\n[1/3] data_service.get_bars(SPY, '1d')")
    from services.data_service import DataNotAvailableError, get_bars

    try:
        df = await get_bars("SPY", "1d", min_bars=50)
    except DataNotAvailableError as e:
        print(f"  FAIL — {e}")
        return 1

    assert isinstance(df.index, pd.DatetimeIndex), "index must be DatetimeIndex"
    assert df.index.tz is not None, "index must be tz-aware"
    assert list(df.columns) == ["open", "high", "low", "close", "volume"], (
        f"unexpected columns: {list(df.columns)}"
    )
    print(f"  OK — {len(df)} bars, "
          f"{df.index[0].date()} -> {df.index[-1].date()}, tz={df.index.tz}")

    # ---- 2. as_of_ts slice (no future leak) -------------------------------
    print("\n[2/3] data_service.get_bars(SPY, '1d', as_of_ts=2022-01-15)")
    cutoff = pd.Timestamp("2022-01-15", tz="UTC")
    try:
        df_hist = await get_bars("SPY", "1d", as_of_ts=cutoff, min_bars=50)
    except DataNotAvailableError as e:
        print(f"  FAIL — {e}")
        return 1

    max_ts = df_hist.index.max()
    assert max_ts <= cutoff, f"look-ahead leak: max bar {max_ts} > cutoff {cutoff}"
    print(f"  OK — {len(df_hist)} bars, max ts = {max_ts.date()} (<= {cutoff.date()})")

    # ---- 3. indicator_service --------------------------------------------
    print("\n[3/3] indicator_service.add_indicators()")
    from services.indicator_service import add_indicators

    enriched = add_indicators(df)
    expected_cols = {
        "rsi_14", "atr_14", "atr_14_pct",
        "sma_20", "sma_50", "sma_200", "ema_20",
        "bb_upper_20", "bb_middle_20", "bb_lower_20", "bb_width_20",
        "kc_upper_20", "kc_middle_20", "kc_lower_20",
        "squeeze_on", "squeeze_fired", "momentum",
        "macd_line", "macd_signal", "macd_hist",
        "volume_sma_20", "volume_ratio",
        "vwap",
    }
    missing = expected_cols - set(enriched.columns)
    if missing:
        print(f"  FAIL — missing columns: {missing}")
        return 1

    # Check the last row has finite values for the core indicators
    # (leading NaNs are fine — warmup period — but the tail must be real).
    tail = enriched.iloc[-1]
    core = ["rsi_14", "atr_14", "sma_20", "sma_50", "vwap"]
    bad = [c for c in core if pd.isna(tail[c])]
    if bad:
        print(f"  FAIL — tail NaNs in core indicators: {bad}")
        return 1

    print(f"  OK — {len(enriched.columns)} columns total; "
          f"tail RSI={tail['rsi_14']:.1f}, "
          f"ATR%={tail['atr_14_pct']:.2f}, "
          f"squeeze_on={bool(tail['squeeze_on'])}")

    # ---- 4. news_service import check ------------------------------------
    print("\n[bonus] news_service imports")
    from services import news_service  # noqa: F401

    # Just check the module has the things we said it would. We don't hit
    # Alpaca/EDGAR here — that needs ALPACA_API_KEY (user sets later).
    for attr in ("get_news", "get_news_multi", "get_filings", "NewsItem", "Filing"):
        assert hasattr(news_service, attr), f"news_service missing {attr}"
    print("  OK — news_service.{get_news, get_news_multi, get_filings, NewsItem, Filing}")

    print("\n" + "=" * 70)
    print("ALL GREEN — Phase 4 Steps 1-3 are wired up correctly.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
