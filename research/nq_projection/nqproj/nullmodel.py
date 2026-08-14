"""Synthetic price generators used as null models.

Purpose: establish what every headline statistic in this study looks like when
there is provably no phenomenon. A projection-zone result is only evidence if
it beats a driftless random walk that shares the instrument's volatility and
session calendar -- because levels defined as multiples of a recent range will
generate a *lot* of apparently meaningful touches on pure noise.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .data import NY, BarSet, from_frame

# CME equity-index futures: Sun 18:00 -> Fri 17:00 NY, 60-minute daily halt.
_HALT_HOUR = 17


def cme_minute_index(start: str, days: int) -> pd.DatetimeIndex:
    """Minute index following the CME equity-index session calendar (NY time)."""
    idx = pd.date_range(start=pd.Timestamp(start, tz=NY), periods=days * 24 * 60, freq="1min")
    dow = idx.dayofweek                     # Mon=0 .. Sun=6
    hour = idx.hour

    open_mask = np.ones(len(idx), dtype=bool)
    open_mask &= ~((dow == 5))                                  # Saturday closed
    open_mask &= ~((dow == 6) & (hour < 18))                    # Sunday pre-18:00 closed
    open_mask &= ~((dow == 4) & (hour >= _HALT_HOUR))           # Friday post-17:00 closed
    open_mask &= ~((dow <= 3) & (hour == _HALT_HOUR))           # daily 17:00 halt
    return idx[open_mask]


def _seasonal_vol(idx: pd.DatetimeIndex, strength: float) -> np.ndarray:
    """U-shaped intraday volatility multiplier.

    Included because a time-of-day 'discovery' can be nothing more than the fact
    that the 09:30-10:00 window is simply more volatile than 03:00.
    """
    if strength <= 0:
        return np.ones(len(idx))
    h = (idx.hour + idx.minute / 60.0).to_numpy(dtype=float)
    # peaks near the 09:30 cash open and the 21:00-22:00 evening reference hour
    peak_open = np.exp(-0.5 * ((h - 9.75) / 1.1) ** 2)
    peak_eve = np.exp(-0.5 * ((h - 21.5) / 1.6) ** 2)
    shape = 1.0 + strength * (1.6 * peak_open + 0.5 * peak_eve)
    return shape / shape.mean()


def simulate(
    start: str = "2018-01-01",
    days: int = 1100,
    s0: float = 12000.0,
    sigma_annual: float = 0.22,
    substeps: int = 10,
    seed: int | None = None,
    df_t: float | None = None,
    vol_seasonality: float = 0.0,
    drift_annual: float = 0.0,
    symbol: str = "NULL",
) -> BarSet:
    """Driftless (by default) random-walk minute bars on a CME calendar.

    Sub-minute steps are simulated and aggregated so each bar has an honest
    high/low -- touch detection reads wicks, so bars built from closes alone
    would understate touch rates and bias the null in our favour.
    """
    rng = np.random.default_rng(seed)
    idx = cme_minute_index(start, days)
    n = len(idx)

    minutes_per_year = 252 * 23 * 60
    sig_min = sigma_annual / np.sqrt(minutes_per_year)
    mu_min = drift_annual / minutes_per_year

    seas = _seasonal_vol(idx, vol_seasonality)
    sig_step = (sig_min * np.sqrt(seas) / np.sqrt(substeps)).astype(np.float64)

    if df_t is None:
        z = rng.standard_normal((n, substeps))
    else:
        # unit-variance Student-t: fat tails without inflating realised vol
        z = rng.standard_t(df_t, size=(n, substeps)) / np.sqrt(df_t / (df_t - 2.0))

    steps = z * sig_step[:, None] + (mu_min / substeps)
    log_path = np.cumsum(steps.reshape(-1))
    prices = s0 * np.exp(log_path)
    p = prices.reshape(n, substeps)

    first = np.empty(n)
    first[0] = s0
    first[1:] = p[:-1, -1]

    frame = pd.DataFrame(
        {
            "open": first,
            "high": np.maximum(p.max(axis=1), first),
            "low": np.minimum(p.min(axis=1), first),
            "close": p[:, -1],
        },
        index=idx,
    )
    return from_frame(frame, symbol=symbol)


def bootstrap_from_real(bs: BarSet, block_hours: float = 24.0, seed: int | None = None,
                        symbol: str = "BOOT") -> BarSet:
    """Stationary block bootstrap of real bars.

    Preserves intraday volatility shape and fat tails while destroying any
    multi-day geometric relationship -- the sharpest null available once real
    data exists, because it keeps everything except the thing under test.
    """
    rng = np.random.default_rng(seed)
    b = bs.bars
    ret = np.log(b["close"]).diff().fillna(0.0).to_numpy()
    hl = (b["high"] / b["close"]).to_numpy(), (b["low"] / b["close"]).to_numpy()

    bars_per_block = max(1, int(block_hours * 60 / bs.minutes))
    n = len(b)
    n_blocks = int(np.ceil(n / bars_per_block))
    starts = rng.integers(0, max(1, n - bars_per_block), size=n_blocks)
    order = np.concatenate([np.arange(s, s + bars_per_block) for s in starts])[:n] % n

    close = b["close"].iloc[0] * np.exp(np.cumsum(ret[order]))
    frame = pd.DataFrame(
        {
            "open": np.concatenate([[close[0]], close[:-1]]),
            "high": np.maximum(close * hl[0][order], close),
            "low": np.minimum(close * hl[1][order], close),
            "close": close,
        },
        index=b.index,
    )
    frame["high"] = frame[["high", "open"]].max(axis=1)
    frame["low"] = frame[["low", "open"]].min(axis=1)
    return from_frame(frame, symbol=symbol)
