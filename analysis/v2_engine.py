#!/usr/bin/env python3
"""
v2 trade engine: structural stop, projection-box target, patient entry.

Direction is settled (04:00 NY, nearest inner zone edge). This tests the trade
built around it:

  STOP    behind the 9pm box - under its low for a long, over its high for a
          short - plus a buffer, so a wick through the edge does not take you out.
  TARGET  the near edge of the daily projection box in the call's direction. If
          that box was already tapped before the call, it becomes support or
          resistance instead: stop goes behind it, and the target becomes the
          nearest still-untapped projection box beyond - however old - or 2:1,
          whichever comes first.
  ENTRY   at the call if price is still near the origin box. If it has already
          run, wait for a pullback to whichever of these sits nearest the box:
          the anchored VWAP, the 9pm box edge, or the 50% level of the combined
          Asia+London range.
  EXIT    flat at 16:55 New York, so a target that never comes cannot reverse
          overnight.

Gold pips: 1 pip = $0.10, so a 20-pip buffer is $2.00. Buffers are swept in
dollars and printed both ways.

VWAP is TWAP - the export has no volume column. On 1H they track closely; on 5m
they would not, which is one of several reasons this wants finer data.

Usage: python3 v2_engine.py NAME=file.csv
"""

import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from zone_sequence import load, build_sessions, pct

NY = ZoneInfo("America/New_York")
PIP = 0.10                 # XAUUSD
CALL_HOUR = 4              # NY, the direction read
FLAT_HOUR = 16             # NY, close everything on this bar (16:55 -> the 16:00 H1 bar)
ASIA_START = 18            # NY, previous evening - Asia through early London
FILL_DEADLINE = 12         # NY, give up waiting for a pullback after this hour


class Trade:
    __slots__ = ("i", "side", "entry", "stop", "target", "risk", "rr", "r_mult",
                 "outcome", "waited", "filled", "tgt_kind")


