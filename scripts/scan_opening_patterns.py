#!/usr/bin/env python
"""
Opening Candle Pattern Scanner
================================
Exhaustively enumerates all 1-3 candle opening patterns at 15min and 30min
timeframes and measures how well each predicts the day's close direction.

Pattern dimensions per candle (4 binary dimensions = 16 combos per candle):
  direction  : BULL / BEAR   close > open vs close < open
  body       : STR  / WK     |close-open| / range > 0.5  (conviction)
  pressure   : HPRS / LPRS   (close-low) / range > 0.5   (buy vs sell dominance)
  volume     : HVOL / LVOL   candle volume vs rolling median for that time-slot

Prediction target: does the day close BULL or BEAR vs the day-open price?

Statistical filter : binomial z-score > Z_THRESHOLD vs 50% baseline
                     AND n >= MIN_SAMPLES training occurrences

Train / test split : first TRAIN_SPLIT % of days per symbol → discover patterns
                     remaining days                          → validate OOS

Output → claude_output.txt
"""
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

pd.set_option("display.width", 200)
pd.set_option("display.max_colwidth", 60)

# ── Config ────────────────────────────────────────────────────────────────────
MIN_SAMPLES    = 15      # minimum occurrences to include a pattern
Z_THRESHOLD    = 2.0     # min binomial z-score vs 50% baseline
TRAIN_SPLIT    = 0.70    # fraction of trading days used for pattern discovery
TOP_N          = 40      # rows shown in the "top patterns" section
DOWNLOAD_DELAY = 0.4     # seconds between yfinance calls

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR     = PROJECT_ROOT / "data" / "historical"
OUTPUT_FILE  = PROJECT_ROOT / "claude_output.txt"


# ── Symbol list ───────────────────────────────────────────────────────────────
def get_symbols() -> list[str]:
    return sorted(
        f.stem.replace("_1d", "")
        for f in DATA_DIR.glob("*_1d.csv")
        if not f.stem.startswith("^")
    )


# ── Data download ─────────────────────────────────────────────────────────────
def download_15m(symbol: str) -> pd.DataFrame | None:
    try:
        df = yf.download(
            symbol, period="60d", interval="15m",
            progress=False, auto_adjust=True,
        )
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.lower() for c in df.columns]
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        df.index = df.index.tz_convert("America/New_York")
        return df
    except Exception:
        return None


def resample_30m(df15: pd.DataFrame) -> pd.DataFrame:
    """Aggregate 15-min bars into 30-min OHLCV bars."""
    return (
        df15.resample("30min", closed="left", label="left")
        .agg(open=("open", "first"), high=("high", "max"),
             low=("low", "min"), close=("close", "last"),
             volume=("volume", "sum"))
        .dropna(subset=["open"])
    )


# ── Candle encoding ───────────────────────────────────────────────────────────
def slot_medians(df: pd.DataFrame, n_slots: int) -> dict:
    """Median volume for each of the first n_slots time-slots (for HVOL/LVOL)."""
    all_times = sorted(set(df.index.time))[:n_slots]
    return {
        t: float(df[df.index.time == t]["volume"].median() or 1.0)
        for t in all_times
    }


def encode(row: pd.Series, avg_vol: float) -> str:
    """
    Return a compact 4-part token for one OHLCV bar.
    Format: DIR.BODY.PRESS.VOL  e.g. BULL.STR.HPRS.HVOL
    """
    o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
    v          = float(row["volume"])
    rng        = h - l

    direction = "BULL" if c > o else "BEAR"
    body      = "STR"  if (abs(c - o) / rng > 0.5  if rng > 1e-9 else False) else "WK"
    pressure  = "HPRS" if ((c - l) / rng > 0.5      if rng > 1e-9 else True)  else "LPRS"
    vol       = "HVOL" if (v > avg_vol * 1.2)                                  else "LVOL"

    return f"{direction}.{body}.{pressure}.{vol}"


