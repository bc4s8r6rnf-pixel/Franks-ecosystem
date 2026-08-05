from __future__ import annotations

from dataclasses import asdict

from .config import Config, default_config
from .models import (
    CatalystAssessment, CatalystClass, DailyFeatures, Instrument,
    OrderFlowFeatures, RiskPlan, Setup, SetupState,
)


def make_risk_plan(
    daily: DailyFeatures,
    flow: OrderFlowFeatures,
    tick_size: float,
    config: Config | None = None,
) -> RiskPlan | None:
    cfg = (config if config is not None else default_config()).risk

    if flow.reclaim_price is None:
        return None
    entry = float(flow.reclaim_price)
    buffer_ = max(
        cfg.min_tick_buffer * tick_size,
        cfg.volatility_buffer_atr_fraction * daily.atr14,
    )
    stop = flow.structural_low - buffer_
    if entry <= stop:
        return None
    distance = daily.sma25 - entry
    if distance <= 0:
        return None

    t1 = entry + cfg.target_1_fraction_to_mean * distance
    t2 = entry + cfg.target_2_fraction_to_mean * distance
    risk = entry - stop
    return RiskPlan(
        entry=entry,
        stop=stop,
        target_1=t1,
        target_2=t2,
        mean_target=daily.sma25,
        risk_per_unit=risk,
        rr_target_1=(t1 - entry) / risk,
        rr_target_2=(t2 - entry) / risk,
        rr_mean=(daily.sma25 - entry) / risk,
    )


def evaluate_long_setup(
    instrument: Instrument,
    daily: DailyFeatures,
    catalyst: CatalystAssessment,
    flow: OrderFlowFeatures | None,
    config: Config | None = None,
) -> Setup:
    cfg = config if config is not None else default_config()
    scan = cfg.scanner
    flow_cfg = cfg.order_flow
    weights = cfg.scoring

    reasons: list[str] = []
    vetoes: list[str] = []
    score = 0.0

    threshold = scan.candidate_min_divergence_pct[instrument.asset_class]

    # Candidate generation: daily BNF core.
    if daily.divergence_pct <= threshold:
        score += min(weights.divergence_max, 10.0 + abs(daily.divergence_pct - threshold))
        reasons.append(f"25-day divergence {daily.divergence_pct:.2f}%")
    else:
        vetoes.append("NOT_EXTREME_ENOUGH_VS_SMA25")

    if daily.robust_return_z <= scan.robust_z_max:
        score += min(weights.robust_return_max, 5.0 + abs(daily.robust_return_z))
        reasons.append(f"Robust return z-score {daily.robust_return_z:.2f}")

    if daily.atr_displacement <= -scan.atr_multiple_min:
        score += min(weights.atr_displacement_max, 5.0 + abs(daily.atr_displacement))
        reasons.append(f"{daily.atr_displacement:.2f} ATR below SMA25")

    if daily.cross_sectional_percentile <= scan.cross_sectional_percentile_max:
        score += weights.cross_sectional
        reasons.append(
            f"Bottom {scan.cross_sectional_percentile_max:.0%} cross-sectional dislocation"
        )

    if daily.dollar_volume < scan.min_dollar_volume:
        vetoes.append("INSUFFICIENT_LIQUIDITY")
    if daily.spread_bps > scan.max_spread_bps:
        vetoes.append("SPREAD_TOO_WIDE")

    # Facts before emotion.
    if catalyst.hard_veto:
        vetoes.append(catalyst.veto_reason or "CATALYST_HARD_VETO")
    elif catalyst.label in {
        CatalystClass.EMOTIONAL_TECHNICAL,
        CatalystClass.LIQUIDITY_STRESS,
    }:
        score += weights.catalyst_non_structural * catalyst.confidence
        reasons.append(f"Catalyst classified {catalyst.label.value}")
    elif catalyst.label == CatalystClass.UNKNOWN:
        vetoes.append("CATALYST_UNRESOLVED")
    else:
        # Macro moves are not automatically invalid, but receive no catalyst points.
        reasons.append(
            f"Macro catalyst requires stricter confirmation: {catalyst.label.value}"
        )

    risk = None
    if flow is None:
        vetoes.append("ORDER_FLOW_NOT_AVAILABLE")
    elif not flow.data_quality_ok:
        vetoes.append("ORDER_FLOW_DATA_QUALITY")
    else:
        if flow.sell_climax_percentile >= flow_cfg.min_climax_share:
            score += weights.sell_flow_climax
            reasons.append("Aggressive sell-volume climax")
        if flow.bid_replenishment_ratio >= flow_cfg.min_replenishment_ratio:
            score += weights.absorption_replenishment
            reasons.append("Bid replenishment / absorption")
        if flow.impact_decay >= flow_cfg.min_impact_decay:
            score += weights.impact_decay
            reasons.append("Seller price-impact decay")
        if flow.failed_auction:
            score += weights.failed_auction
            reasons.append("Failed auction below the extreme")
        if flow.reclaim_price is None:
            vetoes.append("NO_ENTRY_RECLAIM")
        risk = make_risk_plan(daily, flow, instrument.tick_size, cfg)
        if risk is None:
            vetoes.append("NO_VALID_RISK_PLAN")
        else:
            if risk.rr_target_1 < scan.min_reward_risk_to_primary:
                vetoes.append("PRIMARY_TARGET_RR_TOO_LOW")
            if risk.rr_mean < scan.min_reward_risk_to_mean:
                vetoes.append("MEAN_TARGET_RR_TOO_LOW")

    if vetoes:
        state = SetupState.REJECTED
    elif score >= scan.min_score and risk is not None:
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
