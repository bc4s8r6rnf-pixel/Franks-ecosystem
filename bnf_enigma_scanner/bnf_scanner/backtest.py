"""Triple-barrier backtester for the BNF daily displacement layer.

WHAT THIS MEASURES — read before quoting any number it prints.

The full system described in DEVELOPER_HANDOFF.md gates every trade behind four
independent layers:

  1. daily SMA(25) displacement       <- backtestable from daily OHLCV
  2. liquidity / tradability          <- partially backtestable (no spread data)
  3. catalyst classification + veto   <- needs point-in-time news; NOT backtested
  4. order-flow exhaustion + reclaim  <- needs MBO data;        NOT backtested

Daily bars can only exercise layer 1 and part of layer 2. Layers 3 and 4 are the
system's *selectivity* — the handoff is explicit that "no entry from technical
oversold status alone" and "unknown catalyst means no trade". A daily-only
backtest therefore takes every dislocation, including the ones the real system
exists to refuse, and its results are a floor on selectivity rather than an
estimate of the system's performance.

Every report states which layers were active. Do not strip that line off.

Entry/exit model, all decided on bar t and executed from bar t+1 onward:
  entry   next bar's open (no same-bar fills, no look-ahead)
  stop    candidate bar's low, minus the configured volatility/tick buffer
  target  the primary partial: `risk.target_1_fraction_to_mean` of the distance
          from entry to SMA(25)
  timeout close of the bar `backtest.max_holding_days` after entry

When a bar's range spans both the stop and the target, the stop is assumed to
fill first. That is pessimistic and intentional: daily bars cannot say which
came first, and the optimistic assumption is how backtests flatter themselves.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Config, default_config, load_config
from .data import MarketData, load_universe
from .features import compute_daily_features
from .models import AssetClass, Instrument

MIN_HISTORY_BARS = 60  # compute_daily_features' own requirement


@dataclass(frozen=True)
class Trade:
    symbol: str
    asset_class: str
    signal_date: date
    entry_date: date
    exit_date: date
    exit_reason: str  # target | stop | timeout
    entry: float
    stop: float
    target: float
    sma25: float
    exit_price: float
    divergence_pct: float
    robust_return_z: float
    atr_displacement: float
    cross_sectional_percentile: float
    holding_days: int
    gross_return_pct: float
    net_return_pct: float
    mae_pct: float
    reached_mean: bool


@dataclass(frozen=True)
class PeriodStats:
    label: str
    trades: int
    wins: int
    losses: int
    timeouts: int
    win_rate_pct: float
    avg_net_return_pct: float
    total_net_return_pct: float
    compounded_return_pct: float
    profit_factor: float
    avg_win_pct: float
    avg_loss_pct: float
    avg_mae_pct: float
    worst_trade_pct: float
    best_trade_pct: float
    avg_holding_days: float
    reached_mean_pct: float


def _cost_pct(config: Config) -> float:
    """Round-trip cost as a percentage of notional."""
    bt = config.backtest
    return (bt.cost_bps_round_trip + 2.0 * bt.slippage_bps) / 100.0


def _divergence_panel(universe: list[MarketData], sma_days: int) -> dict[AssetClass, pd.DataFrame]:
    """Percentage divergence from SMA(n) for every symbol, grouped by asset class.

    Used only to rank a candidate against its peers on the same date. Each
    column is computed from that symbol's own history, so no cross-symbol
    look-ahead is introduced.
    """
    panels: dict[AssetClass, dict[str, pd.Series]] = {}
    for market in universe:
        close = market.bars["close"].astype(float)
        sma = close.rolling(sma_days).mean()
        divergence = 100.0 * (close / sma - 1.0)
        panels.setdefault(market.instrument.asset_class, {})[market.symbol] = divergence
    return {ac: pd.DataFrame(cols) for ac, cols in panels.items()}


def _cross_sectional_percentile(
    panel: pd.DataFrame, symbol: str, when: pd.Timestamp
) -> float:
    """Fraction of same-class peers at or below this symbol's divergence today."""
    if when not in panel.index:
        return 1.0
    row = panel.loc[when].dropna()
    if len(row) < 2 or symbol not in row:
        # A single-instrument asset class cannot be ranked cross-sectionally.
        # Return 1.0 so the "bottom 5%" bonus is never awarded on no evidence.
        return 1.0
    return float((row <= row[symbol]).sum() / len(row))


