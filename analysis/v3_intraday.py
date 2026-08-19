#!/usr/bin/env python3
"""
v3: the same trade, measured at 15-minute resolution with the real VWAP.

Two things change against v2. The anchor is now built by aggregating every bar
inside the 21:00 New York hour rather than reading one hourly candle, so the
same code works on any intraday timeframe. And VWAP is the genuine volume-
weighted figure exported from the chart, not the TWAP stand-in.

Everything else is v2: stop behind the 9pm box plus a buffer, target the near
edge of the projection box (capped at 2:1), optional patient entry waiting for
VWAP / box edge / the 50% level of the combined Asia-London range, optional
flat at 16:55 New York.

Run the same config against H1 and 15m over the same dates and the difference
is the resolution, not the strategy.

Usage: python3 v3_intraday.py NAME=file.csv [NAME2=file2.csv ...]
"""

import csv
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from zone_sequence import pct

NY = ZoneInfo("America/New_York")
PIP = 0.10
SRC_HOUR, CALL_HOUR, FLAT_HOUR = 21, 4, 16
ASIA_START, FILL_DEADLINE = 18, 12
LVL1 = 2.0


class Bar:
    __slots__ = ("ny", "o", "h", "l", "c", "vwap")


def load(path):
    bars = []
    for row in csv.DictReader(open(path, newline="")):
        t = row.get("time")
        if not t:
            continue
        b = Bar()
        b.ny = datetime.fromtimestamp(int(float(t)), NY)
        b.o, b.h, b.l, b.c = (float(row["open"]), float(row["high"]),
                              float(row["low"]), float(row["close"]))
        v = row.get("VWAP") or row.get("vwap") or ""
        b.vwap = float(v) if v.strip() else None
        bars.append(b)
    bars.sort(key=lambda x: x.ny)
    return bars


class Sess:
    __slots__ = ("day", "rhigh", "rlow", "rng", "u1", "l2", "lo", "hi", "call", "flat")


def sessions(bars):
    """One per 21:00 NY hour, whatever the bar size."""
    idx = {}
    for i, b in enumerate(bars):
        idx.setdefault(b.ny.date(), []).append(i)
    out = []
    last = bars[-1].ny
    for d in sorted(idx):
        an = [i for i in idx[d] if bars[i].ny.hour == SRC_HOUR]
        if not an:
            continue
        hi = max(bars[i].h for i in an)
        lo = min(bars[i].l for i in an)
        if hi <= lo:
            continue
        d0 = d + timedelta(days=1)
        ls = datetime(d0.year, d0.month, d0.day, tzinfo=NY)
        le = ls + timedelta(days=1)
        if le > last:
            continue
        ids = [i for i in range(an[-1] + 1, len(bars)) if ls <= bars[i].ny < le]
        if len(ids) < 20:
            continue
        s = Sess()
        s.day, s.rhigh, s.rlow, s.rng = ls, hi, lo, hi - lo
        s.u1, s.l2 = hi + LVL1 * s.rng, lo - LVL1 * s.rng
        s.lo, s.hi = ids[0], ids[-1]
        s.call = next((i for i in ids if bars[i].ny.hour >= CALL_HOUR), None)
        s.flat = next((i for i in ids if bars[i].ny.hour >= FLAT_HOUR), s.hi)
        if s.call is None:
            continue
        out.append(s)
    return out


def vwap_at(bars, s, i):
    if bars[i].vwap is not None:
        return bars[i].vwap
    acc = [(bars[m].h + bars[m].l + bars[m].c) / 3 for m in range(s.lo, i + 1)]
    return sum(acc) / len(acc)


