#!/usr/bin/env python3
"""
v15: does a Supertrend filter cut losses without costing wins?

Supertrend on the 15m bars, read at the 04:00 call. Take the trade only when
the call agrees with the trend; skip it when it fights the trend. Swept across
ATR period and multiplier, and also computed on aggregated 1h and 4h bars,
because a trend filter usually wants a slower clock than the entry.

Usage: python3 v15_supertrend.py data_XAUUSD_15m.csv
"""
import sys
from v3_intraday import load, sessions, pct
import v14_final as V


def atr_series(rows, n):
    tr = []
    for i, b in enumerate(rows):
        if i == 0:
            tr.append(b[1] - b[2])
        else:
            pc = rows[i-1][3]
            tr.append(max(b[1]-b[2], abs(b[1]-pc), abs(b[2]-pc)))
    out, run = [], None
    for i, t in enumerate(tr):
        if i < n - 1:
            out.append(None); continue
        if run is None:
            run = sum(tr[:n]) / n
        else:
            run = (run * (n-1) + t) / n
        out.append(run)
    return out


def supertrend(rows, period, mult):
    """rows = [(o,h,l,c)]. Returns a direction list: +1 up, -1 down, None warm-up."""
    a = atr_series(rows, period)
    dirs, fub, flb = [], None, None
    prev_dir = 1
    for i, (o, h, l, c) in enumerate(rows):
        if a[i] is None:
            dirs.append(None); continue
        hl2 = (h + l) / 2
        ub, lb = hl2 + mult * a[i], hl2 - mult * a[i]
        pc = rows[i-1][3]
        fub = ub if (fub is None or ub < fub or pc > fub) else fub
        flb = lb if (flb is None or lb > flb or pc < flb) else flb
        if prev_dir == 1:
            d = -1 if c < flb else 1
        else:
            d = 1 if c > fub else -1
        dirs.append(d); prev_dir = d
    return dirs


def aggregate(bars, hours):
    """Group 15m bars into `hours`-hour candles; return (rows, index->group)."""
    rows, idx, cur, start = [], [], None, None
    for i, b in enumerate(bars):
        key = (b.ny.toordinal(), b.ny.hour // hours)
        if key != start:
            if cur: rows.append(cur)
            cur = [b.o, b.h, b.l, b.c]; start = key
        else:
            cur[1] = max(cur[1], b.h); cur[2] = min(cur[2], b.l); cur[3] = b.c
        idx.append(len(rows))          # group this bar belongs to (once closed)
    if cur: rows.append(cur)
    return rows, idx


def run(bars, S, dirs_at_bar):
    """v2.2 with a trend gate at the call. dirs_at_bar[i] = trend at bar i."""
    orig = V.simulate
    plan_filter = {}
    ts = orig(bars, S)
    return ts


def main():
    bars = load(sys.argv[1]); S = sessions(bars)
    base = V.simulate(bars, S)
    n,w,l,wr,pf,a,t,dd = V.stat(base)
    print("="*100)
    print(f"  BASELINE v2.2   {n} trades  {w}W/{l}L  {wr:.1f}%  PF {pf:.2f}  totR {t:+.1f}  DD {dd:.1f}")
    print("="*100)

    rows15 = [(b.o,b.h,b.l,b.c) for b in bars]

    def gated(dirs, bar_of_dir):
        """Re-run the sim, skipping calls that fight the trend."""
        keep = {}
        for s in S:
            ci = next((i for i in range(s.lo,s.hi+1) if bars[i].ny.hour>=4), None)
            if ci is None: continue
            d = dirs[bar_of_dir(ci)] if bar_of_dir(ci) < len(dirs) else None
            keep[s.day] = d
        # patch: drop sessions whose call direction disagrees
        out=[]
        for tr in V.simulate(bars,S):
            out.append(tr)
        return out, keep

    print("\n  Supertrend on 15m bars, read at the call:\n")
    print(f"  {'period':>6} {'mult':>5}   {'n':>3} {'W':>3} {'L':>3} {'win%':>7} {'PF':>7} "
          f"{'totR':>7}   filtered  (of which W/L)")
    for period in (7,10,14,20):
        for mult in (1.5,2.0,3.0,4.0):
            d = supertrend(rows15, period, mult)
            kept, cut = [], []
            for tr in base:
                s = next(x for x in S if x.day.date()==tr["day"])
                ci = next(i for i in range(s.lo,s.hi+1) if bars[i].ny.hour>=4)
                sd = d[ci]
                side = 1 if tr["tgt"] > tr["ent"] else -1
                (kept if (sd is None or sd==side) else cut).append(tr)
            if not kept: continue
            n2,w2,l2,wr2,pf2,a2,t2,dd2 = V.stat(kept)
            cw = sum(1 for x in cut if x["r"]>0); cl = sum(1 for x in cut if x["r"]<0)
            print(f"  {period:6d} {mult:5.1f}   {n2:3d} {w2:3d} {l2:3d} {wr2:6.1f}% {pf2:7.2f} "
                  f"{t2:+7.1f}   {len(cut):5d}     {cw}W/{cl}L  {sum(x['r'] for x in cut):+6.1f} R")

    for hrs,label in ((1,"1h"),(4,"4h")):
        rows,idx = aggregate(bars,hrs)
        print(f"\n  Supertrend on {label} bars:\n")
        print(f"  {'period':>6} {'mult':>5}   {'n':>3} {'W':>3} {'L':>3} {'win%':>7} {'PF':>7} "
              f"{'totR':>7}   filtered  (of which W/L)")
        for period in (7,10,14):
            for mult in (2.0,3.0,4.0):
                d = supertrend(rows,period,mult)
                kept,cut=[],[]
                for tr in base:
                    s = next(x for x in S if x.day.date()==tr["day"])
                    ci = next(i for i in range(s.lo,s.hi+1) if bars[i].ny.hour>=4)
                    g = max(0, idx[ci]-1)
                    sd = d[g] if g < len(d) else None
                    side = 1 if tr["tgt"] > tr["ent"] else -1
                    (kept if (sd is None or sd==side) else cut).append(tr)
                if not kept: continue
                n2,w2,l2,wr2,pf2,a2,t2,dd2 = V.stat(kept)
                cw = sum(1 for x in cut if x["r"]>0); cl = sum(1 for x in cut if x["r"]<0)
                print(f"  {period:6d} {mult:5.1f}   {n2:3d} {w2:3d} {l2:3d} {wr2:6.1f}% {pf2:7.2f} "
                      f"{t2:+7.1f}   {len(cut):5d}     {cw}W/{cl}L  {sum(x['r'] for x in cut):+6.1f} R")


if __name__ == "__main__":
    main()
