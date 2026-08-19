#!/usr/bin/env python3
"""
Given the direction call, where does the stop go and where does the target go?

Entry is the open of the read-hour bar, direction from the call (one inner
zone edge at least `GAP` R closer than the other). Everything below is
measured on those trades only, and every trade is closed at the end of the
lane if neither level is hit - the zones expire at midnight.

  "A stop that is safe"      -> the MAE distribution on trades that DID reach
                                the zone. A stop inside that band would have
                                thrown away a winner.
  "A target that will hit"   -> how often each candidate target is reached,
                                not just what it pays.

Usage: python3 stops_targets.py NAME=file.csv [...]
"""

import sys
from zone_sequence import load, build_sessions, pct, head

READ_HOUR = 8
GAP = 1.5
LVL1 = 2.0

STOPS = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0)
TARGETS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)


class Sig:
    __slots__ = ("i", "j", "side", "entry", "r", "tgt_zone", "dist", "gap",
                 "mae", "mfe", "hit_zone", "bars_to_zone", "end")


def signals(bars, S):
    out = []
    for i, s in enumerate(S):
        j = next((k for k in range(s.lo_idx, s.hi_idx + 1)
                  if bars[k].ny.hour >= READ_HOUR), None)
        if j is None:
            continue
        p = bars[j].o
        d_up, d_dn = (s.u1 - p) / s.rng, (p - s.l2) / s.rng
        if d_up <= 0 or d_dn <= 0:          # a zone was already reached
            continue
        if abs(d_up - d_dn) < GAP:
            continue

        e = Sig()
        e.i, e.j, e.r, e.end = i, j, s.rng, s.hi_idx
        e.side = 1 if d_up < d_dn else -1
        e.entry = p
        e.gap = abs(d_up - d_dn)
        e.tgt_zone = s.u1 if e.side > 0 else s.l2
        e.dist = min(d_up, d_dn)            # how far to the target, in R

        # excursions from entry to the end of the lane, in R
        adverse = favour = 0.0
        e.hit_zone, e.bars_to_zone = False, None
        for m in range(j, s.hi_idx + 1):
            b = bars[m]
            if e.side > 0:
                favour = max(favour, (b.h - p) / s.rng)
                if not e.hit_zone:
                    adverse = max(adverse, (p - b.l) / s.rng)
                if b.h >= e.tgt_zone and not e.hit_zone:
                    e.hit_zone, e.bars_to_zone = True, m - j
            else:
                favour = max(favour, (p - b.l) / s.rng)
                if not e.hit_zone:
                    adverse = max(adverse, (b.h - p) / s.rng)
                if b.l <= e.tgt_zone and not e.hit_zone:
                    e.hit_zone, e.bars_to_zone = True, m - j
        e.mae, e.mfe = adverse, favour
        out.append(e)
    return out


def q(vals, f):
    v = sorted(vals)
    return v[min(len(v) - 1, int(f * len(v)))] if v else 0.0


def run(bars, sigs, stop_R, tgt, zone_target):
    """tgt is an R multiple, or ignored when zone_target is True."""
    rs = []
    for e in sigs:
        sl = e.entry - e.side * stop_R * e.r
        tp = e.tgt_zone if zone_target else e.entry + e.side * tgt * e.r
        risk = stop_R * e.r
        reward = abs(tp - e.entry)
        got = None
        for m in range(e.j, e.end + 1):
            b = bars[m]
            hit_sl = b.l <= sl if e.side > 0 else b.h >= sl
            hit_tp = b.h >= tp if e.side > 0 else b.l <= tp
            if hit_sl:                      # same bar as target -> counted a loss
                got = -1.0
                break
            if hit_tp:
                got = reward / risk
                break
        if got is None:
            got = e.side * (bars[e.end].c - e.entry) / risk
        rs.append(got)
    if not rs:
        return None
    w = sum(1 for r in rs if r > 0)
    return len(rs), pct(w, len(rs)), sum(rs) / len(rs), sum(rs)


def scale_out(bars, sigs, stop_R, frac, runner_R):
    """Bank `frac` at the zone edge, move the stop to entry, run the rest."""
    rs = []
    for e in sigs:
        sl, risk = e.entry - e.side * stop_R * e.r, stop_R * e.r
        tp1, tp2 = e.tgt_zone, e.entry + e.side * runner_R * e.r
        banked, part, got = 0.0, False, None
        for m in range(e.j, e.end + 1):
            b = bars[m]
            if (b.l <= sl) if e.side > 0 else (b.h >= sl):
                got = banked if part else -1.0     # after the partial the stop is at entry
                break
            if not part and ((b.h >= tp1) if e.side > 0 else (b.l <= tp1)):
                banked, part, sl = frac * abs(tp1 - e.entry) / risk, True, e.entry
            if part and ((b.h >= tp2) if e.side > 0 else (b.l <= tp2)):
                got = banked + (1 - frac) * abs(tp2 - e.entry) / risk
                break
        if got is None:
            rem = (1 - frac if part else 1.0) * e.side * (bars[e.end].c - e.entry) / risk
            got = (banked if part else 0.0) + rem
        rs.append(got)
    w = sum(1 for r in rs if r > 0)
    return len(rs), pct(w, len(rs)), sum(rs) / len(rs), sum(rs)


