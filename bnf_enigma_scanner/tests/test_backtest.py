"""Tests for the backtest mechanics that decide whether results are honest.

Look-ahead, optimistic barrier ordering and overlapping positions are the three
ways a mean-reversion backtest flatters itself. Each gets a test.
"""

import numpy as np
import pandas as pd
import pytest

from bnf_scanner.backtest import (
    _cost_pct, _simulate, backtest_market, backtest_universe, summarise,
)
from bnf_scanner.config import default_config
from bnf_scanner.data import MarketData, load_daily_csv, load_universe
from bnf_scanner.models import AssetClass, Instrument


def _bars(closes: list[float], highs=None, lows=None, opens=None, volume=5_000_000) -> pd.DataFrame:
    n = len(closes)
    close = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {
            "open": np.asarray(opens, dtype=float) if opens is not None else close,
            "high": np.asarray(highs, dtype=float) if highs is not None else close * 1.01,
            "low": np.asarray(lows, dtype=float) if lows is not None else close * 0.99,
            "close": close,
            "volume": np.full(n, float(volume)),
        },
        index=pd.bdate_range("2020-01-01", periods=n),
    )


def _market(bars: pd.DataFrame, symbol="TEST") -> MarketData:
    return MarketData(
        instrument=Instrument(symbol, AssetClass.EQUITIES, symbol, 0.01),
        bars=bars,
    )


# --- barrier mechanics -------------------------------------------------------

def test_bar_touching_both_barriers_is_recorded_as_a_stop():
    """Daily bars cannot say which barrier came first, so assume the loss.

    The opposite assumption turns every whipsaw into a winner and is the single
    biggest source of fantasy P/L in a daily backtest.
    """
    bars = _bars(
        closes=[100.0, 100.0, 100.0],
        highs=[100.0, 120.0, 100.0],   # bar 1 spans target and stop
        lows=[100.0, 80.0, 100.0],
    )
    exit_pos, exit_price, reason, _, _ = _simulate(
        bars, signal_pos=0, entry=100.0, stop=90.0, target=110.0,
        sma25=125.0, max_holding_days=5,
    )
    assert reason == "stop"
    assert exit_pos == 1
    assert exit_price == 90.0


def test_target_fill_is_capped_at_the_target_price():
    """A gap through the target fills at the target, not at the extreme high."""
    bars = _bars(closes=[100.0, 100.0], highs=[100.0, 150.0], lows=[100.0, 99.0])
    _, exit_price, reason, _, _ = _simulate(
        bars, signal_pos=0, entry=100.0, stop=90.0, target=110.0,
        sma25=125.0, max_holding_days=5,
    )
    assert reason == "target"
    assert exit_price == 110.0


def test_timeout_exits_at_the_vertical_barrier_close():
    bars = _bars(closes=[100.0] * 8, highs=[101.0] * 8, lows=[99.0] * 8)
    exit_pos, exit_price, reason, _, _ = _simulate(
        bars, signal_pos=0, entry=100.0, stop=90.0, target=110.0,
        sma25=125.0, max_holding_days=3,
    )
    assert reason == "timeout"
    assert exit_pos == 4  # entry bar is 1, plus 3 holding days
    assert exit_price == 100.0


def test_mae_tracks_the_worst_excursion_not_the_exit():
    bars = _bars(closes=[100.0, 100.0, 100.0], highs=[100.0, 100.0, 110.0], lows=[100.0, 95.0, 100.0])
    _, _, reason, mae, _ = _simulate(
        bars, signal_pos=0, entry=100.0, stop=90.0, target=110.0,
        sma25=125.0, max_holding_days=5,
    )
    assert reason == "target"
    assert mae == pytest.approx(-5.0)


# --- no look-ahead -----------------------------------------------------------

def test_entry_uses_the_bar_after_the_signal():
    """The signal bar's own close must never be tradable.

    Bar 60 is the dislocation (close 60). Bar 61 opens at a deliberately
    distinctive 62.5 — that open, not bar 60's close, must be the fill.
    """
    opens = [100.0] * 60 + [100.0, 62.5] + [62.0] * 30
    highs = [100.5] * 60 + [100.0, 63.0] + [64.0] * 30
    lows = [99.5] * 60 + [58.0, 61.0] + [61.0] * 30
    closes = [100.0] * 60 + [60.0, 62.0] + [62.0] * 30
    bars = _bars(closes, highs=highs, lows=lows, opens=opens)

    trades = backtest_market(_market(bars), panel=pd.DataFrame())
    assert trades, "expected the dislocation to generate a setup"
    first = trades[0]
    assert first.entry_date > first.signal_date
    assert first.entry == pytest.approx(62.5)
    # The stop hangs off the signal bar's low, below it by the configured buffer.
    assert first.stop < 58.0


# --- position overlap --------------------------------------------------------

def test_no_overlapping_positions_in_one_instrument():
    """A symbol that stays dislocated for weeks must not stack a trade per day."""
    closes = [100.0] * 60 + [55.0] * 40
    bars = _bars(closes)
    trades = backtest_market(_market(bars), panel=pd.DataFrame())
    for earlier, later in zip(trades, trades[1:]):
        assert later.signal_date >= earlier.exit_date


