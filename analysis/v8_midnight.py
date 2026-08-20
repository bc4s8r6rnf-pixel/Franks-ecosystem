#!/usr/bin/env python3
"""
v8: four questions asked from the chart, answered from the data.

  1. Why did those sessions never produce a call or a trade?
  2. Midnight proximity - is the nearer zone at 00:00 the one that gets hit,
     or the one that gets rejected? Follow it, or fade it?
  3. If price touches or breaks the origin box between 00:00 and 01:00, does
     taking it straight to the nearest zone win?
  4. On the big-range days we currently skip: draw the fib on the most
     prominent swing coming into the day, enter the 0.618, stop behind the
     0.88, target the 2.0 zone. Run to target, take profit at 2R, or go
     break-even at 2R - which is best?

Usage: python3 v8_midnight.py data_XAUUSD_15m.csv
"""

import sys
from v3_intraday import load, sessions, pct

BUF     = 1.0
CUT     = 11        # entry cutoff, NY hour
BIG     = 40.0      # the range filter threshold
MAXHOLD = 5 * 96    # 5 days of 15m bars


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def at_hour(bars, s, h):
    """First bar index at or after hour h of the lane."""
    return next((i for i in range(s.lo, s.hi + 1) if bars[i].ny.hour >= h), None)


def window(bars, s, h0, h1):
    """Bar indices in [h0, h1) NY hours of the lane day."""
    return [i for i in range(s.lo, s.hi + 1) if h0 <= bars[i].ny.hour < h1]


def first_zone_hit(bars, s):
    """Which 2.0 zone gets touched first in the lane? +1 up, -1 down, 0 neither."""
    for i in range(s.lo, s.hi + 1):
        up = bars[i].h >= s.u1
        dn = bars[i].l <= s.l2
        if up and dn:
            return 0        # same bar, unknowable
        if up:
            return 1
        if dn:
            return -1
    return 0


def run(bars, i0, side, entry, stop, tgt, mode="hold", rr_take=2.0):
    """Walk a filled trade forward. mode: hold | tp2 | be2."""
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    rr = abs(tgt - entry) / risk
    lvl2 = entry + side * rr_take * risk
    armed = False
    end = min(len(bars) - 1, i0 + MAXHOLD)
    for m in range(i0, end + 1):
        b = bars[m]
        if (b.l <= stop) if side > 0 else (b.h >= stop):
            return dict(r=0.0 if armed else -1.0, rr=rr, exit=m, risk=risk)
        if mode != "hold" and not armed and rr > rr_take:
            if (b.h >= lvl2) if side > 0 else (b.l <= lvl2):
                if mode == "tp2":
                    return dict(r=rr_take, rr=rr, exit=m, risk=risk)
                armed, stop = True, entry
        if (b.h >= tgt) if side > 0 else (b.l <= tgt):
            return dict(r=rr, rr=rr, exit=m, risk=risk)
    return dict(r=side * (bars[end].c - entry) / risk, rr=rr, exit=end, risk=risk)


def line(tag, ts, width=38):
    if not ts:
        print(f"  {tag:<{width}} no trades")
        return
    w = sum(1 for t in ts if t["r"] > 0)
    l = sum(1 for t in ts if t["r"] < 0)
    f = len(ts) - w - l
    print(f"  {tag:<{width}} {len(ts):3d}  {w:2d}W/{l:2d}L" + (f"/{f:2d}BE" if f else "     ")
          + f"  win {pct(w, len(ts)):5.1f}%  avgR {sum(t['r'] for t in ts)/len(ts):+.2f}"
          + f"  totR {sum(t['r'] for t in ts):+6.1f}")


def head(n, t):
    print("\n" + "=" * 88)
    print(f"  {n}. {t}")
    print("=" * 88)


# --------------------------------------------------------------------------
# 1. why no trade
# --------------------------------------------------------------------------

def q1(bars, S):
    head(1, "WHY A SESSION PRODUCES NOTHING")
    from v7_boxentry import plan
    rows = []
    for k in range(len(S)):
        p = plan(bars, S, k, "first")
        rows.append((S[k].day.date(), S[k].rng, p["out"]))
    tally = {}
    for _, _, o in rows:
        tally[o] = tally.get(o, 0) + 1
    for o, c in sorted(tally.items(), key=lambda x: -x[1]):
        print(f"  {o:<32} {c:4d}   {pct(c, len(rows)):5.1f}%")
    print("\n  the sessions in the screenshots:")
    print(f"  {'date':<12} {'9pm range':>10}   what happened")
    for d, rg, o in rows:
        if str(d) in ("2026-06-01", "2026-06-02", "2026-06-16", "2026-06-17",
                      "2026-06-18", "2026-07-31", "2026-08-03"):
            print(f"  {str(d):<12} ${rg:9.2f}   {o}")


# --------------------------------------------------------------------------
# 2. midnight proximity
# --------------------------------------------------------------------------

