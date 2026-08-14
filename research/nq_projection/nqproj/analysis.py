"""The research questions themselves.

Each function here answers one question from the brief and is written so that a
null result is as readable as a positive one. Where a raw frequency could be
produced by geometry alone, a placebo comparison is built in rather than left
to interpretation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .projections import PathIndex, active_zones_at

NY = "America/New_York"


# --------------------------------------------------------------------------
# Section 8: the strict opposite-2.0 reconstruction
# --------------------------------------------------------------------------

def opposite_zone_test(
    refs: pd.DataFrame,
    path: PathIndex,
    k: float = 2.0,
    windows_hours=(72.0, 120.0),
    max_wait_hours: float = 120.0,
) -> pd.DataFrame:
    """Per reference candle: which k-boundary is hit first, and does the opposite follow?

    Strictly as specified -- the candle must complete first, the first-touched
    side is whichever of H+kR / L-kR price reaches first, and the target is the
    *paired opposite boundary of the same candle*. The clock for the follow-on
    is measured from the first touch (``within_*``) and, because the brief is
    ambiguous about the anchor, also from candle completion (``within_*_from_activate``).
    """
    rows = []
    for r in refs.itertuples():
        start = path.idx_at_or_after(r.activate)
        wait_end = path.idx_at_or_after(r.activate + pd.Timedelta(hours=max_wait_hours))
        if start >= wait_end:
            continue

        up_level = r.H + k * r.R
        dn_level = r.L - k * r.R
        i_up = path.first_touch(start, wait_end, up_level, up=True)
        i_dn = path.first_touch(start, wait_end, dn_level, up=False)

        if i_up < 0 and i_dn < 0:
            rows.append({"ref_id": r.ref_id, "kind": r.kind, "ref_time": r.ref_time,
                         "first_side": None, "R": r.R})
            continue

        if i_dn < 0 or (0 <= i_up < i_dn):
            first_side, first_i, opp_level, opp_up = "up", i_up, dn_level, False
        else:
            first_side, first_i, opp_level, opp_up = "down", i_dn, up_level, True

        first_time = pd.Timestamp(path.ts[first_i]).tz_localize("UTC").tz_convert(NY)
        row = {
            "ref_id": r.ref_id,
            "kind": r.kind,
            "ref_time": r.ref_time,
            "R": r.R,
            "first_side": first_side,
            "first_touch_time": first_time,
            "hours_to_first": (first_time - r.activate).total_seconds() / 3600.0,
        }
        for w in windows_hours:
            end_a = path.idx_at_or_after(first_time + pd.Timedelta(hours=w))
            row[f"within_{w:g}h"] = path.first_touch(first_i, end_a, opp_level, up=opp_up) >= 0
            end_b = path.idx_at_or_after(r.activate + pd.Timedelta(hours=w))
            row[f"within_{w:g}h_from_activate"] = path.first_touch(first_i, end_b, opp_level, up=opp_up) >= 0
        rows.append(row)

    return pd.DataFrame(rows)


def summarise_opposite_test(res: pd.DataFrame) -> dict:
    """Headline rates, conditioned on a first touch having happened at all."""
    if res.empty:
        return {}
    hit = res[res["first_side"].notna()]
    out = {
        "reference_candles": int(len(res)),
        "with_first_touch": int(len(hit)),
        "first_touch_rate": float(len(hit) / len(res)) if len(res) else np.nan,
        "median_hours_to_first": float(hit["hours_to_first"].median()) if len(hit) else np.nan,
    }
    for c in [c for c in res.columns if c.startswith("within_")]:
        out[f"opposite_{c}"] = float(hit[c].mean()) if len(hit) else np.nan
    if len(hit):
        out["first_side_up_share"] = float((hit["first_side"] == "up").mean())
    return out


# --------------------------------------------------------------------------
# Section 10: where do major swing extremes actually stop, in units of R?
# --------------------------------------------------------------------------

def extension_at_extremes(
    swings: pd.DataFrame,
    refs: pd.DataFrame,
    max_age_days: float = 10.0,
    anchor_offset: int = 0,
) -> pd.DataFrame:
    """Normalised extension of each swing extreme against each active reference.

    ``anchor_offset`` shifts which reference candle is used as the anchor while
    keeping the swing fixed. Offset 0 is the real measurement; non-zero offsets
    are placebos that preserve every property of the data except the specific
    swing/anchor pairing, which is what a clustering claim actually rests on.
    """
    if swings.empty or refs.empty:
        return pd.DataFrame()

    r = refs.sort_values("activate").reset_index(drop=True)
    # tz-aware Series.to_numpy() yields object-dtype Timestamps, which will not
    # compare against datetime64; drop to UTC-naive for the searchsorted bounds.
    act = r["activate"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy("datetime64[ns]")
    rows = []

    for s in swings.itertuples():
        end_t = pd.Timestamp(s.end_time)
        last = int(np.searchsorted(act, np.datetime64(end_t.tz_convert("UTC").tz_localize(None)), side="right")) - 1
        if last < 0:
            continue
        oldest = int(np.searchsorted(
            act,
            np.datetime64((end_t - pd.Timedelta(days=max_age_days)).tz_convert("UTC").tz_localize(None)),
            side="left",
        ))
        for j in range(oldest, last + 1):
            jj = j + anchor_offset
            if jj < 0 or jj >= len(r):
                continue
            ref = r.iloc[jj]
            if ref["R"] <= 0:
                continue
            if s.direction > 0:
                ext = (s.end_price - ref["H"]) / ref["R"]
            else:
                ext = (ref["L"] - s.end_price) / ref["R"]
            rows.append(
                {
                    "swing_end": end_t,
                    "direction": s.direction,
                    "mag_in_R": getattr(s, "mag_in_R", np.nan),
                    "ref_id": int(ref["ref_id"]),
                    "ref_kind": ref["kind"],
                    "ref_age_hours": (end_t - r.iloc[j]["activate"]).total_seconds() / 3600.0,
                    "extension": float(ext),
                    "anchor_offset": anchor_offset,
                }
            )
    return pd.DataFrame(rows)


def extension_clustering(
    real: pd.DataFrame,
    placebo: pd.DataFrame,
    ladder=(2.0, 2.5, 3.0, 3.5, 4.0, 5.0),
    tol: float = 0.15,
    lo: float = 0.0,
    hi: float = 8.0,
    bins: int = 80,
) -> pd.DataFrame:
    """Do real extensions pile up at ladder values more than placebo ones?

    Reported as a rate ratio per ladder value plus a global histogram-dispersion
    comparison. A ratio near 1.0 means the ladder value has no special status.
    """
    def _clip(d):
        e = d["extension"].to_numpy(float)
        return e[(e >= lo) & (e <= hi) & np.isfinite(e)]

    a, b = _clip(real), _clip(placebo)
    rows = []
    for kv in ladder:
        ra = float(np.mean(np.abs(a - kv) <= tol)) if len(a) else np.nan
        rb = float(np.mean(np.abs(b - kv) <= tol)) if len(b) else np.nan
        rows.append(
            {
                "ladder_k": kv,
                "real_rate": ra,
                "placebo_rate": rb,
                "ratio": (ra / rb) if (rb and np.isfinite(rb) and rb > 0) else np.nan,
                "n_real": int(len(a)),
                "n_placebo": int(len(b)),
            }
        )
    out = pd.DataFrame(rows)

    # Global shape check: a genuinely clustered distribution is "peakier" than
    # its placebo, which histogram entropy captures without assuming where the
    # peaks should be.
    def _entropy(x):
        if len(x) < 10:
            return np.nan
        h, _ = np.histogram(x, bins=bins, range=(lo, hi))
        p = h / h.sum()
        p = p[p > 0]
        return float(-(p * np.log(p)).sum())

    out.attrs["real_entropy"] = _entropy(a)
    out.attrs["placebo_entropy"] = _entropy(b)
    return out


# --------------------------------------------------------------------------
# Section 11: confluence
# --------------------------------------------------------------------------

def confluence_at_prices(
    points: pd.DataFrame,
    zones: pd.DataFrame,
    max_age_days: float = 10.0,
    bands=(0.10, 0.25, 0.50, 1.00),
    ladder_filter=None,
) -> pd.DataFrame:
    """Count independent projections near each (time, price) point.

    Distance is normalised by each zone's own R, so "near" means near *relative
    to the structure that generated it*. Counting distinct reference candles
    rather than distinct levels prevents one candle's dense ladder from
    manufacturing confluence on its own.
    """
    if points.empty or zones.empty:
        return pd.DataFrame()

    z = zones if ladder_filter is None else zones[zones["k"].isin(ladder_filter)]
    out = []
    for p in points.itertuples():
        when = pd.Timestamp(p.time)
        act = active_zones_at(z, when, max_age_days=max_age_days)
        if act.empty:
            out.append({"time": when, "price": p.price, "nearest_norm_dist": np.nan})
            continue
        d = (act["price"] - p.price).abs() / act["R"].replace(0, np.nan)
        rec = {
            "time": when,
            "price": p.price,
            "nearest_norm_dist": float(d.min()),
            "active_refs": int(act["ref_id"].nunique()),
        }
        for band in bands:
            near = act[d <= band]
            rec[f"n_refs_within_{band:g}R"] = int(near["ref_id"].nunique())
            rec[f"n_levels_within_{band:g}R"] = int(len(near))
        out.append(rec)
    return pd.DataFrame(out)


def confluence_lift(real: pd.DataFrame, placebo: pd.DataFrame, bands=(0.10, 0.25, 0.50, 1.00)) -> pd.DataFrame:
    """Confluence at real swing extremes vs at matched placebo price points."""
    rows = []
    for band in bands:
        col = f"n_refs_within_{band:g}R"
        if col not in real.columns or col not in placebo.columns:
            continue
        rows.append(
            {
                "band_R": band,
                "real_mean_refs": float(real[col].mean()),
                "placebo_mean_refs": float(placebo[col].mean()),
                "lift": float(real[col].mean() / placebo[col].mean()) if placebo[col].mean() else np.nan,
                "real_share_ge2": float((real[col] >= 2).mean()),
                "placebo_share_ge2": float((placebo[col] >= 2).mean()),
            }
        )
    out = pd.DataFrame(rows)
    out.attrs["real_median_nearest"] = float(real["nearest_norm_dist"].median()) if len(real) else np.nan
    out.attrs["placebo_median_nearest"] = float(placebo["nearest_norm_dist"].median()) if len(placebo) else np.nan
    return out


# --------------------------------------------------------------------------
# Section 13: waypoint vs terminal behaviour at a zone
# --------------------------------------------------------------------------

def touch_behaviour(
    touches: pd.DataFrame,
    path: PathIndex,
    forward_hours: float = 48.0,
) -> pd.DataFrame:
    """Post-touch diagnostics for every zone touch.

    Measures penetration, reclaim and subsequent excursion in units of R so that
    "waypoint" and "terminal zone" can be separated empirically instead of by
    eye. ``adverse_R`` is the excursion in the *original* direction after the
    touch (i.e. continuation); ``reversal_R`` is the excursion back through it.
    """
    t = touches[touches["touched"]].copy()
    if t.empty:
        return pd.DataFrame()

    recs = []
    for row in t.itertuples():
        i0 = int(row.touch_idx)
        i1 = path.idx_at_or_after(pd.Timestamp(row.touch_time) + pd.Timedelta(hours=forward_hours))
        i1 = min(max(i1, i0 + 1), len(path))
        hi = path.high[i0:i1]
        lo = path.low[i0:i1]
        if len(hi) == 0:
            continue
        R = row.R
        up = row.side == "up"
        lvl = row.price

        if up:
            pen = (hi.max() - lvl) / R                      # how far beyond the level
            rev = (lvl - lo.min()) / R                      # how far back through it
            beyond = hi > lvl
            # first bar that closes the excursion out by reclaiming the level
            recl = np.argmax(lo < lvl) if (lo < lvl).any() else -1
        else:
            pen = (lvl - lo.min()) / R
            rev = (hi.max() - lvl) / R
            beyond = lo < lvl
            recl = np.argmax(hi > lvl) if (hi > lvl).any() else -1

        recs.append(
            {
                "zone_id": row.zone_id,
                "ref_id": row.ref_id,
                "kind": row.kind,
                "side": row.side,
                "k": row.k,
                "R": R,
                "touch_time": row.touch_time,
                "age_hours_at_touch": row.age_hours_at_touch,
                "ny_hour": pd.Timestamp(row.touch_time).hour,
                "max_penetration_R": float(pen),
                "max_reversal_R": float(rev),
                "bars_beyond": int(beyond.sum()),
                "bars_to_reclaim": int(recl) if recl >= 0 else -1,
                "reclaimed": bool(recl >= 0),
            }
        )
    out = pd.DataFrame(recs)
    if not out.empty:
        # A terminal zone is one price failed to extend from and then reversed
        # away from substantially; the thresholds are reported, not tuned.
        out["terminal_1R"] = (out["max_reversal_R"] >= 1.0) & (out["max_penetration_R"] <= 0.5)
        out["terminal_2R"] = (out["max_reversal_R"] >= 2.0) & (out["max_penetration_R"] <= 0.5)
        out["waypoint"] = out["max_penetration_R"] >= 1.0
    return out


def behaviour_by_bucket(beh: pd.DataFrame, by: str) -> pd.DataFrame:
    """Terminal/waypoint rates grouped by any column (ny_hour, k, kind, age...)."""
    if beh.empty:
        return pd.DataFrame()
    g = beh.groupby(by)
    out = g.agg(
        n=("zone_id", "size"),
        terminal_1R=("terminal_1R", "mean"),
        terminal_2R=("terminal_2R", "mean"),
        waypoint=("waypoint", "mean"),
        med_penetration_R=("max_penetration_R", "median"),
        med_reversal_R=("max_reversal_R", "median"),
        reclaim_rate=("reclaimed", "mean"),
    ).reset_index()
    return out.sort_values(by)


# --------------------------------------------------------------------------
# Section 5: time of day
# --------------------------------------------------------------------------

BUCKETS = [
    ("21-00", 21, 24), ("00-03", 0, 3), ("03-06", 3, 6), ("06-09.5", 6, 9.5),
    ("09.5-10", 9.5, 10), ("10-11", 10, 11), ("11-12", 11, 12),
    ("12-16", 12, 16), ("16-21", 16, 21),
]


def time_of_day_profile(times: pd.Series, bars_index: pd.DatetimeIndex) -> pd.DataFrame:
    """Event rate per NY-time bucket, normalised by how much market time each bucket holds.

    Without the exposure normalisation a 4-hour bucket trivially "wins", which
    is the most common way a time-of-day claim fools its author.
    """
    if len(times) == 0:
        return pd.DataFrame()
    ev = pd.DatetimeIndex(pd.to_datetime(times))
    ev_h = ev.hour + ev.minute / 60.0
    bar_h = bars_index.hour + bars_index.minute / 60.0

    rows = []
    for name, lo, hi in BUCKETS:
        m_ev = (ev_h >= lo) & (ev_h < hi)
        m_bar = (bar_h >= lo) & (bar_h < hi)
        share_ev = float(m_ev.mean())
        share_bar = float(m_bar.mean())
        rows.append(
            {
                "bucket": name,
                "events": int(m_ev.sum()),
                "event_share": share_ev,
                "market_time_share": share_bar,
                "lift": share_ev / share_bar if share_bar > 0 else np.nan,
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Section 9: the projection network
# --------------------------------------------------------------------------

def touch_sequence(touches: pd.DataFrame, dedupe_hours: float = 1.0) -> pd.DataFrame:
    """Chronological stream of zone touches -- the raw material for transitions.

    A dense ladder means one impulse can tag several nearby levels within
    seconds. Left alone those register as "transitions" and swamp the statistic
    with an artefact of level spacing, so touches inside ``dedupe_hours`` of the
    previous one are collapsed into a single event.
    """
    t = touches[touches["touched"]].copy()
    if t.empty:
        return t
    t = t.sort_values("touch_time").reset_index(drop=True)
    cols = ["touch_time", "zone_id", "ref_id", "kind", "side", "k", "price", "R", "age_hours_at_touch"]
    t = t[cols]

    if dedupe_hours and dedupe_hours > 0:
        keep, last = [], None
        gap = pd.Timedelta(hours=dedupe_hours)
        for i, ts in enumerate(pd.to_datetime(t["touch_time"])):
            if last is None or (ts - last) >= gap:
                keep.append(i)
                last = ts
        t = t.iloc[keep].reset_index(drop=True)
    return t


def transition_stats(seq: pd.DataFrame, max_gap_hours: float = 48.0) -> pd.DataFrame:
    """Given a touch, what kind of zone is touched next?

    Answers the 'sequential through layers vs skipping' question: whether the
    next touch tends to be the adjacent ladder step of the same candle, a
    different candle, or the opposite side entirely.
    """
    if len(seq) < 2:
        return pd.DataFrame()
    a = seq.iloc[:-1].reset_index(drop=True)
    b = seq.iloc[1:].reset_index(drop=True)
    gap = (pd.to_datetime(b["touch_time"]) - pd.to_datetime(a["touch_time"])).dt.total_seconds() / 3600.0
    m = gap <= max_gap_hours
    a, b, gap = a[m], b[m], gap[m]
    if a.empty:
        return pd.DataFrame()

    same_ref = (a["ref_id"].to_numpy() == b["ref_id"].to_numpy())
    same_side = (a["side"].to_numpy() == b["side"].to_numpy())
    dk = b["k"].to_numpy() - a["k"].to_numpy()

    return pd.DataFrame(
        [
            {"relation": "same_ref_same_side_next_step", "share": float(np.mean(same_ref & same_side & (np.abs(dk) > 0) & (np.abs(dk) <= 0.5)))},
            {"relation": "same_ref_same_side_skip", "share": float(np.mean(same_ref & same_side & (np.abs(dk) > 0.5)))},
            {"relation": "same_ref_opposite_side", "share": float(np.mean(same_ref & ~same_side))},
            {"relation": "different_ref", "share": float(np.mean(~same_ref))},
            {"relation": "median_gap_hours", "share": float(np.median(gap))},
            {"relation": "n_transitions", "share": float(len(a))},
        ]
    )