def _simulate(
    bars: pd.DataFrame,
    signal_pos: int,
    entry: float,
    stop: float,
    target: float,
    sma25: float,
    max_holding_days: int,
) -> tuple[int, float, str, float, bool]:
    """Walk bars forward from the entry bar until a barrier is touched.

    Returns (exit_pos, exit_price, exit_reason, mae_pct, reached_mean).
    """
    entry_pos = signal_pos + 1
    last_pos = min(entry_pos + max_holding_days, len(bars) - 1)

    mae_pct = 0.0
    reached_mean = False

    for pos in range(entry_pos, last_pos + 1):
        low = float(bars["low"].iloc[pos])
        high = float(bars["high"].iloc[pos])

        mae_pct = min(mae_pct, 100.0 * (low - entry) / entry)
        if high >= sma25:
            reached_mean = True

        # Pessimistic ordering: a bar touching both barriers is treated as a loss.
        if low <= stop:
            return pos, stop, "stop", mae_pct, reached_mean
        if high >= target:
            return pos, target, "target", mae_pct, reached_mean

    return last_pos, float(bars["close"].iloc[last_pos]), "timeout", mae_pct, reached_mean


def backtest_market(
    market: MarketData,
    panel: pd.DataFrame,
    config: Config | None = None,
) -> list[Trade]:
    """Run the daily displacement layer over one instrument's full history."""
    cfg = config if config is not None else default_config()
    scan = cfg.scanner
    risk_cfg = cfg.risk
    bars = market.bars
    instrument: Instrument = market.instrument
    threshold = scan.candidate_min_divergence_pct[instrument.asset_class]
    cost = _cost_pct(cfg)

    close = bars["close"].astype(float)
    sma = close.rolling(scan.sma_days).mean()
    divergence = 100.0 * (close / sma - 1.0)

    trades: list[Trade] = []
    blocked_until = -1  # no overlapping positions in the same instrument

    # A trade needs a bar after the signal to enter on, so stop one short.
    for pos in range(MIN_HISTORY_BARS, len(bars) - 1):
        if pos <= blocked_until:
            continue
        if not (divergence.iloc[pos] <= threshold):
            continue

        history = bars.iloc[: pos + 1]
        when = bars.index[pos]
        percentile = _cross_sectional_percentile(panel, market.symbol, when)

        try:
            # The shared feature function — live and backtest must agree.
            daily = compute_daily_features(
                symbol=market.symbol,
                bars=history,
                cross_sectional_percentile=percentile,
                # Daily CSVs carry no spread. The spread gate is reported as
                # inactive rather than silently passed with a fabricated value.
                spread_bps=0.0,
                contract_multiplier=instrument.contract_multiplier,
            )
        except ValueError:
            continue  # not enough clean history yet

        if daily.dollar_volume < scan.min_dollar_volume:
            continue

        entry = float(bars["open"].iloc[pos + 1])
        buffer_ = max(
            risk_cfg.min_tick_buffer * instrument.tick_size,
            risk_cfg.volatility_buffer_atr_fraction * daily.atr14,
        )
        stop = float(bars["low"].iloc[pos]) - buffer_
        distance = daily.sma25 - entry
        if entry <= stop or distance <= 0:
            continue

        target = entry + risk_cfg.target_1_fraction_to_mean * distance
        rr = (target - entry) / (entry - stop)
        if rr < scan.min_reward_risk_to_primary:
            continue
        if (daily.sma25 - entry) / (entry - stop) < scan.min_reward_risk_to_mean:
            continue

        exit_pos, exit_price, reason, mae_pct, reached_mean = _simulate(
            bars, pos, entry, stop, target, daily.sma25, cfg.backtest.max_holding_days
        )

        gross = 100.0 * (exit_price - entry) / entry
        trades.append(
            Trade(
                symbol=market.symbol,
                asset_class=instrument.asset_class.value,
                signal_date=bars.index[pos].date(),
                entry_date=bars.index[pos + 1].date(),
                exit_date=bars.index[exit_pos].date(),
                exit_reason=reason,
                entry=entry,
                stop=stop,
                target=target,
                sma25=daily.sma25,
                exit_price=exit_price,
                divergence_pct=daily.divergence_pct,
                robust_return_z=daily.robust_return_z,
                atr_displacement=daily.atr_displacement,
                cross_sectional_percentile=percentile,
                holding_days=exit_pos - pos,
                gross_return_pct=gross,
                net_return_pct=gross - cost,
                mae_pct=mae_pct,
                reached_mean=reached_mean,
            )
        )
        blocked_until = exit_pos

    return trades


