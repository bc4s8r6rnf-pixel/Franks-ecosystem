#!/usr/bin/env python3
"""
v20: fib anchored 1 -> starting level, -0.27 -> the opposing 2.0 zone edge.

  price(f) = A + (1-f)/1.27 * (B-A),  A = level 1, B = level -0.27
  so the 0.62 entry sits 29.92% of the way from A to B and the trade is
  2.34:1 by construction.

Anchor choices for A:
  zone     the 2.0 edge opposite the target        (span = 5R)
  asia     Asia high (sell) / Asia low (buy)
  prev     the previous day's Asia high / low

Direction either from the 04:00 call, or purely from premium / discount -
where price sits in the zone-to-zone range at the New York open.
"""
import sys
from mt5_load import load_mt5, add_vwap
import v3_intraday as V3
from v3_intraday import pct

ENT = (1-0.62)/1.27          # 0.2992
MAXHOLD = 2*96


def sess_hl(bars, s, h0, h1, dayshift=0):
    a = s.day.timestamp() + h0*3600 - dayshift*86400
    b = s.day.timestamp() + h1*3600 - dayshift*86400
    idx = [i for i in range(max(0, s.lo-200), min(len(bars), s.hi+1))
           if a <= bars[i].ny.timestamp() < b]
    if len(idx) < 4: return None
    return min(bars[i].l for i in idx), max(bars[i].h for i in idx)


def run(bars, S, anchor="zone", dirmode="call", h0=8, h1=11, buf=0.0, sep=0.15, since=None):
    out = []
    for s in S:
        if since and s.day.year < since: continue
        R = s.rng
        up, dn = s.rhigh+2.0*R, s.rlow-2.0*R      # the 2.0 zone edges
        ci = s.call
        # ---- direction ------------------------------------------------
        if dirmode == "call":
            px = bars[ci].o
            side = 1 if (up-px) < (px-dn) else -1
        else:
            j = next((i for i in range(s.lo, s.hi+1) if bars[i].ny.hour >= h0), None)
            if j is None: out.append(dict(r=None, why="no NY bar")); continue
            px = bars[j].o
            # discount -> buy, premium -> sell
            side = 1 if px < (up+dn)/2 else -1
        B = up if side > 0 else dn                 # target = opposing 2.0 edge
        # ---- anchor A -------------------------------------------------
        zoneA = dn if side > 0 else up
        hl  = sess_hl(bars, s, -5, 0)
        hlp = sess_hl(bars, s, -5, 0, dayshift=1)
        asiaA = None if hl  is None else (hl[0]  if side > 0 else hl[1])
        prevA = None if hlp is None else (hlp[0] if side > 0 else hlp[1])
        if anchor == "zone":
            A = zoneA
        elif anchor == "asia":
            A = asiaA
        elif anchor == "prev":
            A = prevA
        else:
            # the user's rule: Asia tucked in near the zone edge -> use the zone
            # edge; Asia standing well away from it -> use Asia.
            if asiaA is None: A = zoneA
            else:
                gap = abs(asiaA - zoneA) / abs(zoneA - B)   # 0 = on the edge
                cands = [zoneA, asiaA] + ([prevA] if prevA is not None else [])
                if anchor == "auto":
                    A = zoneA if gap <= sep else asiaA
                elif anchor == "near":       # shallowest -> closest to target
                    A = min(cands, key=lambda x: abs(B-x))
                else:                        # "far" -> deepest anchor
                    A = max(cands, key=lambda x: abs(B-x))
        if A is None:
            out.append(dict(r=None, why="no anchor")); continue
        span = B-A
        if (side > 0 and span <= 0) or (side < 0 and span >= 0):
            out.append(dict(r=None, why="anchor past target")); continue
        ent = A + ENT*span
        stop = A - (buf*R if side > 0 else -buf*R)
        risk = abs(ent-stop)
        if risk <= 0: out.append(dict(r=None, why="no risk")); continue
        rr = abs(B-ent)/risk
        # never fill before the bar the direction was decided on
        start = max(s.lo, (ci if dirmode == "call" else j))
        idx = [i for i in range(start, s.hi+1) if h0 <= bars[i].ny.hour < h1]
        if not idx: out.append(dict(r=None, why="no window")); continue
        fill = next((m for m in idx if bars[m].l <= ent <= bars[m].h), None)
        if fill is None:
            out.append(dict(r=None, why="0.62 never touched")); continue
        end = min(len(bars)-1, fill+MAXHOLD); r = None
        for k in range(fill, end+1):
            b = bars[k]
            if (b.l <= stop) if side > 0 else (b.h >= stop): r = -1.0; break
            if (b.h >= B) if side > 0 else (b.l <= B): r = rr; break
        if r is None: r = side*(bars[end].c-ent)/risk
        out.append(dict(r=r, rr=rr, risk=risk, why="filled", day=s.day.date(), side=side))
    return out


def rep(nm, res, w=30):
    ts = [t for t in res if t["r"] is not None]
    if not ts: print(f"  {nm:<{w}} none"); return
    r = [t["r"] for t in ts]
    gp = sum(x for x in r if x > 0); gl = -sum(x for x in r if x < 0)
    w_ = sum(1 for x in r if x > 0); l_ = sum(1 for x in r if x < 0)
    eq = pk = dd = 0
    for t in sorted(ts, key=lambda z: z["day"]):
        eq += t["r"]; pk = max(pk, eq); dd = max(dd, pk-eq)
    print(f"  {nm:<{w}} {len(r):5d} {w_:5d}W {l_:5d}L {pct(w_,len(r)):6.1f}% "
          f"PF {(gp/gl if gl else 99):5.2f} RR {sum(t['rr'] for t in ts)/len(ts):5.2f} "
          f"risk ${sum(t['risk'] for t in ts)/len(ts):7.2f} avgR {sum(r)/len(r):+.2f} "
          f"totR {sum(r):+8.1f} DD {dd:5.1f}")