def build(bars, S, i, cfg):
    """One session -> at most one trade. Returns None when there is no setup."""
    s = S[i]
    call = next((k for k in range(s.lo_idx, s.hi_idx + 1)
                 if bars[k].ny.hour >= CALL_HOUR), None)
    if call is None:
        return None
    flat = next((k for k in range(call, s.hi_idx + 1)
                 if bars[k].ny.hour >= FLAT_HOUR), s.hi_idx)
    px = bars[call].o

    d_up, d_dn = (s.u1 - px) / s.rng, (px - s.l2) / s.rng
    if d_up <= 0 and d_dn <= 0:
        return None
    side = 1 if d_up < d_dn else -1

    # ---- the origin box: the 9pm candle itself -----------------------------
    box_hi, box_lo = s.rhigh, s.rlow

    # ---- target ------------------------------------------------------------
    # Was the projection box in our direction already tapped before the call?
    proj = s.u1 if side > 0 else s.l2
    tapped = any((bars[m].h >= s.u1) if side > 0 else (bars[m].l <= s.l2)
                 for m in range(s.lo_idx, call))
    tgt_kind = "projection"
    if tapped:
        # It is support/resistance now. Look for the nearest untapped box beyond,
        # searching back as far as history allows.
        tgt_kind = "older untapped"
        best = None
        for j in range(i - 1, -1, -1):
            for lvl in ((S[j].u1, S[j].u2) if side > 0 else (S[j].l2, S[j].l1)):
                if (side > 0 and lvl <= px) or (side < 0 and lvl >= px):
                    continue
                # untapped means price never reached it between its lane and now
                hit = any((bars[m].h >= lvl) if side > 0 else (bars[m].l <= lvl)
                          for m in range(S[j].lo_idx, call))
                if hit:
                    continue
                if best is None or abs(lvl - px) < abs(best - px):
                    best = lvl
        proj = best
    else:
        proj = s.u1 if side > 0 else s.l2

    # ---- entry -------------------------------------------------------------
    # How far has price already run from the origin box, in units of R?
    box_edge = box_lo if side > 0 else box_hi          # the edge we pull back to
    run = (px - box_hi) / s.rng if side > 0 else (box_lo - px) / s.rng
    waited = False
    entry_bar, entry = call, px

    if cfg["patient"] and run > cfg["run_thresh"]:
        # candidates for the pullback, all on the retrace side of price
        lo_i = next((k for k in range(s.anchor_idx, s.hi_idx + 1)
                     if bars[k].ny.hour >= ASIA_START or k >= s.lo_idx), s.lo_idx)
        rng_hi = max(bars[m].h for m in range(lo_i, call + 1))
        rng_lo = min(bars[m].l for m in range(lo_i, call + 1))
        half = (rng_hi + rng_lo) / 2
        acc = [(bars[m].h + bars[m].l + bars[m].c) / 3 for m in range(s.lo_idx, call + 1)]
        twap = sum(acc) / len(acc)

        cands = [c for c in (twap, box_edge, half)
                 if (c < px if side > 0 else c > px)]
        if cands:
            # "nearest to the origin box" - the deepest, safest tap
            level = min(cands, key=lambda c: abs(c - box_edge))
            dead = next((k for k in range(call, s.hi_idx + 1)
                         if bars[k].ny.hour >= FILL_DEADLINE), flat)
            fb = next((m for m in range(call, dead + 1)
                       if ((bars[m].l <= level) if side > 0 else (bars[m].h >= level))), None)
            if fb is None:
                return None                     # never came back; no trade
            entry_bar, entry, waited = fb, level, True

    # ---- stop --------------------------------------------------------------
    buf = cfg["buffer"]
    stop = (box_lo - buf) if side > 0 else (box_hi + buf)
    if cfg["stop_mode"] == "flat_R":
        stop = entry - side * cfg["flat_R"] * s.rng
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    if cfg["max_risk_R"] and risk > cfg["max_risk_R"] * s.rng:
        return None                             # too far from the box to be worth it

    # ---- resolve the target ------------------------------------------------
    two_to_one = entry + side * 2.0 * risk
    if proj is None:
        target, tgt_kind = two_to_one, "2:1 (no box)"
    elif (side > 0 and proj <= entry) or (side < 0 and proj >= entry):
        target, tgt_kind = two_to_one, "2:1 (box behind)"
    elif cfg["cap_2to1"] and abs(two_to_one - entry) < abs(proj - entry):
        target, tgt_kind = two_to_one, "2:1 (first)"
    else:
        target = proj

    t = Trade()
    t.i, t.side, t.entry, t.stop, t.target = i, side, entry, stop, target
    t.risk, t.rr = risk, abs(target - entry) / risk
    t.waited, t.filled, t.tgt_kind = waited, entry_bar, tgt_kind

    # ---- walk it -----------------------------------------------------------
    last = flat if cfg["flat_at_close"] else s.hi_idx
    t.outcome, t.r_mult = "open", 0.0
    for m in range(entry_bar, last + 1):
        b = bars[m]
        hs = (b.l <= t.stop) if side > 0 else (b.h >= t.stop)
        ht = (b.h >= t.target) if side > 0 else (b.l <= t.target)
        if hs:
            t.outcome, t.r_mult = "stop", -1.0
            break
        if ht:
            t.outcome, t.r_mult = "target", t.rr
            break
    if t.outcome == "open":
        t.outcome = "timed out"
        t.r_mult = side * (bars[last].c - entry) / risk
    return t


def run(bars, S, cfg):
    ts = [t for i in range(len(S)) if (t := build(bars, S, i, cfg))]
    if not ts:
        return None
    w = sum(1 for t in ts if t.r_mult > 0)
    tot = sum(t.r_mult for t in ts)
    return {"n": len(ts), "win": pct(w, len(ts)), "avg": tot / len(ts), "tot": tot,
            "rr": sum(t.rr for t in ts) / len(ts),
            "risk": sum(t.risk for t in ts) / len(ts),
            "waited": pct(sum(1 for t in ts if t.waited), len(ts)),
            "ts": ts}


BASE = {"patient": False, "run_thresh": 0.5, "buffer": 2.0, "stop_mode": "box",
        "flat_R": 1.5, "max_risk_R": 3.0, "cap_2to1": True, "flat_at_close": True}


def cfg(**kw):
    c = dict(BASE)
    c.update(kw)
    return c


def row(lbl, r):
    if not r:
        print(f"  {lbl:<38} no trades")
        return
    print(f"  {lbl:<38} {r['n']:4d} {r['win']:6.1f}% {r['avg']:+7.2f} {r['tot']:+8.1f} "
          f"{r['rr']:6.2f} {r['risk']:8.2f} {r['waited']:6.1f}%")


HDR = f"  {'variant':<38} {'n':>4} {'win':>7} {'avgR':>7} {'totR':>8} {'RR':>6} {'risk$':>8} {'waited':>7}"