def analyse(name, bars):
    S = build_sessions(bars)
    sigs = signals(bars, S)
    hit = [e for e in sigs if e.hit_zone]
    print()
    print("=" * 78)
    print(f"  {name}   {len(sigs)} signals at {READ_HOUR:02d}:00 NY, gap >= {GAP} R")
    print(f"  Reached the target zone: {len(hit)} ({pct(len(hit), len(sigs)):.1f}%)")
    print("=" * 78)

    # ---- the safe stop -----------------------------------------------------
    head("A SAFE STOP - how far price went AGAINST the winners before paying")
    print("  Measured on the trades that did reach the zone. A stop inside these")
    print("  numbers would have thrown the winner away.")
    print()
    for f, lbl in ((0.5, "median"), (0.75, "75th pct"), (0.9, "90th pct"),
                   (0.95, "95th pct"), (1.0, "worst")):
        print(f"    {lbl:<10} {q([e.mae for e in hit], f):.2f} R")
    print()
    print("  survives   stop needed")
    for f in (0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0):
        print(f"    {f*100:4.0f}%      {q([e.mae for e in hit], f):.2f} R")

    # ---- the target --------------------------------------------------------
    head("A TARGET THAT HITS - how often each one is actually reached")
    print("  target                    reached   median bars to get there")
    print(f"    the zone edge itself     {pct(len(hit), len(sigs)):5.1f}%     "
          f"{q([e.bars_to_zone for e in hit], 0.5):.0f}")
    for t in TARGETS:
        n = sum(1 for e in sigs if e.mfe >= t)
        print(f"    {t:.2f} R from entry        {pct(n, len(sigs)):5.1f}%")
    print()
    print(f"  Distance to the zone edge: median {q([e.dist for e in sigs], 0.5):.2f} R, "
          f"25th {q([e.dist for e in sigs], 0.25):.2f} R, 75th {q([e.dist for e in sigs], 0.75):.2f} R")

    # ---- the grid ----------------------------------------------------------
    head("EXPECTANCY GRID - average R per trade")
    print("  stop \\ target  " + "".join(f"{t:>8.2f}R" for t in TARGETS) + "     zone")
    best = None
    for s_ in STOPS:
        row = f"  {s_:>5.2f} R       "
        for t_ in TARGETS:
            r = run(bars, sigs, s_, t_, False)
            row += f"{r[2]:>+9.2f}"
            if best is None or r[2] > best[0]:
                best = (r[2], s_, t_, False, r)
        rz = run(bars, sigs, s_, 0, True)
        row += f"{rz[2]:>+9.2f}"
        if rz[2] > best[0]:
            best = (rz[2], s_, 0, True, rz)
        print(row)
    tl = "the zone edge" if best[3] else f"{best[2]:.2f} R"
    print()
    print(f"  best: stop {best[1]:.2f} R, target {tl}  ->  "
          f"{best[0]:+.2f} R per trade, {best[4][1]:.1f}% win, n={best[4][0]}")

    # ---- does it survive a split? -----------------------------------------
    head("OUT OF SAMPLE - the best cell on each half")
    half = len(S) // 2
    for lbl, sub in (("first half", [e for e in sigs if e.i < half]),
                     ("second half", [e for e in sigs if e.i >= half])):
        r = run(bars, sub, best[1], best[2], best[3])
        if r:
            print(f"  {lbl:<13} n={r[0]:<4} win {r[1]:5.1f}%  avgR {r[2]:+6.2f}  totR {r[3]:+7.1f}")

    # ---- a couple of sane fixed choices -----------------------------------
    head("SENSIBLE CHOICES - not the peak of the grid, the robust neighbourhood")
    for s_, t_, z, lbl in ((1.0, 0, True, "stop 1.00 R, target the zone edge"),
                           (1.25, 0, True, "stop 1.25 R, target the zone edge"),
                           (1.0, 1.0, False, "stop 1.00 R, target 1.00 R"),
                           (1.25, 1.5, False, "stop 1.25 R, target 1.50 R"),
                           (1.5, 0, True, "stop 1.50 R, target the zone edge")):
        r = run(bars, sigs, s_, t_, z)
        if r:
            print(f"  {lbl:<38} n={r[0]:<4} win {r[1]:5.1f}%  "
                  f"avgR {r[2]:+6.2f}  totR {r[3]:+7.1f}")
    print()
    head("SCALING OUT - bank half at the zone edge, stop to entry, run the rest")
    print("  The zone edge is reached in a median of 2 bars, so the partial comes fast.")
    print()
    print("  stop   bank   runner    n    win     avgR     totR")
    for st in (1.0, 1.25, 1.5):
        for fr in (0.5, 0.7):
            for rn in (2.0, 3.0):
                r = scale_out(bars, sigs, st, fr, rn)
                print(f"  {st:.2f}R   {fr*100:.0f}%    {rn:.1f}R   {r[0]:4d}  {r[1]:5.1f}%  "
                      f"{r[2]:+6.2f}  {r[3]:+7.1f}")
    print()
    rr = [e.r for e in sigs]
    print(f"  For scale: median R on signal days = {q(rr, 0.5):.2f} "
          f"(25th {q(rr, 0.25):.1f}, 75th {q(rr, 0.75):.1f})")
    print()
    print("  Costs are not modelled. Pick from the middle of a good region, never the")
    print("  single best cell - that cell is where the noise happened to land.")


def main():
    for spec in sys.argv[1:]:
        name, _, path = spec.partition("=")
        analyse(name, load(path))


if __name__ == "__main__":
    main()