def backtest_universe(
    universe: list[MarketData], config: Config | None = None
) -> list[Trade]:
    cfg = config if config is not None else default_config()
    panels = _divergence_panel(universe, cfg.scanner.sma_days)
    trades: list[Trade] = []
    for market in universe:
        panel = panels[market.instrument.asset_class]
        trades.extend(backtest_market(market, panel, cfg))
    return sorted(trades, key=lambda t: t.entry_date)


def summarise(trades: list[Trade], label: str) -> PeriodStats:
    if not trades:
        return PeriodStats(
            label=label, trades=0, wins=0, losses=0, timeouts=0, win_rate_pct=0.0,
            avg_net_return_pct=0.0, total_net_return_pct=0.0, compounded_return_pct=0.0,
            profit_factor=0.0, avg_win_pct=0.0, avg_loss_pct=0.0, avg_mae_pct=0.0,
            worst_trade_pct=0.0, best_trade_pct=0.0, avg_holding_days=0.0,
            reached_mean_pct=0.0,
        )

    nets = np.array([t.net_return_pct for t in trades])
    wins = nets[nets > 0]
    losses = nets[nets <= 0]

    gross_profit = float(wins.sum())
    gross_loss = float(-losses.sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else math.inf

    compounded = float(np.prod(1.0 + nets / 100.0) - 1.0) * 100.0

    return PeriodStats(
        label=label,
        trades=len(trades),
        wins=int((nets > 0).sum()),
        losses=int((nets <= 0).sum()),
        timeouts=sum(1 for t in trades if t.exit_reason == "timeout"),
        win_rate_pct=100.0 * len(wins) / len(nets),
        avg_net_return_pct=float(nets.mean()),
        total_net_return_pct=float(nets.sum()),
        compounded_return_pct=compounded,
        profit_factor=profit_factor,
        avg_win_pct=float(wins.mean()) if len(wins) else 0.0,
        avg_loss_pct=float(losses.mean()) if len(losses) else 0.0,
        avg_mae_pct=float(np.mean([t.mae_pct for t in trades])),
        worst_trade_pct=float(nets.min()),
        best_trade_pct=float(nets.max()),
        avg_holding_days=float(np.mean([t.holding_days for t in trades])),
        reached_mean_pct=100.0 * sum(1 for t in trades if t.reached_mean) / len(trades),
    )


ACTIVE_LAYERS = (
    "ACTIVE:   daily SMA(25) displacement, ATR/robust-z anomaly, cross-sectional rank,\n"
    "          dollar-volume liquidity gate, reward-to-risk gates, triple-barrier exits\n"
    "INACTIVE: catalyst classification and veto (needs point-in-time news),\n"
    "          order-flow exhaustion and reclaim trigger (needs MBO data),\n"
    "          spread gate (daily bars carry no spread)"
)


def format_report(trades: list[Trade], config: Config, year: int | None = None) -> str:
    lines: list[str] = []
    add = lines.append

    add("=" * 78)
    add("BNF ENIGMA — daily displacement layer backtest")
    add("=" * 78)
    add(ACTIVE_LAYERS)
    add("")
    add(
        f"Costs applied: {config.backtest.cost_bps_round_trip:.1f} bps round trip "
        f"+ {config.backtest.slippage_bps:.1f} bps slippage each way "
        f"= {_cost_pct(config):.2f}% per trade"
    )
    add(f"Max holding: {config.backtest.max_holding_days} trading days")
    add("")

    if not trades:
        add("No setups triggered. Nothing to report.")
        return "\n".join(lines)

    first, last = trades[0].entry_date, max(t.exit_date for t in trades)
    add(f"Period covered: {first} to {last}   ({len(trades)} setups)")
    add("")

    def table(rows: list[tuple[str, PeriodStats]], title: str) -> None:
        add(title)
        add("-" * 78)
        add(
            f"{'':<14}{'setups':>7}{'win%':>8}{'avg%':>8}{'total%':>9}"
            f"{'compnd%':>9}{'PF':>7}{'MAE%':>8}{'days':>6}"
        )
        for name, stat in rows:
            pf = "inf" if stat.profit_factor == math.inf else f"{stat.profit_factor:.2f}"
            add(
                f"{name:<14}{stat.trades:>7}{stat.win_rate_pct:>8.1f}"
                f"{stat.avg_net_return_pct:>8.2f}{stat.total_net_return_pct:>9.1f}"
                f"{stat.compounded_return_pct:>9.1f}{pf:>7}"
                f"{stat.avg_mae_pct:>8.2f}{stat.avg_holding_days:>6.1f}"
            )
        add("")

    # Since inception, by asset class then overall.
    by_class: dict[str, list[Trade]] = {}
    for t in trades:
        by_class.setdefault(t.asset_class, []).append(t)
    rows = [(ac, summarise(ts, ac)) for ac, ts in sorted(by_class.items())]
    rows.append(("ALL", summarise(trades, "ALL")))
    table(rows, "SINCE INCEPTION")

    # Per calendar year.
    by_year: dict[int, list[Trade]] = {}
    for t in trades:
        by_year.setdefault(t.entry_date.year, []).append(t)
    table(
        [(str(y), summarise(ts, str(y))) for y, ts in sorted(by_year.items())],
        "BY CALENDAR YEAR",
    )

    if year is not None:
        ytd = [t for t in trades if t.entry_date.year == year]
        rows = []
        ytd_by_class: dict[str, list[Trade]] = {}
        for t in ytd:
            ytd_by_class.setdefault(t.asset_class, []).append(t)
        rows = [(ac, summarise(ts, ac)) for ac, ts in sorted(ytd_by_class.items())]
        rows.append(("ALL", summarise(ytd, "ALL")))
        table(rows, f"{year} YEAR TO DATE")

    # Per symbol, since inception.
    by_symbol: dict[str, list[Trade]] = {}
    for t in trades:
        by_symbol.setdefault(t.symbol, []).append(t)
    table(
        [(s, summarise(ts, s)) for s, ts in sorted(by_symbol.items())],
        "BY MARKET (since inception)",
    )

    overall = summarise(trades, "ALL")
    add("Definitions")
    add("-" * 78)
    add("total%    sum of per-trade net returns, equal notional per trade")
    add("compnd%   the same trades compounded sequentially at full notional")
    add("MAE%      average worst unrealised drawdown while in the trade")
    add("PF        gross profit / gross loss, net of costs")
    add("")
    add(
        f"Exits: {overall.wins} winners, {overall.losses} losers, "
        f"{overall.timeouts} timed out at the vertical barrier. "
        f"{overall.reached_mean_pct:.1f}% of setups touched SMA(25) before exiting."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m bnf_scanner.backtest",
        description="Backtest the BNF daily displacement layer over a directory of daily CSVs.",
    )
    parser.add_argument(
        "--data-dir", required=True,
        help="root directory containing equities/ indices/ metals/ fx/ subdirectories of CSVs",
    )
    parser.add_argument("--config", default=None, help="path to config.yaml")
    parser.add_argument(
        "--year", type=int, default=None,
        help="calendar year to break out separately (e.g. the current year for YTD)",
    )
    parser.add_argument("--json", default=None, help="also write per-trade results to this JSON file")
    args = parser.parse_args(argv)

    config = load_config(args.config) if args.config else default_config()
    universe = load_universe(args.data_dir)
    trades = backtest_universe(universe, config)

    print(format_report(trades, config, args.year))

    if args.json:
        payload = {
            "active_layers": ACTIVE_LAYERS,
            "trades": [{**asdict(t),
                        "signal_date": t.signal_date.isoformat(),
                        "entry_date": t.entry_date.isoformat(),
                        "exit_date": t.exit_date.isoformat()} for t in trades],
            "summary": asdict(summarise(trades, "ALL")),
        }
        Path(args.json).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nPer-trade results written to {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
