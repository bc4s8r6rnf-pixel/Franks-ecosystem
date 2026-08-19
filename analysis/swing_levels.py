#!/usr/bin/env python3
"""
Do swing extremes land on zone levels more often than ordinary price does?

The claim: turning points line up with a box from one of the recent days.
The trap: with many boxes on the chart, EVERY price is near one. So the only
honest test is a comparison - are swing highs and lows closer to a level than
ordinary bar highs and lows are? If pivots and non-pivots score the same, the
alignment is an illusion created by level density.

Levels tested per day: both zone edges, the zone EQ midlines, the Enigma high
and low, and the Enigma EQ - every line the indicator actually draws.

Usage: python3 swing_levels.py NAME=file.csv [...]
"""

import sys
from zone_sequence import load, build_sessions, pct, head, virgin

LIVE_DAYS = 10      # how many days of boxes count as "on the chart"
PIVOT_K = 3         # bars each side that define a swing


STRICT = "--strict" in sys.argv


def levels_of(z, bar_idx=None):
    """Every line the indicator draws for one day.

    --strict narrows this to the two daily-zone bands that price has never
    reached. Ninety-nine lines on a chart will sit near anything; a handful of
    untouched ones is the only version of the claim worth testing."""
    if STRICT:
        out = []
        if bar_idx is None or virgin(z, 0, 1, bar_idx):
            out += [("zone edge", z.u1), ("zone edge", z.u2)]
        if bar_idx is None or virgin(z, 0, -1, bar_idx):
            out += [("zone edge", z.l1), ("zone edge", z.l2)]
        return out
    return [
        ("zone edge", z.u1), ("zone edge", z.u2),
        ("zone edge", z.l1), ("zone edge", z.l2),
        ("zone EQ", (z.u1 + z.u2) / 2), ("zone EQ", (z.l1 + z.l2) / 2),
        ("enigma edge", z.rhigh), ("enigma edge", z.rlow),
        ("enigma EQ", (z.rhigh + z.rlow) / 2),
    ]


def analyse(name, bars):
    S = build_sessions(bars)
    n = len(S)

    # which session's lane does each bar belong to
    owner = {}
    for i, s in enumerate(S):
        for j in range(s.lo_idx, s.hi_idx + 1):
            owner[j] = i

    def nearest(j, price):
        """Distance to the closest live level, in units of that day's range."""
        i = owner.get(j)
        if i is None:
            return None, None
        best, lab = None, None
        for age in range(0, LIVE_DAYS + 1):
            k = i - age
            if k < 0:
                break
            for name_, lv in levels_of(S[k], j):
                d = abs(price - lv)
                if best is None or d < best:
                    best, lab = d, name_
        if best is None:          # strict mode: no untouched zone live right now
            return None, None
        return best / S[i].rng, lab

    # ---- classify every bar as a swing high / swing low / neither ----------
    piv_h, piv_l, plain = [], [], []
    for j in range(PIVOT_K, len(bars) - PIVOT_K):
        w = bars[j - PIVOT_K:j + PIVOT_K + 1]
        is_h = all(bars[j].h >= b.h for b in w) and any(bars[j].h > b.h for b in w)
        is_l = all(bars[j].l <= b.l for b in w) and any(bars[j].l < b.l for b in w)
        if is_h:
            piv_h.append(j)
        if is_l:
            piv_l.append(j)
        if not is_h and not is_l:
            plain.append(j)

    print()
    print("=" * 78)
    print(f"  {name}   {n} sessions   {len(piv_h)} swing highs   {len(piv_l)} swing lows")
    per = 4 if STRICT else 9
    print(f"  Mode: {'STRICT - untouched daily-zone edges only' if STRICT else 'ALL lines the indicator draws'}"
          f"   (up to {(LIVE_DAYS + 1) * per} lines live)")
    print("=" * 78)

    def summarise(label, idxs, use_high):
        ds = []
        labs = {}
        for j in idxs:
            d, lab = nearest(j, bars[j].h if use_high else bars[j].l)
            if d is None:
                continue
            ds.append(d)
            labs[lab] = labs.get(lab, 0) + 1
        if not ds:
            return None
        ds.sort()
        return {
            "n": len(ds),
            "median": ds[len(ds) // 2],
            "w10": pct(sum(1 for d in ds if d <= 0.10), len(ds)),
            "w25": pct(sum(1 for d in ds if d <= 0.25), len(ds)),
            "w50": pct(sum(1 for d in ds if d <= 0.50), len(ds)),
            "labs": labs,
        }

    head("ARE SWING EXTREMES CLOSER TO A LEVEL THAN ORDINARY BARS?")
    print("  Distance to the nearest drawn line, in units of that day's 9pm range.")
    print()
    print(f"  {'group':<26} {'n':>6} {'median':>8} {'within .10':>11} "
          f"{'within .25':>11} {'within .50':>11}")

    rows = [
        ("swing highs", piv_h, True),
        ("ordinary bar highs", plain, True),
        ("swing lows", piv_l, False),
        ("ordinary bar lows", plain, False),
    ]
    got = {}
    for lab, idxs, hi in rows:
        r = summarise(lab, idxs, hi)
        if not r:
            continue
        got[lab] = r
        print(f"  {lab:<26} {r['n']:>6} {r['median']:>8.3f} {r['w10']:>10.1f}% "
              f"{r['w25']:>10.1f}% {r['w50']:>10.1f}%")

    head("THE VERDICT")
    for a, b in (("swing highs", "ordinary bar highs"), ("swing lows", "ordinary bar lows")):
        if a in got and b in got and got[b]["w25"] > 0:
            print(f"  {a:<14} are {got[a]['w25']/got[b]['w25']:.1f}x more likely than an "
                  f"ordinary bar to sit within .25 R of a line")
    print()
    for a, b in (("swing highs", "ordinary bar highs"), ("swing lows", "ordinary bar lows")):
        if a in got and b in got:
            edge = got[a]["w25"] - got[b]["w25"]
            print(f"  {a:<14} vs {b:<20} within .25 R:  "
                  f"{got[a]['w25']:5.1f}% vs {got[b]['w25']:5.1f}%   edge {edge:+5.1f} points")
    print()
    print("  An edge near zero means swing points are no closer to the boxes than any")
    print("  other bar - the alignment is the density of the levels, not a signal.")
    print("  An edge of several points means turning points really do seek the lines.")

    head("WHICH LINE DO SWINGS SIT ON?")
    for lab in ("swing highs", "swing lows"):
        if lab not in got:
            continue
        tot = sum(got[lab]["labs"].values())
        parts = ", ".join(f"{k} {pct(v,tot):.0f}%"
                          for k, v in sorted(got[lab]["labs"].items(), key=lambda x: -x[1]))
        print(f"  {lab:<14} {parts}")


def main():
    for spec in sys.argv[1:]:
        if spec.startswith("--"):
            continue
        name, _, path = spec.partition("=")
        analyse(name, load(path))


if __name__ == "__main__":
    main()
