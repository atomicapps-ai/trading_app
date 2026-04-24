#!/usr/bin/env python
"""
Opening 15-Minute Candle Theory Test
=====================================
Theory:  If the first 15-min candle (9:30–9:44 ET) is BEARISH  → day closes BULLISH.
         If the first 15-min candle (9:30–9:44 ET) is BULLISH  → day closes BEARISH.

Trade simulation:
  - Entry     : close of the first 15-min candle  (≈ 9:46 AM ET)
  - Direction : opposite of the first candle direction
  - SL        : low of first candle (LONG) / high of first candle (SHORT)
  - TP        : 2 × SL-distance from entry  (2:1 R:R)
  - Exit      : first of  TP touched | SL touched | market close

Output: claude_output.txt in project root.
"""
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ── Config ────────────────────────────────────────────────────────────────────
RR_RATIO       = 2.0    # TP = entry ± RR_RATIO × SL-distance
DAYS_TO_TEST   = 20     # last N complete trading days per symbol
DOWNLOAD_DELAY = 0.5    # seconds between yfinance calls (rate-limit courtesy)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR     = PROJECT_ROOT / "data" / "historical"
OUTPUT_FILE  = PROJECT_ROOT / "claude_output.txt"


# ── Symbol list ───────────────────────────────────────────────────────────────
def get_symbols() -> list[str]:
    """All symbols with a *_1d.csv in data/historical/, excluding indices (^)."""
    return sorted(
        f.stem.replace("_1d", "")
        for f in DATA_DIR.glob("*_1d.csv")
        if not f.stem.startswith("^")
    )


# ── yfinance 15-minute download ───────────────────────────────────────────────
def download_15m(symbol: str) -> pd.DataFrame | None:
    """Download 60 days of 15-min bars (yfinance maximum for this interval)."""
    try:
        df = yf.download(
            symbol, period="60d", interval="15m",
            progress=False, auto_adjust=True
        )
        if df.empty:
            return None
        # Flatten MultiIndex columns (yfinance ≥ 0.2 wraps single-ticker too)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.lower() for c in df.columns]
        # Normalise to Eastern Time
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        df.index = df.index.tz_convert("America/New_York")
        return df
    except Exception as exc:
        print(f"    download error: {exc}")
        return None


