#!/usr/bin/env python3
"""
Three claims from the chart, tested against the 59-session 15m sample:

  1. The projection box gets hit "every time", so capping the target at 2:1
     is leaving money behind.
  2. On days where the previous session never reached its projection box, that
     box becomes support/resistance - so the stop belongs beyond IT, not just
     beyond the 9pm box.
  3. The entry is better off the 19:00-05:00 range, which is already in.

Entry, stop and arming are v1.1: call 04:00, arm 05:00 when the range closes,
first tap of VWAP / box edge / 50% wins.

Usage: python3 v4_targets.py file.csv
"""

import sys
from v3_intraday import load, sessions, vwap_at, pct, CALL_HOUR, FILL_DEADLINE, RANGE_END


def trade(bars, S, k, tmode, stop_prev, buf=1.0, always=True):
    s = S[k]
    px = bars[s.call].o
    d_up, d_dn = (s.u1 - px) / s.rng, (px - s.l2) / s.rng
    if d_up <= 0 and d_dn <= 0:
        return None
    side = 1 if d_up < d_dn else -1

    # ---- entry: arm at the range close, first tap wins --------------------
    apx = bars[s.arm].o
    box_edge = s.rlow if side > 0 else s.rhigh
    cands = [c for c in (vwap_at(bars, s, s.arm), box_edge, s.half)
             if c is not None and (c < apx if side > 0 else c > apx)]
    if not cands:
        return None
    dead = next((i for i in range(s.arm, s.hi + 1)
                 if bars[i].ny.hour >= FILL_DEADLINE), s.hi)
    ebar = lvl = None
    for m in range(s.arm, dead + 1):
        hit = [c for c in cands if ((bars[m].l <= c) if side > 0 else (bars[m].h >= c))]
        if hit:
            ebar, lvl = m, (max(hit) if side > 0 else min(hit))
            break
    if ebar is None:
        return None
    entry = lvl

    # ---- stop -------------------------------------------------------------
    stop = (s.rlow - buf) if side > 0 else (s.rhigh + buf)
    used_prev = False
    if stop_prev and k > 0:
        p = S[k - 1]
        # the previous session's projection box on OUR stop side
        far = p.l2 - (p.rng * 0.5) if side > 0 else p.u1 + (p.rng * 0.5)
        near = p.l2 if side > 0 else p.u1
        # only if it sits between entry and a sane distance, and was never reached
        reached = any(((bars[m].l <= near) if side > 0 else (bars[m].h >= near))
                      for m in range(p.lo, s.arm))
        if not reached and ((near < entry) if side > 0 else (near > entry)):
            cand = (far - buf) if side > 0 else (far + buf)
            if (cand < stop) if side > 0 else (cand > stop):
                stop, used_prev = cand, True

    risk = abs(entry - stop)
    if risk <= 0:
        return None

    # ---- target -----------------------------------------------------------
    proj = s.u1 if side > 0 else s.l2
    two = entry + side * 2.0 * risk
    ahead = (proj > entry) if side > 0 else (proj < entry)
    if tmode == "cap":
        tgt = two if (not ahead or abs(two - entry) < abs(proj - entry)) else proj
    elif tmode == "uncapped":
        tgt = proj if ahead else two
    else:                                   # "min2to1" - the further of the two
        tgt = two if (not ahead or abs(two - entry) > abs(proj - entry)) else proj

    rr = abs(tgt - entry) / risk
    for m in range(ebar, s.hi + 1):
        b = bars[m]
        if (b.l <= stop) if side > 0 else (b.h >= stop):
            return dict(r=-1.0, rr=rr, risk=risk, out="stop", prev=used_prev)
        if (b.h >= tgt) if side > 0 else (b.l <= tgt):
            return dict(r=rr, rr=rr, risk=risk, out="target", prev=used_prev)
    return dict(r=side * (bars[s.hi].c - entry) / risk, rr=rr, risk=risk,
                out="timeout", prev=used_prev)


def run(bars, S, **kw):
    ts = [t for k in range(len(S)) if (t := trade(bars, S, k, **kw))]
    if not ts:
        return None
    w = sum(1 for t in ts if t["r"] > 0)
    hit = sum(1 for t in ts if t["out"] == "target")
    return dict(n=len(ts), win=pct(w, len(ts)), hit=pct(hit, len(ts)),
                avg=sum(t["r"] for t in ts) / len(ts), tot=sum(t["r"] for t in ts),
                rr=sum(t["rr"] for t in ts) / len(ts),
                risk=sum(t["risk"] for t in ts) / len(ts),
                prev=pct(sum(1 for t in ts if t["prev"]), len(ts)))


HDR = (f"  {'variant':<40} {'n':>4} {'win':>7} {'tgt hit':>8} {'avgR':>7} "
       f"{'totR':>7} {'RR':>6} {'risk$':>8}")


def row(lbl, r):
    if not r:
        print(f"  {lbl:<40} no trades")
        return
    print(f"  {lbl:<40} {r['n']:4d} {r['win']:6.1f}% {r['hit']:7.1f}% {r['avg']:+7.2f} "
          f"{r['tot']:+7.1f} {r['rr']:6.2f} {r['risk']:8.2f}")


bars = load(sys.argv[1])
S = sessions(bars)
print("=" * 100)
print(f"  XAUUSD 15m   {len(S)} sessions   -   target rule and stop placement")
print("=" * 100)
print("\n--- CLAIM 1: is the projection box a better target than 2:1? ---")
print(HDR)
for tm, lbl in (("cap", "target: 2:1 cap (current default)"),
                ("uncapped", "target: the projection box, uncapped"),
                ("min2to1", "target: the FURTHER of box and 2:1")):
    row(lbl, run(bars, S, tmode=tm, stop_prev=False))

print("\n--- CLAIM 2: stop beyond the previous day's unreached box ---")
print(HDR)
for tm in ("cap", "uncapped", "min2to1"):
    r = run(bars, S, tmode=tm, stop_prev=True)
    row(f"{tm} + prev-box stop", r)
    if r:
        print(f"       (the wider stop was used on {r['prev']:.0f}% of trades)")
