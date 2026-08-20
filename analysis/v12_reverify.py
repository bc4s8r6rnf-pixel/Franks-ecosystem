#!/usr/bin/env python3
"""
v12: every earlier decision re-tested against the chart's real VWAP.

Each decision that was made using the reconstructed midnight VWAP is run
again here with bar.vwap. One configurable engine, one sweep per decision,
everything else held at the current v1.6 setting while a single knob moves.

Usage: python3 v12_reverify.py data_XAUUSD_15m.csv
"""

import sys
from v3_intraday import load, sessions, pct

PIP, BUF = 0.10, 1.0

CFG = dict(call=4, entry="first", cut=11, stop="box", stop_pips=80,
           floor=None, be_frac=None, lock=True, maxrng=40.0, flat=None,
           maxhold=5 * 96)


def trade(bars, S, k, c):
    s = S[k]
    ci = next((i for i in range(s.lo, s.hi + 1) if bars[i].ny.hour >= c["call"]), None)
    if ci is None:
        return None, "no call bar"
    if c["maxrng"] and s.rng >= c["maxrng"]:
        return None, "range filter"
    px = bars[ci].o
    side = 1 if (s.u1 - px) < (px - s.l2) else -1
    proj = s.u1 if side > 0 else s.l2
    boxstop = (s.rlow - BUF) if side > 0 else (s.rhigh + BUF)
    if any(((bars[m].h >= proj) if side > 0 else (bars[m].l <= proj))
           for m in range(s.lo, ci + 1)):
        return None, "zone gone before the call"
    dead = next((i for i in range(ci, s.hi + 1) if bars[i].ny.hour >= c["cut"]), None)
    if dead is None:
        return None, "no window"

    fill = None
    for m in range(ci, dead + 1):
        b, v = bars[m], bars[m].vwap
        if (b.l <= boxstop) if side > 0 else (b.h >= boxstop):
            return None, "box stop before entry"
        if (b.h >= proj) if side > 0 else (b.l <= proj):
            return None, "zone hit before entry"
        e = c["entry"]
        if e == "behind":
            if v is not None and ((b.c > v) if side > 0 else (b.c < v)):
                fill = (m + 1, b.c)
                break
            continue
        hv = v if (v is not None and b.l <= v <= b.h) else None
        hb = None
        if b.l <= s.rhigh and b.h >= s.rlow:
            hb = s.rhigh if b.o > s.rhigh else s.rlow if b.o < s.rlow else b.o
        if e == "vwap":
            hb = None
        if e == "box":
            hv = None
        if hv is None and hb is None:
            continue
        ent = hv if hb is None else hb if hv is None else \
              (hv if abs(hv - b.o) <= abs(hb - b.o) else hb)
        fill = (m, ent)
        break
    if fill is None:
        return None, "no entry trigger"
    i0, ent = fill
    if i0 > s.hi:
        return None, "no bars left"

    if c["stop"] == "vwap":
        v = bars[min(i0, len(bars) - 1)].vwap
        if v is None:
            return None, "no vwap"
        stop = v - side * c["stop_pips"] * PIP
        if (side > 0 and stop >= ent) or (side < 0 and stop <= ent):
            return None, "vwap stop past the entry"
    else:
        stop = boxstop
    risk = abs(ent - stop)
    if risk <= 0:
        return None, "no risk"

    if c["floor"] and abs(proj - ent) / risk < c["floor"]:
        tgt, be_at = ent + side * c["floor"] * risk, proj
    else:
        tgt, be_at = proj, None
    if c["be_frac"]:
        be_at = ent + side * c["be_frac"] * abs(tgt - ent)
    rr = abs(tgt - ent) / risk

    end = min(len(bars) - 1, i0 + c["maxhold"])
    if c["flat"] is not None:
        f = next((i for i in range(i0, s.hi + 1) if bars[i].ny.hour >= c["flat"]), s.hi)
        end = min(end, f)
    armed = False
    for m in range(i0, end + 1):
        b = bars[m]
        if (b.l <= stop) if side > 0 else (b.h >= stop):
            return dict(r=0.0 if armed else -1.0, rr=rr, risk=risk, exit=m), "done"
        if be_at is not None and not armed:
            if (b.h >= be_at) if side > 0 else (b.l <= be_at):
                armed, stop = True, ent
        if (b.h >= tgt) if side > 0 else (b.l <= tgt):
            return dict(r=rr, rr=rr, risk=risk, exit=m), "done"
    return dict(r=side * (bars[end].c - ent) / risk, rr=rr, risk=risk, exit=end), "done"


