"""fvg_service — reusable Fair Value Gap (3-candle imbalance) detector.

Single source of truth for FVGs across the app: the intraday strategy uses it for entries,
and the chart layer uses it to draw toggleable FVG zones in trade evidence.

Definition (visually verified 2026-06-30):
  Bullish FVG at middle index i:  high[i-1] < low[i+1]  -> zone [high[i-1], low[i+1]]
  Bearish FVG at middle index i:  low[i-1]  > high[i+1] -> zone [high[i+1], low[i-1]]
The middle candle (i) is the displacement. Optional filters: minimum gap size and a
displacement-strength gate (middle body >= mult x rolling-average body).

Each detected zone is JSON-serialisable for the chart API (epoch seconds + price bounds).
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import numpy as np
import pandas as pd


@dataclass
class FVGZone:
    direction: str          # "bullish" | "bearish"
    top: float              # upper price bound of the gap
    bottom: float           # lower price bound of the gap
    mid: float              # 50% line (consequent encroachment) — common entry
    size: float             # top - bottom, in price
    ts_formed: str          # iso8601 of the middle (displacement) candle
    epoch_formed: int       # epoch seconds of the middle candle (for charts)
    body_ratio: float       # middle body / rolling-avg body (displacement strength)
    filled: bool = False    # has price later traded fully back through the gap?
    epoch_filled: int | None = None

    def to_chart(self) -> dict:
        """Box payload for the Lightweight-Charts overlay (toggleable evidence)."""
        return {"direction": self.direction, "top": self.top, "bottom": self.bottom,
                "mid": self.mid, "from": self.epoch_formed, "filled": self.filled,
                "epoch_filled": self.epoch_filled, "size": self.size}


def detect_fvgs(df: pd.DataFrame, *, min_size: float = 0.0, disp_mult: float = 0.0,
                body_window: int = 20, mark_filled: bool = True) -> list[FVGZone]:
    """Return all 3-candle FVG zones in `df` (a tz-aware OHLC frame, oldest first).

    min_size : minimum gap height in price (filter noise). 0 = no filter.
    disp_mult: require middle body >= disp_mult x rolling-avg body. 0 = no filter.
    mark_filled: flag a zone filled once a later candle trades fully through it.
    """
    if df is None or len(df) < 3:
        return []
    o = df["open"].to_numpy(float); h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float); c = df["close"].to_numpy(float)
    body = np.abs(c - o)
    avg_body = pd.Series(body).rolling(body_window, min_periods=1).mean().to_numpy()
    idx = df.index
    epochs = (idx.view("int64") // 1_000_000_000).astype("int64") if hasattr(idx, "view") \
        else np.array([int(t.timestamp()) for t in idx])
    out: list[FVGZone] = []
    n = len(df)
    for i in range(1, n - 1):
        br = body[i] / avg_body[i] if avg_body[i] > 0 else 0.0
        if disp_mult > 0 and br < disp_mult:
            continue
        # bullish gap
        if h[i - 1] < l[i + 1]:
            bottom, top = float(h[i - 1]), float(l[i + 1]); direction = "bullish"
        # bearish gap
        elif l[i - 1] > h[i + 1]:
            bottom, top = float(h[i + 1]), float(l[i - 1]); direction = "bearish"
        else:
            continue
        size = top - bottom
        if size < min_size:
            continue
        z = FVGZone(direction=direction, top=top, bottom=bottom, mid=(top + bottom) / 2,
                    size=size, ts_formed=idx[i].isoformat(), epoch_formed=int(epochs[i]),
                    body_ratio=round(float(br), 2))
        if mark_filled:
            for j in range(i + 2, n):
                if l[j] <= bottom and h[j] >= top:        # fully traded through
                    z.filled = True; z.epoch_filled = int(epochs[j]); break
        out.append(z)
    return out


def fvgs_for_chart(df: pd.DataFrame, **kw) -> list[dict]:
    """Convenience: detected zones as chart-ready dicts (for /api FVG overlay)."""
    return [z.to_chart() for z in detect_fvgs(df, **kw)]


def fvg_zone_from_notes(notes: str | None) -> dict | None:
    """Parse the 'FVG=bottom..top@mid' tag that replay_fvg embeds in a trade's notes,
    so the review UI / chart can draw the gap as evidence. Returns {bottom,top,mid} or None."""
    if not notes or "FVG=" not in notes:
        return None
    import re
    m = re.search(r"FVG=([0-9.]+)\.\.([0-9.]+)@([0-9.]+)", notes)
    if not m:
        return None
    return {"bottom": float(m.group(1)), "top": float(m.group(2)), "mid": float(m.group(3))}
