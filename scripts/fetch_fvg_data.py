"""fetch_fvg_data.py — one-command FX + gold history for the FVG backtest.

Source: the HistData 1-minute archive republished as parquet on HuggingFace
(`elthariel/histdata_fx_1m`, ~25y, public, no auth). We pull each symbol's
1m ticks once, cache the parquet under data/fx_hist/, and resample to the
30m + 5m CSVs that scripts/replay_fvg._load reads
(data/historical/{SYM}_{interval}.csv, tz-aware datetime + OHLCV).

Why a script and not committed data: the resampled cache is ~1.9 GB — over
GitHub's 100 MB/file limit and against CLAUDE.md's "bar cache is gitignored,
regenerate" rule. HuggingFace IS the durable store; this script is the
reproducible recipe. Run once per machine; the gitignored cache persists.

Usage:
    python -m scripts.fetch_fvg_data                 # 9 FX pairs + XAUUSD
    python -m scripts.fetch_fvg_data --symbols XAUUSD
    python -m scripts.fetch_fvg_data --force         # re-download raw parquet
"""
from __future__ import annotations

import argparse
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd

# Windows consoles default to cp1252, which can't encode characters like the
# arrow below and crashes on print. Force UTF-8 output where the runtime
# supports it (Python 3.7+); harmless elsewhere.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
HIST = ROOT / "data" / "historical"
RAW = ROOT / "data" / "fx_hist"
BASE = "https://huggingface.co/datasets/elthariel/histdata_fx_1m/resolve/main"

# App symbol -> HuggingFace directory (the 9 FVG FX pairs + gold).
SYMBOLS: dict[str, str] = {
    "EURUSD": "eurusd", "USDJPY": "usdjpy", "EURJPY": "eurjpy",
    "GBPJPY": "gbpjpy", "AUDJPY": "audjpy", "EURAUD": "euraud",
    "EURCAD": "eurcad", "GBPUSD": "gbpusd", "AUDUSD": "audusd",
    "XAUUSD": "xauusd",
}
INTERVALS = {"30m": "30min", "5m": "5min"}


def _download(sym: str, hf: str, *, force: bool) -> Path:
    """Fetch {hf}/ticks.parquet → data/fx_hist/{SYM}.parquet, with retries.

    HF's CDN occasionally returns a short read (seen on the 64 MB gold file);
    we retry a few times and only accept a complete download.
    """
    raw = RAW / f"{sym}.parquet"
    if raw.exists() and not force:
        return raw
    url = f"{BASE}/{hf}/ticks.parquet"
    last_err: Exception | None = None
    for attempt in range(1, 5):
        try:
            t0 = time.time()
            tmp = raw.with_suffix(".parquet.part")
            urllib.request.urlretrieve(url, tmp)
            tmp.replace(raw)
            print(f"  downloaded {sym} ({raw.stat().st_size // 1_000_000}MB) "
                  f"in {time.time() - t0:.1f}s")
            return raw
        except Exception as e:  # noqa: BLE001 — retry any transient failure
            last_err = e
            print(f"  {sym} download attempt {attempt} failed: {e}")
            time.sleep(2 * attempt)
    raise RuntimeError(f"{sym}: download failed after retries: {last_err}")


def _resample_and_write(sym: str, raw: Path) -> None:
    df = pd.read_parquet(raw).set_index("ts").sort_index()
    for iv, rule in INTERVALS.items():
        r = (df.resample(rule, label="left", closed="left")
               .agg({"open": "first", "high": "max", "low": "min",
                     "close": "last", "volume": "sum"})
               .dropna(subset=["open"]))
        out = r.rename(columns={"open": "Open", "high": "High", "low": "Low",
                                "close": "Close", "volume": "Volume"})
        out.index.name = "datetime"
        path = HIST / f"{sym}_{iv}.csv"
        out.to_csv(path)
        print(f"    {sym}_{iv}: {len(out):>7} bars "
              f"{out.index[0].date()} -> {out.index[-1].date()}")
    del df


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", default=",".join(SYMBOLS),
                    help="comma-separated app symbols (default: all)")
    ap.add_argument("--force", action="store_true",
                    help="re-download raw parquet even if cached")
    a = ap.parse_args()

    HIST.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    want = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]

    for sym in want:
        hf = SYMBOLS.get(sym)
        if hf is None:
            print(f"[{sym}] SKIP — not in the FVG symbol set")
            continue
        print(f"[{sym}]")
        try:
            raw = _download(sym, hf, force=a.force)
            _resample_and_write(sym, raw)
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR {sym}: {e}")
    print("DONE — run: python -m scripts.compare_fvg_intervals --since 2021-01-01 --intervals 30m,5m")


if __name__ == "__main__":
    main()