# ── Per-symbol day records ─────────────────────────────────────────────────────
def build_records(symbol: str, df15: pd.DataFrame) -> list[dict]:
    """
    One dict per trading day containing:
      - encoded first 3 candles at 15M and 30M
      - day outcome (BULL / BEAR vs day open)
      - entry price and % move to day close for each candle slot
      - MFE / MAE from each entry to end of session
    """
    df30   = resample_30m(df15)
    med15  = slot_medians(df15, 3)
    med30  = slot_medians(df30, 3)
    days   = sorted(set(df15.index.date))
    records: list[dict] = []

    for day in days:
        s15 = df15[df15.index.date == day].between_time("09:30", "15:59")
        s30 = df30[df30.index.date == day].between_time("09:30", "15:59")

        if len(s15) < 5 or len(s30) < 2:
            continue

        day_open  = float(s15.iloc[0]["open"])
        day_close = float(s15.iloc[-1]["close"])
        if abs(day_close - day_open) < 1e-6:
            continue  # skip perfectly flat days

        day_dir = "BULL" if day_close > day_open else "BEAR"

        rec: dict = {"symbol": symbol, "date": str(day), "day_dir": day_dir}

        # ── 15-min candle tokens ──────────────────────────────────────────────
        for i in range(min(3, len(s15))):
            bar  = s15.iloc[i]
            avg  = med15.get(bar.name.time(), 1.0)
            rec[f"c{i+1}_15"] = encode(bar, avg)

            if i + 1 < len(s15):
                entry = float(bar["close"])
                tail  = s15.iloc[i + 1:]
                rec[f"entry_15_c{i+1}"]    = entry
                rec[f"move_15_c{i+1}"]     = (day_close - entry) / entry * 100
                rec[f"mfe_bull_15_c{i+1}"] = _mfe(tail, entry, "BULL")
                rec[f"mae_bull_15_c{i+1}"] = _mae(tail, entry, "BULL")
                rec[f"mfe_bear_15_c{i+1}"] = _mfe(tail, entry, "BEAR")
                rec[f"mae_bear_15_c{i+1}"] = _mae(tail, entry, "BEAR")

        # ── 30-min candle tokens ──────────────────────────────────────────────
        for i in range(min(3, len(s30))):
            bar30  = s30.iloc[i]
            avg    = med30.get(bar30.name.time(), 1.0)
            rec[f"c{i+1}_30"] = encode(bar30, avg)

            # Entry = last 15M close within this 30M slot
            end_ts  = bar30.name + pd.Timedelta(minutes=29)
            slot15  = s15[(s15.index >= bar30.name) & (s15.index <= end_ts)]
            if slot15.empty:
                continue
            entry   = float(slot15.iloc[-1]["close"])
            tail    = s15[s15.index > slot15.index[-1]]
            rec[f"entry_30_c{i+1}"]    = entry
            rec[f"move_30_c{i+1}"]     = (day_close - entry) / entry * 100
            rec[f"mfe_bull_30_c{i+1}"] = _mfe(tail, entry, "BULL")
            rec[f"mae_bull_30_c{i+1}"] = _mae(tail, entry, "BULL")
            rec[f"mfe_bear_30_c{i+1}"] = _mfe(tail, entry, "BEAR")
            rec[f"mae_bear_30_c{i+1}"] = _mae(tail, entry, "BEAR")

        records.append(rec)

    return records


def _mfe(tail: pd.DataFrame, entry: float, direction: str) -> float:
    if tail.empty or entry == 0:
        return 0.0
    if direction == "BULL":
        return max(0.0, (float(tail["high"].max()) - entry) / entry * 100)
    return max(0.0, (entry - float(tail["low"].min())) / entry * 100)


def _mae(tail: pd.DataFrame, entry: float, direction: str) -> float:
    if tail.empty or entry == 0:
        return 0.0
    if direction == "BULL":
        return max(0.0, (entry - float(tail["low"].min())) / entry * 100)
    return max(0.0, (float(tail["high"].max()) - entry) / entry * 100)