# --- costs -------------------------------------------------------------------

def test_costs_are_deducted_from_every_trade():
    cfg = default_config()
    closes = [100.0] * 60 + [60.0] + [61.0] * 40
    trades = backtest_market(_market(_bars(closes)), panel=pd.DataFrame(), config=cfg)
    assert trades
    for t in trades:
        assert t.net_return_pct == pytest.approx(t.gross_return_pct - _cost_pct(cfg))


def test_cost_pct_includes_both_slippage_legs():
    cfg = default_config()
    expected = (cfg.backtest.cost_bps_round_trip + 2 * cfg.backtest.slippage_bps) / 100.0
    assert _cost_pct(cfg) == pytest.approx(expected)


# --- summary statistics ------------------------------------------------------

def test_summarise_of_no_trades_is_all_zero():
    stats = summarise([], "empty")
    assert stats.trades == 0
    assert stats.total_net_return_pct == 0.0
    assert stats.win_rate_pct == 0.0


def test_summary_totals_match_the_trades():
    closes = [100.0] * 60 + [60.0] + [61.0] * 40
    trades = backtest_market(_market(_bars(closes)), panel=pd.DataFrame())
    stats = summarise(trades, "x")
    assert stats.trades == len(trades)
    assert stats.wins + stats.losses == len(trades)
    assert stats.total_net_return_pct == pytest.approx(sum(t.net_return_pct for t in trades))


# --- data loading ------------------------------------------------------------

def _csv(tmp_path, name, rows: str):
    path = tmp_path / name
    path.write_text("date,open,high,low,close,volume\n" + rows, encoding="utf-8")
    return path


def test_loader_rejects_high_below_low(tmp_path):
    path = _csv(tmp_path, "bad.csv", "2024-01-02,10,9,11,10,100\n")
    with pytest.raises(ValueError, match="high < low"):
        load_daily_csv(path)


def test_loader_rejects_duplicate_dates(tmp_path):
    path = _csv(tmp_path, "dupe.csv", "2024-01-02,10,11,9,10,100\n2024-01-02,10,11,9,10,100\n")
    with pytest.raises(ValueError, match="duplicate dates"):
        load_daily_csv(path)


def test_loader_rejects_missing_columns(tmp_path):
    path = tmp_path / "thin.csv"
    path.write_text("date,close\n2024-01-02,10\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing columns"):
        load_daily_csv(path)


def test_loader_sorts_by_date(tmp_path):
    path = _csv(tmp_path, "unsorted.csv",
                "2024-01-03,10,11,9,10,100\n2024-01-02,10,11,9,10,100\n")
    frame = load_daily_csv(path)
    assert list(frame.index) == sorted(frame.index)


def test_empty_universe_directory_is_rejected(tmp_path):
    (tmp_path / "equities").mkdir()
    with pytest.raises(ValueError, match="no CSVs found"):
        load_universe(tmp_path)


def test_universe_backtest_runs_across_asset_classes(tmp_path):
    closes = [100.0] * 60 + [55.0] + [56.0] * 40
    universe = [
        _market(_bars(closes), "AAA"),
        MarketData(
            instrument=Instrument("BBB", AssetClass.INDICES, "BBB", 0.25),
            bars=_bars([100.0] * 60 + [80.0] + [81.0] * 40),
        ),
    ]
    trades = backtest_universe(universe)
    assert {t.asset_class for t in trades} <= {"equities", "indices"}
    assert trades == sorted(trades, key=lambda t: t.entry_date)


# --- contract multiplier / liquidity gate ------------------------------------

def test_futures_notional_uses_the_contract_multiplier():
    """FX quotes ~1.09 and trades in contracts; close*volume alone is nonsense.

    Without the multiplier the dollar-volume gate silently rejected every FX and
    index candidate, so an entire asset class produced zero setups while looking
    like it had simply found no opportunities.
    """
    from bnf_scanner.features import compute_daily_features

    bars = _bars([1.09] * 80, volume=5_000_000)
    cash = compute_daily_features("EUR", bars, 0.5, 0.0, contract_multiplier=1.0)
    futures = compute_daily_features("EUR", bars, 0.5, 0.0, contract_multiplier=125_000.0)

    assert cash.dollar_volume < default_config().scanner.min_dollar_volume
    assert futures.dollar_volume > default_config().scanner.min_dollar_volume
    assert futures.dollar_volume == pytest.approx(cash.dollar_volume * 125_000.0)


def test_fx_instruments_produce_setups():
    closes = [1.09] * 60 + [1.00] + [1.01] * 40
    market = MarketData(
        instrument=Instrument("6E", AssetClass.FX, "6E", 0.00005, contract_multiplier=125_000.0),
        bars=_bars(closes, volume=5_000_000),
    )
    assert backtest_market(market, panel=pd.DataFrame()), "FX must not be gated out on notional"


def test_non_positive_multiplier_is_rejected():
    from bnf_scanner.features import compute_daily_features

    with pytest.raises(ValueError, match="contract_multiplier"):
        compute_daily_features("X", _bars([100.0] * 80), 0.5, 0.0, contract_multiplier=0.0)
