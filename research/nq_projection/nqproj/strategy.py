"""The failed-expansion / reclaim state machine (brief section 14).

    destination zone reached -> price expands beyond -> expansion fails
    -> reclaim confirmed -> enter -> stop beyond the actual swing extreme
    -> target the next projection node in the network

Deliberately built with no indicators: price, time, reference ranges and their
projections only. Every decision uses information available at or before the
bar it is taken on -- the zone map is filtered by activation time, and the stop
is placed at the extreme that had *already* printed when the reclaim confirmed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .projections import PathIndex, active_zones_at

NY = "America/New_York"


@dataclass
class Params:
    entry_k_min: float = 2.0        # only zones at/above this ladder step are destinations
    max_pen_R: float = 1.50         # expansion beyond this is acceptance, not failure
    max_hours_beyond: float = 12.0  # must reclaim within this or the setup is dead
    confirm_close: bool = True      # reclaim confirmed on bar close, not a wick
    stop_buffer_R: float = 0.15     # stop sits beyond the printed extreme by this much
    min_target_R: float = 1.0       # ignore target nodes closer than this
    max_hold_hours: float = 96.0    # time stop
    max_age_days: float = 10.0      # zone-map lifespan
    hours_min: float | None = None  # optional NY-hour entry window
    hours_max: float | None = None


def _hour_ok(ts: pd.Timestamp, p: Params) -> bool:
    if p.hours_min is None or p.hours_max is None:
        return True
    h = ts.hour + ts.minute / 60.0
    if p.hours_min <= p.hours_max:
        return p.hours_min <= h < p.hours_max
    return h >= p.hours_min or h < p.hours_max      # window wrapping midnight


def _pick_target(zones, entry_time, entry_price, direction, R, p: Params):
    """Next projection node in the trade's direction -- the target comes from the map."""
    act = active_zones_at(zones, entry_time, max_age_days=p.max_age_days)
    if act.empty:
        return None
    if direction > 0:
        cand = act[act["price"] > entry_price + p.min_target_R * R]
        return float(cand["price"].min()) if len(cand) else None
    cand = act[act["price"] < entry_price - p.min_target_R * R]
    return float(cand["price"].max()) if len(cand) else None


