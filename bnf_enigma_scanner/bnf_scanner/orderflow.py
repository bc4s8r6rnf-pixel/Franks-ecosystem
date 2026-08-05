from __future__ import annotations
import numpy as np
import pandas as pd
from .models import OrderFlowFeatures


def compute_order_flow_features(events: pd.DataFrame) -> OrderFlowFeatures:
    """Derive transparent exhaustion features from normalised MBO/trade events.

    Required columns:
      timestamp, price, size, aggressor_side, event_type,
      bid_size, ask_size, best_bid, best_ask

    aggressor_side: -1 sell, +1 buy, 0 unknown
    event_type: trade/add/cancel/modify

    A production adapter must reconstruct exchange sequence correctly before
    calling this function.
    """
    required = {
        "timestamp", "price", "size", "aggressor_side", "event_type",
        "bid_size", "ask_size", "best_bid", "best_ask",
    }
    missing = required.difference(events.columns)
    if missing:
        raise ValueError(f"Missing MBO columns: {sorted(missing)}")
    if len(events) < 100:
        raise ValueError("Insufficient order-flow events")

    e = events.sort_values("timestamp").copy()
    trades = e[e["event_type"].eq("trade")].copy()
    sells = trades[trades["aggressor_side"].eq(-1)]
    buys = trades[trades["aggressor_side"].eq(1)]

    sell_vol = float(sells["size"].sum())
    buy_vol = float(buys["size"].sum())
    total = max(1.0, sell_vol + buy_vol)
    ofi = (buy_vol - sell_vol) / total

    # Rolling historical percentiles should be supplied in production.
    # This in-window proxy makes the scaffold executable.
    trade_sizes = trades["size"].astype(float)
    threshold = float(trade_sizes.quantile(0.95)) if len(trade_sizes) else 0.0
    climax_vol = float(sells.loc[sells["size"] >= threshold, "size"].sum())
    climax_pct = climax_vol / max(1.0, sell_vol)

    low = float(trades["price"].min())
    last_price = float(trades["price"].iloc[-1])
    micro_vwap = float(
        (trades["price"] * trades["size"]).sum() / max(1.0, trades["size"].sum())
    )

    first = trades.iloc[: max(10, len(trades)//3)]
    last = trades.iloc[-max(10, len(trades)//3):]
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
    sell_idx = sells.index
    bid_after_sells = e.loc[e.index.intersection(sell_idx), "bid_size"].astype(float)
    base_bid = float(e["bid_size"].median())
    replenishment = float(bid_after_sells.tail(20).mean() / max(1.0, base_bid))

    recent = trades.tail(max(20, len(trades)//5))
    recent_low = float(recent["price"].min())
    failed_auction = recent_low <= low and last_price > recent_low

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
        reclaim_price=micro_vwap if last_price >= micro_vwap else None,
        structural_low=low,
        micro_vwap=micro_vwap,
        data_quality_ok=bool(np.isfinite(micro_vwap)),
    )