# ── Core analysis for one symbol ─────────────────────────────────────────────
def analyze_symbol(symbol: str, df: pd.DataFrame | None, n_days: int) -> list[dict]:
    if df is None or df.empty:
        return []

    trading_days = sorted(set(df.index.date))[-n_days:]
    rows: list[dict] = []

    for day in trading_days:
        # Regular session bars only (9:30 – 15:59 ET)
        session = df[df.index.date == day].between_time("09:30", "15:59")

        # Need at least the first candle + a few more to evaluate the day
        if len(session) < 4:
            continue

        first   = session.iloc[0]          # 9:30 candle
        f_open  = float(first["open"])
        f_close = float(first["close"])
        f_low   = float(first["low"])
        f_high  = float(first["high"])

        # Skip doji (open == close)
        if abs(f_close - f_open) < 1e-6:
            continue

        candle_dir = "BULL" if f_close > f_open else "BEAR"

        # Theory: trade the OPPOSITE direction
        if candle_dir == "BEAR":
            trade_dir = "LONG"
            entry     = f_close
            sl        = f_low
            sl_dist   = entry - sl
            tp        = entry + RR_RATIO * sl_dist
        else:
            trade_dir = "SHORT"
            entry     = f_close
            sl        = f_high
            sl_dist   = sl - entry
            tp        = entry - RR_RATIO * sl_dist

        # Skip near-zero-range candles (would give unrealistic R multiples)
        if sl_dist < 0.005:
            continue

        # Walk remaining bars to check for TP / SL touch
        remaining  = session.iloc[1:]
        how        = "CLOSE"
        exit_price = float(session.iloc[-1]["close"])   # default: held to close

        for _, bar in remaining.iterrows():
            lo = float(bar["low"])
            hi = float(bar["high"])
            if trade_dir == "LONG":
                if lo <= sl:
                    how        = "SL_HIT"
                    exit_price = sl
                    break
                if hi >= tp:
                    how        = "TP_HIT"
                    exit_price = tp
                    break
            else:  # SHORT
                if hi >= sl:
                    how        = "SL_HIT"
                    exit_price = sl
                    break
                if lo <= tp:
                    how        = "TP_HIT"
                    exit_price = tp
                    break

        # P&L in points and R-multiples
        pnl_pts = (exit_price - entry) if trade_dir == "LONG" else (entry - exit_price)
        pnl_r   = pnl_pts / sl_dist
        pct_pnl = pnl_pts / entry * 100

        # Was the day's direction (vs its opening price) what the theory predicted?
        day_close = float(session.iloc[-1]["close"])
        if day_close > f_open:
            day_dir = "BULL"
        elif day_close < f_open:
            day_dir = "BEAR"
        else:
            day_dir = "FLAT"

        theory_ok = (
            (candle_dir == "BULL" and day_dir == "BEAR") or
            (candle_dir == "BEAR" and day_dir == "BULL")
        )

        rows.append(dict(
            date    = str(day),
            candle  = candle_dir,
            trade   = trade_dir,
            entry   = round(entry, 2),
            sl      = round(sl, 2),
            tp      = round(tp, 2),
            exit_at = round(exit_price, 2),
            how     = how,
            pnl_pts = round(pnl_pts, 3),
            pnl_R   = round(pnl_r, 2),
            pct     = round(pct_pnl, 2),
            day_dir = day_dir,
            theory  = "YES" if theory_ok else "NO",
            outcome = "WIN" if pnl_pts > 0 else "LOSS",
        ))

    return rows


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    symbols = get_symbols()
    total   = len(symbols)
    print(f"Opening 15-min candle theory test — {total} symbols, {DAYS_TO_TEST} days each")
    print(f"Downloading 15-min data from yfinance (this may take ~{total//2} seconds)...\n")

    all_rows:     list[dict] = []
    summary_rows: list[dict] = []
    skip_list:    list[str]  = []

    for idx, sym in enumerate(symbols, 1):
        print(f"  [{idx:3d}/{total}] {sym:<6} ...", end=" ", flush=True)
        df   = download_15m(sym)
        rows = analyze_symbol(sym, df, DAYS_TO_TEST)
        time.sleep(DOWNLOAD_DELAY)

        if not rows:
            print("no data / skipped")
            skip_list.append(sym)
            continue

        print(f"{len(rows)} days analysed")
        for r in rows:
            r["symbol"] = sym
        all_rows.extend(rows)

        dft        = pd.DataFrame(rows)
        n          = len(dft)
        theory_pct = dft["theory"].eq("YES").sum() / n * 100
        win_rate   = dft["outcome"].eq("WIN").sum() / n * 100
        avg_r      = dft["pnl_R"].mean()
        avg_pct    = dft["pct"].mean()
        tp_hits    = int(dft["how"].eq("TP_HIT").sum())
        sl_hits    = int(dft["how"].eq("SL_HIT").sum())
        to_close   = int(dft["how"].eq("CLOSE").sum())

        summary_rows.append(dict(
            Symbol     = sym,
            Days       = n,
            Theory_Pct = f"{theory_pct:.0f}%",
            Win_Rate   = f"{win_rate:.0f}%",
            Avg_R      = f"{avg_r:+.2f}R",
            Avg_Pct    = f"{avg_pct:+.1f}%",
            TP_Hits    = tp_hits,
            SL_Hits    = sl_hits,
            To_Close   = to_close,
        ))

    # ── Compose output ────────────────────────────────────────────────────────
    SEP   = "=" * 130
    THIN  = "─" * 130
    lines = []

    lines += [
        SEP,
        "  OPENING 15-MINUTE CANDLE THEORY — TEST RESULTS",
        f"  Theory  : Bearish first 15-min candle (9:30–9:44 ET) → day closes Bullish  (and vice versa)",
        f"  Trade   : Enter at first-candle close | SL = candle low/high | TP = {RR_RATIO:.0f}:1 R:R",
        f"  Scope   : Last {DAYS_TO_TEST} complete trading days per symbol | {len(symbols)} symbols",
        f"  Run at  : {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        SEP,
        "",
    ]

    # ── Overall stats ─────────────────────────────────────────────────────────
    if all_rows:
        all_df    = pd.DataFrame(all_rows)
        n_all     = len(all_df)
        ov_theory = all_df["theory"].eq("YES").sum() / n_all * 100
        ov_win    = all_df["outcome"].eq("WIN").sum() / n_all * 100
        ov_r      = all_df["pnl_R"].mean()
        ov_pct    = all_df["pct"].mean()
        ov_tp     = int(all_df["how"].eq("TP_HIT").sum())
        ov_sl     = int(all_df["how"].eq("SL_HIT").sum())
        ov_cl     = int(all_df["how"].eq("CLOSE").sum())

        lines += [
            "OVERALL AGGREGATE",
            "─" * 60,
            f"  Trade-days analysed : {n_all}  ({len(summary_rows)} symbols)",
            f"  Theory correct      : {ov_theory:.1f}%   (day closed in predicted direction)",
            f"  Trade win rate      : {ov_win:.1f}%   (TP hit or held-to-close profit)",
            f"  Average R           : {ov_r:+.2f}R",
            f"  Average % move      : {ov_pct:+.2f}%  (entry → exit, signed by trade direction)",
            f"  Exits → TP_HIT      : {ov_tp}   SL_HIT: {ov_sl}   Held-to-CLOSE: {ov_cl}",
            "",
        ]

    # ── Summary grid ─────────────────────────────────────────────────────────
    lines.append("PER-SYMBOL SUMMARY")
    lines.append("─" * 80)
    if summary_rows:
        df_sum = pd.DataFrame(summary_rows)
        lines.append(df_sum.to_string(index=False))
    else:
        lines.append("  No data collected.")
    lines.append("")

    if skip_list:
        lines.append(f"Skipped (no 15-min data available): {', '.join(skip_list)}")
        lines.append("")

    # ── Per-symbol detail grids ───────────────────────────────────────────────
    lines.append(SEP)
    lines.append("  PER-SYMBOL DETAIL")
    lines.append(SEP)
    lines.append("")

    col_order = [
        "date", "candle", "trade", "entry", "sl", "tp",
        "exit_at", "how", "pnl_pts", "pnl_R", "pct",
        "day_dir", "theory", "outcome",
    ]

    for sym in symbols:
        sym_rows = [r for r in all_rows if r["symbol"] == sym]
        if not sym_rows:
            continue

        df_det = pd.DataFrame(sym_rows).drop(columns=["symbol"])
        df_det = df_det[[c for c in col_order if c in df_det.columns]]

        n     = len(df_det)
        t_ok  = df_det["theory"].eq("YES").sum()
        wins  = df_det["outcome"].eq("WIN").sum()
        avg_r = df_det["pnl_R"].mean()

        lines.append(THIN)
        lines.append(
            f"  {sym:<6}  |  {n} days  |  "
            f"Theory correct: {t_ok}/{n} ({t_ok/n*100:.0f}%)  |  "
            f"Win rate: {wins}/{n} ({wins/n*100:.0f}%)  |  "
            f"Avg R: {avg_r:+.2f}"
        )
        lines.append(THIN)
        lines.append(df_det.to_string(index=False))
        lines.append("")

    output = "\n".join(lines)
    OUTPUT_FILE.write_text(output, encoding="utf-8")
    print(f"\nDone.  Output written → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
