#!/usr/bin/env python3
"""
v18: EMA trend gate + engulfing trigger, stop on the entry candle.

  direction  unchanged - the 04:00 call
  gate       EMA(n) on 15m or 30m bars
  entry      right side of the EMA already -> enter at once
             wrong side -> wait for an engulfing candle that closes through
  stop       the entry candle's own low/high, plus a buffer
  target     the 2.45 R zone, or a fixed RR

Reports the failure modes as well as the totals: how often the entry-candle
stop is taken, how small it is, and how many sessions never trigger.
"""
import sys
from mt5_load import load_mt5, add_vwap
import v3_intraday as V3
from v3_intraday import pct

LVL, CUT, MAXHOLD = 2.45, 14, 5*96


def agg30(bars):
    """15m -> 30m. Returns rows and, per 15m bar, the last CLOSED 30m index."""
    rows, idx, cur, key = [], [], None, None
    for b in bars:
        k = (b.ny.toordinal(), b.ny.hour, b.ny.minute // 30)
        if k != key:
            if cur: rows.append(cur)
            cur = [b.o, b.h, b.l, b.c]; key = k
        else:
            cur[1] = max(cur[1], b.h); cur[2] = min(cur[2], b.l); cur[3] = b.c
        idx.append(len(rows) - 1)      # last CLOSED 30m bar
    if cur: rows.append(cur)
    return rows, idx


def ema(vals, n):
    k = 2.0/(n+1); out = []; e = None
    for v in vals:
        e = v if e is None else v*k + e*(1-k)
        out.append(e)
    return out


def engulf(b, p, up):
    """body of b engulfs body of p, in direction up."""
    bo, bc = b.o, b.c
    po, pc = p.o, p.c
    if up:
        return bc > bo and bc >= max(po, pc) and bo <= min(po, pc)
    return bc < bo and bc <= min(po, pc) and bo >= max(po, pc)


def run(bars, S, tf=30, n=20, pad=0.0, target="zone", rrfix=2.0, since=None):
    if tf == 30:
        rows, idx = agg30(bars)
        e = ema([r[3] for r in rows], n)
        emaval = lambda i: e[idx[i]] if idx[i] >= 0 else None
    else:
        e = ema([b.c for b in bars], n)
        emaval = lambda i: e[i]
    out = []
    for s in S:
        if since and s.day.year < since: continue
        ci = s.call; px = bars[ci].o; R = s.rng
        u, l = s.rhigh+LVL*R, s.rlow-LVL*R
        side = 1 if (u-px) < (px-l) else -1
        zone = u if side > 0 else l
        if any(((bars[m].h >= zone) if side > 0 else (bars[m].l <= zone))
               for m in range(s.lo, ci+1)): continue
        dead = next((i for i in range(ci, s.hi+1) if bars[i].ny.hour >= CUT), None)
        if dead is None: continue

        fill = None; how = None
        ev = emaval(ci)
        if ev is not None and ((px > ev) if side > 0 else (px < ev)):
            b = bars[ci]
            fill = (ci, b.c, b.l if side > 0 else b.h); how = "already onside"
        else:
            for m in range(ci+1, dead+1):
                b, p = bars[m], bars[m-1]
                ev = emaval(m)
                if ev is None: continue
                onside = (b.c > ev) if side > 0 else (b.c < ev)
                if onside and engulf(b, p, side > 0):
                    fill = (m, b.c, b.l if side > 0 else b.h); how = "engulfing"
                    break
        if fill is None:
            out.append(dict(r=None, how="never triggered", day=s.day.date())); continue
        m, ent, ex = fill
        stop = ex - side*pad*R
        risk = abs(ent-stop)
        if risk <= 0:
            out.append(dict(r=None, how="no risk", day=s.day.date())); continue
        tgt = zone if target == "zone" else ent + side*rrfix*risk
        if (side > 0 and ent >= tgt) or (side < 0 and ent <= tgt):
            out.append(dict(r=None, how="past target", day=s.day.date())); continue
        rr = abs(tgt-ent)/risk
        end = min(len(bars)-1, m+MAXHOLD); r = None; bars_held = 0
        # the stop is this candle's own extreme, so it can only be live from
        # the NEXT bar - checking it on the entry bar stops every trade at once
        for k in range(m+1, end+1):
            b = bars[k]; bars_held = k-m
            if (b.l <= stop) if side > 0 else (b.h >= stop): r = -1.0; break
            if (b.h >= tgt) if side > 0 else (b.l <= tgt): r = rr; break
        if r is None: r = side*(bars[end].c-ent)/risk
        out.append(dict(r=r, rr=rr, risk=risk, how=how, day=s.day.date(),
                        held=bars_held))
    return out


def rep(nm, res, w=30):
    ts = [t for t in res if t["r"] is not None]
    if not ts: print(f"  {nm:<{w}} none"); return
    r = [t["r"] for t in ts]
    gp = sum(x for x in r if x > 0); gl = -sum(x for x in r if x < 0)
    w_ = sum(1 for x in r if x > 0)
    print(f"  {nm:<{w}} {len(r):5d} {pct(w_,len(r)):6.1f}% PF {(gp/gl if gl else 99):5.2f} "
          f"avgRR {sum(t['rr'] for t in ts)/len(ts):5.2f} risk ${sum(t['risk'] for t in ts)/len(ts):6.2f} "
          f"avgR {sum(r)/len(r):+.2f} totR {sum(r):+8.1f}")


def main():
    F = sys.argv[1]
    bars = add_vwap(load_mt5(F, since=2015)); S = V3.sessions(bars)
    print("="*104); print("  EMA GATE + ENGULFING TRIGGER, STOP ON THE ENTRY CANDLE"); print("="*104)
    for tf in (30, 15):
        print(f"\n  --- EMA on {tf}m, target = the 2.45 zone ---")
        for n in (9, 20, 50, 100):
            rep(f"    EMA {n}", run(bars, S, tf, n))
    print("\n  --- 30m EMA 20, fixed RR targets instead of the zone ---")
    for rr in (1.0, 1.5, 2.0, 3.0, 4.0):
        rep(f"    target {rr}:1", run(bars, S, 30, 20, 0.0, "fix", rr))
    print("\n  --- 30m EMA 20, stop padded beyond the entry candle ---")
    for p in (0.0, 0.1, 0.25, 0.5):
        rep(f"    pad {p} x box", run(bars, S, 30, 20, p))


if __name__ == "__main__":
    main()
