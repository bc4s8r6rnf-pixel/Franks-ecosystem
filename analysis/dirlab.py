#!/usr/bin/env python3
"""
dirlab: reverse-engineer the daily direction call on the RXWLES 9pm projection.

LABEL      which 2.0 zone edge trades first inside the lane
           1 = upper (srcHigh + 2R)   0 = lower (srcLow - 2R)   drop = neither

Every feature is evaluated on the OPEN of the decision bar, so nothing in the
matrix can see past the moment a live call would be made.
"""
import math, csv
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
SRC_HOUR = 21


class Bar: __slots__ = ("ny","o","h","l","c","v","t")


def _last_sunday(y, m):
    d = datetime(y, m, 30 if m == 4 else 31)
    while d.month != m: d -= timedelta(days=1)
    while d.weekday() != 6: d -= timedelta(days=1)
    return d

def _eest(dt):
    return _last_sunday(dt.year,3).replace(hour=4) <= dt < _last_sunday(dt.year,10).replace(hour=4)

def load(path, since=None):
    bars = []
    with open(path) as fh:
        r = csv.reader(fh, delimiter=';'); next(r)
        for x in r:
            try: bt = datetime.strptime(x[0], "%Y.%m.%d %H:%M")
            except Exception: continue
            if since and bt.year < since: continue
            utc = bt.replace(tzinfo=timezone.utc) - timedelta(hours=3 if _eest(bt) else 2)
            b = Bar()
            b.ny = utc.astimezone(NY); b.t = b.ny.timestamp()
            try:
                b.o,b.h,b.l,b.c,b.v = (float(x[1]),float(x[2]),float(x[3]),float(x[4]),float(x[5]))
            except Exception: continue
            if b.h < b.l or b.o <= 0: continue
            bars.append(b)
    bars.sort(key=lambda z: z.t)
    return bars


class S: __slots__ = ("day","bh","bl","R","up","dn","lo","hi","bo","bc","bv","f","y","lab")


def sessions(bars):
    idx = {}
    for i,b in enumerate(bars): idx.setdefault(b.ny.date(), []).append(i)
    out, last = [], bars[-1].ny
    for d in sorted(idx):
        an = [i for i in idx[d] if bars[i].ny.hour == SRC_HOUR]
        if not an: continue
        hi = max(bars[i].h for i in an); lo = min(bars[i].l for i in an)
        if hi <= lo: continue
        d0 = d + timedelta(days=1)
        ls = datetime(d0.year,d0.month,d0.day,tzinfo=NY); le = ls + timedelta(days=1)
        if le > last: continue
        ids = [i for i in range(an[-1]+1, len(bars)) if ls <= bars[i].ny < le]
        if len(ids) < 20: continue
        s = S()
        s.day, s.bh, s.bl, s.R = ls, hi, lo, hi-lo
        s.up, s.dn = hi + 2.0*s.R, lo - 2.0*s.R
        s.lo, s.hi = ids[0], ids[-1]
        s.bo, s.bc = bars[an[0]].o, bars[an[-1]].c
        s.bv = sum(bars[i].v for i in an)
        s.y = ls.year
        # ---- label: which 2.0 edge trades first -------------------------
        s.lab = None
        for i in ids:
            hu, hd = bars[i].h >= s.up, bars[i].l <= s.dn
            if hu and hd: s.lab = None; break          # ambiguous inside one bar
            if hu: s.lab = 1; break
            if hd: s.lab = 0; break
        out.append(s)
    return out


def win(bars, s, h0, h1, shift=0):
    """bars whose NY time is in [lane+h0, lane+h1) hours, shifted back `shift` days."""
    a = s.day.timestamp() + h0*3600 - shift*86400
    b = s.day.timestamp() + h1*3600 - shift*86400
    return [i for i in range(max(0, s.lo-400), min(len(bars), s.hi+1))
            if a <= bars[i].t < b]

def ohlc(bars, ii):
    if not ii: return None
    return (bars[ii[0]].o, max(bars[i].h for i in ii),
            min(bars[i].l for i in ii), bars[ii[-1]].c)

def px_at(bars, s, h):
    ii = win(bars, s, h, h+0.25)
    return bars[ii[0]].o if ii else None


# ---------------------------------------------------------------- features
def digital_root(n):
    n = int(abs(n))
    return 0 if n == 0 else 1 + (n-1) % 9

def ema(seq, n):
    k = 2/(n+1); out = []; e = None
    for x in seq:
        e = x if e is None else x*k + e*(1-k)
        out.append(e)
    return out


