"""Reference candles, their projection ladders, and first-touch resolution.

A *reference candle* is one NY hourly candle (21:00 or 09:00). It defines
R = H - L and projects a ladder of levels above H and below L. Zones become
*active* only when the candle completes (22:00 / 10:00) -- nothing may be
measured against a candle while it is still forming, or the whole study
back-leaks information.

Zones persist: a candle's ladder stays on the map for ``max_age_days`` so the
"is an older projection still relevant?" question can be answered from data
rather than assumed away by a daily reset.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .data import BarSet

# The 2.0-2.5 band is the observation under test; the rest of the ladder exists
# so that "price went straight through" can be measured rather than clipped.
DEFAULT_LADDER = (1.0, 1.5, 2.0, 2.5, 2.75, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0, 8.0, 10.0)

REF_HOURS = {"9PM": 21, "9AM": 9}


@dataclass
class PathIndex:
    """Array view over bars supporting fast forward first-touch queries.

    The trick that makes the whole study tractable: running max is
    non-decreasing and running min is non-increasing, so once they are computed
    for a given start bar, the first touch of *any* level is a binary search
    rather than a scan. Reference candles share a start bar across their entire
    ladder, so the running extremes are computed once per candle.
    """

    ts: np.ndarray       # datetime64[ns, UTC-naive ints] bar open times
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    _cache: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_barset(cls, bs: BarSet) -> "PathIndex":
        b = bs.bars
        return cls(
            ts=b.index.values.astype("datetime64[ns]"),
            high=b["high"].to_numpy(float),
            low=b["low"].to_numpy(float),
            close=b["close"].to_numpy(float),
        )

    def __len__(self) -> int:
        return len(self.ts)

    def idx_at_or_after(self, when) -> int:
        t = pd.Timestamp(when)
        # PathIndex.ts holds UTC-naive instants (DatetimeIndex.values), so any
        # tz-aware query has to be pushed through UTC before comparison.
        t = t.tz_convert("UTC").tz_localize(None) if t.tzinfo is not None else t
        return int(np.searchsorted(self.ts, np.datetime64(t, "ns"), side="left"))

    def _extremes(self, start: int, end: int):
        key = (start, end)
        hit = self._cache.get(key)
        if hit is None:
            if len(self._cache) > 512:          # bounded: candles are visited in order
                self._cache.clear()
            hit = (
                np.maximum.accumulate(self.high[start:end]),
                np.minimum.accumulate(self.low[start:end]),
            )
            self._cache[key] = hit
        return hit

    def first_touch(self, start: int, end: int, level: float, up: bool) -> int:
        """Index of the first bar in [start, end) whose range reaches ``level``.

        ``-1`` when the level is never reached inside the window.
        """
        if start >= end or start >= len(self.ts):
            return -1
        end = min(end, len(self.ts))
        cmax, cmin = self._extremes(start, end)
        if up:
            pos = int(np.searchsorted(cmax, level, side="left"))
        else:
            pos = int(np.searchsorted(-cmin, -level, side="left"))
        if pos >= (end - start):
            return -1
        return start + pos


def build_reference_candles(
    bs: BarSet,
    kinds: tuple[str, ...] = ("9PM", "9AM"),
    min_range: float = 0.0,
) -> pd.DataFrame:
    """One row per completed reference candle.

    ``activate`` is the moment the candle closes -- the earliest instant its
    projections may be used for anything.
    """
    hourly = bs.hourly()
    rows = []
    for kind in kinds:
        hour = REF_HOURS[kind]
        sel = hourly[hourly.index.hour == hour]
        for ts, row in sel.iterrows():
            rng = float(row["high"] - row["low"])
            if not np.isfinite(rng) or rng <= min_range:
                continue
            rows.append(
                {
                    "ref_time": ts,
                    "kind": kind,
                    "H": float(row["high"]),
                    "L": float(row["low"]),
                    "C": float(row["close"]),
                    "R": rng,
                    "activate": ts + pd.Timedelta(hours=1),
                }
            )
    cols = ["ref_time", "kind", "H", "L", "C", "R", "activate"]
    if not rows:
        # An hour can legitimately yield nothing -- 17:00 NY is the CME halt, so
        # its handful of stub candles are all zero-range and filtered out.
        return pd.DataFrame(columns=cols + ["ref_id"])
    refs = pd.DataFrame(rows).sort_values("ref_time").reset_index(drop=True)
    refs["ref_id"] = refs.index
    return refs


def build_zones(refs: pd.DataFrame, ladder=DEFAULT_LADDER) -> pd.DataFrame:
    """Explode reference candles into the persistent zone map.

    Upside level k sits at H + kR, downside at L - kR. Both sides of every
    candle stay on the map simultaneously -- that is what makes it a network
    rather than a single daily setup.
    """
    frames = []
    for side, sign, anchor in (("up", 1.0, "H"), ("down", -1.0, "L")):
        for k in ladder:
            f = refs[["ref_id", "ref_time", "kind", "H", "L", "R", "activate"]].copy()
            f["side"] = side
            f["k"] = k
            f["price"] = f[anchor] + sign * k * f["R"]
            frames.append(f)
    z = pd.concat(frames, ignore_index=True)
    z["zone_id"] = np.arange(len(z))
    return z.sort_values(["ref_time", "side", "k"]).reset_index(drop=True)


def resolve_first_touches(
    zones: pd.DataFrame,
    path: PathIndex,
    max_age_days: float = 10.0,
) -> pd.DataFrame:
    """First touch time/age for every zone, within ``max_age_days`` of activation.

    Grouped by activation bar so each reference candle's running extremes are
    built once and reused across its whole ladder.
    """
    horizon = pd.Timedelta(days=max_age_days)
    out_idx = np.full(len(zones), -1, dtype=np.int64)

    zones = zones.reset_index(drop=True)
    for activate, grp in zones.groupby("activate", sort=True):
        start = path.idx_at_or_after(activate)
        end = path.idx_at_or_after(activate + horizon)
        if start >= end:
            continue
        for pos, k_price, side in zip(grp.index.to_numpy(), grp["price"].to_numpy(float), grp["side"].to_numpy()):
            out_idx[pos] = path.first_touch(start, end, k_price, up=(side == "up"))

    res = zones.copy()
    res["touch_idx"] = out_idx
    touched = out_idx >= 0
    res["touched"] = touched
    tt = np.full(len(res), np.datetime64("NaT"), dtype="datetime64[ns]")
    tt[touched] = path.ts[out_idx[touched]]
    res["touch_time"] = pd.to_datetime(tt).tz_localize("UTC").tz_convert("America/New_York")
    res["age_hours_at_touch"] = (
        (res["touch_time"] - res["activate"]).dt.total_seconds() / 3600.0
    )
    return res


def active_zones_at(zones: pd.DataFrame, when: pd.Timestamp, max_age_days: float = 10.0) -> pd.DataFrame:
    """The zone map as it stood at ``when`` -- activated, not yet expired.

    This is the point-in-time view the strategy is allowed to see.
    """
    lo = when - pd.Timedelta(days=max_age_days)
    m = (zones["activate"] <= when) & (zones["activate"] > lo)
    out = zones[m].copy()
    out["age_hours"] = (when - out["activate"]).dt.total_seconds() / 3600.0
    return out