def q2(bars, S):
    head(2, "MIDNIGHT PROXIMITY - FOLLOW THE NEAR ZONE, OR FADE IT?")
    print("  At 00:00 NY, which 2.0 edge is nearer? Then which one actually")
    print("  gets touched first during the day? No trading, just the base rate.\n")
    print(f"  {'group':<26} {'n':>4} {'near hit':>9} {'far hit':>9} {'neither':>9}")
    groups = {"all sessions": lambda s: True,
              f"9pm range < ${BIG:.0f}": lambda s: s.rng < BIG,
              f"9pm range >= ${BIG:.0f}": lambda s: s.rng >= BIG}
    for name, keep in groups.items():
        n = near = far = none = 0
        for s in S:
            if not keep(s):
                continue
            px = bars[s.lo].o
            side = 1 if (s.u1 - px) < (px - s.l2) else -1
            hit = first_zone_hit(bars, s)
            n += 1
            if hit == 0:
                none += 1
            elif hit == side:
                near += 1
            else:
                far += 1
        if n:
            print(f"  {name:<26} {n:4d} {near:5d} {pct(near,n):5.1f}% "
                  f"{far:4d} {pct(far,n):5.1f}% {none:4d} {pct(none,n):5.1f}%")

    print("\n  Same question at 01:00 NY:\n")
    print(f"  {'group':<26} {'n':>4} {'near hit':>9} {'far hit':>9} {'neither':>9}")
    for name, keep in groups.items():
        n = near = far = none = 0
        for s in S:
            if not keep(s):
                continue
            i = at_hour(bars, s, 1)
            if i is None:
                continue
            px = bars[i].o
            side = 1 if (s.u1 - px) < (px - s.l2) else -1
            hit = first_zone_hit(bars, s)
            n += 1
            if hit == 0:
                none += 1
            elif hit == side:
                near += 1
            else:
                far += 1
        if n:
            print(f"  {name:<26} {n:4d} {near:5d} {pct(near,n):5.1f}% "
                  f"{far:4d} {pct(far,n):5.1f}% {none:4d} {pct(none,n):5.1f}%")

    print("\n  And the 04:00 call the engine actually uses, for comparison:\n")
    print(f"  {'group':<26} {'n':>4} {'near hit':>9} {'far hit':>9} {'neither':>9}")
    for name, keep in groups.items():
        n = near = far = none = 0
        for s in S:
            if not keep(s):
                continue
            px = bars[s.call].o
            side = 1 if (s.u1 - px) < (px - s.l2) else -1
            hit = first_zone_hit(bars, s)
            n += 1
            if hit == 0:
                none += 1
            elif hit == side:
                near += 1
            else:
                far += 1
        if n:
            print(f"  {name:<26} {n:4d} {near:5d} {pct(near,n):5.1f}% "
                  f"{far:4d} {pct(far,n):5.1f}% {none:4d} {pct(none,n):5.1f}%")


def q2b(bars, S):
    head("2b", "TRADING IT: MIDNIGHT ENTRY, FOLLOW vs FADE")
    print("  Enter at the 00:00 open, stop behind the 9pm box, target the zone.\n")
    for name, keep in (("all sessions", lambda s: True),
                       (f"range < ${BIG:.0f}", lambda s: s.rng < BIG),
                       (f"range >= ${BIG:.0f}", lambda s: s.rng >= BIG)):
        print(f"  --- {name} ---")
        for label, fade in (("follow the near zone", False), ("fade to the far zone", True)):
            ts = []
            for s in S:
                if not keep(s):
                    continue
                px = bars[s.lo].o
                side = 1 if (s.u1 - px) < (px - s.l2) else -1
                if fade:
                    side = -side
                proj = s.u1 if side > 0 else s.l2
                stop = (s.rlow - BUF) if side > 0 else (s.rhigh + BUF)
                if (side > 0 and px >= proj) or (side < 0 and px <= proj):
                    continue
                if (side > 0 and px <= stop) or (side < 0 and px >= stop):
                    continue
                t = run(bars, s.lo, side, px, stop, proj)
                if t:
                    ts.append(t)
            line("  " + label, ts)


# --------------------------------------------------------------------------
# 3. the origin box between midnight and 01:00
# --------------------------------------------------------------------------

def q3(bars, S):
    head(3, "TOUCHING THE ORIGIN BOX BETWEEN 00:00 AND 01:00")
    print("  If price reaches the 9pm box in that hour, take it immediately.")
    print("  Two readings of direction: toward the nearer zone, or in the")
    print("  direction of the side that got broken.\n")
    for h1, wname in ((1, "00:00-01:00"), (2, "00:00-02:00"), (4, "00:00-04:00")):
        print(f"  --- window {wname} ---")
        for label in ("toward the nearer zone", "with the broken side"):
            ts, n_touch = [], 0
            for s in S:
                idx = window(bars, s, 0, h1)
                hit = next((i for i in idx if bars[i].l <= s.rhigh and bars[i].h >= s.rlow), None)
                if hit is None:
                    continue
                n_touch += 1
                b = bars[hit]
                px = min(max(b.o, s.rlow), s.rhigh) if s.rlow <= b.o <= s.rhigh else \
                     (s.rhigh if b.o > s.rhigh else s.rlow)
                if label == "toward the nearer zone":
                    side = 1 if (s.u1 - px) < (px - s.l2) else -1
                else:
                    side = 1 if b.o > s.rhigh else -1 if b.o < s.rlow else \
                           (1 if b.c >= b.o else -1)
                proj = s.u1 if side > 0 else s.l2
                stop = (s.rlow - BUF) if side > 0 else (s.rhigh + BUF)
                if (side > 0 and px >= proj) or (side < 0 and px <= proj):
                    continue
                t = run(bars, hit, side, px, stop, proj)
                if t:
                    ts.append(t)
            line(f"  {label} ({n_touch} touched)", ts)


