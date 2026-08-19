#!/usr/bin/env python3
"""
Untouched zone edges attract turning points (see swing_levels.py --strict:
swing extremes are 3-4.6x more likely than an ordinary bar to sit on one).

That says the level matters. It does not say the trade works. This asks the
only question that pays: when price ARRIVES at an untouched zone edge, how
often does it turn, how far does it go, and what stop and target harvest it?

Every arrival is one event. No lookahead: the level was untouched and live
before price got there, and the trade is entered at the level itself.

Usage: python3 reversals.py NAME=file.csv [...]
"""

import sys
from zone_sequence import load, build_sessions, virgin, pct, head

LIVE_DAYS = 10
FWD_BARS = 24          # how long a reversal has to play out
STOPS = (0.25, 0.5, 0.75, 1.0)
TARGETS = (0.5, 1.0, 1.5, 2.0, 3.0)


class Ev:
    __slots__ = ("i", "j", "side", "lvl", "r", "age", "edge", "hour",
                 "anchor_q", "rev_R", "cont_R", "first")


def collect(bars, S):
    """One event per arrival at a live, untouched zone edge."""
    evs = []
    for i, s in enumerate(S):
        # how big was tonight's anchor candle against the previous 20?
        q = None
        if i >= 20:
            q = min(4, sum(1 for k in range(i - 20, i) if S[k].rng < S[i].rng) // 4)

        seen = set()
        for age in range(0, LIVE_DAYS + 1):
            k = i - age
            if k < 0:
                break
            z = S[k]
            for side in (1, -1):
                if age > 0 and not virgin(z, 0, side, s.lo_idx):
                    continue
                edges = (("inner", z.u1), ("outer", z.u2)) if side > 0 else \
                        (("inner", z.l2), ("outer", z.l1))
                for edge, lvl in edges:
                    hit = None
                    for j in range(s.lo_idx, s.hi_idx + 1):
                        if (bars[j].h >= lvl) if side > 0 else (bars[j].l <= lvl):
                            hit = j
                            break
                    if hit is None:
                        continue
                    e = Ev()
                    e.i, e.j, e.side, e.lvl, e.r = i, hit, side, lvl, s.rng
                    e.age, e.edge, e.hour = age, edge, bars[hit].ny.hour
                    e.anchor_q = q
                    e.first = lvl not in seen and not seen
                    seen.add(lvl)

                    end = min(hit + FWD_BARS, len(bars) - 1)
                    if side > 0:      # approached from below: reversal is downward
                        ext = max(bars[m].h for m in range(hit, end + 1))
                        low = min(bars[m].l for m in range(hit, end + 1))
                        e.cont_R = (ext - lvl) / s.rng
                        e.rev_R = (lvl - low) / s.rng
                    else:
                        ext = min(bars[m].l for m in range(hit, end + 1))
                        high = max(bars[m].h for m in range(hit, end + 1))
                        e.cont_R = (lvl - ext) / s.rng
                        e.rev_R = (high - lvl) / s.rng
                    evs.append(e)
    return evs


def trade(bars, e, stop_R, tgt_R):
    """Fade the level. Same-bar stop and target counts as a loss."""
    d = -e.side
    entry = e.lvl
    sl = e.lvl + e.side * stop_R * e.r
    tp = e.lvl - e.side * tgt_R * e.r
    end = min(e.j + FWD_BARS, len(bars) - 1)
    for m in range(e.j, end + 1):
        b = bars[m]
        hit_sl = b.h >= sl if d < 0 else b.l <= sl
        hit_tp = b.l <= tp if d < 0 else b.h >= tp
        if hit_sl:
            return -1.0
        if hit_tp:
            return tgt_R / stop_R
    b = bars[end]
    return d * (b.c - entry) / (stop_R * e.r)


def summarise(bars, evs, label, stop_R, tgt_R):
    rs = [trade(bars, e, stop_R, tgt_R) for e in evs]
    if not rs:
        return None
    w = sum(1 for r in rs if r > 0)
    return (label, len(rs), pct(w, len(rs)), sum(rs) / len(rs), sum(rs))


def analyse(name, bars):
    S = build_sessions(bars)
    evs = collect(bars, S)
    print()
    print("=" * 78)
    print(f"  {name}   {len(S)} sessions   {len(evs)} arrivals at an untouched zone edge")
    print("=" * 78)

    # ---- how far does price go after touching a level? ---------------------
    head("ON ARRIVAL - how far price reverses vs how far it carries on")
    print(f"  Measured over the next {FWD_BARS} bars, in units of the day's 9pm range.")
    print()
    print(f"  {'group':<22} {'n':>5} {'med rev':>9} {'med cont':>9} {'rev>cont':>10}")

    def show(lbl, sub):
        if not sub:
            return
        rev = sorted(e.rev_R for e in sub)
        con = sorted(e.cont_R for e in sub)
        beat = pct(sum(1 for e in sub if e.rev_R > e.cont_R), len(sub))
        print(f"  {lbl:<22} {len(sub):>5} {rev[len(rev)//2]:>9.2f} "
              f"{con[len(con)//2]:>9.2f} {beat:>9.1f}%")

    show("all arrivals", evs)
    show("inner edge (2.0)", [e for e in evs if e.edge == "inner"])
    show("outer edge (2.5)", [e for e in evs if e.edge == "outer"])
    show("upper zones", [e for e in evs if e.side > 0])
    show("lower zones", [e for e in evs if e.side < 0])
    show("fresh (age 0)", [e for e in evs if e.age == 0])
    show("carried (age 1+)", [e for e in evs if e.age >= 1])
    for q in range(5):
        show(f"anchor quintile {q + 1}", [e for e in evs if e.anchor_q == q])

    # ---- stop / target sweep ----------------------------------------------
    head("FADE THE LEVEL - stop and target sweep, expectancy in R")
    print("  Entry at the level, stop beyond it, target back the other way.")
    print()
    hdr = "  stop \\ target " + "".join(f"{t:>9.1f}R" for t in TARGETS)
    print(hdr)
    best = None
    for s_ in STOPS:
        row = f"  {s_:>6.2f} R      "
        for t_ in TARGETS:
            r = summarise(bars, evs, "", s_, t_)
            row += f"{r[3]:>+9.2f}"
            if best is None or r[3] > best[0]:
                best = (r[3], s_, t_, r[1], r[2])
        print(row)
    print()
    print(f"  best: stop {best[1]}R / target {best[2]}R -> "
          f"{best[0]:+.2f} R per trade, {best[4]:.1f}% win, n={best[3]}")

    # ---- does it hold out of sample? --------------------------------------
    head("OUT OF SAMPLE - the best cell, refit on each half")
    half = len(S) // 2
    for lbl, sub in (("first half", [e for e in evs if e.i < half]),
                     ("second half", [e for e in evs if e.i >= half])):
        r = summarise(bars, sub, lbl, best[1], best[2])
        if r:
            print(f"  {lbl:<14} n={r[1]:<5} win {r[2]:5.1f}%  avgR {r[3]:+6.2f}  totR {r[4]:+8.1f}")

    # ---- what filters actually help? --------------------------------------
    head(f"FILTERS - same trade (stop {best[1]}R / target {best[2]}R), split every way")
    rows = [("all arrivals", evs),
            ("inner edge only", [e for e in evs if e.edge == "inner"]),
            ("outer edge only", [e for e in evs if e.edge == "outer"]),
            ("fresh zones (age 0)", [e for e in evs if e.age == 0]),
            ("carried zones (age 1+)", [e for e in evs if e.age >= 1]),
            ("first level of the day", [e for e in evs if e.first]),
            ("upper zones", [e for e in evs if e.side > 0]),
            ("lower zones", [e for e in evs if e.side < 0])]
    for q in range(5):
        rows.append((f"anchor quintile {q + 1}", [e for e in evs if e.anchor_q == q]))
    for h0, h1, lbl in ((0, 7, "arrives 00-06 NY"), (7, 12, "arrives 07-11 NY"),
                        (12, 17, "arrives 12-16 NY"), (17, 24, "arrives 17-23 NY")):
        rows.append((lbl, [e for e in evs if h0 <= e.hour < h1]))
    print(f"  {'filter':<26} {'n':>5} {'win':>7} {'avgR':>8} {'totR':>9}")
    for lbl, sub in rows:
        r = summarise(bars, sub, lbl, best[1], best[2])
        if r and r[1] >= 15:
            print(f"  {lbl:<26} {r[1]:>5} {r[2]:>6.1f}% {r[3]:>+8.2f} {r[4]:>+9.1f}")
    print()
    print("  Costs are not modelled. Any cell with n under ~40 is a hint, not a result.")


def main():
    for spec in sys.argv[1:]:
        name, _, path = spec.partition("=")
        analyse(name, load(path))


if __name__ == "__main__":
    main()
