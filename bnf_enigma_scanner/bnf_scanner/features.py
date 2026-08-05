from __future__ import annotations
import numpy as np
import pandas as pd
from .models import DailyFeatures


def _robust_z(series: pd.Series, lookback: int = 252) -> float:
    x = series.dropna().tail(lookback)
    if len(x) < 30:
        return float("nan")
    median = float(x.median())
    mad = float((x - median).abs().median())
    if mad <= 1e-12:
        return 0.0
    return 0.67448975 * (float(x.iloc[-1]) - median) / mad


def compute_daily_features(
    symbol: str,
    bars: pd.DataFrame,
    cross_sectional_percentile: float,
    spread_bps: float,
    contract_multiplier: float = 1.0,
) -> DailyFeatures:
    """Compute the primary BNF daily candidate features.

    Required columns: open, high, low, close, volume.
    Index must be DatetimeIndex in chronological order.

    Args:
        contract_multiplier: notional per unit of quoted volume. 1.0 for cash
            equities; the contract size for futures. Traded notional is
            meaningless for FX and index futures without it.
    """
    required = {"open", "high", "low", "close", "volume"}
    missing = required.difference(bars.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")
    if len(bars) < 60:
        raise ValueError("At least 60 daily bars are required")

    b = bars.sort_index().copy()
    close = b["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [(b["high"] - b["low"]).abs(),
         (b["high"] - prev_close).abs(),
         (b["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)

    sma25 = close.rolling(25).mean()
    atr14 = tr.rolling(14).mean()
    returns = close.pct_change()

    latest_close = float(close.iloc[-1])
    latest_sma = float(sma25.iloc[-1])
    latest_atr = float(atr14.iloc[-1])
    if not np.isfinite(latest_sma) or latest_sma <= 0:
        raise ValueError("Invalid SMA(25)")
    if not np.isfinite(latest_atr) or latest_atr <= 0:
        raise ValueError("Invalid ATR(14)")

    divergence_pct = 100.0 * (latest_close / latest_sma - 1.0)
    atr_displacement = (latest_close - latest_sma) / latest_atr
    if contract_multiplier <= 0:
        raise ValueError("contract_multiplier must be positive")
    dollar_volume = float(latest_close * b["volume"].tail(20).mean() * contract_multiplier)

    return DailyFeatures(
        symbol=symbol,
        timestamp=b.index[-1].to_pydatetime(),
        close=latest_close,
        sma25=latest_sma,
        divergence_pct=divergence_pct,
        robust_return_z=_robust_z(returns),
        atr14=latest_atr,
        atr_displacement=atr_displacement,
        cross_sectional_percentile=float(cross_sectional_percentile),
        dollar_volume=dollar_volume,
        spread_bps=float(spread_bps),
    )
