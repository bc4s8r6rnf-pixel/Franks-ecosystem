#!/usr/bin/env python3
"""
RXWLES PRO zone-sequence analyser.

Reads a TradingView H1 export and measures what price actually does with the
zones the indicator draws:

    src           = the 21:00 New York hourly candle
    r             = src.high - src.low
    Daily Upper   = src.high + 2.0r .. src.high + 2.5r
    Daily Lower   = src.low  - 2.0r .. src.low  - 2.5r
    Enigma        = src.high .. src.low
    lane          = 00:00 NY the following day -> 00:00 NY the day after

Everything resolves in America/New_York, daylight saving included, exactly as
the indicator does.

Usage:  python3 zone_sequence.py FX_XAUUSD_60.csv [more.csv ...]
"""

import csv
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")

# ---- configuration ---------------------------------------------------------
SRC_HOUR    = 21     # Enigma source hour, NY
REF_HOUR    = 9      # "NY open" hour for the proximity read
LVL1        = 2.0    # inner zone boundary, in ranges
LVL2        = 2.5    # outer zone boundary
BOOK_DAYS   = 10     # how many prior sessions of untouched levels stay live
CLUSTER_TOL = 0.25   # levels within this many ranges count as one stacked level
REACT_R     = 1.0    # retrace from the tap extreme that counts as a rejection
USE_ENIGMA  = True   # include old untouched Enigma ranges as levels
MIN_BARS    = 10     # a lane with fewer bars is a holiday or a half day
STOP_R      = 1.0    # entry-model stop, in ranges
FADE_STOP_R = 0.25   # fade-model stop beyond the far edge

OC_NONE, OC_UP, OC_DN, OC_UPDN, OC_DNUP = range(5)
OC_NAME = ["neither    ", "UP only    ", "DOWN only  ", "UP then DN ", "DN then UP "]


# ---------------------------------------------------------------- data -----
class Bar:
    __slots__ = ("ny", "o", "h", "l", "c")

    def __init__(self, ny, o, h, l, c):
        self.ny, self.o, self.h, self.l, self.c = ny, o, h, l, c


def load(path):
    bars = []
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            t = row.get("time")
            if t is None:
                continue
            try:
                ts = int(float(t))
            except ValueError:                       # ISO timestamps
                ts = int(datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp())
            bars.append(Bar(datetime.fromtimestamp(ts, NY),
                            float(row["open"]), float(row["high"]),
                            float(row["low"]), float(row["close"])))
    bars.sort(key=lambda b: b.ny)
    return bars


class Session:
    __slots__ = ("day", "anchor_dir", "rhigh", "rlow", "rng", "u1", "u2", "l1", "l2",
                 "lo_idx", "hi_idx", "lane_hi", "lane_lo", "first", "first_hr",
                 "second", "ny_px", "near", "gap", "outcome", "ambiguous",
                 "touch_u1", "touch_l2", "touch_eh", "touch_el")


