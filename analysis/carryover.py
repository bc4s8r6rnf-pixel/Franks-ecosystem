#!/usr/bin/env python3
"""
The signal fires, the direction is called, and the day ends without price
reaching the zone. What happens next?

Three questions, because they have different answers:
  1. Does the OLD level - the one the call pointed at - get reached the next day,
     even though the indicator has stopped drawing it?
  2. Does the NEXT day's zone on the same side get reached?
  3. If you simply hold the trade through to the end of the next lane instead of
     flattening at midnight, does it pay?

Usage: python3 carryover.py NAME=file.csv
"""

import sys
from zone_sequence import load, build_sessions, pct, head
from stops_targets import signals, q, GAP, READ_HOUR

STOP_R = 1.25


def analyse(name, bars):
    S = build_sessions(bars)
    sigs = signals(bars, S)
    miss = [e for e in sigs if not e.hit_zone]
    hit = [e for e in sigs if e.hit_zone]

    print()
    print("=" * 78)
    print(f"  {name}   {len(sigs)} signals at {READ_HOUR:02d}:00 NY, gap >= {GAP} R")
    print(f"  Reached the zone same day: {len(hit)}    Did not: {len(miss)}")
    print("=" * 78)

    head("1. THE OLD LEVEL - does the next day reach the price it pointed at?")
    reach1 = reach2 = 0
    opp = 0
    for e in miss:
        for step, bucket in ((1, "next"), (2, "two")):
            k = e.i + step
            if k >= len(S):
                continue
            lo, hi = S[k].lo_idx, S[k].hi_idx
            got = any((bars[m].h >= e.tgt_zone) if e.side > 0 else (bars[m].l <= e.tgt_zone)
                      for m in range(lo, hi + 1))
            if step == 1 and got:
                reach1 += 1
            if step == 2 and got:
                reach2 += 1
        # did it instead run the other way, past the level it was NOT pointed at?
        k = e.i + 1
        if k < len(S):
            lo, hi = S[k].lo_idx, S[k].hi_idx
            other = S[e.i].l2 if e.side > 0 else S[e.i].u1
            if any((bars[m].l <= other) if e.side > 0 else (bars[m].h >= other)
                   for m in range(lo, hi + 1)):
                opp += 1
    print(f"  reached the called level the NEXT day        {reach1}/{len(miss)}  "
          f"({pct(reach1, len(miss)):.1f}%)")
    print(f"  reached it within TWO days                   {reach2}/{len(miss)}  "
          f"({pct(reach2, len(miss)):.1f}%)")
    print(f"  went the other way to the opposite level     {opp}/{len(miss)}  "
          f"({pct(opp, len(miss)):.1f}%)")

    head("2. THE NEXT DAY'S CALL - does the direction repeat?")
    same = diff = nosig = 0
    nxt_hit_same = nxt_n = 0
    byi = {e.i: e for e in sigs}
    for e in miss:
        n = byi.get(e.i + 1)
        if n is None:
            nosig += 1
            continue
        if n.side == e.side:
            same += 1
            nxt_n += 1
            if n.hit_zone:
                nxt_hit_same += 1
        else:
            diff += 1
    tot = same + diff
    print(f"  next day produced a signal at all            {tot}/{len(miss)}")
    if tot:
        print(f"    same direction as the missed call          {same}  ({pct(same, tot):.1f}%)")
        print(f"    opposite direction                         {diff}  ({pct(diff, tot):.1f}%)")
    if nxt_n:
        print(f"    of the repeats, reached the zone           {nxt_hit_same}/{nxt_n}  "
              f"({pct(nxt_hit_same, nxt_n):.1f}%)")

    head(f"3. HOLDING ON - same {STOP_R} R stop, but do not flatten at midnight")

    def hold(sub, lanes, target_zone=True, tgt_R=1.5):
        rs = []
        for e in sub:
            end = e.end
            k = e.i
            for _ in range(lanes):
                k += 1
                if k < len(S):
                    end = S[k].hi_idx
            sl = e.entry - e.side * STOP_R * e.r
            risk = STOP_R * e.r
            tp = e.tgt_zone if target_zone else e.entry + e.side * tgt_R * e.r
            got = None
            for m in range(e.j, end + 1):
                b = bars[m]
                if (b.l <= sl) if e.side > 0 else (b.h >= sl):
                    got = -1.0
                    break
                if (b.h >= tp) if e.side > 0 else (b.l <= tp):
                    got = abs(tp - e.entry) / risk
                    break
            if got is None:
                got = e.side * (bars[end].c - e.entry) / risk
            rs.append(got)
        w = sum(1 for r in rs if r > 0)
        return len(rs), pct(w, len(rs)), sum(rs) / len(rs), sum(rs)

    print("  held for      n    win     avgR     totR      (target = the zone edge)")
    for lanes, lbl in ((0, "the day only"), (1, "+1 day"), (2, "+2 days")):
        r = hold(sigs, lanes)
        print(f"  {lbl:<13} {r[0]:3d}  {r[1]:5.1f}%  {r[2]:+6.2f}  {r[3]:+7.1f}")
    print()
    print("  Same, on the subset that missed on day one:")
    for lanes, lbl in ((1, "+1 day"), (2, "+2 days")):
        r = hold(miss, lanes)
        print(f"  {lbl:<13} {r[0]:3d}  {r[1]:5.1f}%  {r[2]:+6.2f}  {r[3]:+7.1f}")
    print()
    print("  A flat or negative line here means midnight is the right place to quit -")
    print("  the level goes stale and holding just pays for the extra risk.")


def main():
    for spec in sys.argv[1:]:
        name, _, path = spec.partition("=")
        analyse(name, load(path))


if __name__ == "__main__":
    main()
