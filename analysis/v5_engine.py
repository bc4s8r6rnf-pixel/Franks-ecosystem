#!/usr/bin/env python3
"""
v5: the full rule set, as specified.

  DIRECTION  04:00 NY, nearest inner zone edge (2.0 R).
  NO TRADE   if the 2.0 target zone was already hit before the call.
  ENTRY      tap of VWAP, before 11:00 NY. Tap, not bar close.
  CANCEL     if the stop level is reached before the VWAP tap.
  CANCEL     if the 2.0 target zone is reached before the VWAP tap.
  NO TRADE   if VWAP is never tapped inside the window.
  STOP       behind the 9pm box plus a buffer.
  TARGET     the 2.0 zone edge. If that is closer than 2:1 from the entry, the
             target becomes the 2:1 level instead and the trade goes to
             break-even when the 2.0 edge is tapped.

Also answers two questions:
  1. Which 9pm range sizes lose money - is the $35-40 band as bad as it looks?
  2. After a big expansion day, when the call repeats yesterday's direction,
     would fading it instead convert losses into wins?

Usage: python3 v5_engine.py file.csv
"""

import sys
from v3_intraday import load, sessions, pct, FILL_DEADLINE

VWAP_CUTOFF = 11        # NY hour - no VWAP entries after this
BUF = 1.0               # stop buffer beyond the 9pm box, in dollars
MIN_RR = 2.0            # the 1:2 floor


def vw_at(bars, s, i):
    """Anchored VWAP at bar i, from the lane open. Real volume when present."""
    num = den = 0.0
    for m in range(s.lo, i + 1):
        b = bars[m]
        tp = (b.h + b.l + b.c) / 3
        v = getattr(b, "vol", None) or 1.0
        num += tp * v
        den += v
    return num / den if den else None


def build(bars, S, k, fade=False, skip_low_rr=False, buf=BUF):
    s = S[k]
    px = bars[s.call].o
    d_up, d_dn = (s.u1 - px) / s.rng, (px - s.l2) / s.rng
    if d_up <= 0 and d_dn <= 0:
        return dict(out="no call")
    side = 1 if d_up < d_dn else -1
    if fade:
        side = -side

    proj = s.u1 if side > 0 else s.l2
    stop = (s.rlow - buf) if side > 0 else (s.rhigh + buf)

    # --- target zone already hit before the call? -------------------------
    if any(((bars[m].h >= proj) if side > 0 else (bars[m].l <= proj))
           for m in range(s.lo, s.call + 1)):
        return dict(out="target already hit pre-call")

    # --- wait for the VWAP tap, cancelling on stop or target -------------
    dead = next((i for i in range(s.call, s.hi + 1)
                 if bars[i].ny.hour >= VWAP_CUTOFF), None)
    if dead is None:
        return dict(out="no window")

    eb = entry = None
    for m in range(s.call, dead + 1):
        b = bars[m]
        if (b.l <= stop) if side > 0 else (b.h >= stop):
            return dict(out="stop hit before entry")
        if (b.h >= proj) if side > 0 else (b.l <= proj):
            return dict(out="target hit before entry")
        v = vw_at(bars, s, m)
        if v is not None and b.l <= v <= b.h:      # the tap, intrabar
            eb, entry = m, v
            break
    if eb is None:
        return dict(out="no VWAP tap")

    risk = abs(entry - stop)
    if risk <= 0:
        return dict(out="no risk")

    rr_box = abs(proj - entry) / risk
    two = entry + side * MIN_RR * risk
    if rr_box >= MIN_RR:
        tgt, be_at = proj, None
    else:
        if skip_low_rr:
            return dict(out="box RR under 1:2")
        tgt, be_at = two, proj          # 2:1 target, break-even on the box tap

    rr = abs(tgt - entry) / risk
    be = False
    for m in range(eb, s.hi + 1):
        b = bars[m]
        hit_stop = (b.l <= stop) if side > 0 else (b.h >= stop)
        if hit_stop:
            return dict(out="stop", r=0.0 if be else -1.0, rr=rr, risk=risk,
                        rng=s.rng, k=k, side=side, be=be)
        if be_at is not None and not be:
            if (b.h >= be_at) if side > 0 else (b.l <= be_at):
                be = True
                stop = entry                       # break-even
        if (b.h >= tgt) if side > 0 else (b.l <= tgt):
            return dict(out="target", r=rr, rr=rr, risk=risk, rng=s.rng, k=k,
                        side=side, be=be)
    last = bars[s.hi].c
    return dict(out="timeout", r=side * (last - entry) / risk, rr=rr, risk=risk,
                rng=s.rng, k=k, side=side, be=be)


