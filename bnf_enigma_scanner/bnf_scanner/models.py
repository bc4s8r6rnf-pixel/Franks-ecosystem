from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Sequence


class AssetClass(str, Enum):
    EQUITIES = "equities"
    INDICES = "indices"
    METALS = "metals"
    FX = "fx"


class CatalystClass(str, Enum):
    EMOTIONAL_TECHNICAL = "emotional_technical"
    LIQUIDITY_STRESS = "liquidity_stress"
    SCHEDULED_MACRO = "scheduled_macro"
    FUNDAMENTAL_REPRICING = "fundamental_repricing"
    STRUCTURAL_REGIME_CHANGE = "structural_regime_change"
    UNKNOWN = "unknown"


class SetupState(str, Enum):
    REJECTED = "rejected"
    WATCH = "watch"
    ARMED = "armed"
    CONFIRMED = "confirmed"


@dataclass(frozen=True)
class Instrument:
    symbol: str
    asset_class: AssetClass
    order_flow_symbol: str
    tick_size: float
    currency: str = "USD"
    sector: str | None = None
    # Notional represented by one unit of quoted volume. 1.0 for cash equities
    # (volume is shares); the contract size for futures (ES=50, GC=100,
    # 6E=125_000). Without it, `close * volume` understates a futures market's
    # traded notional by orders of magnitude and the liquidity gate rejects
    # every FX and index candidate.
    contract_multiplier: float = 1.0


@dataclass(frozen=True)
class NewsItem:
    timestamp: datetime
    headline: str
    source: str
    body: str = ""
    entities: Sequence[str] = ()
    relevance: float = 0.0
    sentiment: float = 0.0
    novelty: float = 0.0
    facts: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CatalystAssessment:
    label: CatalystClass
    probabilities: Mapping[CatalystClass, float]
    confidence: float
    evidence: Sequence[str]
    hard_veto: bool
    veto_reason: str | None = None


@dataclass(frozen=True)
class DailyFeatures:
    symbol: str
    timestamp: datetime
    close: float
    sma25: float
    divergence_pct: float
    robust_return_z: float
    atr14: float
    atr_displacement: float
    cross_sectional_percentile: float
    dollar_volume: float
    spread_bps: float


@dataclass(frozen=True)
class OrderFlowFeatures:
    timestamp: datetime
    aggressive_sell_volume: float
    aggressive_buy_volume: float
    sell_climax_percentile: float
    order_flow_imbalance: float
    bid_replenishment_ratio: float
    price_impact_per_sell_unit: float
    impact_decay: float
    failed_auction: bool
    reclaim_price: float | None
    structural_low: float
    micro_vwap: float
    data_quality_ok: bool = True


@dataclass(frozen=True)
class RiskPlan:
    entry: float
    stop: float
    target_1: float
    target_2: float
    mean_target: float
    risk_per_unit: float
    rr_target_1: float
    rr_target_2: float
    rr_mean: float


@dataclass(frozen=True)
class Setup:
    instrument: Instrument
    state: SetupState
    score: float
    daily: DailyFeatures
    catalyst: CatalystAssessment
    order_flow: OrderFlowFeatures | None
    risk: RiskPlan | None
    reasons: Sequence[str]
    vetoes: Sequence[str]
    feature_snapshot: Mapping[str, Any] = field(default_factory=dict)
