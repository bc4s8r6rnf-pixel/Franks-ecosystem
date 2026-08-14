"""Bar loading and New-York-time normalisation.

Everything downstream assumes a single canonical frame: OHLC bars indexed by a
tz-aware DatetimeIndex in America/New_York, strictly increasing, no duplicates.
Reference candles (9PM / 9AM) are cut from an hourly resample of that frame, so
DST is handled by the tz database rather than by a fixed offset.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

NY = "America/New_York"

_COLUMN_ALIASES = {
    "open": {"open", "o", "openprice"},
    "high": {"high", "h", "highprice"},
    "low": {"low", "l", "lowprice"},
    "close": {"close", "c", "closeprice", "last"},
    "volume": {"volume", "vol", "v", "tickvolume"},
}

_TIME_ALIASES = {
    "timestamp", "time", "datetime", "date", "date_time", "gmt_time", "opentime",
}


@dataclass
class BarSet:
    """Canonical bar frame plus the metadata the rest of the engine needs."""

    bars: pd.DataFrame          # index tz-aware NY; columns open/high/low/close[/volume]
    timeframe: pd.Timedelta     # inferred median bar spacing
    symbol: str = "NQ"

    @property
    def minutes(self) -> float:
        return self.timeframe.total_seconds() / 60.0

    def hourly(self) -> pd.DataFrame:
        """Hourly bars aligned to NY wall-clock hours (the reference-candle grid)."""
        agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
        if "volume" in self.bars.columns:
            agg["volume"] = "sum"
        h = self.bars.resample("1h", label="left", closed="left").agg(agg)
        return h.dropna(subset=["open", "high", "low", "close"])

    def describe(self) -> str:
        b = self.bars
        return (
            f"{self.symbol}: {len(b):,} bars @ {self.minutes:g}m  "
            f"{b.index[0]:%Y-%m-%d %H:%M} -> {b.index[-1]:%Y-%m-%d %H:%M} (NY)"
        )


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    lowered = {str(c).strip().lower().replace(" ", "_"): c for c in df.columns}
    out = {}
    for canon, aliases in _COLUMN_ALIASES.items():
        for low, orig in lowered.items():
            if low in aliases:
                out[canon] = df[orig]
                break
    missing = {"open", "high", "low", "close"} - out.keys()
    if missing:
        raise ValueError(
            f"missing required column(s) {sorted(missing)}; saw {list(df.columns)}"
        )
    return pd.DataFrame(out)


def _find_time_column(df: pd.DataFrame) -> str | None:
    for c in df.columns:
        if str(c).strip().lower().replace(" ", "_") in _TIME_ALIASES:
            return c
    return None


def load_csv(
    path: str,
    source_tz: str = "UTC",
    symbol: str = "NQ",
    date_col: str | None = None,
    time_col: str | None = None,
    sep: str | None = None,
) -> BarSet:
    """Load an OHLC CSV and convert it to New York time.

    ``source_tz`` is the timezone the file's timestamps are *written in*. Get this
    wrong and every reference candle is off by hours, so it is required rather
    than guessed. Files that split date and time across two columns are handled
    via ``date_col``/``time_col``.
    """
    # MT5/TradingView exports are variously comma-, tab- or semicolon-delimited;
    # sniff unless the caller pins it.
    raw = pd.read_csv(path, sep=sep, engine="python" if sep is None else "c")

    if date_col is not None:
        ts_src = raw[date_col].astype(str)
        if time_col is not None:
            ts_src = ts_src + " " + raw[time_col].astype(str)
        ts = pd.to_datetime(ts_src, errors="coerce", format="mixed")
    else:
        tcol = _find_time_column(raw)
        if tcol is None:
            raise ValueError(
                f"no timestamp column found in {list(raw.columns)}; "
                "pass date_col= (and time_col= if split across two columns)"
            )
        ts = pd.to_datetime(raw[tcol], errors="coerce", format="mixed")

    ohlc = _normalise_columns(raw)
    ohlc.index = pd.DatetimeIndex(ts)

    bad = ohlc.index.isna()
    if bad.any():
        ohlc = ohlc[~bad]

    if ohlc.index.tz is None:
        # Ambiguous/nonexistent wall-clock times only arise if the source is
        # already a DST-observing zone; NaT them rather than silently shifting.
        ohlc.index = ohlc.index.tz_localize(
            source_tz, ambiguous="NaT", nonexistent="NaT"
        )
        ohlc = ohlc[~ohlc.index.isna()]
    ohlc.index = ohlc.index.tz_convert(NY)

    return from_frame(ohlc, symbol=symbol)


def from_frame(df: pd.DataFrame, symbol: str = "NQ") -> BarSet:
    """Wrap an already-tz-aware OHLC frame, sorting and de-duplicating it."""
    df = df.copy()
    if df.index.tz is None:
        raise ValueError("frame index must be tz-aware")
    df.index = df.index.tz_convert(NY)
    df = df[~df.index.duplicated(keep="last")].sort_index()

    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])

    # A bar whose high/low doesn't bracket its open/close is corrupt; touch
    # detection reads highs and lows directly, so drop rather than repair.
    ok = (df["high"] >= df[["open", "close"]].max(axis=1) - 1e-9) & (
        df["low"] <= df[["open", "close"]].min(axis=1) + 1e-9
    ) & (df["high"] >= df["low"])
    df = df[ok]

    if len(df) < 2:
        raise ValueError("need at least 2 valid bars")

    deltas = pd.Series(df.index).diff().dropna()
    tf = deltas.median()
    return BarSet(bars=df, timeframe=tf, symbol=symbol)


def data_quality_report(bs: BarSet) -> pd.DataFrame:
    """Session-gap and coverage audit.

    Large gaps are expected (CME closes 17:00-18:00 NY daily and all weekend).
    What matters is whether the 21:00 and 09:00 NY hours are actually populated,
    because a missing reference candle silently removes a day from every
    downstream statistic.
    """
    b = bs.bars
    hourly = bs.hourly()
    rows = []
    for hour in (21, 9, 0):
        h = hourly[hourly.index.hour == hour]
        days = pd.Series(h.index.date).nunique()
        rows.append(
            {
                "ny_hour": hour,
                "hours_present": len(h),
                "distinct_days": days,
                "median_range": float((h["high"] - h["low"]).median()) if len(h) else np.nan,
            }
        )
    span_days = (b.index[-1] - b.index[0]).days
    gaps = pd.Series(b.index).diff()
    rep = pd.DataFrame(rows)
    rep.attrs["span_days"] = span_days
    rep.attrs["bars"] = len(b)
    rep.attrs["gaps_over_2h"] = int((gaps > pd.Timedelta("2h")).sum())
    rep.attrs["gaps_over_24h"] = int((gaps > pd.Timedelta("24h")).sum())
    return rep