# --------------------------------------------------------------------------
# 4. the fib trade on the big days
# --------------------------------------------------------------------------

def swing(bars, s, h0=-5, h1=2):
    """The biggest swing point to swing point move coming into the day.

    Window runs from h0 hours before the lane open to h1 hours after it, so
    the default is 19:00 the night before through 02:00. Returns the largest
    up-swing (low then high) and the largest down-swing (high then low).
    """
    lo_t = s.day.timestamp() + h0 * 3600
    hi_t = s.day.timestamp() + h1 * 3600
    idx = [i for i in range(max(0, s.lo - 60), min(len(bars), s.hi + 1))
           if lo_t <= bars[i].ny.timestamp() < hi_t]
    if len(idx) < 4:
        return None, None
    up = dn = None
    best_u = best_d = 0.0
    run_lo, run_lo_i = bars[idx[0]].l, idx[0]
    run_hi, run_hi_i = bars[idx[0]].h, idx[0]
    for i in idx:
        b = bars[i]
        if b.h - run_lo > best_u:
            best_u, up = b.h - run_lo, (run_lo, b.h, i)
        if run_hi - b.l > best_d:
            best_d, dn = run_hi - b.l, (b.l, run_hi, i)
        if b.l < run_lo:
            run_lo, run_lo_i = b.l, i
        if b.h > run_hi:
            run_hi, run_hi_i = b.h, i
    return up, dn


def q4(bars, S):
    head(4, "THE FIB TRADE ON THE DAYS THE RANGE FILTER SKIPS")
    print("  Swing measured 19:00 the night before to 02:00 NY, the largest")
    print("  swing point to swing point move aligned with the 04:00 call.")
    print("  Entry the 0.618 retracement, stop behind the 0.88, target the 2.0")
    print("  zone. Entry only after the call, cutoff 11:00 NY.\n")

    def build(s, mode, ent_fib=0.618, stop_fib=0.88):
        px = bars[s.call].o
        side = 1 if (s.u1 - px) < (px - s.l2) else -1
        proj = s.u1 if side > 0 else s.l2
        up, dn = swing(bars, s)
        sw = up if side > 0 else dn
        if sw is None:
            return None, "no swing"
        lo, hi, _ = sw
        span = hi - lo
        if span <= 0:
            return None, "no swing"
        if side > 0:
            entry, stop = hi - ent_fib * span, hi - stop_fib * span - BUF
        else:
            entry, stop = lo + ent_fib * span, lo + stop_fib * span + BUF
        if (side > 0 and entry >= proj) or (side < 0 and entry <= proj):
            return None, "entry past the zone"
        dead = next((i for i in range(s.call, s.hi + 1) if bars[i].ny.hour >= CUT), s.hi)
        for m in range(s.call, dead + 1):
            b = bars[m]
            if (b.h >= proj) if side > 0 else (b.l <= proj):
                return None, "zone hit before entry"
            if (b.l <= stop) if side > 0 else (b.h >= stop):
                return None, "stop hit before entry"
            if b.l <= entry <= b.h:
                return run(bars, m, side, entry, stop, proj, mode), "filled"
        return None, "no retracement"

    for gname, keep in ((f"big days, 9pm range >= ${BIG:.0f}", lambda s: s.rng >= BIG),
                        (f"normal days, range < ${BIG:.0f}", lambda s: s.rng < BIG),
                        ("every session", lambda s: True)):
        sub = [s for s in S if keep(s)]
        print(f"  --- {gname}  ({len(sub)} sessions) ---")
        why = {}
        for mode, label in (("hold", "run to the 2.0 zone"),
                            ("tp2", "take profit at 2R"),
                            ("be2", "break-even at 2R, run on")):
            ts = []
            for s in sub:
                t, w = build(s, mode)
                if mode == "hold":
                    why[w] = why.get(w, 0) + 1
                if t:
                    ts.append(t)
            line("  " + label, ts)
        for w, c in sorted(why.items(), key=lambda x: -x[1]):
            if w != "filled":
                print(f"      {c:2d} dropped: {w}")
        print()


def main():
    bars = load(sys.argv[1])
    S = sessions(bars)
    print("=" * 88)
    print(f"  XAUUSD 15m   {len(S)} sessions   {S[0].day.date()} -> {S[-1].day.date()}")
    print("=" * 88)
    q1(bars, S)
    q2(bars, S)
    q2b(bars, S)
    q3(bars, S)
    q4(bars, S)


if __name__ == "__main__":
    main()
