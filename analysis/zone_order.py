#!/usr/bin/env python3
"""
Follow-up: is the ORDER of consumption predictable, not just the first level?

zone_sequence.py established which level goes first. This asks the next
question - once price starts working through the book, does it keep going in a
readable order, and on the days that genuinely tag both sides, what decides
which side leads?

Usage: python3 zone_order.py NAME=file.csv [...]
"""

import sys
from zone_sequence import (load, build_sessions, build_book, pct, head,
                           OC_UP, OC_DN, OC_UPDN, OC_DNUP)


def analyse(name, bars):
    S = build_sessions(bars)
    n = len(S)
    books = [build_book(bars, S, i) for i in range(n)]

    print()
    print("=" * 78)
    print(f"  {name}   {n} sessions")
    print("=" * 78)

    # ---- 1. does the whole ordering follow distance, not just the first? ----
    head("FULL ORDER - is the book consumed nearest-first, all the way down?")
    pairs_ok = pairs_tot = 0
    xok = xtot = 0
    seq2 = seq2_ok = 0
    seq3 = seq3_ok = 0
    for bk in books:
        taken = sorted([L for L in bk if L.order > 0], key=lambda L: L.order)
        if len(taken) < 2:
            continue
        # Every ordered pair: was the one taken earlier also the closer one?
        # Two levels on the SAME side are ordered by geometry - you cannot reach
        # the far one without crossing the near one - so those pairs are free and
        # would inflate the score. Only opposite-side pairs carry information.
        for a in range(len(taken)):
            for b in range(a + 1, len(taken)):
                pairs_tot += 1
                ok = taken[a].dist <= taken[b].dist
                if ok:
                    pairs_ok += 1
                if taken[a].side != taken[b].side:
                    xtot += 1
                    if ok:
                        xok += 1
        pred = sorted(bk, key=lambda L: L.dist)
        seq2 += 1
        if pred[0] is taken[0] and pred[1] is taken[1]:
            seq2_ok += 1
        if len(taken) >= 3 and len(pred) >= 3:
            seq3 += 1
            if pred[0] is taken[0] and pred[1] is taken[1] and pred[2] is taken[2]:
                seq3_ok += 1
    print(f"  all pairs, nearest-first     {pct(pairs_ok, pairs_tot):5.1f}%   n={pairs_tot}"
          "   (inflated - see below)")
    print(f"  OPPOSITE-SIDE pairs only     {pct(xok, xtot):5.1f}%   n={xtot}"
          "   <- the real test, 50% = nothing")
    print(f"  first TWO in the right order {pct(seq2_ok, seq2):5.1f}%   n={seq2}")
    print(f"  first THREE in right order   {pct(seq3_ok, seq3):5.1f}%   n={seq3}")

    # ---- 2. does it keep going the same way? -------------------------------
    head("DIRECTION - once it starts, does it keep eating levels the same side?")
    for k in (2, 3, 4):
        tot = same = 0
        for bk in books:
            taken = sorted([L for L in bk if L.order > 0], key=lambda L: L.order)
            if len(taken) < k:
                continue
            tot += 1
            if all(L.side == taken[0].side for L in taken[:k]):
                same += 1
        if tot:
            print(f"  first {k} consumptions all one side   {pct(same,tot):5.1f}%   n={tot}")

    # ---- 3. the two-sided days: what decides which side leads? -------------
    head("TWO-SIDED DAYS - when both zones do get tagged, which goes first?")
    both = [i for i in range(n) if S[i].outcome in (OC_UPDN, OC_DNUP)]
    print(f"  sessions tagging both zones: {len(both)}")
    if both:
        near_ok = sum(1 for i in both if S[i].ny_px is not None and S[i].first == S[i].near)
        near_n = sum(1 for i in both if S[i].ny_px is not None)
        anch_ok = sum(1 for i in both if S[i].first == S[i].anchor_dir)
        prev_ok = prev_n = 0
        for i in both:
            if i and S[i-1].outcome in (OC_UP, OC_DN):
                prev_n += 1
                ps = 1 if S[i-1].outcome == OC_UP else -1
                if S[i].first == -ps:
                    prev_ok += 1
        print(f"    nearest at NY open led    {pct(near_ok,near_n):5.1f}%   n={near_n}")
        print(f"    9pm candle's own side led {pct(anch_ok,len(both)):5.1f}%   n={len(both)}")
        print(f"    opposite of yesterday led {pct(prev_ok,prev_n):5.1f}%   n={prev_n}")
        print("    (small n - read these as a direction to test, not a result)")

    # ---- 4. restrict to the regime the geometry says is two-sided ----------
    head("SMALL-ANCHOR DAYS ONLY - the regime where both zones are reachable")
    small = []
    for i in range(20, n):
        rank = sum(1 for k in range(i - 20, i) if S[k].rng < S[i].rng)
        if rank // 4 == 0:
            small.append(i)
    if small:
        b_ = sum(1 for i in small if S[i].outcome in (OC_UPDN, OC_DNUP))
        near_ok = sum(1 for i in small if S[i].ny_px is not None and S[i].first == S[i].near)
        near_n = sum(1 for i in small if S[i].ny_px is not None and S[i].first != 0)
        anch_ok = sum(1 for i in small if S[i].first != 0 and S[i].first == S[i].anchor_dir)
        anch_n = sum(1 for i in small if S[i].first != 0)
        print(f"  sessions in the smallest anchor quintile: {len(small)}")
        print(f"    tagged both zones          {pct(b_,len(small)):5.1f}%")
        print(f"    nearest zone led           {pct(near_ok,near_n):5.1f}%   n={near_n}")
        print(f"    9pm candle's own side led  {pct(anch_ok,anch_n):5.1f}%   n={anch_n}")


def main():
    for spec in sys.argv[1:]:
        name, _, path = spec.partition("=")
        analyse(name, load(path))


if __name__ == "__main__":
    main()
