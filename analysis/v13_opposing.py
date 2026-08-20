#!/usr/bin/env python3
"""
v13: never skip a day. Use the opposing call as an exit.

The one-position lock throws a day away whenever a trade is still running. The
alternative asked for: always make the call, and when the new call opposes the
open position, close that position at the call and turn around. When it agrees,
let the old one run.

Four ways to handle a call that arrives with a position already open:

  skip        what v2.0 does - the call is discarded
  flip_both   opposing closes the old one; same direction lets it run. Either
              way the new trade is taken, so agreeing days can stack
  flip_one    opposing closes the old one and the new trade is taken; a call
              that agrees is discarded rather than doubled
  exit_only   opposing closes the old one but no new trade is taken

Runs as one bar-by-bar simulation over the whole file with a real position
book, because more than one trade can be live at once.

Usage: python3 v13_opposing.py data_XAUUSD_15m.csv
"""

import sys
from v3_intraday import load, sessions, pct

BUF, CUT, BIG = 1.0, 14, 40.0
LVL, PULL = 2.5, 0.05
MAXHOLD = 5 * 96


def setups(bars, S):
    """One planned trade per session, keyed by its call bar."""
    out = {}
    lvl = LVL - PULL
    for s in S:
        ci = next((i for i in range(s.lo, s.hi + 1) if bars[i].ny.hour >= 4), None)
        if ci is None or s.rng >= BIG:
            continue
        u1, l2 = s.rhigh + lvl * s.rng, s.rlow - lvl * s.rng
        px = bars[ci].o
        side = 1 if (u1 - px) < (px - l2) else -1
        proj = u1 if side > 0 else l2
        stop = (s.rlow - BUF) if side > 0 else (s.rhigh + BUF)
        if any(((bars[m].h >= proj) if side > 0 else (bars[m].l <= proj))
               for m in range(s.lo, ci + 1)):
            continue
        dead = next((i for i in range(ci, s.hi + 1) if bars[i].ny.hour >= CUT), None)
        if dead is None:
            continue
        out[ci] = dict(day=s.day.date(), side=side, proj=proj, stop=stop, dead=dead)
    return out


def simulate(bars, S, mode):
    plan = setups(bars, S)
    book, pending, done = [], None, []

    for i, b in enumerate(bars):
        # ---- manage what is open -------------------------------------
        still = []
        for p in book:
            if (b.l <= p["stop"]) if p["side"] > 0 else (b.h >= p["stop"]):
                p["r"] = -1.0
                p["exit"] = i
                done.append(p)
                continue
            if (b.h >= p["tgt"]) if p["side"] > 0 else (b.l <= p["tgt"]):
                p["r"] = p["rr"]
                p["exit"] = i
                done.append(p)
                continue
            if i - p["in"] > MAXHOLD:
                p["r"] = p["side"] * (b.c - p["ent"]) / p["risk"]
                p["exit"] = i
                done.append(p)
                continue
            still.append(p)
        book = still

        # ---- a call lands --------------------------------------------
        if i in plan:
            c = plan[i]
            opposed = [p for p in book if p["side"] != c["side"]]
            agreed  = [p for p in book if p["side"] == c["side"]]

            if mode != "skip" and opposed:
                for p in opposed:          # turn around at the call
                    p["r"] = p["side"] * (b.o - p["ent"]) / p["risk"]
                    p["exit"] = i
                    p["closed_by_call"] = True
                    done.append(p)
                book = [p for p in book if p["side"] == c["side"]]

            take = True
            if mode == "skip":
                take = not book
            elif mode == "flip_one":
                take = not agreed
            elif mode == "exit_only":
                take = not book
            if take:
                pending = dict(c)
                pending["armed"] = i

        # ---- a pending setup looking for its tap ----------------------
        if pending is not None:
            side, proj, stop = pending["side"], pending["proj"], pending["stop"]
            if i > pending["dead"]:
                pending = None
            elif i >= pending["armed"]:
                if ((b.l <= stop) if side > 0 else (b.h >= stop)) or \
                   ((b.h >= proj) if side > 0 else (b.l <= proj)):
                    pending = None
                elif b.vwap is not None and b.l <= b.vwap <= b.h:
                    risk = abs(b.vwap - stop)
                    if risk > 0:
                        book.append(dict(day=pending["day"], side=side, ent=b.vwap,
                                         stop=stop, tgt=proj, risk=risk,
                                         rr=abs(proj - b.vwap) / risk, **{"in": i}))
                    pending = None
    return done


def row(nm, ts, w=34):
    if not ts:
        print(f"  {nm:<{w}} none")
        return
    r = [t["r"] for t in ts]
    gp = sum(x for x in r if x > 0)
    gl = -sum(x for x in r if x < 0)
    w_ = sum(1 for x in r if x > 0)
    l_ = sum(1 for x in r if x < 0)
    eq = pk = dd = 0
    for t in sorted(ts, key=lambda z: z["exit"]):
        eq += t["r"]
        pk = max(pk, eq)
        dd = max(dd, pk - eq)
    print(f"  {nm:<{w}} {len(r):3d} {w_:3d}W/{l_:2d}L {pct(w_, len(r)):6.1f}%  "
          f"PF {(gp/gl if gl else 99):5.2f}  avgR {sum(r)/len(r):+.2f}  "
          f"totR {sum(r):+6.1f}  DD {dd:4.1f}")


def main():
    bars = load(sys.argv[1])
    S = sessions(bars)
    print("=" * 96)
    print("  NEVER SKIP A DAY - the opposing call as an exit")
    print("=" * 96 + "\n")
    for m, n in (("skip", "skip the call (v2.0)"),
                 ("flip_both", "opposing flips, agreeing stacks"),
                 ("flip_one", "opposing flips, agreeing skipped"),
                 ("exit_only", "opposing just closes, no new trade")):
        row("  " + n, simulate(bars, S, m))

    print("\n  the trades closed early by an opposing call (flip_one):\n")
    d = [t for t in simulate(bars, S, "flip_one") if t.get("closed_by_call")]
    for t in sorted(d, key=lambda x: x["day"]):
        print(f"    {t['day']}  closed at the call for {t['r']:+.2f} R "
              f"(target was {t['rr']:.2f}:1)")
    print(f"\n    {len(d)} trades cut short, {sum(t['r'] for t in d):+.1f} R between them")


if __name__ == "__main__":
    main()