# ── Pattern scanner ───────────────────────────────────────────────────────────
def scan(records: list[dict]) -> pd.DataFrame:
    """
    For every (timeframe, n_candles) combo, group by pattern key, compute
    hit-rate and z-score, return only rows that pass the significance filter.
    """
    df = pd.DataFrame(records)

    # Train / test split by date (chronological across all symbols)
    all_dates   = sorted(df["date"].unique())
    split_idx   = int(len(all_dates) * TRAIN_SPLIT)
    train_dates = set(all_dates[:split_idx])

    df["split"] = df["date"].apply(lambda d: "train" if d in train_dates else "test")

    rows: list[dict] = []

    for tf in ("15", "30"):
        for n in (1, 2, 3):
            tok_cols   = [f"c{i+1}_{tf}" for i in range(n)]
            entry_col  = f"entry_{tf}_c{n}"
            move_col   = f"move_{tf}_c{n}"

            if not all(c in df.columns for c in tok_cols) or entry_col not in df.columns:
                continue

            # Build pattern key
            sub = df.dropna(subset=tok_cols + ["day_dir", entry_col]).copy()
            sub["_pat"] = sub[tok_cols[0]]
            for col in tok_cols[1:]:
                sub["_pat"] = sub["_pat"] + "  »  " + sub[col]

            train = sub[sub["split"] == "train"]
            test  = sub[sub["split"] == "test"]

            for pat, grp in train.groupby("_pat"):
                n_obs = len(grp)
                if n_obs < MIN_SAMPLES:
                    continue

                bull_n   = int((grp["day_dir"] == "BULL").sum())
                bear_n   = int((grp["day_dir"] == "BEAR").sum())
                dominant = "BULL" if bull_n >= bear_n else "BEAR"
                hit_n    = max(bull_n, bear_n)
                hit_pct  = hit_n / n_obs * 100

                # Binomial z-score vs 50%
                z = (hit_n - n_obs * 0.5) / (n_obs * 0.25) ** 0.5
                if z < Z_THRESHOLD:
                    continue

                # Move % from entry to day-close (signed: positive = correct direction)
                moves     = grp[move_col].dropna() if move_col in grp.columns else pd.Series(dtype=float)
                avg_move  = float(moves.mean()) * (1 if dominant == "BULL" else -1) if len(moves) else float("nan")

                # MFE / MAE for dominant direction
                mfe_col   = f"mfe_{dominant.lower()}_{tf}_c{n}"
                mae_col   = f"mae_{dominant.lower()}_{tf}_c{n}"
                avg_mfe   = float(grp[mfe_col].mean()) if mfe_col in grp.columns else float("nan")
                avg_mae   = float(grp[mae_col].mean()) if mae_col in grp.columns else float("nan")

                # Out-of-sample
                tg        = test[test["_pat"] == pat]
                oos_n     = len(tg)
                oos_hit   = int((tg["day_dir"] == dominant).sum()) if oos_n else 0
                oos_pct   = f"{oos_hit/oos_n*100:.0f}%" if oos_n >= 5 else ("—" if oos_n == 0 else f"~{oos_hit/oos_n*100:.0f}%")

                rows.append(dict(
                    tf        = f"{tf}M",
                    candles   = n,
                    predict   = dominant,
                    train_n   = n_obs,
                    hit_pct   = f"{hit_pct:.0f}%",
                    z         = round(z, 2),
                    avg_move  = f"{avg_move:+.2f}%" if not np.isnan(avg_move) else "—",
                    avg_mfe   = f"{avg_mfe:.2f}%"  if not np.isnan(avg_mfe)  else "—",
                    avg_mae   = f"{avg_mae:.2f}%"  if not np.isnan(avg_mae)  else "—",
                    oos_n     = oos_n,
                    oos_hit   = oos_pct,
                    pattern   = pat,
                ))

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values("z", ascending=False).reset_index(drop=True)


