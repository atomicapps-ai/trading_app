"""ForecastDistribution — the single object every Kronos role consumes.

A forecast is N sampled future OHLC paths plus the statistics derived from them
(directional probability, expected return, dispersion, percentile cone) and a
helper to turn a candidate entry/stop/take-profit into hit probabilities and an
expected-R multiple.

Both the Kronos service and the Brownian baseline return this same shape so the
two are directly comparable (see strategies/KRONOS_UPGRADE_PROPOSAL.md §4a/§5).
"""
from __future__ import annotations

from statistics import mean, pstdev
from typing import Literal

from pydantic import BaseModel, Field


class ForecastPath(BaseModel):
    """One sampled future trajectory (per-step OHLC, length == pred_len)."""

    close: list[float]
    high: list[float]
    low: list[float]


class HitResult(BaseModel):
    """Outcome distribution for a concrete entry/stop/TP over all paths."""

    direction: Literal["long", "short"]
    entry: float
    stop: float
    take_profit: float
    p_tp_before_sl: float          # fraction of paths that hit TP first
    p_sl_before_tp: float          # fraction that hit SL first
    p_neither: float               # fraction that hit neither by the horizon
    p_profit: float                # P(TP first) + P(neither but closes in profit)
    expected_r: float              # mean R multiple across paths (after the stop)


class ForecastDistribution(BaseModel):
    """N-path forecast + derived stats. Produced by kronos_service / baseline_service."""

    source: str                    # "kronos-small", "gbm-baseline", ...
    symbol: str
    interval: str
    as_of: str                     # iso8601 of the last observed bar
    last_close: float
    pred_len: int
    n_paths: int
    paths: list[ForecastPath]

    # derived (filled by build())
    p_up: float = 0.0              # fraction of paths closing above last_close at horizon
    expected_return_pct: float = 0.0
    path_sigma_pct: float = 0.0    # stdev of final returns — the "confidence" / cone width
    cone_p10: list[float] = Field(default_factory=list)
    cone_p50: list[float] = Field(default_factory=list)
    cone_p90: list[float] = Field(default_factory=list)

    @classmethod
    def build(
        cls,
        *,
        source: str,
        symbol: str,
        interval: str,
        as_of: str,
        last_close: float,
        paths: list[ForecastPath],
    ) -> "ForecastDistribution":
        """Construct and compute all derived statistics from the raw paths."""
        n = len(paths)
        pred_len = len(paths[0].close) if n else 0
        finals = [p.close[-1] for p in paths] if pred_len else []
        rets = [(f - last_close) / last_close for f in finals] if last_close else []

        p_up = (sum(1 for f in finals if f > last_close) / n) if n else 0.0
        exp_ret = mean(rets) if rets else 0.0
        sigma = pstdev(rets) if len(rets) > 1 else 0.0

        # percentile cone per future step
        p10, p50, p90 = [], [], []
        for step in range(pred_len):
            col = sorted(p.close[step] for p in paths)
            p10.append(col[int(0.10 * (n - 1))])
            p50.append(col[int(0.50 * (n - 1))])
            p90.append(col[int(0.90 * (n - 1))])

        return cls(
            source=source,
            symbol=symbol,
            interval=interval,
            as_of=as_of,
            last_close=last_close,
            pred_len=pred_len,
            n_paths=n,
            paths=paths,
            p_up=round(p_up, 4),
            expected_return_pct=round(exp_ret * 100, 4),
            path_sigma_pct=round(sigma * 100, 4),
            cone_p10=p10,
            cone_p50=p50,
            cone_p90=p90,
        )

    def hit_probabilities(
        self,
        *,
        entry: float,
        stop: float,
        take_profit: float,
        direction: Literal["long", "short"] = "long",
    ) -> HitResult:
        """Walk every path and record which of TP / SL is touched first.

        Conservative tie-break: if a single bar's range spans both stop and target,
        the stop is assumed to fill first. R is measured in units of initial risk
        (entry-to-stop). Paths that hit neither are marked-to-market at the horizon.
        """
        risk = abs(entry - stop)
        if risk == 0:
            raise ValueError("entry and stop must differ")

        tp_first = sl_first = neither = 0
        in_profit_neither = 0
        r_multiples: list[float] = []

        for path in self.paths:
            outcome: str | None = None
            for hi, lo in zip(path.high, path.low):
                if direction == "long":
                    hit_sl = lo <= stop
                    hit_tp = hi >= take_profit
                else:
                    hit_sl = hi >= stop
                    hit_tp = lo <= take_profit
                if hit_sl:                      # conservative tie-break
                    outcome = "sl"
                    break
                if hit_tp:
                    outcome = "tp"
                    break

            if outcome == "tp":
                tp_first += 1
                r_multiples.append(abs(take_profit - entry) / risk)
            elif outcome == "sl":
                sl_first += 1
                r_multiples.append(-1.0)
            else:
                neither += 1
                final = path.close[-1]
                pnl = (final - entry) if direction == "long" else (entry - final)
                r_multiples.append(pnl / risk)
                if pnl > 0:
                    in_profit_neither += 1

        n = self.n_paths or 1
        return HitResult(
            direction=direction,
            entry=entry,
            stop=stop,
            take_profit=take_profit,
            p_tp_before_sl=round(tp_first / n, 4),
            p_sl_before_tp=round(sl_first / n, 4),
            p_neither=round(neither / n, 4),
            p_profit=round((tp_first + in_profit_neither) / n, 4),
            expected_r=round(mean(r_multiples) if r_multiples else 0.0, 3),
        )
