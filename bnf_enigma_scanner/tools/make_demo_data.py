"""Generate SYNTHETIC daily bars so the backtest CLI can be exercised end to end.

THIS IS NOT MARKET DATA. It is random walks with dislocations injected into them.
Any P/L produced from it measures whether the backtester's plumbing works, not
whether the strategy works. Numbers from this generator must never be quoted as
a result.

Usage:
    python tools/make_demo_data.py --out demo_data
    python -m bnf_scanner.backtest --data-dir demo_data --year 2026
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

# symbol -> (asset class dir, starting price, annualised vol, shock frequency)
DEMO_UNIVERSE = {
    "equities": [("SYNTH_A", 100.0, 0.32), ("SYNTH_B", 45.0, 0.40), ("SYNTH_C", 210.0, 0.26)],
    "indices": [("SYNTH_IDX1", 4200.0, 0.16), ("SYNTH_IDX2", 15000.0, 0.20)],
    "metals": [("SYNTH_GOLD", 1900.0, 0.14), ("SYNTH_SILVER", 23.0, 0.26)],
    "fx": [("SYNTH_EUR", 1.09, 0.08), ("SYNTH_GBP", 1.27, 0.09)],
}


def synthetic_series(
    start_price: float, annual_vol: float, days: int, seed: int
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    daily_vol = annual_vol / np.sqrt(252)

    returns = rng.normal(0.0002, daily_vol, days)
    # Inject occasional sharp dislocations so the candidate gate has something
    # to fire on; roughly a handful per year.
    shock_days = rng.choice(days, size=max(1, days // 90), replace=False)
    returns[shock_days] -= rng.uniform(3.0, 7.0, len(shock_days)) * daily_vol

    close = start_price * np.exp(np.cumsum(returns))
    intraday = np.abs(rng.normal(0, daily_vol * 0.7, days))
    high = close * (1 + intraday)
    low = close * (1 - intraday)
    open_ = np.concatenate([[close[0]], close[:-1]]) * (1 + rng.normal(0, daily_vol * 0.3, days))
    open_ = np.clip(open_, low, high)
    volume = rng.integers(2_000_000, 9_000_000, days).astype(float)
    volume[shock_days] *= 4  # capitulation volume

    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    return pd.DataFrame(
        {"date": dates, "open": open_, "high": high, "low": low, "close": close, "volume": volume}
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="demo_data", help="output directory")
    parser.add_argument("--days", type=int, default=252 * 12, help="trading days of history")
    args = parser.parse_args(argv)

    root = Path(args.out)
    seed = 0
    for asset_class, members in DEMO_UNIVERSE.items():
        target = root / asset_class
        target.mkdir(parents=True, exist_ok=True)
        for symbol, price, vol in members:
            seed += 1
            frame = synthetic_series(price, vol, args.days, seed)
            frame.to_csv(target / f"{symbol}.csv", index=False)

    print(f"Wrote SYNTHETIC demo data to {root}/ — mechanism check only, not market data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