def walk(bars, S, **kw):
    c = dict(CFG)
    c.update(kw)
    ts, busy = [], -1
    for k, s in enumerate(S):
        ci = next((i for i in range(s.lo, s.hi + 1) if bars[i].ny.hour >= c["call"]), None)
        if ci is None:
            continue
        if c["lock"] and ci <= busy:
            continue
        t, _ = trade(bars, S, k, c)
        if t is None:
            continue
        t["day"] = s.day.date()
        ts.append(t)
        busy = t["exit"]
    return ts


def line(tag, ts, w=34):
    if not ts:
        print(f"  {tag:<{w}} no trades")
        return
    win = sum(1 for t in ts if t["r"] > 0)
    los = sum(1 for t in ts if t["r"] < 0)
    print(f"  {tag:<{w}} {len(ts):3d}  {win:2d}W/{los:2d}L  win {pct(win,len(ts)):5.1f}%"
          f"  avgRR {sum(t['rr'] for t in ts)/len(ts):5.2f}"
          f"  risk ${sum(t['risk'] for t in ts)/len(ts):6.2f}"
          f"  avgR {sum(t['r'] for t in ts)/len(ts):+.2f}"
          f"  totR {sum(t['r'] for t in ts):+6.1f}")


def sec(t):
    print("\n" + "=" * 100)
    print("  " + t)
    print("=" * 100)


def main():
    bars = load(sys.argv[1])
    S = sessions(bars)
    print("=" * 100)
    print("  EVERY DECISION RE-TESTED AGAINST THE CHART'S REAL VWAP")
    print("=" * 100)
    line("  CURRENT v1.6", walk(bars, S))

    sec("1. ENTRY TRIGGER")
    for e, n in (("vwap", "VWAP tap only"), ("box", "box touch only"),
                 ("first", "first of either (current)"), ("behind", "close with VWAP behind")):
        line("  " + n, walk(bars, S, entry=e))

    sec("2. TARGET - is the 2:1 floor still dead?")
    line("  zone always (current)", walk(bars, S))
    for f in (1.5, 2.0, 2.5):
        line(f"  floor at {f}:1 + BE at the zone", walk(bars, S, floor=f))

    sec("3. BREAK-EVEN part-way to target")
    line("  off (current)", walk(bars, S))
    for f in (0.4, 0.5, 0.6, 0.75, 0.9):
        line(f"  arm at {int(f*100)}% to target", walk(bars, S, be_frac=f))

    sec("4. ONE POSITION AT A TIME")
    line("  lock on (current)", walk(bars, S))
    line("  lock off", walk(bars, S, lock=False))

    sec("5. RANGE FILTER")
    line("  no filter", walk(bars, S, maxrng=None))
    for m in (30, 35, 40, 45, 50):
        line(f"  skip range >= ${m}", walk(bars, S, maxrng=float(m)))

    sec("6. DIRECTION CALL HOUR")
    for h in range(2, 8):
        line(f"  call at {h:02d}:00", walk(bars, S, call=h))

    sec("7. ENTRY CUTOFF HOUR")
    for h in (9, 10, 11, 12, 14, 16):
        line(f"  cutoff {h:02d}:00", walk(bars, S, cut=h))

    sec("8. TIME EXIT")
    line("  none (current)", walk(bars, S))
    for h in (12, 16, 23):
        line(f"  flat at {h:02d}:00", walk(bars, S, flat=h))

    sec("9. STOP - box against VWAP")
    line("  behind the 9pm box (current)", walk(bars, S))
    for p in (30, 50, 60, 80, 100, 120, 160):
        line(f"  {p:3d} pips beyond VWAP", walk(bars, S, stop="vwap", stop_pips=p))

    sec("10. THE TWO BEST TOGETHER")
    line("  VWAP-behind entry, box stop", walk(bars, S, entry="behind"))
    for p in (60, 80, 120):
        line(f"  VWAP-behind entry, {p} pip stop",
             walk(bars, S, entry="behind", stop="vwap", stop_pips=p))


if __name__ == "__main__":
    main()
