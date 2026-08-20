#!/usr/bin/env python3
"""
Loader for the MetaTrader XAU 15m export.

The file is broker time. Every FX/metals broker of this kind runs EET/EEST -
UTC+2 in winter, UTC+3 from the last Sunday of March to the last Sunday of
October. Converting broker -> UTC -> America/New_York with the real rules is
the only safe way to do it, because the EU and US DST switch dates differ by
about three weeks each spring and autumn, and a naive fixed offset silently
moves the 21:00 anchor by an hour on those weeks.
"""
import csv
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


class Bar:
    __slots__ = ("ny", "o", "h", "l", "c", "vol", "vwap")


def _last_sunday(year, month):
    d = datetime(year, month, 31) if month != 4 else datetime(year, month, 30)
    while d.month != month:
        d -= timedelta(days=1)
    while d.weekday() != 6:
        d -= timedelta(days=1)
    return d


def _eest(dt):
    """Is this naive broker timestamp inside EEST (UTC+3)?"""
    start = _last_sunday(dt.year, 3).replace(hour=4)    # 01:00 UTC = 03:00 EET
    end   = _last_sunday(dt.year, 10).replace(hour=4)   # 01:00 UTC = 04:00 EEST
    return start <= dt < end


def load_mt5(path, since=None):
    bars = []
    with open(path) as fh:
        r = csv.reader(fh, delimiter=';')
        next(r)
        for x in r:
            try:
                bt = datetime.strptime(x[0], "%Y.%m.%d %H:%M")
            except Exception:
                continue
            if since and bt.year < since:
                continue
            off = 3 if _eest(bt) else 2
            utc = bt.replace(tzinfo=timezone.utc) - timedelta(hours=off)
            b = Bar()
            b.ny = utc.astimezone(NY)
            try:
                b.o, b.h, b.l, b.c = float(x[1]), float(x[2]), float(x[3]), float(x[4])
                b.vol = float(x[5])
            except Exception:
                continue
            if b.h < b.l or b.o <= 0:
                continue
            b.vwap = None
            bars.append(b)
    bars.sort(key=lambda z: z.ny)
    return bars


def add_vwap(bars, anchor_hour=18, src=lambda b: b.h):
    """Session-anchored VWAP, resetting at anchor_hour NY, volume weighted."""
    num = den = 0.0
    prev = None
    for b in bars:
        newsess = prev is None or (b.ny.hour >= anchor_hour and
                                   (prev.ny.hour < anchor_hour or b.ny.date() != prev.ny.date()))
        if newsess:
            num = den = 0.0
        v = b.vol if b.vol and b.vol > 0 else 1.0
        num += src(b) * v
        den += v
        b.vwap = num / den if den else None
        prev = b
    return bars


if __name__ == "__main__":
    import sys
    from collections import Counter
    bars = load_mt5(sys.argv[1], since=2015)
    print(f"  {len(bars)} bars   {bars[0].ny}  ->  {bars[-1].ny}\n")
    op, cl = Counter(), Counter()
    for i in range(1, len(bars)):
        if (bars[i].ny - bars[i-1].ny).total_seconds() / 3600 > 12:
            cl[(bars[i-1].ny.weekday(), bars[i-1].ny.hour)] += 1
            op[(bars[i].ny.weekday(), bars[i].ny.hour)] += 1
    D = "Mon Tue Wed Thu Fri Sat Sun".split()
    print("  after conversion to New York time:")
    print("    weekly close:", ", ".join(f"{D[d]} {h:02d}:xx x{n}" for (d, h), n in cl.most_common(2)))
    print("    weekly open :", ", ".join(f"{D[d]} {h:02d}:xx x{n}" for (d, h), n in op.most_common(2)))
    vol, cnt = Counter(), Counter()
    for b in bars:
        vol[b.ny.hour] += b.vol; cnt[b.ny.hour] += 1
    q = sorted((vol[h]/cnt[h], h) for h in vol)
    print(f"    quietest NY hour: {q[0][1]:02d}:xx   busiest: {q[-1][1]:02d}:xx")
    print("\n  expected: close Fri 16:xx (last bar 16:45), open Sun 18:xx, quietest 17:xx")
