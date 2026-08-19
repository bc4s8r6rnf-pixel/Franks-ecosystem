#!/usr/bin/env python3
"""
Direction only. Not "which zone gets tagged" - just: was the call right?

Scoring is a symmetric race from the read price: does price travel +X R in the
called direction before it travels -X R against? Every day gets a verdict, so
coverage and accuracy can be traded off against each other honestly. The goal
here is the most WINNING DAYS, not the highest percentage on a handful of them.

VWAP note: the TradingView export carries no volume column, so this computes
TWAP - the running mean of the typical price (H+L+C)/3 - anchored either at the
lane open or at the 21:00 source candle. On 1H FX/CFD data TWAP and VWAP track
each other closely, but it is a proxy and it is labelled as one. Re-export with
volume and this becomes a true VWAP with a one-line change.

Usage: python3 vwap_direction.py NAME=file.csv
"""

import sys
from zone_sequence import load, build_sessions, pct, head

RACE_R = 1.0        # +X R before -X R
HOURS = range(1, 15)


class Day:
    __slots__ = ("i", "bars_idx", "twapL", "twapS")


def prep(bars, S):
    """Anchored TWAP series for each lane: from the lane open, and from 21:00."""
    out = []
    for i, s in enumerate(S):
        d = Day()
        d.i = i
        d.bars_idx = list(range(s.lo_idx, s.hi_idx + 1))
        tl, ts = {}, {}
        acc = 0.0
        for k, j in enumerate(d.bars_idx):
            b = bars[j]
            acc += (b.h + b.l + b.c) / 3
            tl[j] = acc / (k + 1)
        # anchored at the source candle: include the 22:00 -> 00:00 gap
        start = s.anchor_idx if hasattr(s, "anchor_idx") else d.bars_idx[0]
        acc, cnt = 0.0, 0
        for j in range(start, s.hi_idx + 1):
            b = bars[j]
            acc += (b.h + b.l + b.c) / 3
            cnt += 1
            ts[j] = acc / cnt
        d.twapL, d.twapS = tl, ts
        out.append(d)
    return out


def race(bars, s, j, side, entry, r, x):
    """+1 win, -1 loss, 0 neither reached by the end of the lane."""
    up, dn = entry + x * r, entry - x * r
    for m in range(j, s.hi_idx + 1):
        b = bars[m]
        hu, hd = b.h >= up, b.l <= dn
        if hu and hd:
            return -1                      # same bar both ways: count it against us
        if hu:
            return 1 if side > 0 else -1
        if hd:
            return -1 if side > 0 else 1
    return 0


def calls(bars, S, D, hour):
    """Every signal's opinion at this hour, plus the outcome."""
    rows = []
    for i, s in enumerate(S):
        j = next((k for k in range(s.lo_idx, s.hi_idx + 1)
                  if bars[k].ny.hour >= hour), None)
        if j is None or j == s.hi_idx:
            continue
        p = bars[j].o
        d_up, d_dn = (s.u1 - p) / s.rng, (p - s.l2) / s.rng
        prox = 1 if d_up < d_dn else -1
        gap = abs(d_up - d_dn)
        tl, ts = D[i].twapL.get(j), D[i].twapS.get(j)
        k3 = D[i].bars_idx[max(0, D[i].bars_idx.index(j) - 3)]
        slope = D[i].twapL.get(j, 0) - D[i].twapL.get(k3, 0)
        rows.append({
            "i": i, "j": j, "p": p, "r": s.rng, "s": s,
            "prox": prox, "gap": gap,
            "twapL": (1 if tl is not None and p >= tl else -1),
            "twapS": (1 if ts is not None and p >= ts else -1),
            "slope": (1 if slope >= 0 else -1),
            "anchor": s.anchor_dir,
            "mom": 1 if p >= bars[s.lo_idx].o else -1,
        })
    return rows


def score(bars, rows, pick, x=RACE_R):
    """pick(row) -> +1 / -1 / 0 (skip). Returns wins, losses, pushes, taken."""
    w = l = z = 0
    for rw in rows:
        side = pick(rw)
        if side == 0:
            continue
        o = race(bars, rw["s"], rw["j"], side, rw["p"], rw["r"], x)
        if o > 0:
            w += 1
        elif o < 0:
            l += 1
        else:
            z += 1
    return w, l, z, w + l + z


def line(lbl, res, total):
    w, l, z, n = res
    dec = w + l
    print(f"  {lbl:<34} {n:4d} {pct(n,total):6.1f}% {w:5d} {l:5d} {z:4d} "
          f"{pct(w,dec) if dec else 0:7.1f}% {w-l:+6d}")


