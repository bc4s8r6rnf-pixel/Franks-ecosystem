"""
v28: the four reference-point anchors, exactly as drawn on the chart.

  -0.27 pinned to the target 2.0 edge, 1 on one of four fixed references:
     Z   today's opposing 2.0 edge
     A   the Asia swing extreme        19:00 - 00:00 NY
     P   yesterday's last confirmed swing pivot
     PZ  yesterday's opposing 2.0 edge

  entry = A + (1-f)/1.27 x (T - A),  stop on the 1, target the -0.27
     f 0.62 -> 2.34 : 1     f 0.70 -> 3.23 : 1     f 0.79 -> 5.05 : 1
"""
import csv, pickle, numpy as np, collections
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
NY=ZoneInfo("America/New_York")
class Bar: __slots__=("ny","o","h","l","c","t")
def load_tv(p):
    out=[]
    for r in csv.DictReader(open(p)):
        try: t=int(float(r["time"]))
        except: continue
        b=Bar(); b.t=t; b.ny=datetime.fromtimestamp(t,NY)
        b.o,b.h,b.l,b.c=float(r["open"]),float(r["high"]),float(r["low"]),float(r["close"])
        out.append(b)
    out.sort(key=lambda z:z.t); return out
class S: __slots__=("day","bh","bl","R","up","dn","lo","hi","y")
def sessions(B):
    idx={}
    for i,b in enumerate(B): idx.setdefault(b.ny.date(),[]).append(i)
    out=[]; last=B[-1].ny
    for d in sorted(idx):
        an=[i for i in idx[d] if B[i].ny.hour==21]
        if not an: continue
        hi=max(B[i].h for i in an); lo=min(B[i].l for i in an)
        if hi<=lo: continue
        d0=d+timedelta(days=1)
        ls=datetime(d0.year,d0.month,d0.day,tzinfo=NY); le=ls+timedelta(days=1)
        if le>last: continue
        ids=[i for i in range(an[-1]+1,len(B)) if ls<=B[i].ny<le]
        if len(ids)<20: continue
        s=S(); s.day=ls; s.bh,s.bl,s.R=hi,lo,hi-lo
        s.up,s.dn=hi+2*s.R, lo-2*s.R; s.lo,s.hi=ids[0],ids[-1]; s.y=ls.year
        out.append(s)
    return out
def pivots(B, lr=5):
    """confirmed pivot high/low, keyed by the bar the pivot CONFIRMS on"""
    ph={}; pl={}
    for i in range(lr, len(B)-lr):
        w=range(i-lr,i+lr+1)
        if all(B[i].h>=B[j].h for j in w): ph[i+lr]=B[i].h
        if all(B[i].l<=B[j].l for j in w): pl[i+lr]=B[i].l
    return ph,pl
def build(B, lr=5):
    Sx=sessions(B); PH,PL=pivots(B,lr)
    rows=[]; lastPH=lastPL=None; prevUp=prevDn=None
    for k,s in enumerate(Sx):
        # last confirmed pivot as of the lane open, and yesterday's zone edges
        for i in range(0 if k==0 else Sx[k-1].lo, s.lo):
            if i in PH: lastPH=PH[i]
            if i in PL: lastPL=PL[i]
        # asia 19:00-00:00 NY, the five hours before the lane
        a0=s.day.timestamp()-5*3600; a1=s.day.timestamp()
        aw=[i for i in range(max(0,s.lo-260),s.lo) if a0<=B[i].t<a1]
        aHi=max((B[i].h for i in aw), default=None)
        aLo=min((B[i].l for i in aw), default=None)
        j=next((i for i in range(s.lo,s.hi+1) if B[i].ny.hour>=4), None)
        rows.append(dict(s=s,i0=j,pvH=lastPH,pvL=lastPL,aHi=aHi,aLo=aLo,
                         pUp=prevUp,pDn=prevDn))
        prevUp,prevDn=s.up,s.dn
    return rows
F={0.62:(1-0.62)/1.27, 0.70:(1-0.70)/1.27, 0.79:(1-0.79)/1.27}
MAX=2*96
def trade(B,r,anch,fib):
    s=r["s"]
    if r["i0"] is None: return dict(r=None,why="no bar")
    px=B[r["i0"]].o
    side=1 if (s.up-px)<(px-s.dn) else -1
    T = s.up if side>0 else s.dn
    A = (s.dn if side>0 else s.up) if anch=="Z" else \
        ((r["aLo"] if side>0 else r["aHi"]) if anch=="A" else
        ((r["pvL"] if side>0 else r["pvH"]) if anch=="P" else
         (r["pDn"] if side>0 else r["pUp"])))
    if A is None: return dict(r=None,why="no anchor")
    span=T-A
    if (side>0 and span<=0) or (side<0 and span>=0): return dict(r=None,why="anchor past target")
    ent=A+F[fib]*span; stop=A; risk=abs(ent-stop)
    if risk<=0: return dict(r=None,why="no risk")
    rr=abs(T-ent)/risk
    if (side>0 and ent>=px) or (side<0 and ent<=px): return dict(r=None,why="already through")
    fill=next((m for m in range(r["i0"],s.hi+1) if B[m].l<=ent<=B[m].h),None)
    if fill is None: return dict(r=None,why="never reached")
    end=min(len(B)-1,fill+MAX); out=None
    for m in range(fill,end+1):
        b=B[m]
        if (b.l<=stop) if side>0 else (b.h>=stop): out=-1.0; break
        if (b.h>=T) if side>0 else (b.l<=T): out=rr; break
    if out is None: out=side*(B[end].c-ent)/risk
    return dict(r=out,rr=rr,risk=risk,why="filled",day=s.day.date(),y=s.y,side=side)
