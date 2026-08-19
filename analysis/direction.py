#!/usr/bin/env python3
"""
Which zone does the day go to, and when can you know?

For every hour of the lane this asks: if I read the chart NOW and call the
side, how often am I right about the NEXT zone tagged? Only tags at or after
the reading hour count - a zone already tagged before you looked is not a
prediction. It also reports how far price still has to travel when the call is
made, because a 100% call with nothing left to travel is not a call at all.

Usage: python3 direction.py NAME=file.csv [...]
"""

import sys
from zone_sequence import load, build_sessions, pct, head


def tags_of(bars, s):
    """Every moment either zone is tagged: (bar index, side)."""
    out = []
    seen_u = seen_l = False
    for j in range(s.lo_idx, s.hi_idx + 1):
        if not seen_u and bars[j].h >= s.u1:
            out.append((j, 1))
            seen_u = True
        if not seen_l and bars[j].l <= s.l2:
            out.append((j, -1))
            seen_l = True
    out.sort()
    return out


def analyse(name, bars):
    S = build_sessions(bars)
    n = len(S)
    tags = [tags_of(bars, s) for s in S]

    print()
    print("=" * 78)
    print(f"  {name}   {n} sessions")
    print(f"  Days that tag a zone at all: {pct(sum(1 for s in S if s.first), n):.1f}%")
    print("=" * 78)

    def read_at(i, hour):
        """The call you would make reading the chart at this NY hour."""
        s = S[i]
        bar = next((j for j in range(s.lo_idx, s.hi_idx + 1)
                    if bars[j].ny.hour == hour), None)
        if bar is None:
            return None
        p = bars[bar].o
        d_up, d_dn = (s.u1 - p) / s.rng, (p - s.l2) / s.rng
        if d_up <= 0 or d_dn <= 0:
            return None                      # a zone is already tagged; nothing to call
        pred = 1 if d_up < d_dn else -1
        nxt = next(((j, sd) for j, sd in tags[i] if j >= bar), None)
        if nxt is None:
            return None                      # no zone tagged after this hour
        return {"pred": pred, "actual": nxt[1], "gap": abs(d_up - d_dn),
                "travel": min(d_up, d_dn), "i": i}

    # ---- 1. which hour gives the best call? --------------------------------
    head("ACCURACY BY READING HOUR - 'the nearest zone is the next one tagged'")
    print("  hour    calls   correct   coverage   median travel still to go")
    best_hour, best_acc = None, -1
    for h in list(range(0, 24)):
        rs = [r for i in range(n) if (r := read_at(i, h))]
        if len(rs) < 20:
            continue
        ok = sum(1 for r in rs if r["pred"] == r["actual"])
        tv = sorted(r["travel"] for r in rs)
        acc = pct(ok, len(rs))
        print(f"  {h:02d}:00   {len(rs):5d}   {acc:6.1f}%   {pct(len(rs),n):6.1f}%"
              f"        {tv[len(tv)//2]:.2f} R")
        if acc > best_acc:
            best_acc, best_hour = acc, h

    # ---- 2. at the best hour, does conviction help? ------------------------
    head(f"AT {best_hour:02d}:00 NY - accuracy by how lopsided the read is")
    rs = [r for i in range(n) if (r := read_at(i, best_hour))]
    print("  gap band        calls   correct   median travel")
    for lo, hi, lbl in ((0, .5, "0.0 - 0.5 R"), (.5, 1.0, "0.5 - 1.0 R"),
                        (1.0, 2.0, "1.0 - 2.0 R"), (2.0, 99, "2.0 R +   ")):
        sub = [r for r in rs if lo <= r["gap"] < hi]
        if not sub:
            continue
        ok = sum(1 for r in sub if r["pred"] == r["actual"])
        tv = sorted(r["travel"] for r in sub)
        print(f"  {lbl}    {len(sub):5d}   {pct(ok,len(sub)):6.1f}%      {tv[len(tv)//2]:.2f} R")

    # ---- 3. the practical recipe: every hour x conviction threshold --------
    head("THE RECIPE - accuracy vs how many days you actually get to trade")
    print("  Only taking the call when the gap clears a threshold.")
    print()
    print("  hour   gap>=0.5        gap>=1.0        gap>=1.5        gap>=2.0")
    print("         acc    n         acc    n         acc    n         acc    n")
    for h in range(0, 24):
        hr_rs = [r for i in range(n) if (r := read_at(i, h))]
        if len(hr_rs) < 20:
            continue
        cells = []
        for g in (0.5, 1.0, 1.5, 2.0):
            sub = [r for r in hr_rs if r["gap"] >= g]
            if len(sub) < 10:
                cells.append("    -     -  ")
                continue
            ok = sum(1 for r in sub if r["pred"] == r["actual"])
            cells.append(f"{pct(ok,len(sub)):6.1f}% {len(sub):4d}  ")
        print(f"  {h:02d}:00 " + "".join(cells))

    # ---- 3b. what a signal is really worth, counting the days it fizzles ---
    head("EVERY SIGNAL, NOTHING EXCLUDED - including days no zone is ever tagged")
    print("  The accuracy above is conditional on a zone being tagged. Live, you do not")
    print("  know that in advance, so here is what a signal is actually worth.")
    print()
    print("  hour  gap    signals  correct  wrong  no tag         of decided")
    for h in range(3, 13):
        for g in (1.0, 1.5, 2.0):
            ok = wrong = none = 0
            for i, s in enumerate(S):
                bar = next((j for j in range(s.lo_idx, s.hi_idx + 1)
                            if bars[j].ny.hour == h), None)
                if bar is None:
                    continue
                p = bars[bar].o
                d_up, d_dn = (s.u1 - p) / s.rng, (p - s.l2) / s.rng
                if d_up <= 0 or d_dn <= 0 or abs(d_up - d_dn) < g:
                    continue
                pred = 1 if d_up < d_dn else -1
                nxt = next(((j, sd) for j, sd in tags[i] if j >= bar), None)
                if nxt is None:
                    none += 1
                elif nxt[1] == pred:
                    ok += 1
                else:
                    wrong += 1
            tot = ok + wrong + none
            if tot < 15:
                continue
            print(f"  {h:02d}:00 >={g:.1f}  {tot:6d}  {ok:7d}  {wrong:5d}  {none:4d} "
                  f"({pct(none,tot):4.1f}%)     {pct(ok, ok + wrong):5.1f}%")
    print()
    print("  The wrong-side count is the real risk. The no-tag count is the cost of")
    print("  waiting - those are the days the signal fires and the move never comes.")

    # ---- 4. is the call actually hard, or is price already there? ----------
    head("IS THE CALL TRIVIAL? - travel still required when the call is made")
    for g in (0.5, 1.0, 1.5, 2.0):
        sub = [r for r in rs if r["gap"] >= g]
        if len(sub) < 10:
            continue
        tv = sorted(r["travel"] for r in sub)
        ok = sum(1 for r in sub if r["pred"] == r["actual"])
        far = sum(1 for r in sub if r["travel"] >= 1.0)
        print(f"  gap>={g}:  {pct(ok,len(sub)):5.1f}% correct, n={len(sub)},  "
              f"median travel {tv[len(tv)//2]:.2f} R,  "
              f"{pct(far,len(sub)):.0f}% still had 1.0 R+ to travel")
    print()
    print("  If median travel is well above zero the call is real - price still had")
    print("  to cover ground to get there. Near zero and you are calling a tap-in.")

    # ---- 5. do other signals beat proximity at that hour? ------------------
    head(f"ALTERNATIVE SIGNALS AT {best_hour:02d}:00 NY")
    alts = {"nearest zone (proximity)": lambda r, s: r["pred"],
            "side the 9pm candle closed": lambda r, s: s.anchor_dir,
            "price above/below 9pm mid": lambda r, s: 1 if r["px"] >= (s.rhigh + s.rlow) / 2 else -1,
            "direction since lane open": lambda r, s: r["mom"]}
    rich = []
    for r in rs:
        s = S[r["i"]]
        bar = next(j for j in range(s.lo_idx, s.hi_idx + 1) if bars[j].ny.hour == best_hour)
        r["px"] = bars[bar].o
        r["mom"] = 1 if bars[bar].o >= bars[s.lo_idx].o else -1
        rich.append((r, s))
    for lbl, fn in alts.items():
        ok = sum(1 for r, s in rich if fn(r, s) == r["actual"])
        print(f"  {lbl:<30} {pct(ok,len(rich)):5.1f}%   n={len(rich)}")
    both = [(r, s) for r, s in rich if r["pred"] == s.anchor_dir]
    if len(both) >= 15:
        ok = sum(1 for r, s in both if r["pred"] == r["actual"])
        print(f"  {'proximity AND 9pm candle agree':<30} {pct(ok,len(both)):5.1f}%   n={len(both)}")


def main():
    for spec in sys.argv[1:]:
        name, _, path = spec.partition("=")
        analyse(name, load(path))


if __name__ == "__main__":
    main()