def analyse(name, bars):
    S = build_sessions(bars)
    D = prep(bars, S)
    n = len(S)
    print()
    print("=" * 96)
    print(f"  {name}   {n} sessions   scoring: +{RACE_R} R before -{RACE_R} R from the read price")
    print("=" * 96)

    head("EVERY SIGNAL ON ITS OWN, ALL DAYS TAKEN (100% coverage)")
    print(f"  {'signal':<34} {'n':>4} {'cover':>7} {'win':>5} {'loss':>5} {'flat':>4} "
          f"{'acc':>8} {'net':>6}")
    per_hour = {}
    for h in HOURS:
        rows = calls(bars, S, D, h)
        per_hour[h] = rows
    # pick the hour that works best for the plain proximity rule, as the anchor
    best_h, best_net = None, None
    for h in HOURS:
        w, l, z, t = score(bars, per_hour[h], lambda r: r["prox"])
        if best_net is None or (w - l) > best_net:
            best_net, best_h = w - l, h
    rows = per_hour[best_h]
    print(f"  --- read at {best_h:02d}:00 NY ---")
    for lbl, fn in (("zone proximity", lambda r: r["prox"]),
                    ("TWAP (lane-anchored)", lambda r: r["twapL"]),
                    ("TWAP (21:00-anchored)", lambda r: r["twapS"]),
                    ("TWAP slope", lambda r: r["slope"]),
                    ("9pm candle direction", lambda r: r["anchor"]),
                    ("move since lane open", lambda r: r["mom"])):
        line(lbl, score(bars, rows, fn), n)

    head("BY HOUR - proximity alone vs TWAP alone vs the two agreeing")
    print(f"  {'hour':<6} {'proximity':>20} {'TWAP':>20} {'both agree':>26}")
    print(f"  {'':<6} {'acc':>8}{'net':>6}{'n':>6} {'acc':>8}{'net':>6}{'n':>6} "
          f"{'acc':>10}{'net':>7}{'n':>6}{'cover':>7}")
    for h in HOURS:
        rw = per_hour[h]
        a = score(bars, rw, lambda r: r["prox"])
        b = score(bars, rw, lambda r: r["twapL"])
        c = score(bars, rw, lambda r: r["prox"] if r["prox"] == r["twapL"] else 0)
        def cell(x, wide=False):
            w, l, z, t = x
            d = w + l
            return (f"{pct(w,d) if d else 0:{10 if wide else 8}.1f}%"
                    f"{w-l:{7 if wide else 6}d}{t:6d}")
        print(f"  {h:02d}:00 {cell(a)} {cell(b)} {cell(c, True)}{pct(c[3],n):6.1f}%")

    head("LOOSENING THE GAP - and using TWAP to decide the days proximity cannot")
    print("  'fallback' = take proximity when the gap clears the threshold, otherwise")
    print("  take TWAP's opinion, so every day still gets a call.")
    print()
    print(f"  {'rule':<34} {'n':>4} {'cover':>7} {'win':>5} {'loss':>5} {'flat':>4} "
          f"{'acc':>8} {'net':>6}")
    for g in (0.0, 0.5, 1.0, 1.5, 2.0):
        line(f"proximity only, gap >= {g:.1f}",
             score(bars, rows, lambda r, g=g: r["prox"] if r["gap"] >= g else 0), n)
    print()
    for g in (0.5, 1.0, 1.5, 2.0):
        line(f"fallback to TWAP, gap >= {g:.1f}",
             score(bars, rows, lambda r, g=g: r["prox"] if r["gap"] >= g else r["twapL"]), n)
    print()
    for g in (0.5, 1.0, 1.5):
        line(f"agree, else TWAP, gap >= {g:.1f}",
             score(bars, rows,
                   lambda r, g=g: r["prox"] if (r["gap"] >= g and r["prox"] == r["twapL"])
                   else r["twapL"]), n)

    head("RANKED BY WINNING DAYS - the goal is the most wins, not the best percentage")
    cands = []
    for h in HOURS:
        rw = per_hour[h]
        for lbl, fn in (
            ("proximity", lambda r: r["prox"]),
            ("TWAP", lambda r: r["twapL"]),
            ("TWAP 21:00", lambda r: r["twapS"]),
            ("prox+TWAP agree", lambda r: r["prox"] if r["prox"] == r["twapL"] else 0),
            ("prox, else TWAP (g1.0)",
             lambda r: r["prox"] if r["gap"] >= 1.0 else r["twapL"]),
            ("prox, else TWAP (g1.5)",
             lambda r: r["prox"] if r["gap"] >= 1.5 else r["twapL"]),
            ("TWAP + slope agree",
             lambda r: r["twapL"] if r["twapL"] == r["slope"] else 0),
            ("prox+TWAP+slope agree",
             lambda r: r["prox"] if r["prox"] == r["twapL"] == r["slope"] else 0),
        ):
            w, l, z, t = score(bars, rw, fn)
            cands.append((w - l, pct(w, w + l) if w + l else 0, t, h, lbl, w, l))
    cands.sort(reverse=True)
    print(f"  {'rank':<5} {'net':>5} {'acc':>7} {'taken':>6} {'cover':>7} {'hour':>6}  rule")
    for k, (net, acc, t, h, lbl, w, l) in enumerate(cands[:14], 1):
        print(f"  {k:<5} {net:+5d} {acc:6.1f}% {t:6d} {pct(t,n):6.1f}% {h:02d}:00  "
              f"{lbl}   ({w}W / {l}L)")


def main():
    for spec in sys.argv[1:]:
        name, _, path = spec.partition("=")
        analyse(name, load(path))


if __name__ == "__main__":
    main()