def rep(nm,res,w=24,cost=0.0):
    ts=[t for t in res if t.get("r") is not None]
    if not ts: print(f"  {nm:<{w}} no trades"); return
    rv=np.array([t["r"]-(cost/t["risk"] if cost else 0) for t in ts])
    gp=rv[rv>0].sum(); gl=-rv[rv<0].sum()
    eq=pk=dd=0
    for t in sorted(ts,key=lambda z:z["day"]): eq+=t["r"]; pk=max(pk,eq); dd=max(dd,pk-eq)
    print(f"  {nm:<{w}} {len(rv):4d} {int((rv>0).sum()):4d}W {int((rv<0).sum()):4d}L "
          f"{100*(rv>0).mean():6.1f}% PF {(gp/gl if gl else 99):5.2f} RR "
          f"{np.mean([t['rr'] for t in ts]):5.2f} risk ${np.mean([t['risk'] for t in ts]):7.2f} "
          f"avgR {rv.mean():+.3f} totR {rv.sum():+7.1f} DD {dd:5.1f}")
HDR=(f"  {'anchor':<24} {'n':>4} {'W':>5} {'L':>5} {'win%':>7} {'PF':>8} {'RR':>8} "
     f"{'risk':>12} {'avgR':>9} {'totR':>8} {'DD':>7}")
TV=load_tv("/root/.claude/uploads/986dcf13-ec74-53a1-b424-6a3e3047f197/830a2bc9-FX_XAUUSD_15_8a5ec.csv")
MT5,_=pickle.load(open("bs.pkl","rb"))
NAMES={"Z":"Z  today's zone edge","A":"A  Asia extreme",
       "P":"P  yesterday's swing","PZ":"PZ yesterday's zone"}
for tag,B in (("OANDA-matched window, 27 May - 19 Aug 2026",TV),("MT5, 2004-2026",MT5)):
    R_=build(B)
    print("="*124); print(f"  {tag}   {len(R_)} lanes"); print("="*124)
    for fib in (0.62,0.70,0.79):
        print(f"\n  --- entry at the {fib:.2f}  ({(1-F[fib])/F[fib]:.2f} : 1) ---")
        print(HDR)
        for a in ("Z","A","P","PZ"):
            rep("  "+NAMES[a],[trade(B,r,a,fib) for r in R_])
    print("\n  fill behaviour at the 0.62:")
    for a in ("Z","A","P","PZ"):
        c=collections.Counter(trade(B,r,a,0.62)["why"] for r in R_); tot=sum(c.values())
        print(f"    {NAMES[a]:<24} filled {c['filled']:4d} ({100*c['filled']/tot:4.1f}%)   "
              f"never reached {c['never reached']:4d}   already through {c['already through']:4d}   "
              f"no anchor {c['no anchor']:3d}   past target {c['anchor past target']:3d}")
    print()

import math
print("="*124)
print("  SIGNIFICANCE, COSTS, AND WHETHER THE RECENT WINDOW IS SPECIAL")
print("="*124)
def sig(res,fib):
    ts=[t for t in res if t.get("r") is not None]
    if len(ts)<8: return None
    r=np.array([t["r"] for t in ts]); w=(r>0).mean()
    need=1/(1+(1-F[fib])/F[fib]); se=math.sqrt(need*(1-need)/len(r))
    return len(ts), 100*w, 100*need, (w-need)/se
print(f"\n  {'sample':<34} {'anchor':<22} {'n':>4} {'win%':>7} {'need':>7} {'z':>7}  verdict")
for tag,B,R_ in (("OANDA window 2026",TV,build(TV)),("MT5 2004-2026",MT5,build(MT5))):
    for fib in (0.62,0.79):
        for a in ("Z","A","P","PZ"):
            v=sig([trade(B,r,a,fib) for r in R_],fib)
            if not v: continue
            n,w,need,z=v
            print(f"  {tag+' @ '+format(fib,'.2f'):<34} {NAMES[a]:<22} {n:4d} {w:6.1f}% "
                  f"{need:6.1f}% {z:+7.2f}  {'significant' if abs(z)>1.96 else 'INSIDE NOISE'}")
    print()
R5=build(MT5)
print("  MT5 by era, anchor P (yesterday's swing) at the 0.62 and the 0.79:")
print(HDR)
for fib in (0.62,0.79):
    for a,b in ((2004,2010),(2010,2015),(2015,2020),(2020,2024),(2024,2027)):
        ts=[t for t in (trade(MT5,r,"P",fib) for r in R5)
            if t.get("r") is not None and a<=t["y"]<b]
        rep(f"  {a}-{b-1} @ {fib:.2f}", ts)
    print()
print("  net of a $0.25 round trip:")
print(HDR)
for tag,B,R_ in (("OANDA 2026",TV,build(TV)),("MT5 all",MT5,R5)):
    for fib in (0.62,0.79):
        for a in ("Z","A","P"):
            rep(f"  {tag} {NAMES[a][:2]} @{fib:.2f}",[trade(B,r,a,fib) for r in R_],cost=0.25)
    print()
print("  combined book - take whichever of Z / A / P fills first each day (0.79):")
print(HDR)
for tag,B,R_ in (("OANDA 2026",TV,build(TV)),("MT5 all",MT5,R5)):
    out=[]
    for r in R_:
        cands=[trade(B,r,a,0.79) for a in ("Z","A","P")]
        ok=[c for c in cands if c.get("r") is not None]
        if ok: out.append(max(ok,key=lambda c:c["risk"]))   # deepest anchor = widest stop
    rep(f"  {tag} deepest-of-three", out)
