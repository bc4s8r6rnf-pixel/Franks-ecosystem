#!/usr/bin/env python3
"""
Does skipping the call while the previous trade is still open avoid losses?

The v5 engine flattens at the lane close, so trades never overlap and the
question cannot even arise. The charts show trades running well past midnight
to their target, so this removes the time exit first: hold until target or
stop, capped at a few days, and only then ask whether the overlap rule helps.

Three variants:
  A  flat at the lane close          (v5 baseline)
  B  hold to target or stop          (no time exit, overlaps allowed)
  C  hold to target or stop, and skip the call while a trade is still open

Usage: python3 v6_overlap.py file.csv
"""

import sys
from v3_intraday import load, sessions, pct
from v5_engine import vw_at, VWAP_CUTOFF, BUF, MIN_RR

MAX_LANES = 5           # give a held trade this many lanes to resolve


def setup(bars, S, k, buf=BUF):
    """Everything up to the fill. Returns None with a reason if it never fills."""
    s = S[k]
    px = bars[s.call].o
    d_up, d_dn = (s.u1 - px) / s.rng, (px - s.l2) / s.rng
    if d_up <= 0 and d_dn <= 0:
        return None, "no call"
    side = 1 if d_up < d_dn else -1
    proj = s.u1 if side > 0 else s.l2
    stop = (s.rlow - buf) if side > 0 else (s.rhigh + buf)

    if any(((bars[m].h >= proj) if side > 0 else (bars[m].l <= proj))
           for m in range(s.lo, s.call + 1)):
        return None, "target already hit pre-call"

    dead = next((i for i in range(s.call, s.hi + 1)
                 if bars[i].ny.hour >= VWAP_CUTOFF), None)
    if dead is None:
        return None, "no window"

    for m in range(s.call, dead + 1):
        b = bars[m]
        if (b.l <= stop) if side > 0 else (b.h >= stop):
            return None, "stop hit before entry"
        if (b.h >= proj) if side > 0 else (b.l <= proj):
            return None, "target hit before entry"
        v = vw_at(bars, s, m)
        if v is not None and b.l <= v <= b.h:
            risk = abs(v - stop)
            if risk <= 0:
                return None, "no risk"
            rr_box = abs(proj - v) / risk
            if rr_box >= MIN_RR:
                tgt, be_at = proj, None
            else:
                tgt, be_at = v + side * MIN_RR * risk, proj
            return dict(k=k, eb=m, side=side, entry=v, stop=stop, tgt=tgt,
                        be_at=be_at, risk=risk, rr=abs(tgt - v) / risk,
                        rng=s.rng), None
    return None, "no VWAP tap"


def walk(bars, S, t, hold):
    """Resolve the trade. hold=False stops at the lane close."""
    k = t["k"]
    end = S[k].hi if not hold else S[min(k + MAX_LANES, len(S) - 1)].hi
    side, stop, be = t["side"], t["stop"], False
    for m in range(t["eb"], end + 1):
        b = bars[m]
        if (b.l <= stop) if side > 0 else (b.h >= stop):
            return (0.0 if be else -1.0), m, ("BE" if be else "stop")
        if t["be_at"] is not None and not be:
            if (b.h >= t["be_at"]) if side > 0 else (b.l <= t["be_at"]):
                be, stop = True, t["entry"]
        if (b.h >= t["tgt"]) if side > 0 else (b.l <= t["tgt"]):
            return t["rr"], m, "target"
    return side * (bars[end].c - t["entry"]) / t["risk"], end, "timeout"


def run(bars, S, hold, no_overlap):
    out, busy, skipped = [], -1, 0
    for k in range(len(S)):
        if no_overlap and S[k].call <= busy:
            skipped += 1
            continue
        t, _ = setup(bars, S, k)
        if t is None:
            continue
        r, exit_bar, how = walk(bars, S, t, hold)
        busy = exit_bar
        out.append(dict(r=r, how=how, rr=t["rr"], risk=t["risk"], rng=t["rng"],
                        bars=exit_bar - t["eb"]))
    return out, skipped


def show(lbl, ts, skipped=None):
    if not ts:
        print(f"  {lbl:<44} no trades")
        return
    w = sum(1 for t in ts if t["r"] > 0)
    l = sum(1 for t in ts if t["r"] < 0)
    be = sum(1 for t in ts if t["how"] == "BE")
    tot = sum(t["r"] for t in ts)
    hrs = sorted(t["bars"] for t in ts)
    extra = f"  skipped {skipped}" if skipped is not None else ""
    print(f"  {lbl:<44} {len(ts):3d}  {w:3d}W/{l:3d}L  BE {be:2d}  "
          f"win {pct(w, len(ts)):5.1f}%  avgR {tot/len(ts):+6.2f}  totR {tot:+7.1f}  "
          f"median hold {hrs[len(hrs)//2]/4:.1f}h{extra}")


bars = load(sys.argv[1])
S = sessions(bars)
print("=" * 108)
print(f"  XAUUSD 15m   {len(S)} sessions   -   does the overlap rule help?")
print("=" * 108)
print(f"  {'variant':<44} {'n':>3}  {'W/L':>10}  {'BE':>5}  {'win':>9}  {'avgR':>11}  "
      f"{'totR':>11}")

a, _ = run(bars, S, hold=False, no_overlap=False)
show("A  flat at the lane close (v5 baseline)", a)
b, _ = run(bars, S, hold=True, no_overlap=False)
show("B  hold to target or stop", b)
c, sk = run(bars, S, hold=True, no_overlap=True)
show("C  hold + skip while a trade is open", c, sk)

print("\n--- how the held trades end ---")
for lbl, ts in (("B  overlaps allowed", b), ("C  overlaps skipped", c)):
    ways = {}
    for t in ts:
        ways[t["how"]] = ways.get(t["how"], 0) + 1
    print(f"  {lbl:<24} " + "   ".join(f"{k} {v}" for k, v in sorted(ways.items())))

print("\n--- and with the $40 range filter on top ---")
for lbl, ts, sk2 in (("B + range filter", b, None), ("C + range filter", c, sk)):
    sub = [t for t in ts if t["rng"] < 40]
    show(lbl, sub)
