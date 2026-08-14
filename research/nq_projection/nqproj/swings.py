"""Objective major-swing detection.

The brief's methodological demand is to work *backwards* from genuinely large
swings rather than forwards from every zone touch, so swings must be defined
without reference to projections -- otherwise the answer is circular.

A volatility-normalised zigzag on hourly bars produces the pivot skeleton; the
"major" filters are then applied on top. Several thresholds are supported
because a finding that only survives at one magic threshold is not a finding.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .data import BarSet


def atr(hourly: pd.DataFrame, n: int = 14) -> pd.Series:
    """Causal ATR: shifted so bar i's value uses only information before i."""
    h, l, c = hourly["high"], hourly["low"], hourly["close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=max(2, n // 2)).mean().shift(1)


def zigzag(
    hourly: pd.DataFrame,
    threshold: pd.Series,
) -> pd.DataFrame:
    """Alternating confirmed pivots.

    A running extreme is promoted to a pivot once price retraces from it by
    ``threshold`` (a per-bar price distance). Pivots are timestamped at the bar
    that made the extreme, but they are only *known* at the later bar that
    confirmed them -- both are recorded, and anything forward-looking must use
    ``confirm_time``.
    """
    hi = hourly["high"].to_numpy(float)
    lo = hourly["low"].to_numpy(float)
    idx = hourly.index
    th = threshold.reindex(idx).to_numpy(float)

    piv: list[dict] = []
    direction = 0
    max_i, max_p = 0, hi[0]
    min_i, min_p = 0, lo[0]

    for i in range(1, len(hi)):
        t = th[i]
        if not np.isfinite(t) or t <= 0:
            continue

        if hi[i] > max_p:
            max_p, max_i = hi[i], i
        if lo[i] < min_p:
            min_p, min_i = lo[i], i

        if direction >= 0 and (max_p - lo[i]) >= t and max_i != i:
            piv.append({"kind": "high", "bar": max_i, "price": max_p, "confirm_bar": i})
            direction = -1
            min_p, min_i = lo[i], i
        elif direction <= 0 and (hi[i] - min_p) >= t and min_i != i:
            piv.append({"kind": "low", "bar": min_i, "price": min_p, "confirm_bar": i})
            direction = 1
            max_p, max_i = hi[i], i

    if not piv:
        return pd.DataFrame(columns=["kind", "time", "price", "confirm_time"])

    p = pd.DataFrame(piv)
    # Consecutive same-kind pivots can appear when a leg extends; keep the
    # more extreme one so the sequence strictly alternates.
    keep = []
    for r in p.to_dict("records"):
        if keep and keep[-1]["kind"] == r["kind"]:
            better = r["price"] > keep[-1]["price"] if r["kind"] == "high" else r["price"] < keep[-1]["price"]
            if better:
                keep[-1] = r
            continue
        keep.append(r)
    p = pd.DataFrame(keep)

    p["time"] = idx[p["bar"].to_numpy()]
    p["confirm_time"] = idx[p["confirm_bar"].to_numpy()]
    return p[["kind", "time", "price", "confirm_time", "bar", "confirm_bar"]]


def swings_from_pivots(pivots: pd.DataFrame) -> pd.DataFrame:
    """Legs between consecutive pivots, with the extreme that terminated each."""
    if len(pivots) < 2:
        return pd.DataFrame()
    a = pivots.iloc[:-1].reset_index(drop=True)
    b = pivots.iloc[1:].reset_index(drop=True)
    sw = pd.DataFrame(
        {
            "start_time": a["time"].to_numpy(),
            "start_price": a["price"].to_numpy(float),
            "end_time": b["time"].to_numpy(),
            "end_price": b["price"].to_numpy(float),
            "end_kind": b["kind"].to_numpy(),
            "confirm_time": b["confirm_time"].to_numpy(),
        }
    )
    sw["direction"] = np.where(sw["end_kind"] == "high", 1, -1)
    sw["magnitude"] = (sw["end_price"] - sw["start_price"]).abs()
    sw["duration_hours"] = (
        (pd.to_datetime(sw["end_time"]) - pd.to_datetime(sw["start_time"])).dt.total_seconds() / 3600.0
    )
    return sw


def detect_swings(
    bs: BarSet,
    mode: str = "atr",
    k: float = 3.0,
    refs: pd.DataFrame | None = None,
    atr_n: int = 14,
) -> pd.DataFrame:
    """Zigzag swings under one threshold definition.

    ``mode``:
      ``atr``      -- k * hourly ATR (self-scaling to regime)
      ``pct``      -- k percent of price
      ``refrange`` -- k * trailing median reference-candle range (needs ``refs``)
    """
    hourly = bs.hourly()
    if mode == "atr":
        th = k * atr(hourly, atr_n)
    elif mode == "pct":
        th = (k / 100.0) * hourly["close"].shift(1)
    elif mode == "refrange":
        if refs is None or refs.empty:
            raise ValueError("mode='refrange' needs refs")
        r = refs.set_index("activate")["R"].sort_index()
        med = r.rolling(20, min_periods=5).median()
        th = k * med.reindex(hourly.index, method="ffill")
    else:
        raise ValueError(f"unknown mode {mode!r}")

    piv = zigzag(hourly, th)
    sw = swings_from_pivots(piv)
    if not sw.empty:
        sw["mode"] = mode
        sw["k"] = k
    return sw


def label_major(
    swings: pd.DataFrame,
    refs: pd.DataFrame,
    bs: BarSet,
    ref_multiples=(3.0, 5.0),
    daily_range_frac: float = 1.0,
) -> pd.DataFrame:
    """Attach several independent 'is this a major swing?' verdicts.

    Each swing's magnitude is normalised by (a) the range of the most recent
    reference candle available when the swing started, and (b) the trailing
    daily range. A swing that is major under only one definition is a weak
    observation, which is exactly what these columns let us see.
    """
    if swings.empty:
        return swings

    sw = swings.copy()
    st = pd.to_datetime(sw["start_time"])

    r = refs.sort_values("activate")
    pos = np.searchsorted(r["activate"].to_numpy(), st.to_numpy(), side="right") - 1
    sw["ref_R_at_start"] = np.where(pos >= 0, r["R"].to_numpy()[np.clip(pos, 0, None)], np.nan)
    sw["mag_in_R"] = sw["magnitude"] / sw["ref_R_at_start"]

    daily = bs.bars["high"].resample("1D").max() - bs.bars["low"].resample("1D").min()
    trail = daily.rolling(20, min_periods=5).median().shift(1)
    trail_ny = trail.reindex(pd.DatetimeIndex(st).normalize(), method="ffill")
    sw["trailing_daily_range"] = trail_ny.to_numpy()
    sw["mag_in_daily"] = sw["magnitude"] / sw["trailing_daily_range"]

    for m in ref_multiples:
        sw[f"major_ge_{m:g}R"] = sw["mag_in_R"] >= m
    sw["major_daily"] = sw["mag_in_daily"] >= daily_range_frac
    sw["major_multihour"] = sw["duration_hours"] >= 4.0
    return sw