def summarise(ts):
    live = [t for t in ts if "r" in t]
    if not live:
        return None
    w = sum(1 for t in live if t["r"] > 0)
    l = sum(1 for t in live if t["r"] < 0)
    return dict(n=len(live), w=w, l=l, win=pct(w, len(live)),
                avg=sum(t["r"] for t in live) / len(live),
                tot=sum(t["r"] for t in live),
                rr=sum(t["rr"] for t in live) / len(live),
                risk=sum(t["risk"] for t in live) / len(live))


def main():
    bars = load(sys.argv[1])
    S = sessions(bars)
    print("=" * 92)
    print(f"  XAUUSD 15m   {len(S)} sessions   -   v5 rules, VWAP entry before "
          f"{VWAP_CUTOFF}:00 NY")
    print("=" * 92)

    ts = [build(bars, S, k) for k in range(len(S))]

    print("\n--- WHY SESSIONS DROP OUT ---")
    reasons = {}
    for t in ts:
        reasons[t["out"]] = reasons.get(t["out"], 0) + 1
    for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {r:<32} {c:4d}   {pct(c, len(S)):5.1f}%")

    r = summarise(ts)
    print("\n--- THE RESULT ---")
    if r:
        print(f"  trades {r['n']}   {r['w']}W / {r['l']}L   win {r['win']:.1f}%   "
              f"avgR {r['avg']:+.2f}   totR {r['tot']:+.1f}   avg RR {r['rr']:.2f}   "
              f"avg risk ${r['risk']:.2f}")
    r2 = summarise([build(bars, S, k, skip_low_rr=True) for k in range(len(S))])
    if r2:
        print(f"  skipping sub-1:2 boxes instead of retargeting: trades {r2['n']}  "
              f"{r2['w']}W / {r2['l']}L  win {r2['win']:.1f}%  avgR {r2['avg']:+.2f}  "
              f"totR {r2['tot']:+.1f}")

    # ---- 1. range-size buckets ------------------------------------------
    print("\n" + "=" * 92)
    print("  QUESTION 1: which 9pm range sizes lose? (is $35-40 the bad band?)")
    print("=" * 92)
    live = [t for t in ts if "r" in t]
    bands = [(0, 20), (20, 25), (25, 30), (30, 35), (35, 40), (40, 50), (50, 999)]
    print(f"  {'range $':<14} {'trades':>7} {'% of all':>9} {'W':>4} {'L':>4} "
          f"{'win%':>7} {'avgR':>7} {'totR':>8}")
    for lo, hi in bands:
        sub = [t for t in live if lo <= t["rng"] < hi]
        if not sub:
            continue
        w = sum(1 for t in sub if t["r"] > 0)
        l = sum(1 for t in sub if t["r"] < 0)
        lbl = f"${lo}-{hi}" if hi < 999 else f"${lo}+"
        print(f"  {lbl:<14} {len(sub):7d} {pct(len(sub), len(live)):8.1f}% {w:4d} {l:4d} "
              f"{pct(w, len(sub)):6.1f}% {sum(t['r'] for t in sub)/len(sub):+7.2f} "
              f"{sum(t['r'] for t in sub):+8.1f}")

    # ---- 2. fading the day after a big expansion ------------------------
    print("\n" + "=" * 92)
    print("  QUESTION 2: after a big expansion day, does fading the repeat call help?")
    print("=" * 92)
    print(f"  {'prev day range >':<18} {'n':>4} {'follow W/L':>12} {'follow avgR':>12} "
          f"{'fade W/L':>10} {'fade avgR':>11}")
    for thr in (60, 80, 100, 120, 150, 200):
        idx = []
        for k in range(1, len(S)):
            p = S[k - 1]
            prng = max(bars[m].h for m in range(p.lo, p.hi + 1)) - \
                   min(bars[m].l for m in range(p.lo, p.hi + 1))
            if prng < thr:
                continue
            pdir = 1 if bars[p.hi].c >= bars[p.lo].o else -1
            t = ts[k]
            if "r" not in t or t["side"] != pdir:      # only the repeat-direction days
                continue
            idx.append(k)
        if len(idx) < 3:
            continue
        fol = [ts[k] for k in idx]
        fad = [x for k in idx if "r" in (x := build(bars, S, k, fade=True))]
        fw = sum(1 for t in fol if t["r"] > 0)
        fl = sum(1 for t in fol if t["r"] < 0)
        dw = sum(1 for t in fad if t["r"] > 0)
        dl = sum(1 for t in fad if t["r"] < 0)
        print(f"  ${thr:<17} {len(idx):4d} {f'{fw}W/{fl}L':>12} "
              f"{sum(t['r'] for t in fol)/len(fol):+12.2f} {f'{dw}W/{dl}L':>10} "
              f"{(sum(t['r'] for t in fad)/len(fad) if fad else 0):+11.2f}")


if __name__ == "__main__":
    main()
