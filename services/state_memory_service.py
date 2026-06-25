"""state_memory_service — build, persist, and query the bar-state matrix.

Storage layout under data/state_memory/{interval}/:
    index.faiss        — FAISS IndexFlatL2 over standardized 8-vec
    metadata.parquet   — per-row sidecar: symbol, ts, fwd_1h, fwd_4h, fwd_1d, fwd_5d
    scaler.npz         — feature mean + std used to standardize at insert/query

The index is built offline by scripts/build_state_memory.py over every
cached CSV in data/historical/{SYMBOL}_{INTERVAL}.csv. Queries are served
in-process by load_index() + query().
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from agents.state_memory import encoder, labeler
from services.settings_service import DATA_DIR

log = logging.getLogger(__name__)

STATE_MEMORY_DIR = DATA_DIR / "state_memory"
HISTORICAL_DIR = DATA_DIR / "historical"


@dataclass
class StateMemoryIndex:
    """In-memory bundle of FAISS index + sidecar metadata + scaler."""
    interval: str
    index: object  # faiss.IndexFlatL2 (avoid hard import at module level)
    metadata: pd.DataFrame  # columns: symbol, ts, fwd_1h, fwd_4h, fwd_1d, fwd_5d
    feat_mean: np.ndarray
    feat_std: np.ndarray

    @property
    def size(self) -> int:
        return int(self.index.ntotal)


def interval_dir(interval: str) -> Path:
    return STATE_MEMORY_DIR / interval


def _standardize(features: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    out = (features - mean) / np.where(std > 1e-9, std, 1.0)
    return out.astype(np.float32, copy=False)


def encode_one_csv(
    csv_path: Path, interval: str
) -> tuple[np.ndarray, pd.DataFrame] | None:
    """Encode every bar in one historical CSV to (features, sidecar).

    Returns None when the CSV is too short or empty after warmup.
    Sidecar columns: symbol, ts, fwd_1h, fwd_4h, fwd_1d, fwd_5d.
    """
    symbol = csv_path.stem.rsplit("_", 1)[0].upper()
    try:
        df = pd.read_csv(csv_path, index_col=0)
    except Exception as e:
        log.warning("read failed %s: %s", csv_path, e)
        return None

    df.index = pd.to_datetime(df.index, utc=True, errors="coerce")
    df = df[df.index.notna()]
    if df.empty or len(df) < 250:
        return None

    cols = {c.lower(): c for c in df.columns}
    rename = {cols[k]: k for k in ("open", "high", "low", "close", "volume") if k in cols}
    if len(rename) < 5:
        log.warning("%s: missing OHLCV columns, got %s", csv_path, list(df.columns))
        return None
    df = df.rename(columns=rename)

    feats, valid = encoder.encode_bars(df)
    labels = labeler.label_bars(df, interval)

    label_valid = ~np.isnan(np.column_stack([labels[h] for h in labeler.HORIZONS])).any(axis=1)
    keep = valid & label_valid
    if not keep.any():
        return None

    sidecar = pd.DataFrame({
        "symbol": symbol,
        "ts": df.index[keep],
        **{h: labels[h][keep] for h in labeler.HORIZONS},
    })
    return feats[keep], sidecar


def build_index(
    interval: str,
    symbols: Iterable[str] | None = None,
    *,
    out_dir: Path | None = None,
) -> StateMemoryIndex:
    """Build a fresh FAISS index from cached CSVs in data/historical/.

    If symbols is None, every {SYM}_{INTERVAL}.csv in data/historical/ is used.
    """
    import faiss

    out_dir = out_dir or interval_dir(interval)
    out_dir.mkdir(parents=True, exist_ok=True)

    if symbols is None:
        files = sorted(HISTORICAL_DIR.glob(f"*_{interval}.csv"))
    else:
        files = [HISTORICAL_DIR / f"{s.upper()}_{interval}.csv" for s in symbols]
        files = [f for f in files if f.exists()]

    if not files:
        raise RuntimeError(
            f"build_index: no CSVs found for interval={interval!r} in {HISTORICAL_DIR}"
        )

    feat_chunks: list[np.ndarray] = []
    side_chunks: list[pd.DataFrame] = []
    for f in files:
        result = encode_one_csv(f, interval)
        if result is None:
            log.info("skip %s (too short or unusable)", f.name)
            continue
        feats, side = result
        feat_chunks.append(feats)
        side_chunks.append(side)
        log.info("encoded %s: %d bars", f.name, len(side))

    if not feat_chunks:
        raise RuntimeError("build_index: no usable bars across any CSV")

    feats = np.concatenate(feat_chunks, axis=0)
    metadata = pd.concat(side_chunks, ignore_index=True)

    feat_mean = feats.mean(axis=0).astype(np.float32)
    feat_std = feats.std(axis=0).astype(np.float32)
    standardized = _standardize(feats, feat_mean, feat_std)

    index = faiss.IndexFlatL2(encoder.N_FEATURES)
    index.add(standardized)

    faiss.write_index(index, str(out_dir / "index.faiss"))
    metadata.to_parquet(out_dir / "metadata.parquet", index=False)
    np.savez(out_dir / "scaler.npz", mean=feat_mean, std=feat_std)

    log.info("wrote index (%d vectors) to %s", index.ntotal, out_dir)
    return StateMemoryIndex(interval, index, metadata, feat_mean, feat_std)


def load_index(interval: str, *, out_dir: Path | None = None) -> StateMemoryIndex:
    import faiss

    out_dir = out_dir or interval_dir(interval)
    if not (out_dir / "index.faiss").exists():
        raise FileNotFoundError(
            f"no state_memory index at {out_dir} — run scripts/build_state_memory.py first"
        )

    index = faiss.read_index(str(out_dir / "index.faiss"))
    metadata = pd.read_parquet(out_dir / "metadata.parquet")
    sc = np.load(out_dir / "scaler.npz")
    return StateMemoryIndex(
        interval=interval,
        index=index,
        metadata=metadata,
        feat_mean=sc["mean"].astype(np.float32),
        feat_std=sc["std"].astype(np.float32),
    )


def query(
    sm: StateMemoryIndex,
    query_features: np.ndarray,
    k: int = 50,
    *,
    exclude_self_within_bars: int = 0,
) -> pd.DataFrame:
    """Find the k nearest historical states to one or more query vectors.

    query_features: shape (Q, 8) raw (un-standardized) features.
    exclude_self_within_bars: drop neighbors whose row index is within this
        many positions of the query (only meaningful when the query came
        from a row already in the index).

    Returns a long-format DataFrame:
        query_idx, rank, distance, symbol, ts, fwd_1h, fwd_4h, fwd_1d, fwd_5d
    """
    if query_features.ndim == 1:
        query_features = query_features[None, :]
    q_std = _standardize(query_features.astype(np.float32), sm.feat_mean, sm.feat_std)

    k_search = k + max(1, exclude_self_within_bars * 2 + 1)
    distances, indices = sm.index.search(q_std, k_search)

    rows: list[dict] = []
    for q_i in range(q_std.shape[0]):
        kept = 0
        for rank, (d, idx) in enumerate(zip(distances[q_i], indices[q_i])):
            if idx < 0:
                continue
            row = sm.metadata.iloc[int(idx)]
            rows.append({
                "query_idx": q_i,
                "rank": kept,
                "distance": float(d),
                "symbol": row["symbol"],
                "ts": row["ts"],
                **{h: float(row[h]) for h in labeler.HORIZONS},
            })
            kept += 1
            if kept >= k:
                break
    return pd.DataFrame(rows)


def encode_state_for(symbol: str, interval: str, as_of_ts: pd.Timestamp) -> np.ndarray:
    """Encode the bar at-or-before as_of_ts for `symbol` from cached CSV.

    Convenience for the query CLI. Returns a 1D float32 array of length 8.
    """
    csv_path = HISTORICAL_DIR / f"{symbol.upper()}_{interval}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)
    df = pd.read_csv(csv_path, index_col=0)
    df.index = pd.to_datetime(df.index, utc=True, errors="coerce")
    df = df[df.index.notna()]

    cols = {c.lower(): c for c in df.columns}
    rename = {cols[k]: k for k in ("open", "high", "low", "close", "volume") if k in cols}
    df = df.rename(columns=rename)

    if as_of_ts.tz is None:
        as_of_ts = as_of_ts.tz_localize("UTC")

    df = df[df.index <= as_of_ts]
    if df.empty:
        raise ValueError(f"no bars at or before {as_of_ts} for {symbol}")

    feats, valid = encoder.encode_bars(df)
    last_valid_idx = np.where(valid)[0]
    if len(last_valid_idx) == 0:
        raise ValueError(f"no warmed-up bar for {symbol} by {as_of_ts}")
    return feats[last_valid_idx[-1]]
