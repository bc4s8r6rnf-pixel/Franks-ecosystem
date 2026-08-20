#!/usr/bin/env python3
"""
v9: two add-ons and one timing question, measured as a tradeable portfolio.

Everything runs as one sequential walk with the one-position lock, so a trade
that is still open blocks whatever would have come next. Nothing here is
allowed to peek at how the day turned out.

  ADD-ON A  midnight box break. Price reaches the 9pm origin box between
            00:00 and 02:00 NY -> take it in the direction of the break,
            stop the far side of the box, target the 2.0 zone. Optionally
            only when the break is decisive by some fraction of R.

  ADD-ON B  the fib trade, big-range days only - the ones the range filter
            throws away. Swing 19:00 to 02:00, enter the 0.618, stop behind
            the 0.88, target either the -0.27 extension or the 2.0 zone.

  TIMING    the direction call at 03:00 against 04:00.

Usage: python3 v9_addons.py data_XAUUSD_15m.csv
"""

import sys
from v3_intraday import load, sessions, pct
from v5_engine import vw_at
from v8_midnight import swing, run, window, BUF, CUT, MAXHOLD

BIG = 40.0


# --------------------------------------------------------------------------
# the three trade builders. Each returns (fill_bar, side, entry, stop, tgt)
# --------------------------------------------------------------------------

def engine(bars, s, call_i):
    """v1.6: 04:00 call, first touch of VWAP or the box, target the zone."""
    px = bars[call_i].o
    side = 1 if (s.u1 - px) < (px - s.l2) else -1
    proj = s.u1 if side > 0 else s.l2
    stop = (s.rlow - BUF) if side > 0 else (s.rhigh + BUF)
    if any(((bars[m].h >= proj) if side > 0 else (bars[m].l <= proj))
           for m in range(s.lo, call_i + 1)):
        return None, "zone gone before the call"
    dead = next((i for i in range(call_i, s.hi + 1) if bars[i].ny.hour >= CUT), None)
    if dead is None:
        return None, "no window"
    if s.rlow <= px <= s.rhigh:
        return (call_i, side, px, stop, proj), "filled"
    for m in range(call_i, dead + 1):
        b = bars[m]
        if (b.l <= stop) if side > 0 else (b.h >= stop):
            return None, "stop hit before entry"
        if (b.h >= proj) if side > 0 else (b.l <= proj):
            return None, "zone hit before entry"
        v = vw_at(bars, s, m)
        hv = v if (v is not None and b.l <= v <= b.h) else None
        hb = None
        if b.l <= s.rhigh and b.h >= s.rlow:
            hb = s.rhigh if b.o > s.rhigh else s.rlow if b.o < s.rlow else b.o
        if hv is None and hb is None:
            continue
        ent = hv if hb is None else hb if hv is None else \
              (hv if abs(hv - b.o) <= abs(hb - b.o) else hb)
        return (m, side, ent, stop, proj), "filled"
    return None, "no entry trigger"


def boxbreak(bars, s, h1=2, minbreak=0.0):
    """Add-on A. Direction is the side of the box price is on."""
    for i in window(bars, s, 0, h1):
        b = bars[i]
        if not (b.l <= s.rhigh and b.h >= s.rlow):
            continue
        if b.o > s.rhigh:
            side, ent, over = 1, s.rhigh, (b.o - s.rhigh) / s.rng
        elif b.o < s.rlow:
            side, ent, over = -1, s.rlow, (s.rlow - b.o) / s.rng
        else:
            side, ent, over = (1 if b.c >= b.o else -1), b.o, 0.0
        if over < minbreak:
            return None, "break too shallow"
        proj = s.u1 if side > 0 else s.l2
        stop = (s.rlow - BUF) if side > 0 else (s.rhigh + BUF)
        if (side > 0 and ent >= proj) or (side < 0 and ent <= proj):
            return None, "past the zone"
        return (i, side, ent, stop, proj), "filled"
    return None, "box never reached"


def fibtrade(bars, s, call_i, tgt_fib=-0.27, ent_fib=0.618, stop_fib=0.88):
    """Add-on B. tgt_fib None means target the 2.0 zone instead."""
    px = bars[call_i].o
    side = 1 if (s.u1 - px) < (px - s.l2) else -1
    up, dn = swing(bars, s)
    sw = up if side > 0 else dn
    if sw is None:
        return None, "no swing"
    lo, hi, _ = sw
    span = hi - lo
    if span <= 0:
        return None, "no swing"
    zone = s.u1 if side > 0 else s.l2
    if side > 0:
        ent, stop = hi - ent_fib * span, hi - stop_fib * span - BUF
        tgt = (hi - tgt_fib * span) if tgt_fib is not None else zone
    else:
        ent, stop = lo + ent_fib * span, lo + stop_fib * span + BUF
        tgt = (lo + tgt_fib * span) if tgt_fib is not None else zone
    if (side > 0 and ent >= tgt) or (side < 0 and ent <= tgt):
        return None, "entry past the target"
    dead = next((i for i in range(call_i, s.hi + 1) if bars[i].ny.hour >= CUT), s.hi)
    for m in range(call_i, dead + 1):
        b = bars[m]
        if (b.h >= tgt) if side > 0 else (b.l <= tgt):
            return None, "target hit before entry"
        if (b.l <= stop) if side > 0 else (b.h >= stop):
            return None, "stop hit before entry"
        if b.l <= ent <= b.h:
            return (m, side, ent, stop, tgt), "filled"
    return None, "no retracement"


