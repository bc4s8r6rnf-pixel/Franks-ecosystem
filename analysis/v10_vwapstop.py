#!/usr/bin/env python3
"""
v10: two ideas about the VWAP.

  STOP    Put the stop a fixed distance the far side of the VWAP instead of
          behind the 9pm box. 30 pips on gold is $3.00.

  ENTRY   Only take the trade with the VWAP behind price - above it for a
          long, below it for a short. If it is not, wait for a bar to close
          back on the correct side and enter on that close.

Both swept across a range of settings, because a rule that only works at one
value is a curve fit, not an edge.

Usage: python3 v10_vwapstop.py data_XAUUSD_15m.csv
"""

import sys
from v3_intraday import load, sessions, pct
from v5_engine import vw_at
from v8_midnight import run, BUF

PIP = 0.10
CUT = 11
BIG = 40.0


def build(bars, s, ci, stop_pips=None, need_side=False, trail=False):
    """Returns (entry_bar, side, entry, stop, target, same_bar_stop) or None."""
    px = bars[ci].o
    side = 1 if (s.u1 - px) < (px - s.l2) else -1
    proj = s.u1 if side > 0 else s.l2
    boxstop = (s.rlow - BUF) if side > 0 else (s.rhigh + BUF)
    if any(((bars[m].h >= proj) if side > 0 else (bars[m].l <= proj))
           for m in range(s.lo, ci + 1)):
        return None, "zone gone before the call"
    dead = next((i for i in range(ci, s.hi + 1) if bars[i].ny.hour >= CUT), None)
    if dead is None:
        return None, "no window"

    for m in range(ci, dead + 1):
        b = bars[m]
        v = vw_at(bars, s, m)
        if (b.l <= boxstop) if side > 0 else (b.h >= boxstop):
            return None, "box stop reached before entry"
        if (b.h >= proj) if side > 0 else (b.l <= proj):
            return None, "zone hit before entry"

        if need_side:
            # wait for a close with the VWAP behind price
            if v is None:
                continue
            if (b.c > v) if side > 0 else (b.c < v):
                ent, same = b.c, False          # filled on the close
            else:
                continue
        else:
            hv = v if (v is not None and b.l <= v <= b.h) else None
            hb = None
            if b.l <= s.rhigh and b.h >= s.rlow:
                hb = s.rhigh if b.o > s.rhigh else s.rlow if b.o < s.rlow else b.o
            if s.rlow <= px <= s.rhigh and m == ci:
                hb = px
            if hv is None and hb is None:
                continue
            ent = hv if hb is None else hb if hv is None else \
                  (hv if abs(hv - b.o) <= abs(hb - b.o) else hb)
            same = True

        if stop_pips is None:
            stop = boxstop
        else:
            if v is None:
                continue
            stop = v - side * stop_pips * PIP
            # a stop already the wrong side of entry is not a stop
            if (side > 0 and stop >= ent) or (side < 0 and stop <= ent):
                return None, "VWAP stop sits past the entry"
        if (side > 0 and ent >= proj) or (side < 0 and ent <= proj):
            return None, "entry past the zone"
        return (m, side, ent, stop, proj, same), "filled"
    return None, "no entry trigger"


def walk(bars, S, stop_pips=None, need_side=False, big=BIG):
    ts, busy, why = [], -1, {}
    for s in S:
        ci = next((i for i in range(s.lo, s.hi + 1) if bars[i].ny.hour >= 4), None)
        if ci is None or ci <= busy:
            continue
        if s.rng >= big:
            continue
        got, w = build(bars, s, ci, stop_pips, need_side)
        why[w] = why.get(w, 0) + 1
        if got is None:
            continue
        m, side, ent, stop, tgt, same = got
        t = run(bars, m if same else m + 1, side, ent, stop, tgt)
        if t is None:
            continue
        t["day"], t["rng"] = s.day.date(), s.rng
        ts.append(t)
        busy = t["exit"]
    return ts, why


def line(tag, ts, w=44):
    if not ts:
        print(f"  {tag:<{w}} no trades")
        return
    win = sum(1 for t in ts if t["r"] > 0)
    los = sum(1 for t in ts if t["r"] < 0)
    print(f"  {tag:<{w}} {len(ts):3d}  {win:2d}W/{los:2d}L  win {pct(win, len(ts)):5.1f}%"
          f"  avgRR {sum(t['rr'] for t in ts)/len(ts):6.2f}"
          f"  avg risk ${sum(t['risk'] for t in ts)/len(ts):6.2f}"
          f"  avgR {sum(t['r'] for t in ts)/len(ts):+.2f}  totR {sum(t['r'] for t in ts):+6.1f}")


def main():
    bars = load(sys.argv[1])
    S = sessions(bars)
    print("=" * 108)
    print(f"  XAUUSD 15m   {len(S)} sessions")
    print("=" * 108)

    base, _ = walk(bars, S)
    print("\n  BASELINE - v1.6, stop behind the 9pm box, first touch of VWAP or box")
    line("  v1.6", base)

    print("\n" + "=" * 108)
    print("  TEST 1: stop a fixed distance the far side of the VWAP")
    print("=" * 108)
    for p in (10, 20, 30, 40, 60, 80, 120, 160, 200, 300):
        t, w = walk(bars, S, stop_pips=p)
        line(f"  stop {p:3d} pips (${p*PIP:5.2f}) beyond VWAP", t)
    print("\n  why sessions drop out at 30 pips:")
    _, w = walk(bars, S, stop_pips=30)
    for r, c in sorted(w.items(), key=lambda x: -x[1]):
        print(f"    {r:<34} {c:3d}")

    print("\n" + "=" * 108)
    print("  TEST 2: only enter with the VWAP behind price (enter on the close)")
    print("=" * 108)
    t, w = walk(bars, S, need_side=True)
    line("  VWAP-behind close, stop behind the box", t)
    for r, c in sorted(w.items(), key=lambda x: -x[1]):
        print(f"    {r:<34} {c:3d}")

    print("\n" + "=" * 108)
    print("  TEST 3: both together")
    print("=" * 108)
    for p in (30, 60, 120, 200):
        t, _ = walk(bars, S, stop_pips=p, need_side=True)
        line(f"  VWAP-behind close + {p:3d} pip VWAP stop", t)


if __name__ == "__main__":
    main()
