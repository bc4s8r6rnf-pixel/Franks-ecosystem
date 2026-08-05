from __future__ import annotations

import numpy as np
import pandas as pd

from .config import OrderFlowConfig, default_config
from .models import OrderFlowFeatures


def compute_order_flow_features(
    events: pd.DataFrame,
    tick_size: float,
    config: OrderFlowConfig | None = None,
) -> OrderFlowFeatures:
    """Derive transparent exhaustion features from normalised MBO/trade events.

    Required columns:
      timestamp, price, size, aggressor_side, event_type,
      bid_size, ask_size, best_bid, best_ask

    aggressor_side: -1 sell, +1 buy, 0 unknown
    event_type: trade/add/cancel/modify

    A production adapter must reconstruct exchange sequence correctly before
    calling this function.

    Args:
        events: normalised order-flow events, one row per event.
        tick_size: instrument tick size, used to size the reclaim threshold.
        config: order-flow thresholds. Defaults to the bundled ``config.yaml``.
    """
    cfg = config if config is not None else default_config().order_flow

    required = {
        "timestamp", "price", "size", "aggressor_side", "event_type",
        "bid_size", "ask_size", "best_bid", "best_ask",
    }
    missing = required.difference(events.columns)
    if missing:
        raise ValueError(f"Missing MBO columns: {sorted(missing)}")
    if len(events) < 100:
        raise ValueError("Insufficient order-flow events")
    if tick_size <= 0:
        raise ValueError("tick_size must be positive")

    e = events.sort_values("timestamp").copy()
    trades = e[e["event_type"].eq("trade")].copy()
    if trades.empty:
        raise ValueError("No trade events in order-flow window")
    trades = trades.reset_index(drop=True)

    sells = trades[trades["aggressor_side"].eq(-1)]
    buys = trades[trades["aggressor_side"].eq(1)]

    sell_vol = float(sells["size"].sum())
    buy_vol = float(buys["size"].sum())
    total = max(1.0, sell_vol + buy_vol)
    ofi = (buy_vol - sell_vol) / total

    # Rolling historical percentiles should be supplied in production.
    # This in-window proxy makes the scaffold executable.
    trade_sizes = trades["size"].astype(float)
    threshold = float(trade_sizes.quantile(cfg.climax_percentile)) if len(trade_sizes) else 0.0
    climax_vol = float(sells.loc[sells["size"] >= threshold, "size"].sum())
    climax_pct = climax_vol / max(1.0, sell_vol)

    prices = trades["price"].astype(float)
    sizes = trades["size"].astype(float)
    low = float(prices.min())
    last_price = float(prices.iloc[-1])

    # --- Anchored micro-VWAP -------------------------------------------------
    # The reclaim reference must be anchored at the exhaustion low, not computed
    # across the whole feed. A whole-window VWAP sits far above price in any
    # sustained sell-off, so a genuine reclaim off the low can never clear it and
    # the entry trigger never fires. Anchoring at the low measures the only thing
    # the trigger cares about: whether buyers have taken control of the auction
    # *since* the extreme printed.
    anchor_idx = int(prices.idxmin())
    anchored = trades.iloc[anchor_idx:]
    anchored_notional = float((anchored["price"] * anchored["size"]).sum())
    anchored_volume = float(anchored["size"].sum())
    micro_vwap = (
        anchored_notional / anchored_volume if anchored_volume > 0 else float(prices.iloc[-1])
    )

    first = trades.iloc[: max(10, len(trades) // 3)]
    last = trades.iloc[-max(10, len(trades) // 3):]
    first_sell = first[first["aggressor_side"].eq(-1)]
    last_sell = last[last["aggressor_side"].eq(-1)]

    def impact_per_unit(frame: pd.DataFrame) -> float:
        if len(frame) < 2:
            return 0.0
        price_impact = abs(float(frame["price"].iloc[-1] - frame["price"].iloc[0]))
        volume = float(frame["size"].sum())
        return price_impact / max(1.0, volume)

    initial_impact = impact_per_unit(first_sell)
    final_impact = impact_per_unit(last_sell)
    impact_decay = 1.0 - (final_impact / initial_impact) if initial_impact > 0 else 0.0

    # Approximate replenishment: bid size after sell trades relative to median.
    bid_after_sells = sells["bid_size"].astype(float)
    base_bid = float(e["bid_size"].median())
    replenishment = float(bid_after_sells.tail(20).mean() / max(1.0, base_bid))

    recent = trades.tail(max(20, len(trades) // 5))
    recent_low = float(recent["price"].min())
    failed_auction = recent_low <= low and last_price > recent_low

    reclaim_price = _confirmed_reclaim(
        trades=trades,
        anchor_idx=anchor_idx,
        micro_vwap=micro_vwap,
        tick_size=tick_size,
        cfg=cfg,
    )

    return OrderFlowFeatures(
        timestamp=pd.to_datetime(e["timestamp"].iloc[-1]).to_pydatetime(),
        aggressive_sell_volume=sell_vol,
        aggressive_buy_volume=buy_vol,
        sell_climax_percentile=float(min(1.0, climax_pct)),
        order_flow_imbalance=float(ofi),
        bid_replenishment_ratio=replenishment,
        price_impact_per_sell_unit=float(final_impact),
        impact_decay=float(impact_decay),
        failed_auction=bool(failed_auction),
        reclaim_price=reclaim_price,
        structural_low=low,
        micro_vwap=float(micro_vwap),
        data_quality_ok=bool(np.isfinite(micro_vwap) and np.isfinite(low)),
    )


def _confirmed_reclaim(
    trades: pd.DataFrame,
    anchor_idx: int,
    micro_vwap: float,
    tick_size: float,
    cfg: OrderFlowConfig,
) -> float | None:
    """Return the entry price if the anchored micro-VWAP reclaim is confirmed.

    The handoff requires "confirmation persistence to avoid a one-tick false
    reclaim": price must clear the anchored VWAP by ``min_reclaim_ticks`` and
    then *hold* above it for ``confirmation_window_seconds``. A single print
    poking through is not a trigger.

    Returns the price at which confirmation completed, or ``None``.
    """
    trigger_level = micro_vwap + cfg.min_reclaim_ticks * tick_size
    window = trades.iloc[anchor_idx:]
    if window.empty:
        return None

    timestamps = pd.to_datetime(window["timestamp"])
    prices = window["price"].astype(float)
    above = prices >= trigger_level
    if not above.any():
        return None

    hold = pd.Timedelta(seconds=cfg.confirmation_window_seconds)
    positions = np.flatnonzero(above.to_numpy())

    for start in positions:
        breach_time = timestamps.iloc[start]
        # Everything from the breach to the end of the confirmation window must
        # stay above the trigger; one print back below resets the count and we
        # look for the next candidate breach.
        in_window = timestamps.iloc[start:] <= breach_time + hold
        segment = above.iloc[start:][in_window.to_numpy()]
        if not segment.all():
            continue
        # Only confirm when the window actually elapsed within the data; a
        # reclaim still in progress at the end of the feed is not yet a trigger.
        if timestamps.iloc[-1] - breach_time < hold:
            return None
        confirm_pos = int(np.flatnonzero((timestamps >= breach_time + hold).to_numpy())[0])
        return float(prices.iloc[confirm_pos])

    return None
