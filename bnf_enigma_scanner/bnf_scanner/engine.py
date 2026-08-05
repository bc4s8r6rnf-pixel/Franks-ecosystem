from __future__ import annotations
from dataclasses import asdict
from .models import (
    AssetClass, CatalystClass, DailyFeatures, Instrument, OrderFlowFeatures,
    RiskPlan, Setup, SetupState, CatalystAssessment,
)


DEFAULT_DIVERGENCE = {
    AssetClass.EQUITIES: -12.0,
    AssetClass.INDICES: -5.0,
    AssetClass.METALS: -6.0,
    AssetClass.FX: -3.0,
}


def make_risk_plan(
    daily: DailyFeatures,
    flow: OrderFlowFeatures,
    tick_size: float,
    volatility_buffer_atr_fraction: float = 0.15,
    min_tick_buffer: int = 3,
    t1_fraction: float = 0.40,
    t2_fraction: float = 0.70,
) -> RiskPlan | None:
    if flow.reclaim_price is None:
        return None
    entry = float(flow.reclaim_price)
    buffer_ = max(
        min_tick_buffer * tick_size,
        volatility_buffer_atr_fraction * daily.atr14,
    )
    stop = flow.structural_low - buffer_
    if entry <= stop:
        return None
    distance = daily.sma25 - entry
    if distance <= 0:
        return None

    t1 = entry + t1_fraction * distance
    t2 = entry + t2_fraction * distance
    risk = entry - stop
    return RiskPlan(
        entry=entry,
        stop=stop,
        target_1=t1,
        target_2=t2,
        mean_target=daily.sma25,
        risk_per_unit=risk,
        rr_target_1=(t1-entry)/risk,
        rr_target_2=(t2-entry)/risk,
        rr_mean=(daily.sma25-entry)/risk,
    )


def evaluate_long_setup(
    instrument: Instrument,
    daily: DailyFeatures,
    catalyst: CatalystAssessment,
    flow: OrderFlowFeatures | None,
    min_score: float = 80.0,
    min_dollar_volume: float = 50_000_000,
    max_spread_bps: float = 25.0,
    min_rr_primary: float = 1.8,
    min_rr_mean: float = 3.0,
) -> Setup:
    reasons: list[str] = []
    vetoes: list[str] = []
    score = 0.0

    threshold = DEFAULT_DIVERGENCE[instrument.asset_class]

    # Candidate generation: daily BNF core.
    if daily.divergence_pct <= threshold:
        score += min(20.0, 10.0 + abs(daily.divergence_pct - threshold))
        reasons.append(f"25-day divergence {daily.divergence_pct:.2f}%")
    else:
        vetoes.append("NOT_EXTREME_ENOUGH_VS_SMA25")

    if daily.robust_return_z <= -2.5:
        score += min(10.0, 5.0 + abs(daily.robust_return_z))
        reasons.append(f"Robust return z-score {daily.robust_return_z:.2f}")

    if daily.atr_displacement <= -2.0:
        score += min(10.0, 5.0 + abs(daily.atr_displacement))
        reasons.append(f"{daily.atr_displacement:.2f} ATR below SMA25")

    if daily.cross_sectional_percentile <= 0.05:
        score += 10.0
        reasons.append("Bottom 5% cross-sectional dislocation")

    if daily.dollar_volume < min_dollar_volume:
        vetoes.append("INSUFFICIENT_LIQUIDITY")
    if daily.spread_bps > max_spread_bps:
        vetoes.append("SPREAD_TOO_WIDE")

    # Facts before emotion.
    if catalyst.hard_veto:
        vetoes.append(catalyst.veto_reason or "CATALYST_HARD_VETO")
    elif catalyst.label in {
        CatalystClass.EMOTIONAL_TECHNICAL,
        CatalystClass.LIQUIDITY_STRESS,
    }:
        score += 15.0 * catalyst.confidence
        reasons.append(f"Catalyst classified {catalyst.label.value}")
    elif catalyst.label == CatalystClass.UNKNOWN:
        vetoes.append("CATALYST_UNRESOLVED")
    else:
        # Macro moves are not automatically invalid, but receive no catalyst points.
        reasons.append(f"Macro catalyst requires stricter confirmation: {catalyst.label.value}")

    risk = None
    if flow is None:
        vetoes.append("ORDER_FLOW_NOT_AVAILABLE")
    elif not flow.data_quality_ok:
        vetoes.append("ORDER_FLOW_DATA_QUALITY")
    else:
        if flow.sell_climax_percentile >= 0.20:
            score += 10.0
            reasons.append("Aggressive sell-volume climax")
        if flow.bid_replenishment_ratio >= 1.50:
            score += 10.0
            reasons.append("Bid replenishment / absorption")
        if flow.impact_decay >= 0.35:
            score += 5.0
            reasons.append("Seller price-impact decay")
        if flow.failed_auction:
            score += 5.0
            reasons.append("Failed auction below the extreme")
        if flow.reclaim_price is None:
            vetoes.append("NO_ENTRY_RECLAIM")
        risk = make_risk_plan(daily, flow, instrument.tick_size)
        if risk is None:
            vetoes.append("NO_VALID_RISK_PLAN")
        else:
            if risk.rr_target_1 < min_rr_primary:
                vetoes.append("PRIMARY_TARGET_RR_TOO_LOW")
            if risk.rr_mean < min_rr_mean:
                vetoes.append("MEAN_TARGET_RR_TOO_LOW")

    if vetoes:
        state = SetupState.REJECTED
    elif score >= min_score and risk is not None:
        state = SetupState.CONFIRMED
    elif flow is not None and flow.reclaim_price is not None:
        state = SetupState.ARMED
    else:
        state = SetupState.WATCH

    snapshot = {
        "daily": asdict(daily),
        "catalyst": {
            **asdict(catalyst),
            "label": catalyst.label.value,
            "probabilities": {k.value: v for k, v in catalyst.probabilities.items()},
        },
        "order_flow": asdict(flow) if flow else None,
        "risk": asdict(risk) if risk else None,
    }

    return Setup(
        instrument=instrument,
        state=state,
        score=round(score, 2),
        daily=daily,
        catalyst=catalyst,
        order_flow=flow,
        risk=risk,
        reasons=reasons,
        vetoes=vetoes,
        feature_snapshot=snapshot,
    )
