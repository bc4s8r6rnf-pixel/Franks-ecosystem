"""
v24: the -0.27 is always pinned to the target 2.0 edge. Where does the 1 go?

  price(f) = A + (1-f)/1.27 * (B-A)      A = fib 1, B = fib -0.27 = target edge

    f 0.79 -> 16.54% of the way from A to B   stop at A -> 5.05 : 1
    f 0.70 -> 23.62%                                    -> 3.23 : 1
    f 0.62 -> 29.92%                                    -> 2.34 : 1

  RR depends ONLY on which fib you enter at, never on the anchor. The anchor
  decides how deep the entry sits, how often it fills, and the dollar risk.
"""
import pickle, numpy as np, dirlab, collections
B,S=pickle.load(open("bs.pkl","rb"))
L=[s for s in S if s.lab is not None]
for s in L:
    s.f=None
    for i in range(s.lo,s.hi+1):
        if B[i].h>=s.up or B[i].l<=s.dn: s.f=B[i].t; break
F={0.62:(1-0.62)/1.27, 0.70:(1-0.70)/1.27, 0.79:(1-0.79)/1.27}
MAXHOLD=2*96

def pivots(i0, side, look=96, lr=3):
    """most recent confirmed 15m pivot low (buy) / high (sell) before bar i0"""
    best=None
    for i in range(max(lr,i0-look), i0-lr):
        w=range(i-lr,i+lr+1)
        if side>0 and all(B[i].l<=B[j].l for j in w): best=B[i].l
        if side<0 and all(B[i].h>=B[j].h for j in w): best=B[i].h
    return best

def ext(s,h0,h1,side,shift=0):
    q=dirlab.ohlc(B,dirlab.win(B,s,h0,h1,shift))
    return None if q is None else (q[2] if side>0 else q[1])

def anchors(s,i0,side):
    R=s.R
    A={}
    A["zone"]  = (s.bl-2*R) if side>0 else (s.bh+2*R)
    A["box"]   = s.bl if side>0 else s.bh
    A["asia"]  = ext(s,-5,0,side)
    A["london"]= ext(s,2,4,side)
    A["pre"]   = ext(s,0,4,side)
    A["prevd"] = ext(s,-24,0,side,shift=0) if False else None
    q=dirlab.ohlc(B,[i for i in range(max(0,s.lo-96),s.lo)])
    A["prevd"] = None if q is None else (q[2] if side>0 else q[1])
    A["swing"] = pivots(i0,side)
    return A

ROWS=[]
for k in range(3,len(L)):
    s=L[k]; R=s.R
    ii=dirlab.win(B,s,4,4.25)
    if not ii: continue
    i0=ii[0]; px=B[i0].o
    z2u,z2d=s.bh+2*R, s.bl-2*R
    pz=(px-z2d)/(z2u-z2d); side=1 if pz>.5 else -1
    Bt = z2u if side>0 else z2d
    resolved = s.f is not None and s.f<=B[i0].t
    prevlane=dirlab.ohlc(B,[i for i in range(max(0,s.lo-96),s.lo)])
    prng=(prevlane[1]-prevlane[2]) if prevlane else np.nan
    ROWS.append(dict(s=s,i0=i0,px=px,side=side,Bt=Bt,R=R,conf=abs(pz-.5),lab=s.lab,
                     y=s.y,day=s.day.date(),A=anchors(s,i0,side),resolved=resolved,
                     ratio=R/prng if prng and prng>0 else np.nan,
                     dist=abs(Bt-px)/R))
print(f"sessions with a call at 04:00: {len(ROWS)}")