def build_sessions(bars):
    """One record per 21:00 candle, covering the 00:00->00:00 lane it governs."""
    by_time = {b.ny: i for i, b in enumerate(bars)}
    last_ny = bars[-1].ny
    out = []

    for i, b in enumerate(bars):
        if b.ny.hour != SRC_HOUR:
            continue
        rng = b.h - b.l
        if rng <= 0:
            continue

        d0 = b.ny.date() + timedelta(days=1)
        lane_start = datetime(d0.year, d0.month, d0.day, tzinfo=NY)
        d1 = d0 + timedelta(days=1)
        lane_end = datetime(d1.year, d1.month, d1.day, tzinfo=NY)
        if lane_end > last_ny:                       # still running, or truncated
            continue

        idxs = [j for j in range(i + 1, len(bars))
                if lane_start <= bars[j].ny < lane_end]
        if len(idxs) < MIN_BARS:
            continue

        s = Session()
        s.day, s.rhigh, s.rlow, s.rng = lane_start, b.h, b.l, rng
        s.anchor_dir = 1 if b.c >= b.o else -1
        s.u1, s.u2 = b.h + LVL1 * rng, b.h + LVL2 * rng
        s.l2, s.l1 = b.l - LVL1 * rng, b.l - LVL2 * rng
        s.lo_idx, s.hi_idx = idxs[0], idxs[-1]
        s.lane_hi = max(bars[j].h for j in idxs)
        s.lane_lo = min(bars[j].l for j in idxs)
        s.first = s.second = 0
        s.first_hr = -1
        s.ny_px = s.near = s.gap = None
        s.ambiguous = False

        for j in idxs:
            bb = bars[j]
            if s.ny_px is None and bb.ny.hour == REF_HOUR:
                s.ny_px = bb.o
                d_up, d_dn = (s.u1 - bb.o) / rng, (bb.o - s.l2) / rng
                s.near = 1 if d_up < d_dn else -1
                s.gap = abs(d_up - d_dn)

            t_up, t_dn = bb.h >= s.u1, bb.l <= s.l2
            if s.first == 0:
                if t_up and t_dn:
                    # One H1 bar reached both. Infer the order from the candle's
                    # direction and flag it - H1 cannot resolve this.
                    s.ambiguous = True
                    s.first = -1 if bb.c >= bb.o else 1
                    s.second = -s.first
                    s.first_hr = bb.ny.hour
                elif t_up or t_dn:
                    s.first = 1 if t_up else -1
                    s.first_hr = bb.ny.hour
            elif s.second == 0 and ((s.first > 0 and t_dn) or (s.first < 0 and t_up)):
                s.second = -s.first

        s.outcome = (OC_NONE if s.first == 0 else
                     (OC_UP if s.first > 0 else OC_DN) if s.second == 0 else
                     (OC_UPDN if s.first > 0 else OC_DNUP))
        out.append(s)

    # First time each level was ever reached, searched forward across later
    # lanes too - this is what makes a level "virgin".
    for k, s in enumerate(out):
        stop = out[min(k + BOOK_DAYS + 1, len(out) - 1)].hi_idx
        s.touch_u1 = s.touch_l2 = s.touch_eh = s.touch_el = None
        for j in range(s.lo_idx, stop + 1):
            bb = bars[j]
            if s.touch_u1 is None and bb.h >= s.u1:
                s.touch_u1 = j
            if s.touch_l2 is None and bb.l <= s.l2:
                s.touch_l2 = j
            if s.touch_eh is None and bb.h >= s.rhigh:
                s.touch_eh = j
            if s.touch_el is None and bb.l <= s.rlow:
                s.touch_el = j
            if None not in (s.touch_u1, s.touch_l2, s.touch_eh, s.touch_el):
                break
    return out


# ------------------------------------------------------------- the book ----
class Level:
    __slots__ = ("sess", "kind", "age", "side", "near", "far", "rng",
                 "cluster", "dist", "dist_own", "order", "bar", "result")


def virgin(s, kind, side, lane_start_idx):
    t = ((s.touch_eh if side > 0 else s.touch_el) if kind == 1 else
         (s.touch_u1 if side > 0 else s.touch_l2))
    return t is None or t >= lane_start_idx


