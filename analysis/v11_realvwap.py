#!/usr/bin/env python3
"""
v11: everything re-measured against the VWAP exported from the chart.

Earlier tests reconstructed the VWAP anchored at midnight from hlc3. The
chart's VWAP is session-anchored - it resets at 18:00 NY in 54 of 59 sessions
- and sourced from the high. Median disagreement between the two was $7.13,
worst case $111.65, which makes any test of a $3.00 stop placed relative to
"the VWAP" worthless. This file uses bar.vwap, the exported column.

It also reports both intrabar assumptions, because with a tight stop the
question of whether the entry bar can stop you out dominates the answer:

  pessimistic  the stop is live on the entry bar itself
  optimistic   the stop is live from the next bar

The truth is in between and 15m OHLC cannot resolve it.

Usage: python3 v11_realvwap.py data_XAUUSD_15m.csv
"""

import sys
from v3_intraday import load, sessions, pct
from v8_midnight import run, BUF

PIP, CUT, BIG = 0.10, 11, 40.0


def build(bars, s, ci, stop_pips=None, need_side=False):
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
        v = b.vwap                       # the chart's own VWAP
        if (b.l <= boxstop) if side > 0 else (b.h >= boxstop):
            return None, "box stop reached before entry"
        if (b.h >= proj) if side > 0 else (b.l <= proj):
            return None, "zone hit before entry"

        if need_side:
            if v is None:
                continue
            if not ((b.c > v) if side > 0 else (b.c < v)):
                continue
            ent, same = b.c, False
        else:
            hv = v if (v is not None and b.l <= v <= b.h) else None
            hb = None
            if b.l <= s.rhigh and b.h >= s.rlow:
                hb = s.rhigh if b.o > s.rhigh else s.rlow if b.o < s.rlow else b.o
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
            if (side > 0 and stop >= ent) or (side < 0 and stop <= ent):
                return None, "VWAP stop sits past the entry"
        if (side > 0 and ent >= proj) or (side < 0 and ent <= proj):
            return None, "entry past the zone"
        return (m, side, ent, stop, proj, same), "filled"
    return None, "no entry trigger"


def walk(bars, S, stop_pips=None, need_side=False, optimistic=False):
    ts, busy, why = [], -1, {}
    for s in S:
        ci = next((i for i in range(s.lo, s.hi + 1) if bars[i].ny.hour >= 4), None)
        if ci is None or ci <= busy or s.rng >= BIG:
            continue
        got, w = build(bars, s, ci, stop_pips, need_side)
        why[w] = why.get(w, 0) + 1
        if got is None:
            continue
        m, side, ent, stop, tgt, same = got
        start = m if (same and not optimistic) else m + 1
        if start > s.hi:
            continue
        t = run(bars, start, side, ent, stop, tgt)
        if t is None:
            continue
        t["day"] = s.day.date()
        ts.append(t)
        busy = t["exit"]
    return ts, why


def line(tag, ts, w=40):
    if not ts:
        print(f"  {tag:<{w}} no trades")
        return
    win = sum(1 for t in ts if t["r"] > 0)
    print(f"  {tag:<{w}} {len(ts):3d}  {win:2d}W/{len(ts)-win:2d}L  win {pct(win,len(ts)):5.1f}%"
          f"  avgRR {sum(t['rr'] for t in ts)/len(ts):6.2f}"
          f"  risk ${sum(t['risk'] for t in ts)/len(ts):6.2f}"
          f"  avgR {sum(t['r'] for t in ts)/len(ts):+.2f}  totR {sum(t['r'] for t in ts):+6.1f}")


def main():
    bars = load(sys.argv[1])
    S = sessions(bars)
    print("=" * 104)
    print("  RE-RUN WITH THE CHART'S OWN VWAP (session-anchored, from the export)")
    print("=" * 104)

    for opt in (False, True):
        nm = "optimistic (stop live from the next bar)" if opt else \
             "pessimistic (stop live on the entry bar)"
        print(f"\n  --- {nm} ---")
        b, _ = walk(bars, S, optimistic=opt)
        line("  baseline: box stop, first touch", b)
        for p in (10, 20, 30, 50, 80, 120, 200):
            t, _ = walk(bars, S, stop_pips=p, optimistic=opt)
            line(f"  stop {p:3d} pips (${p*PIP:5.2f}) beyond VWAP", t)
        t, _ = walk(bars, S, need_side=True, optimistic=opt)
        line("  VWAP behind price, box stop", t)


if __name__ == "__main__":
    main()
