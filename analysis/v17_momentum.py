#!/usr/bin/env python3
"""
v17: wait for the move to START rather than predicting that it will.

Every entry tested so far is a level - tap the VWAP, touch the box. Those are
mean-reversion triggers: they fire while price is still coming back. This tests
momentum triggers instead, which fire once it is already going.

  BOS      break the highest high (long) / lowest low (short) of the last N bars
  DISP     a bar closes beyond the call price by k x ATR(14)
  FAIL     price probes toward the stop, fails, and closes back through the box

Direction and target are unchanged: the 04:00 call, the 2.45 R zone, stop
behind the 9pm box. Only the entry moves.
"""
import sys
from mt5_load import load_mt5, add_vwap
import v3_intraday as V3
from v3_intraday import pct

LVL, BUF, CUT, MAXHOLD = 2.45, 0.5, 14, 5*96


def atr14(bars, i, n=14):
    if i < n: return None
    s = 0.0
    for k in range(i-n+1, i+1):
        pc = bars[k-1].c
        s += max(bars[k].h-bars[k].l, abs(bars[k].h-pc), abs(bars[k].l-pc))
    return s/n


def run(bars, S, mode, param=None, cut=CUT):
    ts = []
    for s in S:
        ci = s.call
        px = bars[ci].o; R = s.rng
        u, l = s.rhigh+LVL*R, s.rlow-LVL*R
        side = 1 if (u-px) < (px-l) else -1
        proj = u if side > 0 else l
        stop = (s.rlow-BUF) if side > 0 else (s.rhigh+BUF)
        if any(((bars[m].h >= proj) if side > 0 else (bars[m].l <= proj))
               for m in range(s.lo, ci+1)): continue
        dead = next((i for i in range(ci, s.hi+1) if bars[i].ny.hour >= cut), None)
        if dead is None: continue

        fill = None
        for m in range(ci, dead+1):
            b = bars[m]
            if (b.l <= stop) if side > 0 else (b.h >= stop): break
            if (b.h >= proj) if side > 0 else (b.l <= proj): break
            if mode == "market":
                fill = (m, b.o if m == ci else b.c); break
            if mode == "bos":
                n = param
                if m-n < s.lo: continue
                ref = max(bars[k].h for k in range(m-n, m)) if side > 0 else \
                      min(bars[k].l for k in range(m-n, m))
                if (b.h >= ref) if side > 0 else (b.l <= ref):
                    fill = (m, ref); break
            elif mode == "disp":
                a = atr14(bars, m)
                if a is None: continue
                lvl = px + side*param*a
                if (b.c >= lvl) if side > 0 else (b.c <= lvl):
                    fill = (m, b.c); break
            elif mode == "fail":
                near = s.rhigh if side > 0 else s.rlow
                probe = near - side*param*R
                got = any(((bars[k].l <= probe) if side > 0 else (bars[k].h >= probe))
                          for k in range(ci, m+1))
                if got and ((b.c > near) if side > 0 else (b.c < near)):
                    fill = (m, b.c); break
        if fill is None: continue
        m, ent = fill
        risk = abs(ent-stop)
        if risk <= 0: continue
        rr = abs(proj-ent)/risk
        if (side > 0 and ent >= proj) or (side < 0 and ent <= proj): continue
        end = min(len(bars)-1, m+MAXHOLD)
        r = None
        for k in range(m, end+1):
            b = bars[k]
            if (b.l <= stop) if side > 0 else (b.h >= stop): r = -1.0; break
            if (b.h >= proj) if side > 0 else (b.l <= proj): r = rr; break
        if r is None: r = side*(bars[end].c-ent)/risk
        ts.append(dict(r=r, rr=rr, risk=risk, day=s.day.date()))
    return ts


def row(nm, ts, w=26):
    if not ts: print(f"  {nm:<{w}} none"); return
    r = [t['r'] for t in ts]
    gp = sum(x for x in r if x > 0); gl = -sum(x for x in r if x < 0)
    w_ = sum(1 for x in r if x > 0)
    eq = pk = dd = 0
    for x in r: eq += x; pk = max(pk, eq); dd = max(dd, pk-eq)
    print(f"  {nm:<{w}} {len(r):5d} {pct(w_,len(r)):6.1f}% PF {(gp/gl if gl else 99):5.2f} "
          f"avgRR {sum(t['rr'] for t in ts)/len(ts):5.2f} avgR {sum(r)/len(r):+.2f} "
          f"totR {sum(r):+8.1f} DD {dd:5.1f}")


def main():
    F = sys.argv[1]
    bars = add_vwap(load_mt5(F, since=2015)); S = V3.sessions(bars)
    print("="*104)
    print(f"  MOMENTUM ENTRIES - {len(S)} sessions, 2015-2026")
    print("="*104 + "\n")
    row("  market at the call", run(bars, S, "market"))
    print("\n  break of structure - take out the last N bars' extreme:")
    for n in (4, 8, 12, 20, 32):
        row(f"    BOS {n} bars ({n*15}m)", run(bars, S, "bos", n))
    print("\n  displacement - close beyond the call price by k x ATR14:")
    for k in (0.5, 1.0, 1.5, 2.0, 3.0):
        row(f"    DISP {k} x ATR", run(bars, S, "disp", k))
    print("\n  failure swing - probe toward the stop, then close back through:")
    for f in (0.3, 0.5, 0.7, 0.9):
        row(f"    FAIL probe {f} of box", run(bars, S, "fail", f))


if __name__ == "__main__":
    main()