def trade(bars, S, k, cfg):
    s = S[k]
    px = bars[s.call].o
    d_up, d_dn = (s.u1 - px) / s.rng, (px - s.l2) / s.rng
    if d_up <= 0 and d_dn <= 0:
        return None
    side = 1 if d_up < d_dn else -1

    proj = s.u1 if side > 0 else s.l2
    if (side > 0 and proj <= px) or (side < 0 and proj >= px):
        proj = None

    ebar, entry, waited = s.call, px, False
    box_edge = s.rlow if side > 0 else s.rhigh
    run = (px - s.rhigh) / s.rng if side > 0 else (s.rlow - px) / s.rng

    if cfg["patient"] and run > cfg["run_thresh"]:
        a0 = next((i for i in range(s.lo, s.call + 1)
                   if bars[i].ny.hour >= ASIA_START), s.lo)
        rh = max(bars[m].h for m in range(a0, s.call + 1))
        rl = min(bars[m].l for m in range(a0, s.call + 1))
        cands = [c for c in (vwap_at(bars, s, s.call), box_edge, (rh + rl) / 2)
                 if (c < px if side > 0 else c > px)]
        if cands:
            dead = next((i for i in range(s.call, s.hi + 1)
                         if bars[i].ny.hour >= FILL_DEADLINE), s.flat)
            if cfg["first_touch"]:
                # Whichever level price reaches first. Within one bar the shallowest
                # retracement is the one it met on the way, so that is the fill.
                fb = lvl = None
                for m in range(s.call, dead + 1):
                    hit = [c for c in cands
                           if ((bars[m].l <= c) if side > 0 else (bars[m].h >= c))]
                    if hit:
                        fb = m
                        lvl = max(hit) if side > 0 else min(hit)
                        break
            else:
                lvl = min(cands, key=lambda c: abs(c - box_edge))
                fb = next((m for m in range(s.call, dead + 1)
                           if ((bars[m].l <= lvl) if side > 0 else (bars[m].h >= lvl))), None)
            if fb is None:
                return None
            ebar, entry, waited = fb, lvl, True

    stop = ((s.rlow - cfg["buffer"]) if side > 0 else (s.rhigh + cfg["buffer"])) \
        if cfg["stop_mode"] == "box" else entry - side * cfg["flat_R"] * s.rng
    risk = abs(entry - stop)
    if risk <= 0:
        return None

    two = entry + side * 2.0 * risk
    if proj is None or (side > 0 and proj <= entry) or (side < 0 and proj >= entry):
        tgt = two
    elif cfg["cap_2to1"] and abs(two - entry) < abs(proj - entry):
        tgt = two
    else:
        tgt = proj

    last = s.flat if cfg["flat_at_close"] else s.hi
    rr = abs(tgt - entry) / risk
    for m in range(ebar, last + 1):
        b = bars[m]
        if (b.l <= stop) if side > 0 else (b.h >= stop):
            return dict(r=-1.0, rr=rr, risk=risk, waited=waited, out="stop")
        if (b.h >= tgt) if side > 0 else (b.l <= tgt):
            return dict(r=rr, rr=rr, risk=risk, waited=waited, out="target")
    return dict(r=side * (bars[last].c - entry) / risk, rr=rr, risk=risk,
                waited=waited, out="timeout")


BASE = dict(patient=False, run_thresh=0.5, buffer=2.0, stop_mode="box",
            flat_R=1.25, cap_2to1=True, flat_at_close=True, first_touch=True)


def cfg(**kw):
    c = dict(BASE)
    c.update(kw)
    return c


def run(bars, S, c, lo=None, hi=None):
    ts = []
    for k, s in enumerate(S):
        if lo and s.day < lo:
            continue
        if hi and s.day > hi:
            continue
        t = trade(bars, S, k, c)
        if t:
            ts.append(t)
    if not ts:
        return None
    w = sum(1 for t in ts if t["r"] > 0)
    return dict(n=len(ts), win=pct(w, len(ts)), avg=sum(t["r"] for t in ts) / len(ts),
                tot=sum(t["r"] for t in ts), rr=sum(t["rr"] for t in ts) / len(ts),
                risk=sum(t["risk"] for t in ts) / len(ts),
                waited=pct(sum(1 for t in ts if t["waited"]), len(ts)))


HDR = (f"  {'variant':<34} {'n':>4} {'win':>7} {'avgR':>7} {'totR':>7} "
       f"{'RR':>6} {'risk$':>8} {'waited':>7}")


def row(lbl, r):
    if not r:
        print(f"  {lbl:<34} no trades")
        return
    print(f"  {lbl:<34} {r['n']:4d} {r['win']:6.1f}% {r['avg']:+7.2f} {r['tot']:+7.1f} "
          f"{r['rr']:6.2f} {r['risk']:8.2f} {r['waited']:6.1f}%")


def main():
    for spec in sys.argv[1:]:
        name, _, path = spec.partition("=")
        bars = load(path)
        S = sessions(bars)
        has_v = any(b.vwap is not None for b in bars)
        print()
        print("=" * 92)
        print(f"  {name}   {len(S)} sessions   {S[0].day:%Y-%m-%d} -> {S[-1].day:%Y-%m-%d}"
              f"   VWAP: {'real' if has_v else 'TWAP proxy'}")
        print("=" * 92)

        print("\n--- STOP BUFFER BEHIND THE 9PM BOX ---")
        print(HDR)
        for b in (0.0, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0):
            row(f"box - ${b:.2f} ({b/PIP:.0f}p)", run(bars, S, cfg(buffer=b)))
        row("flat 1.25 R stop", run(bars, S, cfg(stop_mode="flat")))

        print("\n--- PATIENT ENTRY (real VWAP / box edge / 50% Asia-London) ---")
        print(HDR)
        row("enter at the call", run(bars, S, cfg()))
        for th in (0.0, 0.25, 0.5, 0.75, 1.0):
            row(f"wait when run > {th:.2f} R", run(bars, S, cfg(patient=True, run_thresh=th)))

        print("\n--- FLAT AT 16:55 vs HOLD TO MIDNIGHT ---")
        print(HDR)
        for pat in (False, True):
            for fl in (True, False):
                row(("patient" if pat else "at call") + (", flat 16:55" if fl else ", midnight"),
                    run(bars, S, cfg(patient=pat, flat_at_close=fl)))

        print("\n--- TARGET ---")
        print(HDR)
        row("capped at 2:1", run(bars, S, cfg(patient=True, cap_2to1=True)))
        row("uncapped", run(bars, S, cfg(patient=True, cap_2to1=False)))


if __name__ == "__main__":
    main()
