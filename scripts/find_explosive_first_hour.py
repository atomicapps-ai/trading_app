"""scripts/find_explosive_first_hour.py — identify "explosive" first-hour
moves in cached 30m bars and characterize the 5-day setup that preceded them.

Definition (rigorous, reproducible):

  For each (symbol, trading_day):
    first_hour_return = close[10:00 ET] / open[9:30 ET] - 1
    abs_return        = |first_hour_return|

  Per-symbol distribution of first_hour_return is computed across its full
  history; the bar's z-score is z = (r - mean_sym) / std_sym.

  An "explosive" first-hour move is flagged when BOTH:
    1) |z| >= Z_THRESHOLD (default 3.0)         ← unusual for THIS symbol
    2) |first_hour_return| >= ATR_MULT * atr14_pct
                                                ← absolute size gate
                                                  (avoid false flags on
                                                  symbols with ultra-tight
                                                  vol distributions)

  ATR_MULT default 0.75 means the first-hour move alone covered 0.75 of
  one full daily ATR — a substantial chunk of normal day's range packed
  into one hour.

The 5-day pre-pattern features describe what the chart looked like BEFORE
the explosive bar. They are pure functions of bars[-7..-2] (i.e. the 5
trading days ending the day BEFORE the explosive day):

  prior_avg_range_pct   — mean (high-low)/close over last 5 days
  atr_contraction       — atr14 today / atr14 30d ago  (<1 = contracting)
  volume_z_5d           — z-score of last-5-day avg vol vs 60-day mean
  sma9_sma20_spread_pct — |sma9-sma20|/close on day-before  (small = flat)
  closes_above_sma20_5d — count of days last 5 with close > sma20  (0..5)
  green_days_5d         — count of bars where close>open last 5 days
  body_pct_avg_5d       — mean |close-open|/(high-low) last 5 days
  consolidation_score   — heuristic: low atr_contraction + low spread +
                          balanced direction → high score (0..1)

Outputs:
  data/state_memory/explosive_first_hour.csv  — every flagged row + features
  data/state_memory/explosive_first_hour.md   — top-K human-readable summary

CLI:
    python scripts/find_explosive_first_hour.py
    python scripts/find_explosive_first_hour.py --z 2.5 --top 30
    python scripts/find_explosive_first_hour.py --screener core_universe_100
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services import universe_service  # noqa: E402

log = logging.getLogger(__name__)

HISTORICAL_DIR = ROOT / "data" / "historical"
OUT_DIR = ROOT / "data" / "state_memory"
EARNINGS_CSV = ROOT / "data" / "earnings_history.csv"
CORP_ACTIONS_CSV = ROOT / "data" / "corporate_actions.csv"


def _load_corporate_actions() -> tuple[dict[str, set[pd.Timestamp]], dict[tuple[str, pd.Timestamp], float]]:
    """Build (split_dates, dividend_amounts).

    split_dates: {symbol -> set of normalized dates (midnight)}.
                 Alpaca raw prices show splits as "gaps", so any date here
                 should disable the GAP trigger.
    dividend_amounts: {(symbol, date) -> cash dividend per share}.  Used
                      to detect ex-dividend gaps that look like real moves
                      but aren't.
    """
    if not CORP_ACTIONS_CSV.exists():
        log.warning("corporate_actions.csv not found at %s", CORP_ACTIONS_CSV)
        return {}, {}
    df = pd.read_csv(CORP_ACTIONS_CSV)
    df["date"] = pd.to_datetime(df["date"])
    splits: dict[str, set[pd.Timestamp]] = {}
    divs: dict[tuple[str, pd.Timestamp], float] = {}
    for _, r in df.iterrows():
        sym = str(r["symbol"]).upper()
        d = pd.Timestamp(r["date"].date())
        if r["kind"] == "split":
            splits.setdefault(sym, set()).add(d)
        elif r["kind"] == "dividend":
            divs[(sym, d)] = float(r["value"])
    return splits, divs


def _load_earnings_dates() -> dict[str, set[pd.Timestamp]]:
    """Build {symbol -> set of dates whose first-hour was an earnings reaction}.

    yfinance gives us a timestamped earnings announcement (e.g. 06:00 or
    16:00 ET).  Map each announcement to the trading day whose 09:30 ET
    open will price it in:
      · ts.hour < 9                    -> mark date(ts)            (BMO)
      · 9 <= ts.hour < 14              -> mark date(ts)            (mid-session)
      · ts.hour >= 14                  -> mark date(ts) + 1 day    (AMC)
    Also mark date(ts) itself as a buffer so we never miss a hit.
    Returns dates as tz-naive pd.Timestamp at midnight, US/Eastern calendar.
    """
    if not EARNINGS_CSV.exists():
        log.warning("earnings_history.csv not found at %s — proceeding without earnings filter",
                    EARNINGS_CSV)
        return {}
    df = pd.read_csv(EARNINGS_CSV)
    df["earnings_ts"] = pd.to_datetime(df["earnings_ts"], utc=True)
    out: dict[str, set[pd.Timestamp]] = {}
    for sym, group in df.groupby("symbol"):
        dates: set[pd.Timestamp] = set()
        for ts in group["earnings_ts"]:
            ts_et = ts.tz_convert("America/New_York")
            d = pd.Timestamp(ts_et.date())
            dates.add(d)
            if ts_et.hour >= 14:
                dates.add(d + pd.Timedelta(days=1))
        out[str(sym).upper()] = dates
    return out


def _load_30m(symbol: str) -> pd.DataFrame | None:
    p = HISTORICAL_DIR / f"{symbol.upper()}_30m.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, index_col=0)
    df.index = pd.to_datetime(df.index, utc=True, errors="coerce")
    df = df[df.index.notna()]
    cols = {c.lower(): c for c in df.columns}
    rename = {cols[k]: k for k in ("open", "high", "low", "close", "volume") if k in cols}
    if len(rename) < 5:
        return None
    df = df.rename(columns=rename)
    df = df[["open", "high", "low", "close", "volume"]].copy()
    df.index = df.index.tz_convert("America/New_York")
    return df


def _aggregate_daily(df30: pd.DataFrame) -> pd.DataFrame:
    """Roll 30m bars into one row per trading day with first-hour stats."""
    et = df30.index.tz_convert("America/New_York")
    df30 = df30.assign(
        date=et.date,
        time=et.time,
    )

    rows: list[dict] = []
    for date, day in df30.groupby("date"):
        day = day.sort_index()
        if len(day) < 2:
            continue
        # First-hour bars: 09:30 + 10:00 (30m bar covering 10:00–10:30 starts at 10:00).
        hh_mm = day["time"].apply(lambda t: t.hour * 100 + t.minute).to_numpy()
        first_idx = np.where(hh_mm == 930)[0]
        second_idx = np.where(hh_mm == 1000)[0]
        if len(first_idx) == 0 or len(second_idx) == 0:
            continue
        b1 = day.iloc[first_idx[0]]
        b2 = day.iloc[second_idx[0]]
        first_open = float(b1["open"])
        first_close = float(b2["close"])
        first_high = max(float(b1["high"]), float(b2["high"]))
        first_low = min(float(b1["low"]), float(b2["low"]))
        first_vol = float(b1["volume"]) + float(b2["volume"])

        day_high = float(day["high"].max())
        day_low = float(day["low"].min())
        day_close = float(day.iloc[-1]["close"])
        day_vol = float(day["volume"].sum())
        rows.append({
            "date": pd.Timestamp(date),
            "first_open": first_open,
            "first_close": first_close,
            "first_high": first_high,
            "first_low": first_low,
            "first_return": first_close / first_open - 1.0,
            "first_range_pct": (first_high - first_low) / first_open,
            "first_vol": first_vol,
            "day_high": day_high,
            "day_low": day_low,
            "day_close": day_close,
            "day_vol": day_vol,
        })
    out = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    return out


def _label_outcome(daily: pd.DataFrame, day_idx: int, atr_pct: float) -> dict:
    """Forward outcome metrics: did the first-hour move CONTINUE, FADE, or REVERSE?

    All metrics are anchored at the close of the explosive day (i.e. the
    move "continues" the day-of and we're asking what happened after).
    Returns dict with:
        outcome_1d_pct, outcome_3d_pct, outcome_5d_pct, outcome_10d_pct
        max_favorable_5d_pct  — best move in the same direction within 5d
        max_adverse_5d_pct    — worst move against the direction within 5d
        outcome_label ∈ {CONTINUE, FADE, REVERSE, MIXED}
    Decision rules (relative to the first-hour return r):
        CONTINUE — sign(outcome_5d) == sign(r) AND |outcome_5d| >= 0.5 * atr_pct
        REVERSE  — sign(outcome_5d) != sign(r) AND |outcome_5d| >= 0.5 * atr_pct
        FADE     — |outcome_5d| < 0.5 * atr_pct (move dissipated)
        MIXED    — anything else
    """
    today = daily.iloc[day_idx]
    anchor = float(today["day_close"])
    r0 = float(today["first_return"])  # the first-hour return; sign drives "direction"
    out: dict = {
        "outcome_1d_pct":  np.nan,
        "outcome_3d_pct":  np.nan,
        "outcome_5d_pct":  np.nan,
        "outcome_10d_pct": np.nan,
        "max_favorable_5d_pct": np.nan,
        "max_adverse_5d_pct":   np.nan,
        "outcome_label": "UNKNOWN",
    }
    n = len(daily)
    for tag, k in [("outcome_1d_pct", 1), ("outcome_3d_pct", 3),
                   ("outcome_5d_pct", 5), ("outcome_10d_pct", 10)]:
        j = day_idx + k
        if j < n:
            out[tag] = 100.0 * (float(daily.iloc[j]["day_close"]) / anchor - 1.0)

    # Path metrics over the next 5 days
    j_end = min(day_idx + 5, n - 1)
    if j_end > day_idx:
        future = daily.iloc[day_idx + 1: j_end + 1]
        if len(future) > 0:
            move_dir = 1.0 if r0 >= 0 else -1.0
            highs = future["day_high"].to_numpy(dtype=float)
            lows = future["day_low"].to_numpy(dtype=float)
            if move_dir > 0:
                out["max_favorable_5d_pct"] = 100.0 * (highs.max() / anchor - 1.0)
                out["max_adverse_5d_pct"]   = 100.0 * (lows.min()  / anchor - 1.0)
            else:
                out["max_favorable_5d_pct"] = 100.0 * (anchor / lows.min()  - 1.0)
                out["max_adverse_5d_pct"]   = 100.0 * (anchor / highs.max() - 1.0)

    # Label based on the 5d outcome relative to first-hour direction
    o5 = out["outcome_5d_pct"]
    if not np.isnan(o5) and not np.isnan(atr_pct):
        threshold = 50.0 * atr_pct  # 0.5 ATR in pct units (atr_pct is fractional)
        same_sign = (o5 >= 0) == (r0 >= 0)
        magnitude = abs(o5)
        if magnitude < threshold:
            out["outcome_label"] = "FADE"
        elif same_sign:
            out["outcome_label"] = "CONTINUE"
        else:
            out["outcome_label"] = "REVERSE"
    return out


def _add_indicators(daily: pd.DataFrame) -> pd.DataFrame:
    """Add per-day indicators we'll reference when building pre-pattern features."""
    out = daily.copy()
    out["range_pct"] = (out["day_high"] - out["day_low"]) / out["day_close"]
    # True range, ATR(14)
    prev_close = out["day_close"].shift(1)
    tr = pd.concat([
        out["day_high"] - out["day_low"],
        (out["day_high"] - prev_close).abs(),
        (out["day_low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    out["atr14"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    out["atr14_pct"] = out["atr14"] / out["day_close"]
    # SMA9, SMA20 on close
    out["sma9"] = out["day_close"].rolling(9, min_periods=9).mean()
    out["sma20"] = out["day_close"].rolling(20, min_periods=20).mean()
    # Volume baseline
    out["vol_sma60"] = out["day_vol"].rolling(60, min_periods=20).mean()
    out["vol_std60"] = out["day_vol"].rolling(60, min_periods=20).std()
    return out


def _compute_prepattern(daily: pd.DataFrame, day_idx: int) -> dict | None:
    """Features computed strictly from days [day_idx-5, day_idx-1] inclusive."""
    if day_idx < 35:  # need warmup for atr/sma
        return None
    prev = daily.iloc[day_idx - 5: day_idx]
    if len(prev) < 5:
        return None
    today = daily.iloc[day_idx]
    yesterday = daily.iloc[day_idx - 1]

    prior_avg_range_pct = float(prev["range_pct"].mean())

    atr_today = float(yesterday["atr14"])  # the ATR going INTO the explosive day
    atr_30d_ago = float(daily.iloc[day_idx - 30]["atr14"]) if day_idx >= 30 else np.nan
    atr_contraction = atr_today / atr_30d_ago if atr_30d_ago and not np.isnan(atr_30d_ago) else np.nan

    vol5 = float(prev["day_vol"].mean())
    vol_sma60 = float(yesterday["vol_sma60"]) if not pd.isna(yesterday["vol_sma60"]) else np.nan
    vol_std60 = float(yesterday["vol_std60"]) if not pd.isna(yesterday["vol_std60"]) else np.nan
    volume_z_5d = (vol5 - vol_sma60) / vol_std60 if vol_std60 and vol_std60 > 0 else np.nan

    sma9 = float(yesterday["sma9"])
    sma20 = float(yesterday["sma20"])
    close = float(yesterday["day_close"])
    sma_spread_pct = abs(sma9 - sma20) / close if close > 0 else np.nan

    closes_above_sma20_5d = int((prev["day_close"] > prev["sma20"]).sum())

    # Direction: count of (close>open) days where open is approximated by prev day's close
    prev_close_shift = prev["day_close"].shift(1)
    green_days = int((prev["day_close"] > prev_close_shift).sum())

    # Body proxy via range: how much of each day's range was net move
    body_pct_avg_5d = float(((prev["day_close"] - prev_close_shift).abs() /
                             (prev["day_high"] - prev["day_low"]).replace(0, np.nan)).mean())

    # Consolidation score: low ATR contraction + low SMA spread + neutral direction
    parts = []
    if not np.isnan(atr_contraction):
        parts.append(1.0 - min(1.0, atr_contraction))         # contraction → high
    if not np.isnan(sma_spread_pct):
        parts.append(max(0.0, 1.0 - sma_spread_pct * 50.0))   # tight (<2%) → high
    parts.append(1.0 - abs(green_days - 2.5) / 2.5)           # 2-3 green → balanced
    consolidation_score = float(np.mean(parts)) if parts else np.nan

    return {
        "prior_avg_range_pct": prior_avg_range_pct,
        "atr_contraction": atr_contraction,
        "volume_z_5d": volume_z_5d,
        "sma9_sma20_spread_pct": sma_spread_pct,
        "closes_above_sma20_5d": closes_above_sma20_5d,
        "green_days_5d": green_days,
        "body_pct_avg_5d": body_pct_avg_5d,
        "consolidation_score": consolidation_score,
        "atr14_pct_yest": float(yesterday["atr14_pct"]) if not pd.isna(yesterday["atr14_pct"]) else np.nan,
    }


def scan_symbol(
    symbol: str,
    *,
    z_threshold: float,
    atr_mult: float,
    earnings_dates: set[pd.Timestamp] | None = None,
    split_dates: set[pd.Timestamp] | None = None,
    dividends: dict[pd.Timestamp, float] | None = None,
) -> pd.DataFrame:
    df30 = _load_30m(symbol)
    if df30 is None or df30.empty:
        return pd.DataFrame()
    daily = _aggregate_daily(df30)
    if len(daily) < 60:
        return pd.DataFrame()
    daily = _add_indicators(daily)

    # Three explosive behaviors, each scored independently:
    #   first_return_z  — open-to-close walk (one-way move)
    #   first_range_z   — wick / whipsaw within the first hour
    #   gap_z           — overnight gap (today's open vs prior close)
    fr = daily["first_return"].dropna()
    if len(fr) < 60:
        return pd.DataFrame()
    mu, sigma = float(fr.mean()), float(fr.std())
    if not sigma or np.isnan(sigma):
        return pd.DataFrame()
    daily["first_return_z"] = (daily["first_return"] - mu) / sigma

    rg = daily["first_range_pct"].dropna()
    if len(rg) >= 60:
        rg_mu, rg_sigma = float(rg.mean()), float(rg.std())
        daily["first_range_z"] = (daily["first_range_pct"] - rg_mu) / rg_sigma if rg_sigma else np.nan
    else:
        daily["first_range_z"] = np.nan

    daily["gap_pct"] = (daily["first_open"] / daily["day_close"].shift(1)) - 1.0
    gp = daily["gap_pct"].dropna()
    if len(gp) >= 60:
        gp_mu, gp_sigma = float(gp.mean()), float(gp.std())
        daily["gap_z"] = (daily["gap_pct"] - gp_mu) / gp_sigma if gp_sigma else np.nan
    else:
        daily["gap_z"] = np.nan

    rows: list[dict] = []
    for i in range(len(daily)):
        r = float(daily.iloc[i]["first_return"])
        z = float(daily.iloc[i]["first_return_z"])
        rng = float(daily.iloc[i]["first_range_pct"])
        rng_z = float(daily.iloc[i]["first_range_z"]) if not pd.isna(daily.iloc[i]["first_range_z"]) else np.nan
        gp = float(daily.iloc[i]["gap_pct"]) if not pd.isna(daily.iloc[i]["gap_pct"]) else np.nan
        gp_z = float(daily.iloc[i]["gap_z"]) if not pd.isna(daily.iloc[i]["gap_z"]) else np.nan
        atr_pct = float(daily.iloc[i]["atr14_pct"]) if not pd.isna(daily.iloc[i]["atr14_pct"]) else np.nan
        if np.isnan(atr_pct):
            continue
        if np.isnan(z) and np.isnan(rng_z) and np.isnan(gp_z):
            continue

        # Three independent triggers; ANY can flag the bar.
        ret_trigger   = (not np.isnan(z)) and abs(z) >= z_threshold and abs(r) >= atr_mult * atr_pct
        range_trigger = (not np.isnan(rng_z)) and rng_z >= z_threshold and rng >= atr_mult * atr_pct
        gap_trigger   = (not np.isnan(gp_z)) and abs(gp_z) >= z_threshold and (not np.isnan(gp)) and abs(gp) >= atr_mult * atr_pct

        # Mask GAP trigger on known corporate actions
        date_norm = pd.Timestamp(daily.iloc[i]["date"].date())
        is_split = bool(split_dates and date_norm in split_dates)
        div_amt = dividends.get(date_norm) if dividends else None
        # ex-div gap = -div_amt / prior_close; treat as artifact when |gap| within
        # 50bps of the implied ex-div drop OR within 0.5x the dividend yield.
        is_div_gap = False
        if div_amt is not None and i > 0 and not np.isnan(gp):
            prior_close = float(daily.iloc[i - 1]["day_close"])
            if prior_close > 0:
                expected_drop = -div_amt / prior_close
                # ex-dividends create a small downward gap; if observed gap is
                # within 0.6% of expected_drop, attribute to the dividend.
                if abs(gp - expected_drop) < 0.006:
                    is_div_gap = True
        gap_artifact = is_split or is_div_gap
        if gap_artifact:
            gap_trigger = False  # suppress; the others are still valid

        if not (ret_trigger or range_trigger or gap_trigger):
            continue

        pre = _compute_prepattern(daily, i)
        if pre is None:
            continue
        outcome = _label_outcome(daily, i, atr_pct)
        is_earnings = bool(earnings_dates and date_norm in earnings_dates)
        triggers = []
        if ret_trigger:   triggers.append("RET")
        if range_trigger: triggers.append("RANGE")
        if gap_trigger:   triggers.append("GAP")
        row = {
            "symbol": symbol,
            "date": daily.iloc[i]["date"].strftime("%Y-%m-%d"),
            "interval": "30m",
            "first_open": daily.iloc[i]["first_open"],
            "first_close": daily.iloc[i]["first_close"],
            "first_return_pct": 100.0 * r,
            "first_return_z": z,
            "first_range_pct": 100.0 * rng,
            "first_range_z": rng_z,
            "gap_pct": 100.0 * gp if not np.isnan(gp) else np.nan,
            "gap_z": gp_z,
            "atr14_pct_x": r / atr_pct if atr_pct else np.nan,
            "direction": "UP" if r > 0 else "DOWN",
            "triggers": "+".join(triggers),
            "is_earnings_day": is_earnings,
            "is_split_day": is_split,
            "is_dividend_day": is_div_gap,
            **pre,
            **outcome,
        }
        rows.append(row)
    return pd.DataFrame(rows)


async def _resolve_symbols(screener: str | None) -> list[str]:
    if screener is None:
        files = sorted(HISTORICAL_DIR.glob("*_30m.csv"))
        return [f.stem.rsplit("_", 1)[0] for f in files]
    preset = await universe_service.get_preset_db(screener)
    if preset is None:
        raise SystemExit(f"screener {screener!r} not found")
    return list(preset.get("tickers") or [])


def _format_md(df: pd.DataFrame, top: int) -> str:
    if df.empty:
        return "no explosive moves found at this threshold."

    df_sorted = df.copy()
    df_sorted["abs_z"] = df_sorted["first_return_z"].abs()
    df_sorted = df_sorted.sort_values("abs_z", ascending=False).head(top)

    lines: list[str] = [
        "# Explosive first-hour moves",
        "",
        "Top moves ranked by |first-hour z-score| × consolidation score.",
        "Each row shows the symbol/date and the 5-day setup that preceded it.",
        "",
        "## Definition",
        "",
        "An explosive first-hour move = first-hour return on the 30m chart",
        "(09:30→10:30 ET, 2 bars) where BOTH:",
        f"  · |z-score| of first-hour return ≥ Z (per-symbol distribution)",
        f"  · |first-hour return| ≥ ATR_MULT × daily ATR(14) — i.e. the first",
        f"    hour alone moved at least ATR_MULT of one full normal day's range",
        "",
        "## Top hits",
        "",
        "| Symbol | Date | Dir | 1h % | z | ATR× | Cons.score | ATR contract | Vol z (5d) | SMA9-20 % | Closes>SMA20 (5d) |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, r in df_sorted.iterrows():
        lines.append(
            f"| {r['symbol']} | {r['date']} | {r['direction']} | "
            f"{r['first_return_pct']:+.2f} | {r['first_return_z']:+.2f} | "
            f"{r['atr14_pct_x']:+.2f} | {r['consolidation_score']:.2f} | "
            f"{r['atr_contraction']:.2f} | {r['volume_z_5d']:+.2f} | "
            f"{100*r['sma9_sma20_spread_pct']:.2f} | "
            f"{int(r['closes_above_sma20_5d'])} |"
        )

    lines += [
        "",
        "## How to verify in TradingView",
        "",
        "Open each symbol on the **30-minute chart**, jump to the date column",
        "above (use the chart date selector). The marked candle is the 09:30 ET",
        "bar. The first-hour move spans that bar + the 10:00 ET bar.",
        "",
        "Or load `scripts/pine/explosive_first_hour.pine` as an indicator on a",
        "30m chart of any of these symbols. It will draw a 🚀/⚠️ icon on the",
        "09:30 bar of every day matching the same definition above so you can",
        "scroll back through history and spot-check the setups.",
        "",
    ]
    return "\n".join(lines)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--screener", default="core_universe_100")
    ap.add_argument("--z", type=float, default=3.0,
                    help="abs z-score threshold (per-symbol)")
    ap.add_argument("--atr-mult", type=float, default=0.75,
                    help="abs first-hour move must be >= atr-mult * atr14_pct")
    ap.add_argument("--top", type=int, default=30,
                    help="how many top hits to dump in markdown")
    ap.add_argument("--exclude-earnings", action="store_true",
                    help="drop earnings-day hits before writing CSV/MD")
    args = ap.parse_args()

    symbols = await _resolve_symbols(args.screener)
    earnings = _load_earnings_dates()
    if earnings:
        print(f"loaded earnings dates for {len(earnings)} symbols "
              f"({sum(len(v) for v in earnings.values()):,} total dates)")
    splits_map, divs_map = _load_corporate_actions()
    if splits_map or divs_map:
        n_splits = sum(len(v) for v in splits_map.values())
        n_divs = len(divs_map)
        print(f"loaded {n_splits} split dates + {n_divs} dividend dates")
    # Re-shape divs_map per-symbol for fast scan-time lookups
    divs_by_symbol: dict[str, dict[pd.Timestamp, float]] = {}
    for (sym, d), amt in divs_map.items():
        divs_by_symbol.setdefault(sym, {})[d] = amt

    print(f"scanning {len(symbols)} symbols on 30m bars at "
          f"|z|>={args.z}, ATR_mult>={args.atr_mult}...")

    chunks: list[pd.DataFrame] = []
    for sym in symbols:
        try:
            chunk = scan_symbol(
                sym, z_threshold=args.z, atr_mult=args.atr_mult,
                earnings_dates=earnings.get(sym.upper()),
                split_dates=splits_map.get(sym.upper()),
                dividends=divs_by_symbol.get(sym.upper()),
            )
        except Exception as e:
            log.warning("%s: %s", sym, e)
            continue
        if not chunk.empty:
            chunks.append(chunk)
            print(f"  {sym:<6s} {len(chunk):>3d} hits")

    if not chunks:
        print("no hits")
        return 0

    out = pd.concat(chunks, ignore_index=True)
    if args.exclude_earnings and "is_earnings_day" in out.columns:
        before = len(out)
        out = out[~out["is_earnings_day"]].reset_index(drop=True)
        print(f"\nfiltered earnings-day hits: {before} -> {len(out)} "
              f"({before - len(out)} dropped)")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / "explosive_first_hour.csv"
    md_path = OUT_DIR / "explosive_first_hour.md"
    out.to_csv(csv_path, index=False)
    md_path.write_text(_format_md(out, top=args.top), encoding="utf-8")

    print(f"\n{len(out):,} total hits across {out['symbol'].nunique()} symbols")
    if "is_earnings_day" in out.columns:
        n_earn = int(out["is_earnings_day"].sum())
        print(f"  earnings-day:     {n_earn:>4d} ({100 * n_earn / len(out):.0f}%)")
        print(f"  non-earnings:     {len(out) - n_earn:>4d}")
    print(f"  CSV: {csv_path}")
    print(f"  MD : {md_path}")

    print("\nTop 10 by |z|:")
    top_view = out.assign(abs_z=out["first_return_z"].abs()) \
                  .sort_values("abs_z", ascending=False).head(10)
    cols = ["symbol", "date", "direction", "first_return_pct",
            "first_return_z", "atr14_pct_x", "consolidation_score",
            "atr_contraction", "volume_z_5d"]
    print(top_view[cols].to_string(index=False, float_format=lambda x: f"{x:+.3f}"))

    print("\nDirection split:")
    print(out["direction"].value_counts().to_string())

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
