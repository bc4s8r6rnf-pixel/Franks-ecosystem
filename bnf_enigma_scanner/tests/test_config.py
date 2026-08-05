import textwrap

import pytest

from bnf_scanner.config import load_config, default_config
from bnf_scanner.models import AssetClass


def test_bundled_config_loads():
    cfg = default_config()
    assert cfg.scanner.sma_days == 25
    assert set(cfg.scanner.candidate_min_divergence_pct) == set(AssetClass)
    assert cfg.order_flow.min_reclaim_ticks >= 1
    assert cfg.backtest.max_holding_days > 0


def test_config_is_cached():
    assert default_config() is default_config()


def _write(tmp_path, body: str):
    path = tmp_path / "config.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def _valid_body() -> str:
    return """
    scanner:
      sma_days: 25
      candidate_min_divergence_pct: {equities: -12.0, indices: -5.0, metals: -6.0, fx: -3.0}
      robust_z_max: -2.5
      atr_multiple_min: 2.0
      cross_sectional_percentile_max: 0.05
      min_dollar_volume: 1
      max_spread_bps: 25
      min_score: 80
      min_reward_risk_to_primary: 1.8
      min_reward_risk_to_mean: 3.0
      max_alerts_per_asset_class: 3
      event_lockout_minutes: 30
    catalyst: {lookback_hours: 48, structural_probability_veto: 0.55, unknown_probability_veto: 0.45, minimum_source_count: 2}
    order_flow: {climax_percentile: 0.95, absorption_percentile: 0.9, min_climax_share: 0.2, min_replenishment_ratio: 1.5, min_impact_decay: 0.35, min_reclaim_ticks: 2, confirmation_window_seconds: 300}
    risk: {volatility_buffer_atr_fraction: 0.15, min_tick_buffer: 3, target_1_fraction_to_mean: 0.4, target_2_fraction_to_mean: 0.7}
    scoring: {divergence_max: 20.0, robust_return_max: 10.0, atr_displacement_max: 10.0, cross_sectional: 10.0, catalyst_non_structural: 15.0, sell_flow_climax: 10.0, absorption_replenishment: 10.0, impact_decay: 5.0, failed_auction: 5.0, regime_suitability: 5.0}
    backtest: {max_holding_days: 25, cost_bps_round_trip: 10.0, slippage_bps: 5.0, walk_forward_test_days: 252, embargo_days: 25}
    """


def test_round_trip_of_valid_file(tmp_path):
    cfg = load_config(_write(tmp_path, _valid_body()))
    assert cfg.scanner.min_dollar_volume == 1


def test_unknown_key_is_rejected(tmp_path):
    body = _valid_body().replace("event_lockout_minutes: 30", "event_lockout_minutes: 30\n      typo_key: 1")
    with pytest.raises(ValueError, match="unknown keys"):
        load_config(_write(tmp_path, body))


def test_missing_key_is_rejected(tmp_path):
    body = _valid_body().replace("      min_score: 80\n", "")
    with pytest.raises(ValueError, match="missing keys"):
        load_config(_write(tmp_path, body))


def test_missing_asset_class_is_rejected(tmp_path):
    body = _valid_body().replace(", fx: -3.0", "")
    with pytest.raises(ValueError, match="missing asset classes"):
        load_config(_write(tmp_path, body))


def test_unknown_asset_class_is_rejected(tmp_path):
    body = _valid_body().replace("fx: -3.0", "fx: -3.0, crypto: -20.0")
    with pytest.raises(ValueError, match="unknown asset class"):
        load_config(_write(tmp_path, body))


def test_missing_file_is_rejected(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yaml")
