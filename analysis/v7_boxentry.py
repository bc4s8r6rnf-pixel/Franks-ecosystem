#!/usr/bin/env python3
"""
v7: does adding the origin-box edge as a second entry trigger help?

Same rule set as v1.3 of the indicator:
  direction at 04:00 NY, stop behind the 9pm box + $1, target the 2.0 edge or
  2:1 (whichever gives at least 1:2), hold to target or stop across sessions,
  one position at a time, skip 9pm ranges >= $40.

The only thing that changes between the runs is what fills the trade:
  vwap   tap of the anchored VWAP                          (v1.3 as shipped)
  box    touch of the 21:00 origin box - if price is
         already inside the box at the call, fill at once
  first  whichever of the two happens first

Usage: python3 v7_boxentry.py data_XAUUSD_15m.csv
"""

import sys
from v3_intraday import load, sessions, pct
from v5_engine import vw_at, VWAP_CUTOFF, BUF, MIN_RR

MAXDAYS = 5
MAXRNG  = 40.0


def plan(bars, S, k, mode, rngfilter=True):
    """Everything up to the fill. Returns a dict; 'eb' set when filled."""
    s = S[k]
    if rngfilter and s.rng >= MAXRNG:
        return dict(out="range filter")
    px = bars[s.call].o
    d_up, d_dn = (s.u1 - px) / s.rng, (px - s.l2) / s.rng
    if d_up <= 0 and d_dn <= 0:
        return dict(out="no call")
    side = 1 if d_up < d_dn else -1
    proj = s.u1 if side > 0 else s.l2
    stop = (s.rlow - BUF) if side > 0 else (s.rhigh + BUF)

    if any(((bars[m].h >= proj) if side > 0 else (bars[m].l <= proj))
           for m in range(s.lo, s.call + 1)):
        return dict(out="target already hit pre-call")

    dead = next((i for i in range(s.call, s.hi + 1)
                 if bars[i].ny.hour >= VWAP_CUTOFF), None)
    if dead is None:
        return dict(out="no window")

    # price already inside the box at the moment of the call -> fill at once
    if mode in ("box", "first") and s.rlow <= px <= s.rhigh:
        return dict(out="filled", eb=s.call, entry=px, side=side, proj=proj,
                    stop=stop, s=s, k=k, how="in the box")

    for m in range(s.call, dead + 1):
        b = bars[m]
        if (b.l <= stop) if side > 0 else (b.h >= stop):
            return dict(out="stop hit before entry")
        if (b.h >= proj) if side > 0 else (b.l <= proj):
            return dict(out="target hit before entry")

        hit_v = hit_b = None
        if mode in ("vwap", "first"):
            v = vw_at(bars, s, m)
            if v is not None and b.l <= v <= b.h:
                hit_v = v
        if mode in ("box", "first"):
            if b.l <= s.rhigh and b.h >= s.rlow:          # bar touches the box
                hit_b = min(max(b.o, s.rlow), s.rhigh) if s.rlow <= b.o <= s.rhigh \
                        else (s.rhigh if b.o > s.rhigh else s.rlow)
        if hit_v is None and hit_b is None:
            continue
        if hit_v is not None and hit_b is not None:
            # both inside the same bar - take the one nearer the open, which is
            # the one price would have reached first coming off it
            pick = ("vwap", hit_v) if abs(hit_v - b.o) <= abs(hit_b - b.o) \
                   else ("box", hit_b)
        else:
            pick = ("vwap", hit_v) if hit_v is not None else ("box", hit_b)
        return dict(out="filled", eb=m, entry=pick[1], side=side, proj=proj,
                    stop=stop, s=s, k=k, how=pick[0])
    return dict(out="no tap")


def resolve(bars, p):
    """Run the filled trade forward to target or stop, across sessions."""
    s, side, entry, stop, proj = p["s"], p["side"], p["entry"], p["stop"], p["proj"]
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    rr_box = abs(proj - entry) / risk
    if rr_box >= MIN_RR:
        tgt, be_at = proj, None
    else:
        tgt, be_at = entry + side * MIN_RR * risk, proj
    rr = abs(tgt - entry) / risk
    be = False
    end = min(len(bars) - 1, s.hi + MAXDAYS * 96)
    for m in range(p["eb"], end + 1):
        b = bars[m]
        if (b.l <= stop) if side > 0 else (b.h >= stop):
            return dict(r=0.0 if be else -1.0, rr=rr, risk=risk, rng=s.rng,
                        exit=m, how=p["how"], be=be, out="stop")
        if be_at is not None and not be:
            if (b.h >= be_at) if side > 0 else (b.l <= be_at):
                be, stop = True, entry
        if (b.h >= tgt) if side > 0 else (b.l <= tgt):
            return dict(r=rr, rr=rr, risk=risk, rng=s.rng, exit=m, how=p["how"],
                        be=be, out="target")
    return dict(r=side * (bars[end].c - entry) / risk, rr=rr, risk=risk,
                rng=s.rng, exit=end, how=p["how"], be=be, out="timeout")


def walk(bars, S, mode, lock=True, rngfilter=True):
    trades, reasons, busy = [], {}, -1
    for k in range(len(S)):
        if lock and S[k].call <= busy:
            reasons["skipped - trade open"] = reasons.get("skipped - trade open", 0) + 1
            continue
        p = plan(bars, S, k, mode, rngfilter)
        if p["out"] != "filled":
            reasons[p["out"]] = reasons.get(p["out"], 0) + 1
            continue
        t = resolve(bars, p)
        if t is None:
            continue
        trades.append(t)
        busy = t["exit"]
    return trades, reasons


def line(tag, ts):
    if not ts:
        print(f"  {tag:<28} no trades")
        return
    w = sum(1 for t in ts if t["r"] > 0)
    l = sum(1 for t in ts if t["r"] < 0)
    print(f"  {tag:<28} {len(ts):3d} trades  {w:2d}W/{l:2d}L  win {pct(w, len(ts)):5.1f}%  "
          f"avgR {sum(t['r'] for t in ts)/len(ts):+.2f}  totR {sum(t['r'] for t in ts):+6.1f}  "
          f"avg risk ${sum(t['risk'] for t in ts)/len(ts):5.2f}  "
          f"avg RR {sum(t['rr'] for t in ts)/len(ts):.2f}")


def main():
    bars = load(sys.argv[1])
    S = sessions(bars)
    print("=" * 104)
    print(f"  {len(S)} sessions   -   what fills the trade?")
    print("=" * 104)
    runs = {}
    for mode in ("vwap", "box", "first"):
        ts, why = walk(bars, S, mode)
        runs[mode] = (ts, why)
        line({"vwap": "VWAP tap only (v1.3)", "box": "box touch only",
              "first": "either, whichever first"}[mode], ts)

    print("\n--- with the range filter off ---")
    for mode in ("vwap", "box", "first"):
        ts, _ = walk(bars, S, mode, rngfilter=False)
        line(mode, ts)

    print("\n--- what filled them, in the 'whichever first' run ---")
    ts, why = runs["first"]
    for h in ("vwap", "box", "in the box"):
        sub = [t for t in ts if t["how"] == h]
        if sub:
            line("  " + h, sub)

    print("\n--- why sessions dropped out (whichever first) ---")
    for r, c in sorted(why.items(), key=lambda x: -x[1]):
        print(f"  {r:<32} {c:4d}")


if __name__ == "__main__":
    main()
