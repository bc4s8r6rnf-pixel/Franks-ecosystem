"""v29: direction accuracy on OANDA-matched data, and the best stop for the fib entry."""
import numpy as np, pickle, math
exec(open("v28_anchors.py").read().split('def rep(')[0])
TV=load_tv("/root/.claude/uploads/986dcf13-ec74-53a1-b424-6a3e3047f197/830a2bc9-FX_XAUUSD_15_8a5ec.csv")
MT5,_=pickle.load(open("bs.pkl","rb"))
def acc(B,tag):
    Sx=sessions(B); ok=n=res=0
    for s in Sx:
        j=next((i for i in range(s.lo,s.hi+1) if B[i].ny.hour>=4),None)
        if j is None: continue
        # was a zone already taken before the call?
        gone=any(B[i].h>=s.up or B[i].l<=s.dn for i in range(s.lo,j))
        lab=None
        for i in range(s.lo,s.hi+1):
            if B[i].h>=s.up: lab=1; break
            if B[i].l<=s.dn: lab=0; break
        if lab is None: continue
        px=B[j].o; call=1 if (s.up-px)<(px-s.dn) else 0
        if gone: res+=1; continue
        n+=1; ok+= (call==lab)
    return n,100*ok/max(1,n),res
print("="*104)
print("A. DIRECTION CALL - is it the same on OANDA-matched data as on the long history?")
print("="*104)
for tag,B in (("OANDA-matched, May-Aug 2026",TV),("MT5, 2004-2026",MT5)):
    n,a,r=acc(B,tag)
    print(f"  {tag:<32} undecided-at-04:00 lanes {n:5d}   accuracy {a:5.2f}%   "
          f"(+{r} already resolved, excluded)")
print("\n  For reference, from the 22-year study on 4,449 undecided sessions:")
print("    all              71.5%        |pos-0.5| >= 0.15   80.5%")
print("    2018-2026        72.6%        |pos-0.5| >= 0.25   85.0%")
print("    2023-2026        73.4%        |pos-0.5| >= 0.30   88.5%")

print("\n"+"="*116)
print("B. THE BEST STOP FOR THE FIB ENTRY  (anchor P, target the 2.0 zone)")
print("="*116)
def lv(A,T,f): return A+(1-f)/1.27*(T-A)
def trade2(B,r,anch,fib,stopf):
    s=r["s"]
    if r["i0"] is None: return dict(r=None)
    px=B[r["i0"]].o
    side=1 if (s.up-px)<(px-s.dn) else -1
    T=s.up if side>0 else s.dn
    A=(s.dn if side>0 else s.up) if anch=="Z" else \
      ((r["aLo"] if side>0 else r["aHi"]) if anch=="A" else
      ((r["pvL"] if side>0 else r["pvH"]) if anch=="P" else (r["pDn"] if side>0 else r["pUp"])))
    if A is None: return dict(r=None)
    span=T-A
    if (side>0 and span<=0) or (side<0 and span>=0): return dict(r=None)
    ent=lv(A,T,fib); stop=lv(A,T,stopf) if stopf<1.0 else A
    risk=abs(ent-stop)
    if risk<=0: return dict(r=None)
    rr=abs(T-ent)/risk
    if (side>0 and ent>=px) or (side<0 and ent<=px): return dict(r=None)
    fill=next((m for m in range(r["i0"],s.hi+1) if B[m].l<=ent<=B[m].h),None)
    if fill is None: return dict(r=None)
    end=min(len(B)-1,fill+MAX); out=None
    for m in range(fill,end+1):
        b=B[m]
        if (b.l<=stop) if side>0 else (b.h>=stop): out=-1.0; break
        if (b.h>=T) if side>0 else (b.l<=T): out=rr; break
    if out is None: out=side*(B[end].c-ent)/risk
    return dict(r=out,rr=rr,risk=risk,day=s.day.date(),y=s.y)
def rep2(nm,res,w=26,cost=0.0):
    ts=[t for t in res if t.get("r") is not None]
    if not ts: print(f"  {nm:<{w}} none"); return
    rv=np.array([t["r"]-(cost/t["risk"] if cost else 0) for t in ts])
    gp=rv[rv>0].sum(); gl=-rv[rv<0].sum()
    eq=pk=dd=0
    for t in sorted(ts,key=lambda z:z["day"]): eq+=t["r"]; pk=max(pk,eq); dd=max(dd,pk-eq)
    need=1/(1+np.mean([t["rr"] for t in ts]))
    z=((rv>0).mean()-need)/math.sqrt(need*(1-need)/len(rv))
    print(f"  {nm:<{w}} {len(rv):4d} {100*(rv>0).mean():6.1f}% PF {(gp/gl if gl else 99):5.2f} "
          f"RR {np.mean([t['rr'] for t in ts]):6.2f} need {100*need:5.1f}% z {z:+5.2f} "
          f"risk ${np.mean([t['risk'] for t in ts]):7.2f} avgR {rv.mean():+.3f} "
          f"totR {rv.sum():+8.1f} DD {dd:5.1f}")
H2=(f"  {'stop':<26} {'n':>4} {'win%':>7} {'PF':>8} {'RR':>9} {'need':>10} {'z':>7} "
    f"{'risk':>12} {'avgR':>9} {'totR':>9} {'DD':>7}")
for tag,B in (("OANDA window 2026",TV),("MT5 2004-2026",MT5)):
    R_=build(B)
    for fib in (0.62,0.79):
        print(f"\n  --- {tag}, entry at the {fib:.2f}, anchor P ---"); print(H2)
        for sf,nm in ((0.88,"0.88 level"),(0.95,"0.95 level"),(1.0,"the 1 anchor"),
                      (1.05,"5% past the 1"),(1.15,"15% past the 1")):
            rep2(f"  stop {nm}",[trade2(B,r,"P",fib,sf) for r in R_])