def trade(r, aname, fib, buf=0.0, allow_mkt=False):
    A=r["A"].get(aname); side=r["side"]; Bt=r["Bt"]; px=r["px"]; R=r["R"]; s=r["s"]
    if A is None: return dict(r=None,why="no anchor")
    span=Bt-A
    if (side>0 and span<=0) or (side<0 and span>=0): return dict(r=None,why="anchor past target")
    ent=A+F[fib]*span
    stop=A-side*buf*R
    risk=abs(ent-stop)
    if risk<=0: return dict(r=None,why="no risk")
    rr=abs(Bt-ent)/risk
    already=(side>0 and ent>=px) or (side<0 and ent<=px)
    if already and not allow_mkt: return dict(r=None,why="entry already through price")
    fill = r["i0"] if already else next((m for m in range(r["i0"],s.hi+1)
                                         if B[m].l<=ent<=B[m].h), None)
    if already: ent=px; risk=abs(ent-stop); rr=abs(Bt-ent)/risk
    if fill is None: return dict(r=None,why="never reached")
    if risk<=0 or (side>0 and Bt<=ent) or (side<0 and Bt>=ent):
        return dict(r=None,why="degenerate")
    end=min(len(B)-1,fill+MAXHOLD); out=None
    for m in range(fill,end+1):
        b=B[m]
        if (b.l<=stop) if side>0 else (b.h>=stop): out=-1.0; break
        if (b.h>=Bt) if side>0 else (b.l<=Bt): out=rr; break
    if out is None: out=side*(B[end].c-ent)/risk
    return dict(r=out,rr=rr,risk=risk,why="filled",day=r["day"],y=r["y"],
                conf=r["conf"],ratio=r["ratio"],dist=r["dist"],ent=ent,edge=side*(px-ent))

def rep(nm,res,w=30,cost=0.0):
    ts=[t for t in res if t.get("r") is not None]
    if not ts: print(f"  {nm:<{w}} none"); return None
    rv=np.array([t["r"]-(cost/t["risk"] if cost else 0) for t in ts])
    gp=rv[rv>0].sum(); gl=-rv[rv<0].sum()
    ts2=sorted(ts,key=lambda z:z["day"]); eq=pk=dd=0
    for t,v in zip(ts2,[x["r"] for x in ts2]): eq+=v; pk=max(pk,eq); dd=max(dd,pk-eq)
    print(f"  {nm:<{w}} {len(rv):5d} {(rv>0).sum():5d}W {(rv<0).sum():5d}L {100*(rv>0).mean():6.1f}% "
          f"PF {(gp/gl if gl else 99):5.2f} RR {np.mean([t['rr'] for t in ts]):5.2f} "
          f"risk ${np.mean([t['risk'] for t in ts]):7.2f} avgR {rv.mean():+.3f} "
          f"totR {rv.sum():+8.1f} DD {dd:5.1f}")
    return rv.mean()
HDR=(f"  {'variant':<30} {'n':>5} {'W':>6} {'L':>6} {'win%':>7} {'PF':>8} {'RR':>8} "
     f"{'risk':>12} {'avgR':>7} {'totR':>9} {'DD':>7}")
NAMES=["zone","box","asia","london","pre","prevd","swing"]

print("\n"+"="*126)
print("U. EVERY ANCHOR x EVERY ENTRY FIB.  -0.27 always on the target 2.0 edge, stop always on the 1 anchor")
print("="*126)
for fib in (0.62,0.70,0.79):
    print(f"\n  --- entry at the {fib:.2f} retracement   (fixed {(1-F[fib])/F[fib]:.2f} : 1) ---")
    print(HDR)
    for a in NAMES:
        rep(f"  1 anchored to {a}", [trade(r,a,fib) for r in ROWS])

print("\n"+"="*126)
print("V. FILL BEHAVIOUR  -  why each anchor misses days")
print("="*126)
print(f"  {'anchor':<12} {'filled':>7} {'fill%':>7} {'never reached':>14} {'already past':>14} "
      f"{'past target':>12} {'none':>6}")
for a in NAMES:
    c=collections.Counter(trade(r,a,0.62)["why"] for r in ROWS)
    tot=sum(c.values())
    print(f"  {a:<12} {c['filled']:7d} {100*c['filled']/tot:6.1f}% {c['never reached']:14d} "
          f"{c['entry already through price']:14d} {c['anchor past target']:12d} {c['no anchor']:6d}")

print("\n"+"="*126)
print("W. THE DAYS THE ZONE-TO-ZONE 0.62 NEVER REACHED  -  does a nearer anchor rescue them?")
print("="*126)
miss={r["day"] for r in ROWS if trade(r,"zone",0.62)["why"]!="filled"}
print(f"  {len(miss)} of {len(ROWS)} days ({100*len(miss)/len(ROWS):.1f}%) the zone-to-zone 0.62 never filled\n")
print(HDR)
MR=[r for r in ROWS if r["day"] in miss]
for fib in (0.62,0.70,0.79):
    for a in ("asia","london","pre","swing","box"):
        rep(f"  {a} @ {fib:.2f}", [trade(r,a,fib) for r in MR])
    print()
