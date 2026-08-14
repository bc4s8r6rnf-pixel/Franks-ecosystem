"""Correctness tests for the projection engine.

These check the things that would silently corrupt every downstream statistic:
projection arithmetic, first-touch resolution, timezone/DST handling, and the
absence of lookahead in zone activation.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nqproj import analysis as A
from nqproj import data as D
from nqproj import projections as P
from nqproj import swings as S

NY = "America/New_York"


def _bars(prices, start="2021-03-01 00:00", freq="1min"):
    """Minute bars whose high/low straddle each close by a fixed tick."""
    idx = pd.date_range(pd.Timestamp(start, tz=NY), periods=len(prices), freq=freq)
    p = np.asarray(prices, dtype=float)
    return D.from_frame(
        pd.DataFrame({"open": p, "high": p + 0.25, "low": p - 0.25, "close": p}, index=idx)
    )


def test_projection_arithmetic():
    refs = pd.DataFrame([{"ref_id": 0, "ref_time": pd.Timestamp("2021-03-01 21:00", tz=NY),
                          "kind": "9PM", "H": 100.0, "L": 90.0, "R": 10.0,
                          "activate": pd.Timestamp("2021-03-01 22:00", tz=NY)}])
    z = P.build_zones(refs, ladder=(2.0, 2.5))
    up = z[z["side"] == "up"].set_index("k")["price"]
    dn = z[z["side"] == "down"].set_index("k")["price"]
    assert up[2.0] == 120.0 and up[2.5] == 125.0, "H + kR"
    assert dn[2.0] == 70.0 and dn[2.5] == 65.0, "L - kR"
    print("ok projection arithmetic")


def test_reference_candle_and_activation():
    """9PM candle is the 21:00-22:00 hour and cannot be used before it closes."""
    n = 60 * 30
    bs = _bars(np.full(n, 100.0) + np.arange(n) * 0.0, start="2021-03-01 00:00")
    b = bs.bars.copy()
    mask = (b.index.hour == 21) & (b.index.day == 1)
    b.loc[mask, "high"] = 110.0
    b.loc[mask, "low"] = 90.0
    bs2 = D.from_frame(b)

    refs = P.build_reference_candles(bs2, kinds=("9PM",))
    r = refs.iloc[0]
    assert r["ref_time"].hour == 21
    assert r["H"] == 110.0 and r["L"] == 90.0 and r["R"] == 20.0
    assert r["activate"] == r["ref_time"] + pd.Timedelta(hours=1), "no lookahead"
    print("ok reference candle + activation")


def test_first_touch():
    prices = np.array([100, 101, 102, 105, 103, 99, 95, 108], dtype=float)
    bs = _bars(prices)
    path = P.PathIndex.from_barset(bs)

    assert path.first_touch(0, len(prices), 104.0, up=True) == 3
    assert path.first_touch(0, len(prices), 96.0, up=False) == 6
    assert path.first_touch(0, len(prices), 200.0, up=True) == -1
    # window is respected
    assert path.first_touch(0, 3, 104.0, up=True) == -1
    # searching from after the event finds the later occurrence, not the earlier
    assert path.first_touch(4, len(prices), 104.0, up=True) == 7
    print("ok first touch")


def test_opposite_zone_logic():
    """Hand-built path: up-2.0 touched first, then down-2.0 reached."""
    n = 60 * 26
    p = np.full(n, 100.0)
    bs = _bars(p, start="2021-06-01 00:00")
    b = bs.bars.copy()

    ref_mask = (b.index.hour == 21) & (b.index.day == 1)
    b.loc[ref_mask, "high"] = 110.0
    b.loc[ref_mask, "low"] = 100.0          # H=110 L=100 R=10 -> up2.0=130, down2.0=80

    after = b.index > pd.Timestamp("2021-06-01 22:00", tz=NY)
    hits_up = after & (b.index < pd.Timestamp("2021-06-01 23:00", tz=NY))
    b.loc[hits_up, "high"] = 131.0
    hits_dn = b.index > pd.Timestamp("2021-06-02 00:00", tz=NY)
    b.loc[hits_dn, "low"] = 79.0

    bs2 = D.from_frame(b)
    refs = P.build_reference_candles(bs2, kinds=("9PM",))
    path = P.PathIndex.from_barset(bs2)
    res = A.opposite_zone_test(refs, path, k=2.0, windows_hours=(72.0,))

    row = res.iloc[0]
    assert row["first_side"] == "up", row["first_side"]
    assert bool(row["within_72h"]) is True
    print("ok opposite-zone logic")


def test_dst_hours_are_wall_clock():
    """21:00 NY stays 21:00 across a DST boundary (fixed-offset code would drift)."""
    idx = pd.date_range(pd.Timestamp("2021-03-12 00:00", tz="UTC"), periods=60 * 24 * 5, freq="1min")
    df = pd.DataFrame({"open": 1.0, "high": 1.25, "low": 0.75, "close": 1.0}, index=idx)
    bs = D.from_frame(df)
    refs = P.build_reference_candles(bs, kinds=("9PM",), min_range=-1.0)
    assert set(pd.DatetimeIndex(refs["ref_time"]).hour) == {21}
    assert len(refs) >= 4
    print("ok DST wall-clock")


def test_zigzag_alternates():
    t = np.linspace(0, 6 * np.pi, 2000)
    p = 100 + 10 * np.sin(t)
    bs = _bars(p, freq="1h")
    hourly = bs.hourly()
    th = pd.Series(5.0, index=hourly.index)
    piv = S.zigzag(hourly, th)
    kinds = piv["kind"].tolist()
    assert len(piv) >= 4
    assert all(a != b for a, b in zip(kinds, kinds[1:])), "pivots must alternate"
    assert (piv["confirm_time"] >= piv["time"]).all(), "confirmation cannot precede the pivot"
    print("ok zigzag alternation")


def test_active_zones_respect_time():
    refs = pd.DataFrame([
        {"ref_id": 0, "ref_time": pd.Timestamp("2021-03-01 21:00", tz=NY), "kind": "9PM",
         "H": 100.0, "L": 90.0, "R": 10.0, "activate": pd.Timestamp("2021-03-01 22:00", tz=NY)},
        {"ref_id": 1, "ref_time": pd.Timestamp("2021-03-05 21:00", tz=NY), "kind": "9PM",
         "H": 100.0, "L": 90.0, "R": 10.0, "activate": pd.Timestamp("2021-03-05 22:00", tz=NY)},
    ])
    z = P.build_zones(refs, ladder=(2.0,))
    at = P.active_zones_at(z, pd.Timestamp("2021-03-03 12:00", tz=NY), max_age_days=10)
    assert set(at["ref_id"]) == {0}, "future candle must not be visible"
    aged = P.active_zones_at(z, pd.Timestamp("2021-03-06 12:00", tz=NY), max_age_days=2)
    assert set(aged["ref_id"]) == {1}, "expired candle must drop out"
    print("ok point-in-time zone map")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns:
        f()
    print(f"\n{len(fns)} tests passed")