def main():
    for spec in sys.argv[1:]:
        name, _, path = spec.partition("=")
        bars = load(path)
        S = build_sessions(bars)
        print()
        print("=" * 96)
        print(f"  {name}   {len(S)} sessions   call {CALL_HOUR:02d}:00 NY, flat {FLAT_HOUR}:55 NY")
        print("=" * 96)

        print("\n--- 1. STOP BUFFER BEHIND THE 9PM BOX (entry at the call) ---")
        print(HDR)
        for b in (0.0, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0):
            row(f"box - ${b:.2f}  ({b/PIP:.0f} pips)", run(bars, S, cfg(buffer=b)))
        print("  reference:")
        row("flat 1.5 R stop", run(bars, S, cfg(stop_mode="flat_R", flat_R=1.5)))
        row("flat 1.25 R stop", run(bars, S, cfg(stop_mode="flat_R", flat_R=1.25)))

        print("\n--- 2. PATIENT ENTRY (wait for VWAP / box edge / 50% Asia-London) ---")
        print(HDR)
        row("enter at the call", run(bars, S, cfg(buffer=2.0)))
        for th in (0.25, 0.5, 0.75, 1.0, 1.5):
            row(f"wait when run > {th:.2f} R", run(bars, S, cfg(patient=True, run_thresh=th)))

        print("\n--- 3. FLAT AT 16:55 vs HOLD TO MIDNIGHT ---")
        print(HDR)
        for pat in (False, True):
            for fl in (True, False):
                lbl = ("patient" if pat else "at call") + (", flat 16:55" if fl else ", to midnight")
                row(lbl, run(bars, S, cfg(patient=pat, run_thresh=0.5, flat_at_close=fl)))

        print("\n--- 4. TARGET RULE ---")
        print(HDR)
        row("box target, capped at 2:1", run(bars, S, cfg(patient=True, cap_2to1=True)))
        row("box target, uncapped", run(bars, S, cfg(patient=True, cap_2to1=False)))

        print("\n--- 6. THE WICK QUESTION - how far past the box edge do winners dip? ---")
        c = cfg(buffer=500.0, max_risk_R=None)      # a stop so far out it never fires
        over = []
        for i in range(len(S)):
            t = build(bars, S, i, c)
            if t is None or t.outcome != "target":
                continue
            edge = S[i].rlow if t.side > 0 else S[i].rhigh
            worst = 0.0
            for m in range(t.filled, S[i].hi_idx + 1):
                b = bars[m]
                worst = max(worst, (edge - b.l) if t.side > 0 else (b.h - edge))
                if (b.h >= t.target) if t.side > 0 else (b.l <= t.target):
                    break
            over.append(max(0.0, worst))
        over.sort()
        print(f"  {len(over)} trades reached target. Buffer needed to keep this share of them:")
        for f in (0.5, 0.7, 0.8, 0.9, 0.95, 1.0):
            v = over[min(len(over) - 1, int(f * len(over)))]
            print(f"    {f*100:4.0f}%   ${v:8.2f}  ({v/PIP:6.0f} pips)")
        print()
        print("  buffer         n   stopped   would have hit target later     net avgR")
        for b in (0.0, 1.0, 2.0, 5.0, 12.0, 20.0, 35.0):
            c = cfg(buffer=b, max_risk_R=None)
            st = res = 0
            rs = []
            for i in range(len(S)):
                t = build(bars, S, i, c)
                if t is None:
                    continue
                rs.append(t.r_mult)
                if t.outcome != "stop":
                    continue
                st += 1
                if any(((bars[m].h >= t.target) if t.side > 0 else (bars[m].l <= t.target))
                       for m in range(t.filled, S[i].hi_idx + 1)):
                    res += 1
            print(f"  ${b:5.2f} ({b/PIP:3.0f}p) {len(rs):4d}  {st:5d}     {res:5d}  "
                  f"({pct(res,st):4.1f}%)              {sum(rs)/len(rs):+.2f}")

        print("\n--- 5. MAX RISK FILTER (skip when the box is too far) ---")
        print(HDR)
        for mr in (1.0, 1.5, 2.0, 3.0, None):
            row(f"max risk {mr if mr else 'none'} R",
                run(bars, S, cfg(patient=True, max_risk_R=mr)))


if __name__ == "__main__":
    main()