def build_book(bars, sessions, i):
    """Every level still live and still in front of price when lane i opens."""
    s = sessions[i]
    px = bars[s.lo_idx].o
    book = []

    for age in range(0, BOOK_DAYS + 1):
        j = i - age
        if j < 0:
            break
        z = sessions[j]
        for kind in (0, 1):
            if kind == 1 and (not USE_ENIGMA or age == 0):
                # Tonight's own Enigma range is where price already sits - it
                # would win every proximity contest for trivial reasons.
                continue
            for side in (1, -1):
                if age > 0 and not virgin(z, kind, side, s.lo_idx):
                    continue
                if kind == 1:
                    near = z.rhigh if side > 0 else z.rlow
                    far = (z.rhigh + 0.25 * z.rng) if side > 0 else (z.rlow - 0.25 * z.rng)
                else:
                    near = z.u1 if side > 0 else z.l2
                    far = z.u2 if side > 0 else z.l1
                if (side > 0 and near <= px) or (side < 0 and near >= px):
                    continue                     # behind price, not a target
                L = Level()
                L.sess, L.kind, L.age, L.side = j, kind, age, side
                L.near, L.far, L.rng = near, far, z.rng
                L.dist = abs(near - px) / s.rng          # in units of today's range
                L.dist_own = abs(near - px) / z.rng      # in units of the level's own range
                L.order, L.bar, L.result = 0, None, 0
                book.append(L)

    tol = CLUSTER_TOL * s.rng
    for a in book:
        a.cluster = sum(1 for b in book if abs(a.near - b.near) <= tol)

    # Consumption order, and what happened at each level once reached.
    order = 0
    for j in range(s.lo_idx, s.hi_idx + 1):
        bb = bars[j]
        while True:
            hits = [L for L in book if L.order == 0 and
                    (bb.h >= L.near if L.side > 0 else bb.l <= L.near)]
            if not hits:
                break
            L = min(hits, key=lambda L: abs(L.near - bb.o))
            order += 1
            L.order, L.bar = order, j
        for L in book:
            if L.order == 0 or L.result == 2:
                continue
            if L.side > 0:
                ext = max(bars[k].h for k in range(L.bar, j + 1))
                if ext >= L.far:
                    L.result = 2
                elif ext - bb.l >= REACT_R * L.rng:
                    L.result = 1
                elif L.result == 0:
                    L.result = 3
            else:
                ext = min(bars[k].l for k in range(L.bar, j + 1))
                if ext <= L.far:
                    L.result = 2
                elif bb.h - ext >= REACT_R * L.rng:
                    L.result = 1
                elif L.result == 0:
                    L.result = 3
    return book


# ------------------------------------------------------------- printing ----
def pct(a, b):
    return 0.0 if b <= 0 else 100.0 * a / b


def rule(w=78):
    print("-" * w)


def head(t):
    print()
    rule()
    print(t)
    rule()


# ---------------------------------------------------------------- rules ----
RULES = [
    ("nearest in price",                  lambda L, a, ls: -L.dist),
    ("nearest, scaled by its own range",  lambda L, a, ls: -L.dist_own),
    ("oldest untouched first (FIFO)",     lambda L, a, ls: L.age * 10.0 - L.dist),
    ("newest first (LIFO)",               lambda L, a, ls: -L.age * 10.0 - L.dist),
    ("widest anchor candle wins",         lambda L, a, ls: L.rng),
    ("tightest anchor candle wins",       lambda L, a, ls: -L.rng),
    ("biggest cluster",                   lambda L, a, ls: float(L.cluster)),
    ("cluster first, nearest as tiebreak",lambda L, a, ls: L.cluster * 10.0 - L.dist),
    ("side the 9pm candle closed toward", lambda L, a, ls: (10.0 if L.side == a else 0.0) - L.dist),
    ("opposite side to last consumed",    lambda L, a, ls: (10.0 if ls and L.side == -ls else 0.0) - L.dist),
    ("same side as last consumed",        lambda L, a, ls: (10.0 if ls and L.side == ls else 0.0) - L.dist),
]

def features(L, anchor_dir):
    d = min(L.dist, 6.0)
    return (1.0 - d / 6.0,
            L.age / BOOK_DAYS,
            min(L.cluster - 1, 3) / 3.0,
            1.0 if L.side == anchor_dir else 0.0)


def walk(bars, s, entry_idx, side, entry, tp, sl):
    """Returns realised R. Same-bar target-and-stop is scored as a loss."""
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    for j in range(entry_idx, s.hi_idx + 1):
        b = bars[j]
        hit_sl = b.l <= sl if side > 0 else b.h >= sl
        hit_tp = b.h >= tp if side > 0 else b.l <= tp
        if hit_sl:
            return -1.0
        if hit_tp:
            return abs(tp - entry) / risk
    return side * (bars[s.hi_idx].c - entry) / risk


