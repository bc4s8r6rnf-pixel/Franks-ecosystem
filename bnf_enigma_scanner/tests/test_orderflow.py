"""Tests for the anchored micro-VWAP reclaim trigger.

The bug these pin down: micro-VWAP was computed across the entire event feed, so
in any sustained sell-off the reference sat far above price and a genuine reclaim
off the low could never clear it. The trigger never fired and every setup died on
NO_ENTRY_RECLAIM.
"""

import numpy as np
import pandas as pd
import pytest

from bnf_scanner.config import default_config
from bnf_scanner.orderflow import compute_order_flow_features

TICK = 0.01


def _feed(prices: list[float], seconds: list[int] | None = None) -> pd.DataFrame:
    n = len(prices)
    if seconds is None:
        seconds = list(range(n))
    base = pd.Timestamp("2026-01-05 14:30:00", tz="UTC")
    price = np.asarray(prices, dtype=float)
    return pd.DataFrame({
        "timestamp": [base + pd.Timedelta(seconds=int(s)) for s in seconds],
        "price": price,
        "size": np.full(n, 10.0),
        "aggressor_side": np.where(np.diff(price, prepend=price[0]) >= 0, 1, -1),
        "event_type": "trade",
        "bid_size": np.full(n, 100.0),
        "ask_size": np.full(n, 100.0),
        "best_bid": price - TICK,
        "best_ask": price + TICK,
    })


def _selloff_then_reclaim() -> list[float]:
    # 600s of steady decline, then 900s holding well above the flush low.
    decline = list(np.linspace(100.0, 90.0, 600))
    recovery = list(np.linspace(90.0, 95.0, 900))
    return decline + recovery


def test_reclaim_fires_after_a_sustained_selloff():
    """The whole-feed VWAP here is ~94; the anchored VWAP is ~92.5.

    Under the old whole-feed anchoring the last price (95) would have to clear a
    reference dragged up by 600 seconds of pre-flush prices. Anchoring at the low
    measures only what happened after the extreme, which is the question the
    trigger is actually asking.
    """
    flow = compute_order_flow_features(_feed(_selloff_then_reclaim()), tick_size=TICK)
    assert flow.structural_low == pytest.approx(90.0, abs=0.05)
    assert flow.reclaim_price is not None
    # Anchored VWAP must sit inside the recovery leg, not up in the pre-flush range.
    assert 90.0 < flow.micro_vwap < 95.0


def test_one_tick_poke_above_vwap_is_not_a_reclaim():
    """A single print through the level must not arm an entry.

    The handoff calls for "confirmation persistence to avoid a one-tick false
    reclaim"; without it the trigger fires on noise.
    """
    prices = list(np.linspace(100.0, 90.0, 600))
    prices += list(np.linspace(90.0, 90.2, 400))  # limps along below the anchored VWAP
    prices[-200] = 99.0                            # single spike far above
    flow = compute_order_flow_features(_feed(prices), tick_size=TICK)
    assert flow.reclaim_price is None


def test_reclaim_still_in_progress_at_end_of_feed_does_not_confirm():
    """A reclaim that has not yet held for the confirmation window is not a trigger."""
    hold = default_config().order_flow.confirmation_window_seconds
    prices = list(np.linspace(100.0, 90.0, 600))
    prices += list(np.linspace(90.0, 95.0, hold - 100))  # ends before the hold elapses
    flow = compute_order_flow_features(_feed(prices), tick_size=TICK)
    assert flow.reclaim_price is None


def test_price_that_never_recovers_has_no_reclaim():
    flow = compute_order_flow_features(
        _feed(list(np.linspace(100.0, 85.0, 1200))), tick_size=TICK
    )
    assert flow.reclaim_price is None
    assert flow.structural_low == pytest.approx(85.0, abs=0.05)


def test_tick_size_must_be_positive():
    with pytest.raises(ValueError, match="tick_size"):
        compute_order_flow_features(_feed(_selloff_then_reclaim()), tick_size=0.0)


def test_short_feed_is_rejected():
    with pytest.raises(ValueError, match="Insufficient"):
        compute_order_flow_features(_feed([100.0] * 50), tick_size=TICK)
