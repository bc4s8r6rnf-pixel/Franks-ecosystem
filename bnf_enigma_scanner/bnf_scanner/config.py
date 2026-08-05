"""Typed configuration loaded from ``config.yaml``.

Before this module existed, ``config.yaml`` was inert documentation: every
threshold was hard-coded in :mod:`bnf_scanner.engine`, so the file and the code
could disagree without anything noticing. Now the YAML is the single source of
truth and the engine reads it.

Loading is strict on purpose. An unknown or missing key raises rather than
silently falling back to a default, because a typo in a threshold file is a
silent change to trading behaviour — exactly the failure the handoff's
"every alert is reproducible from an immutable feature snapshot" rule exists to
prevent.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Mapping

import yaml

from .models import AssetClass

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


@dataclass(frozen=True)
class ScannerConfig:
    sma_days: int
    candidate_min_divergence_pct: Mapping[AssetClass, float]
    robust_z_max: float
    atr_multiple_min: float
    cross_sectional_percentile_max: float
    min_dollar_volume: float
    max_spread_bps: float
    min_score: float
    min_reward_risk_to_primary: float
    min_reward_risk_to_mean: float
    max_alerts_per_asset_class: int
    event_lockout_minutes: int


@dataclass(frozen=True)
class CatalystConfig:
    lookback_hours: int
    structural_probability_veto: float
    unknown_probability_veto: float
    minimum_source_count: int


@dataclass(frozen=True)
class OrderFlowConfig:
    climax_percentile: float
    absorption_percentile: float
    min_climax_share: float
    min_replenishment_ratio: float
    min_impact_decay: float
    min_reclaim_ticks: int
    confirmation_window_seconds: int


@dataclass(frozen=True)
class RiskConfig:
    volatility_buffer_atr_fraction: float
    min_tick_buffer: int
    target_1_fraction_to_mean: float
    target_2_fraction_to_mean: float


@dataclass(frozen=True)
class ScoringConfig:
    divergence_max: float
    robust_return_max: float
    atr_displacement_max: float
    cross_sectional: float
    catalyst_non_structural: float
    sell_flow_climax: float
    absorption_replenishment: float
    impact_decay: float
    failed_auction: float
    regime_suitability: float


@dataclass(frozen=True)
class BacktestConfig:
    max_holding_days: int
    cost_bps_round_trip: float
    slippage_bps: float
    walk_forward_test_days: int
    embargo_days: int


@dataclass(frozen=True)
class Config:
    scanner: ScannerConfig
    catalyst: CatalystConfig
    order_flow: OrderFlowConfig
    risk: RiskConfig
    scoring: ScoringConfig
    backtest: BacktestConfig


def _build(cls: type, payload: Any, path: str) -> Any:
    """Instantiate a config dataclass, rejecting missing and unknown keys."""
    if not isinstance(payload, Mapping):
        raise ValueError(f"config section '{path}' must be a mapping, got {type(payload).__name__}")

    expected = {f.name for f in fields(cls)}
    provided = set(payload)
    if missing := expected - provided:
        raise ValueError(f"config section '{path}' is missing keys: {sorted(missing)}")
    if unknown := provided - expected:
        raise ValueError(f"config section '{path}' has unknown keys: {sorted(unknown)}")

    return cls(**{f.name: payload[f.name] for f in fields(cls)})


def _parse_divergence(payload: Any) -> Mapping[AssetClass, float]:
    if not isinstance(payload, Mapping):
        raise ValueError("scanner.candidate_min_divergence_pct must be a mapping")

    parsed: dict[AssetClass, float] = {}
    for key, value in payload.items():
        try:
            asset_class = AssetClass(key)
        except ValueError as exc:
            valid = sorted(a.value for a in AssetClass)
            raise ValueError(
                f"unknown asset class '{key}' in candidate_min_divergence_pct; expected one of {valid}"
            ) from exc
        parsed[asset_class] = float(value)

    # A missing asset class would otherwise surface as a KeyError deep inside the
    # engine on whichever instrument happened to be scanned first.
    if missing := set(AssetClass) - set(parsed):
        raise ValueError(
            f"candidate_min_divergence_pct is missing asset classes: {sorted(a.value for a in missing)}"
        )
    return parsed


def load_config(path: str | Path | None = None) -> Config:
    """Load and validate the YAML configuration.

    Args:
        path: config file to read. Defaults to the ``config.yaml`` shipped
            alongside the package.
    """
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise FileNotFoundError(f"config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    if not isinstance(raw, Mapping):
        raise ValueError(f"config file {config_path} did not parse to a mapping")

    expected_sections = {f.name for f in fields(Config)}
    if missing := expected_sections - set(raw):
        raise ValueError(f"config file {config_path} is missing sections: {sorted(missing)}")
    if unknown := set(raw) - expected_sections:
        raise ValueError(f"config file {config_path} has unknown sections: {sorted(unknown)}")

    scanner_payload = dict(raw["scanner"])
    scanner_payload["candidate_min_divergence_pct"] = _parse_divergence(
        scanner_payload.get("candidate_min_divergence_pct")
    )

    return Config(
        scanner=_build(ScannerConfig, scanner_payload, "scanner"),
        catalyst=_build(CatalystConfig, raw["catalyst"], "catalyst"),
        order_flow=_build(OrderFlowConfig, raw["order_flow"], "order_flow"),
        risk=_build(RiskConfig, raw["risk"], "risk"),
        scoring=_build(ScoringConfig, raw["scoring"], "scoring"),
        backtest=_build(BacktestConfig, raw["backtest"], "backtest"),
    )


_DEFAULT: Config | None = None


def default_config() -> Config:
    """Return the bundled configuration, parsed once and cached."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = load_config()
    return _DEFAULT