def report_model(name, res):
    if not res:
        print(f"  {name:<44} no qualifying sessions")
        return
    wins = sum(1 for r in res if r > 0)
    tot = sum(res)
    print(f"  {name:<44} n={len(res):<4} win {pct(wins,len(res)):5.1f}%  "
          f"avgR {tot/len(res):+6.2f}  totR {tot:+8.1f}")


# --------------------------------------------------------------- driver ----
def analyse(name, bars):
    S = build_sessions(bars)
    n = len(S)
    print()
    print("=" * 78)
    print(f"  {name}   {n} sessions   {S[0].day:%Y-%m-%d} -> {S[-1].day:%Y-%m-%d}")
    print(f"  Zones: src.high + {LVL1}r..{LVL2}r  /  src.low - {LVL1}r..{LVL2}r   "
          f"(r = the {SRC_HOUR}:00 NY candle)")
    print("=" * 78)

    books, firsts, ranks = [], [], []
    last_side = 0
    for i in range(n):
        bk = build_book(bars, S, i)
        books.append(bk)
        taken = [L for L in bk if L.order == 1]
        if taken:
            L = taken[0]
            firsts.append(L)
            ranks.append(1 + sum(1 for o in bk if o.dist < L.dist))
            consumed = [o for o in bk if o.order > 0]
            last_side = max(consumed, key=lambda o: o.order).side
        else:
            firsts.append(None)
            ranks.append(None)

    # ---- base rates --------------------------------------------------------
    oc = [sum(1 for s in S if s.outcome == k) for k in range(5)]
    head("BASE RATES")
    for k in range(5):
        print(f"  {OC_NAME[k]}  {oc[k]:4d}   {pct(oc[k], n):5.1f}%")
    both, one = oc[OC_UPDN] + oc[OC_DNUP], oc[OC_UP] + oc[OC_DN]
    print()
    print(f"  BOTH zones tagged      {both:4d}   {pct(both, n):5.1f}%")
    print(f"  ONE zone only          {one:4d}   {pct(one, n):5.1f}%")
    print(f"  NEITHER reached        {oc[OC_NONE]:4d}   {pct(oc[OC_NONE], n):5.1f}%")
    amb = sum(1 for s in S if s.ambiguous)
    print(f"  ({amb} sessions tagged both inside one H1 bar - order inferred)")

    # ---- regime ------------------------------------------------------------
    need = 1.0 + 2.0 * LVL1
    head(f"REGIME - a day must expand {need:.1f} R to tag both zones")
    exps = [(s.lane_hi - s.lane_lo) / s.rng for s in S]
    enough = sum(1 for e in exps if e >= need)
    print(f"  Mean day expansion:                  {sum(exps)/len(exps):.2f} R")
    print(f"  Days with the room to tag both:      {pct(enough, n):5.1f}%")
    print(f"  Days that actually tagged both:      {pct(both, n):5.1f}%")
    print(f"  Gap (had the room, did not use it):  {pct(enough, n) - pct(both, n):5.1f} points")
    print()
    print("  Outcome by anchor-candle size (ranked against the previous 20):")
    print("    anchor size     both%   one%  none%   mean expansion    n")
    for q in range(5):
        rows = []
        for i in range(20, n):
            rank = sum(1 for k in range(i - 20, i) if S[k].rng < S[i].rng)
            if min(4, rank // 4) == q:
                rows.append(i)
        if not rows:
            continue
        b_ = sum(1 for i in rows if S[i].outcome in (OC_UPDN, OC_DNUP))
        z_ = sum(1 for i in rows if S[i].outcome == OC_NONE)
        e_ = sum(exps[i] for i in rows) / len(rows)
        nm = ["smallest 20%", "2nd quintile", "middle 20% ", "4th quintile", "largest 20% "][q]
        print(f"    {nm}    {pct(b_,len(rows)):5.1f}%  {pct(len(rows)-b_-z_,len(rows)):5.1f}%  "
              f"{pct(z_,len(rows)):5.1f}%      {e_:5.2f} R      {len(rows):4d}")

    # ---- hypotheses --------------------------------------------------------
    head("HYPOTHESIS 1 - after a one-sided day, does the OTHER side go first?")
    t = o = 0
    for i in range(1, n):
        p = S[i - 1]
        if p.outcome in (OC_UP, OC_DN) and S[i].first != 0:
            t += 1
            if S[i].first == -(1 if p.outcome == OC_UP else -1):
                o += 1
    print(f"  Other side first: {o} / {t} = {pct(o,t):.1f}%   (coin flip = 50.0%)")

    head("HYPOTHESIS 2 - does price go to the zone it was nearest at the NY open?")
    t = h = 0
    for s in S:
        if s.ny_px is None or s.first == 0:
            continue
        t += 1
        if s.first == s.near:
            h += 1
    print(f"  Nearest zone tagged first: {h} / {t} = {pct(h,t):.1f}%")
    print()
    print("  Split by how lopsided the proximity read was:")
    print("    gap band          nearest first     n")
    for lo, hi in ((0, .25), (.25, .75), (.75, 1.5), (1.5, 99)):
        t2 = h2 = 0
        for s in S:
            if s.ny_px is None or s.first == 0 or not (lo <= s.gap < hi):
                continue
            t2 += 1
            if s.first == s.near:
                h2 += 1
        print(f"    {lo:.2f} - {hi:.2f} R        {pct(h2,t2):5.1f}%       {t2:4d}")

    # ---- transitions -------------------------------------------------------
    head("SEQUENCE - yesterday's outcome (row) vs today's first tap")
    print("  yesterday ->      UP first   DN first   neither      n")
    for a in range(5):
        up = sum(1 for i in range(1, n) if S[i-1].outcome == a and S[i].first > 0)
        dn = sum(1 for i in range(1, n) if S[i-1].outcome == a and S[i].first < 0)
        nz = sum(1 for i in range(1, n) if S[i-1].outcome == a and S[i].first == 0)
        tot = up + dn + nz
        print(f"  {OC_NAME[a]}   {pct(up,tot):5.1f}%    {pct(dn,tot):5.1f}%    "
              f"{pct(nz,tot):5.1f}%    {tot:4d}")

    # ---- timing ------------------------------------------------------------
    head("TIMING - NY hour of the first tap")
    hrs = {}
    for s in S:
        if s.first:
            hrs[s.first_hr] = hrs.get(s.first_hr, 0) + 1
    tot = sum(hrs.values())
    for h_ in sorted(hrs, key=lambda x: (x - SRC_HOUR - 1) % 24):
        print(f"  {h_:02d}:00 NY  {pct(hrs[h_],tot):5.1f}%  {hrs[h_]:4d}  "
              f"{'#' * int(round(pct(hrs[h_],tot)/2))}")

    # ---- carry-forward -----------------------------------------------------
    head("CARRY-FORWARD - respect rate by age of the untouched level")
    print("  age   met   respected   blown   stalled    respect rate")
    for age in range(0, min(7, BOOK_DAYS + 1)):
        met = res = bl = st = 0
        for bk in books:
            for L in bk:
                if L.age != age or L.result == 0:
                    continue
                met += 1
                res += L.result == 1
                bl += L.result == 2
                st += L.result == 3
        if met:
            print(f"  {age:3d}  {met:5d}   {res:6d}   {bl:6d}   {st:6d}      {pct(res,met):5.1f}%")

    head("TAKEN FIRST - by age, as a rate against how often that age was live")
    print("  age   taken first   times live   taken-first rate")
    for age in range(0, min(7, BOOK_DAYS + 1)):
        live = sum(1 for bk in books for L in bk if L.age == age)
        got = sum(1 for L in firsts if L is not None and L.age == age)
        if live:
            print(f"  {age:3d}   {got:6d}        {live:7d}       {pct(got,live):5.1f}%")

    head("LEVEL TYPE - which drawn object does price actually travel to?")
    for kind, nm in ((0, "Daily Zone (2.0-2.5)"), (1, "Enigma range boundary")):
        live = sum(1 for bk in books for L in bk if L.kind == kind)
        got = sum(1 for L in firsts if L is not None and L.kind == kind)
        if live:
            print(f"  {nm:<24} taken first {got:5d}   live {live:6d}   {pct(got,live):5.1f}%")

    # ---- was it simply the closest? ---------------------------------------
    head("FIRST LEVEL TAKEN - its rank in the nearest-first ordering")
    rk = [r for r in ranks if r]
    for k in range(1, 8):
        c = rk.count(k)
        if c:
            print(f"  rank {k:2d}   {pct(c,len(rk)):5.1f}%  {c:4d}  {'#' * int(round(pct(c,len(rk))/2))}"
                  f"{'   <- pure proximity' if k == 1 else ''}")
    print(f"  ({len(rk)} sessions where the book offered a real choice)")

    # ---- tournament --------------------------------------------------------
    head("ORDERING RULES - which predicts the level taken first?")
    print("  rule                                          top-1     MRR      n")
    valid = [i for i in range(n) if firsts[i] is not None and len(books[i]) >= 2]
    ls_at = {}
    ls = 0
    for i in range(n):
        ls_at[i] = ls
        cons = [L for L in books[i] if L.order > 0]
        if cons:
            ls = max(cons, key=lambda L: L.order).side
    for nm, fn in RULES:
        hit = 0
        mrr = 0.0
        for i in valid:
            bk, W, a = books[i], firsts[i], S[i].anchor_dir
            sc = [(fn(L, a, ls_at[i]), L) for L in bk]
            wsc = fn(W, a, ls_at[i])
            rank = 1 + sum(1 for v, _ in sc if v > wsc)
            best = max(sc, key=lambda t: t[0])[1]
            hit += best is W
            mrr += 1.0 / rank
        print(f"  {nm:<44} {pct(hit,len(valid)):5.1f}%   {mrr/len(valid):5.3f}   {len(valid):4d}")
    chance = sum(1.0 / len(books[i]) for i in valid) / len(valid)
    print(f"  {'CHANCE (random pick from the book)':<44} {100*chance:5.1f}%       -    {len(valid):4d}")

    # ---- formula search ----------------------------------------------------
    head("FORMULA SEARCH - fit on the first half, scored on the second")
    grid = (-1.0, -0.5, 0.0, 0.5, 1.0)
    split = n // 2
    train = [i for i in valid if i < split]
    test = [i for i in valid if i >= split]

    def acc(ws, idxs):
        hit = 0
        for i in idxs:
            best, bv = None, None
            for L in books[i]:
                f = features(L, S[i].anchor_dir)
                v = sum(w * x for w, x in zip(ws, f))
                if bv is None or v > bv:
                    bv, best = v, L
            hit += best is firsts[i]
        return pct(hit, len(idxs))

    best_w, best_a = None, -1
    for w0 in grid:
        for w1 in grid:
            for w2 in grid:
                for w3 in grid:
                    if w0 == w1 == w2 == w3 == 0:
                        continue
                    a = acc((w0, w1, w2, w3), train)
                    if a > best_a:
                        best_a, best_w = a, (w0, w1, w2, w3)
    ch_test = 100 * sum(1.0 / len(books[i]) for i in test) / len(test) if test else 0
    print(f"  best weights:  proximity {best_w[0]:+.1f}   staleness {best_w[1]:+.1f}   "
          f"confluence {best_w[2]:+.1f}   anchor-bias {best_w[3]:+.1f}")
    print(f"  train (first half)   {best_a:5.1f}%   n={len(train)}")
    print(f"  TEST  (second half)  {acc(best_w, test):5.1f}%   n={len(test)}")
    print(f"  chance on test       {ch_test:5.1f}%")

    # ---- second level given the first --------------------------------------
    head("SECOND LEVEL, GIVEN THE FIRST")
    same = opp = older = newer = tot = 0
    for i in range(n):
        f1 = firsts[i]
        s2 = [L for L in books[i] if L.order == 2]
        if f1 is None or not s2:
            continue
        L = s2[0]
        tot += 1
        same += L.side == f1.side
        opp += L.side != f1.side
        older += L.age > f1.age
        newer += L.age < f1.age
    print(f"  sessions with a 2nd consumption: {tot}")
    print(f"    same side as the first:  {pct(same,tot):5.1f}%")
    print(f"    opposite side:           {pct(opp,tot):5.1f}%")
    print(f"    an OLDER level next:     {pct(older,tot):5.1f}%")
    print(f"    a NEWER level next:      {pct(newer,tot):5.1f}%")

    # ---- entry models ------------------------------------------------------
    head("ENTRY MODELS - pre-specified, costs NOT modelled")
    m = {k: [] for k in range(1, 7)}
    for i, s in enumerate(S):
        if s.ny_px is not None:
            for mode in (1, 3, 4, 5):
                side = s.near
                if mode in (3, 5):
                    if i == 0 or S[i-1].outcome not in (OC_UP, OC_DN):
                        continue
                    ps = 1 if S[i-1].outcome == OC_UP else -1
                    if mode == 5:
                        side = -ps
                    elif side != -ps:
                        continue
                if mode == 4 and s.gap < 0.5:
                    continue
                entry = s.ny_px
                tp = s.u1 if side > 0 else s.l2
                if (side > 0 and tp <= entry) or (side < 0 and tp >= entry):
                    continue
                ny_idx = next(j for j in range(s.lo_idx, s.hi_idx + 1)
                              if bars[j].ny.hour == REF_HOUR)
                r_ = walk(bars, s, ny_idx, side, entry, tp, entry - side * STOP_R * s.rng)
                if r_ is not None:
                    m[mode].append(r_)

        if s.first and not s.ambiguous:                      # model 2: fade the tap
            side = -s.first
            entry = s.u1 if s.first > 0 else s.l2
            tp = s.l2 if s.first > 0 else s.u1
            sl = (s.u2 + FADE_STOP_R * s.rng) if s.first > 0 else (s.l1 - FADE_STOP_R * s.rng)
            idx = next((j for j in range(s.lo_idx, s.hi_idx + 1)
                        if (bars[j].h >= s.u1 if s.first > 0 else bars[j].l <= s.l2)), None)
            if idx is not None:
                r_ = walk(bars, s, idx, side, entry, tp, sl)
                if r_ is not None:
                    m[2].append(r_)

        for side in (1, -1):                                 # model 6: ride the break
            far = s.u2 if side > 0 else s.l1
            idx = next((j for j in range(s.lo_idx, s.hi_idx + 1)
                        if (bars[j].h >= far if side > 0 else bars[j].l <= far)), None)
            if idx is None:
                continue
            cand = [L for L in books[i] if L.age >= 1 and L.side == side and
                    ((L.near > far) if side > 0 else (L.near < far))]
            if not cand:
                continue
            tgt = min(cand, key=lambda L: abs(L.near - far))
            r_ = walk(bars, s, idx, side, far, tgt.near, far - side * STOP_R * s.rng)
            if r_ is not None:
                m[6].append(r_)

    report_model("1  NY open -> nearest zone", m[1])
    report_model("2  fade the first tap -> opposite zone", m[2])
    report_model("3  nearest AND opposite of yesterday", m[3])
    report_model("4  nearest AND decisive proximity gap", m[4])
    report_model("5  opposite of yesterday, ignoring proximity", m[5])
    report_model("6  break of today's zone -> old virgin level", m[6])
    print()
    print("  Model 5 is the control for model 3. If 3 does not beat 5, the proximity")
    print("  read adds nothing. Subtract spread and commission before believing any of it.")


def main():
    for spec in sys.argv[1:]:
        name, _, paths = spec.partition("=")
        if not paths:
            name, paths = spec.rsplit("/", 1)[-1], spec
        bars, seen = [], set()
        for p in paths.split(","):
            for b in load(p):
                if b.ny not in seen:
                    seen.add(b.ny)
                    bars.append(b)
        bars.sort(key=lambda b: b.ny)
        analyse(name, bars)


if __name__ == "__main__":
    main()
