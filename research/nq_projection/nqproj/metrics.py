"""Trade-level reporting.

Everything is expressed in R (risk multiples) so results are comparable across
regimes and instruments, and so a handful of outsized winners cannot hide
behind a currency total.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _streak(flags: np.ndarray, value: bool) -> int:
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f == value else 0
        best = max(best, cur)
    return best


def summarise(trades: pd.DataFrame, slippage_R: float = 0.0) -> dict:
    """Full performance summary; ``slippage_R`` is deducted from every trade."""
    if trades is None or trades.empty:
        return {"trades": 0}

    r = trades["r_multiple"].to_numpy(float) - slippage_R
    wins, losses = r[r > 0], r[r <= 0]
    gross_win, gross_loss = wins.sum(), -losses.sum()

    equity = np.cumsum(r)
    peak = np.maximum.accumulate(np.concatenate([[0.0], equity]))
    dd = peak - np.concatenate([[0.0], equity])

    t0 = pd.to_datetime(trades["entry_time"])
    span_weeks = max((t0.max() - t0.min()).days / 7.0, 1e-9)

    return {
        "trades": int(len(r)),
        "win_rate": float((r > 0).mean()),
        "avg_R": float(r.mean()),
        "total_R": float(r.sum()),
        "median_winner_R": float(np.median(wins)) if len(wins) else np.nan,
        "median_loser_R": float(np.median(losses)) if len(losses) else np.nan,
        "profit_factor": float(gross_win / gross_loss) if gross_loss > 0 else np.inf,
        "expectancy_R": float(r.mean()),
        "max_drawdown_R": float(dd.max()),
        "max_consec_wins": _streak(r > 0, True),
        "max_consec_losses": _streak(r > 0, False),
        "trades_per_week": float(len(r) / span_weeks),
        "avg_MAE_R": float(trades["mae_R"].mean()) if "mae_R" in trades else np.nan,
        "avg_MFE_R": float(trades["mfe_R"].mean()) if "mfe_R" in trades else np.nan,
        "median_hours_in_trade": float(trades["hours_in_trade"].median()) if "hours_in_trade" in trades else np.nan,
    }


def by_period(trades: pd.DataFrame, freq: str = "YE", slippage_R: float = 0.0) -> pd.DataFrame:
    """Performance split by calendar period -- the first place curve-fits show."""
    if trades is None or trades.empty:
        return pd.DataFrame()
    t = trades.copy()
    t["entry_time"] = pd.to_datetime(t["entry_time"])
    rows = []
    for period, grp in t.groupby(pd.Grouper(key="entry_time", freq=freq)):
        if grp.empty:
            continue
        s = summarise(grp, slippage_R=slippage_R)
        s["period"] = str(period.date())
        rows.append(s)
    return pd.DataFrame(rows).set_index("period") if rows else pd.DataFrame()


def slippage_curve(trades: pd.DataFrame, levels=(0.0, 0.02, 0.05, 0.10, 0.20)) -> pd.DataFrame:
    """Expectancy decay as execution costs rise.

    An edge that dies at 0.05R of slippage is not tradeable, however good the
    frictionless numbers look.
    """
    rows = []
    for s in levels:
        m = summarise(trades, slippage_R=s)
        rows.append({"slippage_R": s, "avg_R": m.get("avg_R"), "profit_factor": m.get("profit_factor"),
                     "total_R": m.get("total_R"), "win_rate": m.get("win_rate")})
    return pd.DataFrame(rows)