def build(bars, S, dhour=4.0):
    """One feature dict per session, all evaluated at the open of `dhour`."""
    # lane closes / highs / lows, for the multi-day context
    lc = [bars[s.hi].c for s in S]
    lh = [max(bars[i].h for i in range(s.lo, s.hi+1)) for s in S]
    ll = [min(bars[i].l for i in range(s.lo, s.hi+1)) for s in S]
    e10, e20, e50, e200 = ema(lc,10), ema(lc,20), ema(lc,50), ema(lc,200)
    tr = [lh[i]-ll[i] for i in range(len(S))]
    atr20 = ema(tr,20); atr100 = ema(tr,100)

    rows = []
    for k, s in enumerate(S):
        if k < 200: rows.append(None); continue
        R = s.R
        di = win(bars, s, dhour, dhour+0.25)
        if not di: rows.append(None); continue
        d0 = di[0]; px = bars[d0].o
        f = {}
        # ---- A. where price sits ------------------------------------
        f["pos_zone"]   = (px - s.dn)/(s.up - s.dn)
        f["d_up_R"]     = (s.up - px)/R
        f["d_dn_R"]     = (px - s.dn)/R
        f["closer_up"]  = 1.0 if (s.up-px) < (px-s.dn) else 0.0     # <- the 04:00 call
        f["pos_box"]    = (px - s.bl)/R
        f["outside_box"]= 1.0 if px > s.bh else (-1.0 if px < s.bl else 0.0)
        # ---- B. the 9pm box itself ----------------------------------
        f["box_body"]   = (s.bc - s.bo)/R
        f["box_clspos"] = (s.bc - s.bl)/R
        f["box_R"]      = R
        f["R_rel"]      = R/max(1e-9, atr20[k-1])
        f["R_pctile"]   = sum(1 for j in range(k-100,k) if S[j].R < R)/100.0
        # ---- C. sessions before the decision -------------------------
        for nm, h0, h1 in (("asia",-5,0), ("pre",0,dhour), ("eve",-6,-3), ("ldn",3,dhour)):
            q = ohlc(bars, win(bars, s, h0, h1))
            if q is None:
                f[nm+"_dir"]=f[nm+"_rng"]=f[nm+"_hi"]=f[nm+"_lo"]=0.0; continue
            o,hh,lw,cc = q
            f[nm+"_dir"] = (cc-o)/R
            f[nm+"_rng"] = (hh-lw)/R
            f[nm+"_hi"]  = (hh - s.bh)/R
            f[nm+"_lo"]  = (s.bl - lw)/R
        # ---- C2. liquidity sweeps: which side went first -------------
        aq = ohlc(bars, win(bars, s, -5, 0))
        sw = 0.0
        if aq:
            for i in win(bars, s, 0, dhour):
                if bars[i].h >= aq[1]: sw = 1.0; break
                if bars[i].l <= aq[2]: sw = -1.0; break
        f["sweep_asia"] = sw
        swb = 0.0
        for i in win(bars, s, 0, dhour):
            if bars[i].h >= s.bh: swb = 1.0; break
            if bars[i].l <= s.bl: swb = -1.0; break
        f["sweep_box"] = swb
        # ---- D. multi-day context -----------------------------------
        f["prev_lab"] = (1.0 if S[k-1].lab==1 else -1.0 if S[k-1].lab==0 else 0.0)
        st = 0
        for j in range(k-1, max(-1,k-11), -1):
            if S[j].lab is None or (st and S[j].lab != S[k-1].lab): break
            st += 1
        f["streak"] = st * f["prev_lab"]
        for n in (1,2,3,5,10,20):
            f[f"ret{n}"] = (px - lc[k-n])/max(1e-9, atr20[k-1])
        # unmitigated projection edges left behind
        uu = dd = 0; nu = nd = 9.0
        for j in range(max(0,k-20), k):
            for lvl, sgn in ((S[j].up,1), (S[j].dn,-1)):
                touched = any(bars[i].l <= lvl <= bars[i].h
                              for i in range(S[j].lo, min(len(bars), s.lo)))
                if touched: continue
                if lvl > px: uu += 1; nu = min(nu, (lvl-px)/R)
                else:        dd += 1; nd = min(nd, (px-lvl)/R)
        f["unmit_up"], f["unmit_dn"] = float(uu), float(dd)
        f["unmit_bal"] = float(uu-dd)
        f["unmit_nu"], f["unmit_nd"] = min(nu,9.0), min(nd,9.0)
        # ---- E. trend ------------------------------------------------
        a = max(1e-9, atr20[k-1])
        f["v_e10"]  = (px-e10[k-1])/a;  f["v_e20"] = (px-e20[k-1])/a
        f["v_e50"]  = (px-e50[k-1])/a;  f["v_e200"]= (px-e200[k-1])/a
        f["sl_e20"] = (e20[k-1]-e20[k-6])/a
        f["sl_e50"] = (e50[k-1]-e50[k-11])/a
        f["stack"]  = float((e10[k-1]>e20[k-1]) + (e20[k-1]>e50[k-1]) + (e50[k-1]>e200[k-1])) - 1.5
        for n in (20,60):
            hi_ = max(lh[k-n:k]); lo_ = min(ll[k-n:k])
            f[f"rngpos{n}"] = (px-lo_)/max(1e-9, hi_-lo_)
        f["volreg"] = atr20[k-1]/max(1e-9, atr100[k-1])
        # ---- F. the 3-6-9 / Gann battery -----------------------------
        f["mod9"]    = px % 9
        f["mod10"]   = px % 10
        f["mod50"]   = px % 50
        f["mod90"]   = px % 90
        f["mod100"]  = px % 100
        f["mod360"]  = px % 360
        f["d_to_90"] = min(px % 90, 90 - px % 90)
        f["d_to_100"]= min(px % 100, 100 - px % 100)
        f["sq9"]     = (math.sqrt(px)*180) % 360
        f["sq9_sin"] = math.sin(math.radians((math.sqrt(px)*180) % 360))
        f["droot"]   = float(digital_root(round(px)))
        f["droot369"]= 1.0 if digital_root(round(px)) in (3,6,9) else 0.0
        # ---- G. clock: the 18:00 / 21:00 / 00:00 / 03:00 opens --------
        prev = None
        for nm, h in (("h18",-6),("h19",-5),("h20",-4),("h21",-3),("h22",-2),
                      ("h00",0),("h01",1),("h02",2),("h03",3)):
            q = px_at(bars, s, h)
            f["pz_"+nm] = ((q - s.dn)/(s.up - s.dn)) if q else 0.5
            f["dl_"+nm] = ((px - q)/R) if q else 0.0
            if prev is not None and q: f["seg_"+nm] = (q-prev)/R
            prev = q if q else prev
        f["dow"]   = float(s.day.weekday())
        f["dom"]   = float(s.day.day)
        f["month"] = float(s.day.month)
        f["doy9"]  = float(digital_root(s.day.timetuple().tm_yday))
        rows.append(f)
    return rows