# --------------------------------------------------------------------------
# the sequential portfolio
# --------------------------------------------------------------------------

def portfolio(bars, S, call_hour=4, use_box=False, box_h1=2, box_min=0.0,
              use_fib=False, fib_tgt=-0.27, big=BIG, mode="hold"):
    """One walk, one position at a time, in bar order."""
    trades, busy, log = [], -1, []
    for k, s in enumerate(S):
        call_i = next((i for i in range(s.lo, s.hi + 1)
                       if bars[i].ny.hour >= call_hour), None)
        if call_i is None:
            continue

        # A midnight trade would be taken before the call, so it gets first
        # refusal - but only if nothing is already open at that hour.
        placed = None
        if use_box:
            bx, _ = boxbreak(bars, s, box_h1, box_min)
            if bx and bx[0] > busy:
                placed, src = bx, "box"

        if placed is None:
            if call_i <= busy:
                log.append((s.day.date(), "skipped - trade open", None))
                continue
            if s.rng >= big:
                if use_fib:
                    fb, why = fibtrade(bars, s, call_i, fib_tgt)
                    if fb:
                        placed, src = fb, "fib"
                    else:
                        log.append((s.day.date(), "big day - " + why, None))
                        continue
                else:
                    log.append((s.day.date(), "range filter", None))
                    continue
            else:
                en, why = engine(bars, s, call_i)
                if en:
                    placed, src = en, "engine"
                else:
                    log.append((s.day.date(), why, None))
                    continue

        i, side, ent, stop, tgt = placed
        t = run(bars, i, side, ent, stop, tgt, mode)
        if t is None:
            continue
        t["day"], t["src"], t["rng"] = s.day.date(), src, s.rng
        trades.append(t)
        busy = t["exit"]
        log.append((s.day.date(), src, t["r"]))
    return trades, log


def line(tag, ts, w=42):
    if not ts:
        print(f"  {tag:<{w}} no trades")
        return
    win = sum(1 for t in ts if t["r"] > 0)
    los = sum(1 for t in ts if t["r"] < 0)
    flat = len(ts) - win - los
    print(f"  {tag:<{w}} {len(ts):3d}  {win:2d}W/{los:2d}L"
          + (f"/{flat:2d}BE" if flat else "     ")
          + f"  win {pct(win, len(ts)):5.1f}%"
          + f"  avgR {sum(t['r'] for t in ts)/len(ts):+.2f}"
          + f"  totR {sum(t['r'] for t in ts):+6.1f}")


def diff(base, test, name):
    """Day-by-day: what did the change actually convert?"""
    b = {t["day"]: t["r"] for t in base}
    x = {t["day"]: t["r"] for t in test}
    new_win = [d for d in x if d not in b and x[d] > 0]
    new_los = [d for d in x if d not in b and x[d] < 0]
    lost    = [d for d in b if d not in x]
    w2l = [d for d in b if d in x and b[d] > 0 > x[d]]
    l2w = [d for d in b if d in x and b[d] < 0 < x[d]]
    print(f"\n  --- {name} vs baseline, day by day ---")
    print(f"    new trading days that WON   : {len(new_win)}   {sorted(new_win)}")
    print(f"    new trading days that LOST  : {len(new_los)}   {sorted(new_los)}")
    print(f"    baseline days now not taken : {len(lost)}   {sorted(lost)}")
    print(f"    baseline WINS turned to loss: {len(w2l)}   {sorted(w2l)}")
    print(f"    baseline LOSSES turned to win: {len(l2w)}  {sorted(l2w)}")
    print(f"    net R change: {sum(x.values()) - sum(b.values()):+.1f}")


def main():
    bars = load(sys.argv[1])
    S = sessions(bars)
    print("=" * 92)
    print(f"  XAUUSD 15m   {len(S)} sessions   {S[0].day.date()} -> {S[-1].day.date()}")
    print("=" * 92)

    base, _ = portfolio(bars, S)
    print("\n  BASELINE - v1.6 as it stands")
    line("  engine only", base)

    print("\n" + "=" * 92)
    print("  TIMING: the direction call at 03:00 against 04:00")
    print("=" * 92)
    for h in (2, 3, 4, 5):
        t, _ = portfolio(bars, S, call_hour=h)
        line(f"  call at {h:02d}:00", t)

    print("\n" + "=" * 92)
    print("  ADD-ON B: the fib trade on the big days only")
    print("=" * 92)
    for tf, nm in ((-0.27, "target the -0.27 extension"),
                   (-0.68, "target the -0.68 extension"),
                   (None,  "target the 2.0 zone")):
        t, _ = portfolio(bars, S, use_fib=True, fib_tgt=tf)
        line("  " + nm, t)
    best, _ = portfolio(bars, S, use_fib=True, fib_tgt=-0.27)
    diff(base, best, "fib on big days, -0.27 target")
    print("\n  the big-day trades themselves:")
    for t in best:
        if t["src"] == "fib":
            print(f"    {t['day']}  range ${t['rng']:6.2f}  R {t['r']:+6.2f}  "
                  f"(target was {t['rr']:.2f}:1, risk ${t['risk']:.2f})")

    print("\n" + "=" * 92)
    print("  ADD-ON A: the midnight box break, taken live before the call")
    print("=" * 92)
    for h1 in (1, 2):
        for mb in (0.0, 0.25, 0.5, 1.0):
            t, _ = portfolio(bars, S, use_box=True, box_h1=h1, box_min=mb)
            line(f"  window 00:00-{h1:02d}:00, break >= {mb:.2f} R", t)


if __name__ == "__main__":
    main()