# ── Output helpers ────────────────────────────────────────────────────────────
def fmt_table(df: pd.DataFrame) -> str:
    return df.to_string(index=False)


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    symbols = get_symbols()
    total   = len(symbols)
    print(f"Opening candle pattern scanner — {total} symbols | 15M + 30M | 1-3 candles")
    print(f"Downloading 15-min data from yfinance...\n")

    all_records: list[dict] = []
    skip_list:   list[str]  = []

    for idx, sym in enumerate(symbols, 1):
        print(f"  [{idx:3d}/{total}] {sym:<6} ...", end=" ", flush=True)
        df15 = download_15m(sym)
        time.sleep(DOWNLOAD_DELAY)

        if df15 is None or df15.empty:
            print("no data")
            skip_list.append(sym)
            continue

        recs = build_records(sym, df15)
        print(f"{len(recs)} days")
        all_records.extend(recs)

    print(f"\nTotal day-records : {len(all_records)}")
    print("Scanning patterns  ...")

    results = scan(all_records)

    # ── Build output file ─────────────────────────────────────────────────────
    SEP  = "=" * 145
    THIN = "─" * 145
    out  = []

    out += [
        SEP,
        "  OPENING CANDLE PATTERN SCANNER",
        f"  Dimensions : direction | body strength | buy/sell pressure | volume vs slot-median",
        f"  Timeframes : 15-min and 30-min  |  1, 2, and 3 candle sequences",
        f"  Filter     : z-score ≥ {Z_THRESHOLD} (binomial vs 50% baseline)  AND  n ≥ {MIN_SAMPLES} train samples",
        f"  Split      : {int(TRAIN_SPLIT*100)}% train / {100-int(TRAIN_SPLIT*100)}% test (chronological)",
        f"  Symbols    : {len(symbols)-len(skip_list)} of {total}  |  Day-records: {len(all_records)}",
        f"  Run at     : {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        SEP,
        "",
        "COLUMN LEGEND",
        "  tf        = timeframe (15M or 30M)",
        "  candles   = how many opening candles form the pattern (1, 2, or 3)",
        "  predict   = direction the pattern predicts for the day close (BULL / BEAR)",
        "  train_n   = number of training occurrences",
        "  hit_pct   = % of training days the day closed in the predicted direction",
        "  z         = binomial z-score vs 50% random baseline (≥2 = 95% confidence)",
        "  avg_move  = avg % move from entry to day-close (positive = in predicted direction)",
        "  avg_mfe   = avg max favourable excursion % from entry during remaining session",
        "  avg_mae   = avg max adverse excursion % from entry during remaining session",
        "  oos_n     = out-of-sample observations  |  oos_hit = OOS hit rate",
        "",
        "CANDLE TOKEN FORMAT:  DIR.BODY.PRESS.VOL",
        "  DIR   : BULL (close > open)  /  BEAR (close < open)",
        "  BODY  : STR (body > 50% of candle range)  /  WK (body ≤ 50%)",
        "  PRESS : HPRS (close in upper half of range)  /  LPRS (close in lower half)",
        "  VOL   : HVOL (> 1.2× time-slot median)  /  LVOL (≤ 1.2× median)",
        "  Multi-candle patterns separated by  »",
        "",
    ]

    if results.empty:
        out.append("  No patterns met the significance threshold.")
    else:
        n_sig = len(results)
        n_strong = int((results["z"] >= 3.0).sum())

        out += [
            f"  {n_sig} significant patterns found   ({n_strong} with z ≥ 3.0)",
            "",
        ]

        # Top N overall
        out.append(THIN)
        out.append(f"  TOP {min(TOP_N, n_sig)} PATTERNS  (all timeframes/lengths, ranked by z-score)")
        out.append(THIN)
        out.append(fmt_table(results.head(TOP_N)))
        out.append("")

        # Per timeframe × candle count
        for tf in ("15M", "30M"):
            for n in (1, 2, 3):
                sub = results[(results["tf"] == tf) & (results["candles"] == n)]
                if sub.empty:
                    continue
                out.append(THIN)
                out.append(f"  {tf}  {n}-CANDLE PATTERNS  —  {len(sub)} significant")
                out.append(THIN)
                out.append(fmt_table(sub))
                out.append("")

        # High-conviction section
        strong = results[results["z"] >= 3.0]
        if not strong.empty:
            out.append(SEP)
            out.append(f"  HIGH-CONVICTION PATTERNS  (z ≥ 3.0)  —  {len(strong)} patterns")
            out.append(SEP)
            out.append(fmt_table(strong))
            out.append("")

        # OOS survivors: hit_pct ≥ 60% in both train AND OOS (where oos_n ≥ 5)
        def oos_pct_val(row: pd.Series) -> float:
            s = row["oos_hit"].replace("%", "").replace("~", "").replace("—", "nan")
            try:
                return float(s)
            except ValueError:
                return float("nan")

        results["_oos_val"] = results.apply(oos_pct_val, axis=1)
        survivors = results[
            (results["oos_n"] >= 5) &
            (results["_oos_val"] >= 60) &
            (results["hit_pct"].str.replace("%", "").astype(float) >= 60)
        ].drop(columns=["_oos_val"])

        if not survivors.empty:
            out.append(SEP)
            out.append(f"  OOS-VALIDATED PATTERNS  (train hit ≥ 60% AND oos hit ≥ 60% with n ≥ 5)")
            out.append(SEP)
            out.append(fmt_table(survivors))
            out.append("")

    if skip_list:
        out.append(f"Skipped (no 15-min data): {', '.join(skip_list)}")

    OUTPUT_FILE.write_text("\n".join(out), encoding="utf-8")
    print(f"Done.  Output → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