def run(
    touches: pd.DataFrame,
    zones: pd.DataFrame,
    path: PathIndex,
    p: Params = Params(),
) -> pd.DataFrame:
    """Walk every zone touch through the state machine and collect trades."""
    t = touches[touches["touched"] & (touches["k"] >= p.entry_k_min)].copy()
    if t.empty:
        return pd.DataFrame()
    t = t.sort_values("touch_time")

    trades = []
    busy_until = None

    for row in t.itertuples():
        touch_time = pd.Timestamp(row.touch_time)
        if busy_until is not None and touch_time <= busy_until:   # one position at a time
            continue

        i0 = int(row.touch_idx)
        R, lvl = row.R, row.price
        up = row.side == "up"                   # up-side zone -> failure trades short
        i_dead = path.idx_at_or_after(touch_time + pd.Timedelta(hours=p.max_hours_beyond))
        i_dead = min(max(i_dead, i0 + 1), len(path))

        hi, lo, cl = path.high[i0:i_dead], path.low[i0:i_dead], path.close[i0:i_dead]
        if len(hi) < 2:
            continue

        # --- expansion, then failure/reclaim -------------------------------
        if up:
            run_ext = np.maximum.accumulate(hi)
            reclaimed = (cl < lvl) if p.confirm_close else (lo < lvl)
        else:
            run_ext = np.minimum.accumulate(lo)
            reclaimed = (cl > lvl) if p.confirm_close else (hi > lvl)

        reclaimed[0] = False                    # the touch bar itself cannot be the reclaim
        if not reclaimed.any():
            continue
        j = int(np.argmax(reclaimed))

        extreme = float(run_ext[j])
        pen_R = (extreme - lvl) / R if up else (lvl - extreme) / R
        if pen_R > p.max_pen_R:                 # price accepted outside: waypoint, not terminal
            continue

        entry_idx = i0 + j
        entry_time = pd.Timestamp(path.ts[entry_idx]).tz_localize("UTC").tz_convert(NY)
        if not _hour_ok(entry_time, p):
            continue
        entry = float(cl[j])

        # --- geometry -------------------------------------------------------
        direction = -1 if up else 1
        stop = extreme + p.stop_buffer_R * R if up else extreme - p.stop_buffer_R * R
        risk = abs(entry - stop)
        if risk <= 0:
            continue

        target = _pick_target(zones, entry_time, entry, direction, R, p)
        if target is None:
            continue

        # --- resolve --------------------------------------------------------
        i_end = path.idx_at_or_after(entry_time + pd.Timedelta(hours=p.max_hold_hours))
        i_end = min(max(i_end, entry_idx + 1), len(path))
        i_stop = path.first_touch(entry_idx, i_end, stop, up=up)
        i_tgt = path.first_touch(entry_idx, i_end, target, up=(direction > 0))

        if i_stop >= 0 and (i_tgt < 0 or i_stop <= i_tgt):
            exit_idx, exit_price, outcome = i_stop, stop, "stop"
        elif i_tgt >= 0:
            exit_idx, exit_price, outcome = i_tgt, target, "target"
        else:
            exit_idx = i_end - 1
            exit_price, outcome = float(path.close[exit_idx]), "time"

        seg_hi = path.high[entry_idx:exit_idx + 1]
        seg_lo = path.low[entry_idx:exit_idx + 1]
        if direction > 0:
            mfe, mae = (seg_hi.max() - entry) / risk, (entry - seg_lo.min()) / risk
        else:
            mfe, mae = (entry - seg_lo.min()) / risk, (seg_hi.max() - entry) / risk

        exit_time = pd.Timestamp(path.ts[exit_idx]).tz_localize("UTC").tz_convert(NY)
        trades.append(
            {
                "entry_time": entry_time,
                "exit_time": exit_time,
                "direction": direction,
                "entry": entry,
                "stop": stop,
                "target": target,
                "exit": exit_price,
                "outcome": outcome,
                "r_multiple": direction * (exit_price - entry) / risk,
                "risk_points": risk,
                "mae_R": float(mae),
                "mfe_R": float(mfe),
                "hours_in_trade": (exit_time - entry_time).total_seconds() / 3600.0,
                "zone_k": row.k,
                "zone_kind": row.kind,
                "zone_side": row.side,
                "zone_age_hours": row.age_hours_at_touch,
                "penetration_R": float(pen_R),
                "ny_hour": entry_time.hour,
            }
        )
        busy_until = exit_time

    return pd.DataFrame(trades)


def walk_forward(
    touches: pd.DataFrame,
    zones: pd.DataFrame,
    path: PathIndex,
    grid: list[Params],
    train_years: int = 2,
    test_years: int = 1,
    metric: str = "avg_R",
) -> pd.DataFrame:
    """Anchored walk-forward: choose parameters in-sample, report out-of-sample only.

    The returned frame contains *only* test-window trades, tagged with the fold
    that selected them, so the aggregate is a genuine out-of-sample record
    rather than the in-sample fit re-presented.
    """
    from .metrics import summarise

    all_trades = {i: run(touches, zones, path, p) for i, p in enumerate(grid)}
    times = pd.concat([t["entry_time"] for t in all_trades.values() if not t.empty])
    if times.empty:
        return pd.DataFrame()

    start, end = times.min(), times.max()
    folds, cursor = [], start
    while True:
        tr_end = cursor + pd.DateOffset(years=train_years)
        te_end = tr_end + pd.DateOffset(years=test_years)
        if tr_end >= end:
            break
        folds.append((cursor, tr_end, min(te_end, end)))
        cursor = tr_end

    out = []
    for tr0, tr1, te1 in folds:
        best_i, best_v = None, -np.inf
        for i, tdf in all_trades.items():
            if tdf.empty:
                continue
            tr = tdf[(tdf["entry_time"] >= tr0) & (tdf["entry_time"] < tr1)]
            if len(tr) < 10:                     # too few to select on
                continue
            v = summarise(tr).get(metric, -np.inf)
            if v > best_v:
                best_i, best_v = i, v
        if best_i is None:
            continue
        te = all_trades[best_i]
        te = te[(te["entry_time"] >= tr1) & (te["entry_time"] < te1)].copy()
        te["fold_train_end"] = tr1
        te["param_idx"] = best_i
        te["train_metric"] = best_v
        out.append(te)

    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()
