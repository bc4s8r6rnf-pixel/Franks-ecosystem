from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd

from bnf_scanner import (
    AssetClass, Instrument, NewsItem, assess_catalyst,
    compute_daily_features, compute_order_flow_features,
    evaluate_long_setup,
)


def synthetic_daily() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    dates = pd.date_range(end=pd.Timestamp.now(tz="UTC"), periods=90, freq="B")
    close = 100 + np.cumsum(rng.normal(0, 0.6, len(dates)))
    close[-1] = close[-2] * 0.84  # synthetic dislocation
    high = close + rng.uniform(0.3, 1.2, len(close))
    low = close - rng.uniform(0.3, 1.2, len(close))
    open_ = close + rng.normal(0, 0.3, len(close))
    volume = rng.integers(1_000_000, 3_000_000, len(close))
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


def synthetic_mbo() -> pd.DataFrame:
    rng = np.random.default_rng(11)
    n = 2000
    now = pd.Timestamp.now(tz="UTC")
    timestamps = [now - pd.Timedelta(seconds=n-i) for i in range(n)]
    price = 85 + np.cumsum(rng.normal(-0.0007, 0.01, n))
    price[-250:] += np.linspace(-0.6, 0.35, 250)  # flush and reclaim
    side = rng.choice([-1, 1], size=n, p=[0.62, 0.38])
    side[-150:] = rng.choice([-1, 1], size=150, p=[0.45, 0.55])
    size = rng.integers(1, 40, n)
    size[1200:1500] *= 5
    return pd.DataFrame({
        "timestamp": timestamps,
        "price": price,
        "size": size,
        "aggressor_side": side,
        "event_type": "trade",
        "bid_size": rng.integers(50, 250, n),
        "ask_size": rng.integers(50, 250, n),
        "best_bid": price - 0.01,
        "best_ask": price + 0.01,
    })


instrument = Instrument(
    symbol="DEMO",
    asset_class=AssetClass.EQUITIES,
    order_flow_symbol="DEMO.NATIVE",
    tick_size=0.01,
    sector="Industrials",
)

daily = compute_daily_features(
    "DEMO", synthetic_daily(), cross_sectional_percentile=0.01, spread_bps=5
)

news = [
    NewsItem(
        timestamp=datetime.now(timezone.utc) - timedelta(hours=3),
        headline="Broad market panic triggers technical selloff",
        source="SourceA",
        relevance=0.95,
        novelty=0.9,
    ),
    NewsItem(
        timestamp=datetime.now(timezone.utc) - timedelta(hours=2),
        headline="Forced liquidation weighs on sector; no company announcement",
        source="SourceB",
        relevance=0.9,
        novelty=0.8,
    ),
]
catalyst = assess_catalyst(instrument, news)
flow = compute_order_flow_features(synthetic_mbo())
setup = evaluate_long_setup(instrument, daily, catalyst, flow)

print("State:", setup.state.value)
print("Score:", setup.score)
print("Reasons:", *setup.reasons, sep="\n- ")
print("Vetoes:", setup.vetoes)
print("Risk:", setup.risk)
