"""Daily bar loading for research and backtesting.

The scaffold deliberately does not bundle a market-data vendor client. Point-in-
time, survivorship-bias-free data is the single hardest requirement in
DEVELOPER_HANDOFF.md and it is a licensing decision, not a code decision. What
this module provides is the boundary: drop correctly-formed CSVs into a
directory tree and the backtester runs against them.

Expected layout — one directory per asset class, one CSV per instrument::

    data/
      equities/AAPL.csv
      indices/ES.csv
      metals/GC.csv
      fx/6E.csv

Each CSV needs a header with at least::

    date,open,high,low,close,volume

`date` must parse to a date, rows must be unique per date, and prices must be
adjusted for corporate actions *as of the point in time being simulated*. The
loader enforces shape and ordering; it cannot detect a survivorship-biased or
back-adjusted file, so that remains the data provider's guarantee.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .models import AssetClass, Instrument

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")

# Tick sizes are instrument properties, not data properties. These defaults are
# only used when a universe file does not specify one.
DEFAULT_TICK_SIZE = {
    AssetClass.EQUITIES: 0.01,
    AssetClass.INDICES: 0.25,
    AssetClass.METALS: 0.10,
    AssetClass.FX: 0.00005,
}

# Notional per unit of quoted volume. Cash equities quote shares, so 1.0.
# Futures quote contracts: these are representative CME sizes (ES=50, GC=100,
# 6E=125_000) and MUST be replaced per instrument from reference data — a
# mis-set multiplier moves an instrument across the liquidity gate.
DEFAULT_CONTRACT_MULTIPLIER = {
    AssetClass.EQUITIES: 1.0,
    AssetClass.INDICES: 50.0,
    AssetClass.METALS: 100.0,
    AssetClass.FX: 125_000.0,
}


@dataclass(frozen=True)
class MarketData:
    """A single instrument and its daily history."""

    instrument: Instrument
    bars: pd.DataFrame

    @property
    def symbol(self) -> str:
        return self.instrument.symbol


def load_daily_csv(path: str | Path) -> pd.DataFrame:
    """Load and validate one daily OHLCV CSV."""
    path = Path(path)
    frame = pd.read_csv(path)
    frame.columns = [str(c).strip().lower() for c in frame.columns]

    if "date" not in frame.columns:
        raise ValueError(f"{path.name}: missing 'date' column")
    if missing := [c for c in REQUIRED_COLUMNS if c not in frame.columns]:
        raise ValueError(f"{path.name}: missing columns {missing}")

    frame["date"] = pd.to_datetime(frame["date"], utc=False, errors="raise")
    if frame["date"].duplicated().any():
        dupes = frame.loc[frame["date"].duplicated(), "date"].dt.date.unique()[:5]
        raise ValueError(f"{path.name}: duplicate dates, e.g. {list(dupes)}")

    frame = frame.sort_values("date").set_index("date")
    for column in REQUIRED_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    if frame[list(REQUIRED_COLUMNS)].isna().any().any():
        bad = frame[frame[list(REQUIRED_COLUMNS)].isna().any(axis=1)].index[:5]
        raise ValueError(f"{path.name}: non-numeric or missing values on {[str(d.date()) for d in bad]}")

    # A high below the low means the file is broken; silently backtesting it
    # would produce barrier touches that never happened.
    if (frame["high"] < frame["low"]).any():
        raise ValueError(f"{path.name}: rows where high < low")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError(f"{path.name}: non-positive prices")

    return frame[list(REQUIRED_COLUMNS)]


def load_universe(data_dir: str | Path) -> list[MarketData]:
    """Load every instrument under ``data_dir``, one subdirectory per asset class."""
    root = Path(data_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"data directory not found: {root}")

    universe: list[MarketData] = []
    for asset_class in AssetClass:
        class_dir = root / asset_class.value
        if not class_dir.is_dir():
            continue
        for csv_path in sorted(class_dir.glob("*.csv")):
            symbol = csv_path.stem.upper()
            bars = load_daily_csv(csv_path)
            instrument = Instrument(
                symbol=symbol,
                asset_class=asset_class,
                order_flow_symbol=symbol,
                tick_size=DEFAULT_TICK_SIZE[asset_class],
                contract_multiplier=DEFAULT_CONTRACT_MULTIPLIER[asset_class],
            )
            universe.append(MarketData(instrument=instrument, bars=bars))

    if not universe:
        expected = ", ".join(a.value for a in AssetClass)
        raise ValueError(
            f"no CSVs found under {root}. Expected subdirectories named: {expected}"
        )
    return universe
