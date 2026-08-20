#!/usr/bin/env python3
"""
v19: session-range fib entry into the New York open.

  DIRECTION  the 04:00 NY call, unchanged.
  RANGE      Asia   19:00 (prev) -> 00:00 NY
             London 01:00 -> 05:00 NY
             Both   19:00 (prev) -> 05:00 NY
  ANCHORS    for a SELL: 1 = top of the range, 0 = bottom
             for a BUY : 1 = bottom of the range, 0 = top
  ENTRY      the 0.618 level, touched between 08:00 and 09:45 NY
  TARGET     the -0.27 extension beyond the 0 anchor
  STOP       behind the 1 anchor

For a sell that works out as
  entry  = lo + 0.618 * (hi-lo)
  target = lo - 0.270 * (hi-lo)
  stop   = hi + buffer
so reward:risk is (0.618+0.270)/(1-0.618) = 2.32 : 1 before the buffer.
"""
import sys
from mt5_load import load_mt5, add_vwap
import v3_intraday as V3
from v3_intraday import pct

ENT_F, TGT_F = 0.618, -0.270
WIN_START, WIN_END = 8, 10          # 08:00 to 09:45 NY
MAXHOLD = 2*96


def session_range(bars, s, which):
    """Returns (lo, hi) for the named session preceding this lane."""
    day0 = s.day.timestamp()
    if which == "asia":   a, b = day0-5*3600, day0            # 19:00 -> 00:00
    elif which == "london": a, b = day0+1*3600, day0+5*3600   # 01:00 -> 05:00
    else:                 a, b = day0-5*3600, day0+5*3600     # 19:00 -> 05:00
    idx = [i for i in range(max(0, s.lo-80), min(len(bars), s.hi+1))
           if a <= bars[i].ny.timestamp() < b]
    if len(idx) < 4: return None
    return min(bars[i].l for i in idx), max(bars[i].h for i in idx)


def run(bars, S, which="both", buf=0.0, ent_f=ENT_F, tgt_f=TGT_F,
        strict_candles=False, since=None):
    out = []
    for s in S:
        if since and s.day.year < since: continue
        ci = s.call; px = bars[ci].o; R = s.rng
        u, l = s.rhigh+2.45*R, s.rlow-2.45*R
        side = 1 if (u-px) < (px-l) else -1        # +1 buy, -1 sell
        rng = session_range(bars, s, which)
        if rng is None:
            out.append(dict(r=None, why="no session range")); continue
        lo, hi = rng
        span = hi-lo
        if span <= 0:
            out.append(dict(r=None, why="no span")); continue
        if side < 0:                                # SELL: 1=top, 0=bottom
            ent  = lo + ent_f*span
            tgt  = lo + tgt_f*span
            stop = hi + buf*span
        else:                                       # BUY: 1=bottom, 0=top
            ent  = hi - ent_f*span
            tgt  = hi - tgt_f*span
            stop = lo - buf*span
        risk = abs(ent-stop)
        if risk <= 0:
            out.append(dict(r=None, why="no risk")); continue
        rr = abs(tgt-ent)/risk
        idx = [i for i in range(s.lo, s.hi+1)
               if WIN_START <= bars[i].ny.hour < WIN_END]
        if strict_candles:
            idx = [i for i in idx if bars[i].ny.minute in (0, 30)]
        if not idx:
            out.append(dict(r=None, why="no window")); continue
        fill = None
        for m in idx:
            b = bars[m]
            if b.l <= ent <= b.h: fill = m; break
        if fill is None:
            out.append(dict(r=None, why="0.618 never touched")); continue
        # already through the stop or the target at entry time?
        if (side > 0 and ent <= stop) or (side < 0 and ent >= stop):
            out.append(dict(r=None, why="stop past entry")); continue
        end = min(len(bars)-1, fill+MAXHOLD); r = None
        for k in range(fill, end+1):
            b = bars[k]
            hs = (b.l <= stop) if side > 0 else (b.h >= stop)
            ht = (b.h >= tgt) if side > 0 else (b.l <= tgt)
            if hs and ht: r = -1.0; break          # same bar -> score the loss
            if hs: r = -1.0; break
            if ht: r = rr; break
        if r is None: r = side*(bars[end].c-ent)/risk
        out.append(dict(r=r, rr=rr, risk=risk, why="filled",
                        day=s.day.date(), side=side, span=span))
    return out


def rep(nm, res, w=28, since=None):
    ts = [t for t in res if t["r"] is not None and (not since or t["day"].year >= since)]
    if not ts: print(f"  {nm:<{w}} none"); return
    r = [t["r"] for t in ts]
    gp = sum(x for x in r if x > 0); gl = -sum(x for x in r if x < 0)
    w_ = sum(1 for x in r if x > 0); l_ = sum(1 for x in r if x < 0)
    eq = pk = dd = 0
    for t in sorted(ts, key=lambda z: z["day"]):
        eq += t["r"]; pk = max(pk, eq); dd = max(dd, pk-eq)
    print(f"  {nm:<{w}} {len(r):5d} {w_:5d}W {l_:5d}L {pct(w_,len(r)):6.1f}% "
          f"PF {(gp/gl if gl else 99):5.2f} RR {sum(t['rr'] for t in ts)/len(ts):5.2f} "
          f"risk ${sum(t['risk'] for t in ts)/len(ts):6.2f} avgR {sum(r)/len(r):+.2f} "
          f"totR {sum(r):+8.1f} DD {dd:5.1f}")
