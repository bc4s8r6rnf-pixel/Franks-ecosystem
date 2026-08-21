import pickle, numpy as np, dirlab
B,S = pickle.load(open("bs.pkl","rb"))
MAXHOLD=2*96
def sim(d=0.0, tgt=2.0, conf=0.0, brk=False, h0=4, h1=24, since=2005, cost=0.0):
    out=[]
    for s in S:
        R=s.R; up=s.bh+2*R; dn=s.bl-2*R
        if s.day.year<since: continue
        ii=dirlab.win(B,s,h0,h0+.25)
        if not ii: continue
        px=B[ii[0]].o; pz=(px-dn)/(up-dn)
        if abs(pz-.5)<conf: continue
        side=1 if pz>.5 else -1
        if brk:
            if   px>s.bh: side=1
            elif px<s.bl: side=-1
            else: continue
        A=dn if side>0 else up
        Bt=(s.bh+tgt*R) if side>0 else (s.bl-tgt*R)
        ent=(s.bl-d*R) if side>0 else (s.bh+d*R)
        risk=abs(ent-A)
        if risk<=0 or (side>0 and Bt<=ent) or (side<0 and Bt>=ent): continue
        rr=abs(Bt-ent)/risk
        idx=[i for i in range(max(s.lo,ii[0]),s.hi+1) if h0<=(B[i].ny.hour or 0)<h1 or h1==24]
        fill=next((m for m in idx if B[m].l<=ent<=B[m].h),None)
        if fill is None: continue
        end=min(len(B)-1,fill+MAXHOLD); r=None
        for k in range(fill,end+1):
            b=B[k]
            if (b.l<=A) if side>0 else (b.h>=A): r=-1.0; break
            if (b.h>=Bt) if side>0 else (b.l<=Bt): r=rr; break
        if r is None: r=side*(B[end].c-ent)/risk
        out.append(dict(r=r-cost/risk, rr=rr, risk=risk, day=s.day.date(), y=s.day.year))
    return out
def rep(nm,ts,w=34):
    if not ts: print(f"  {nm:<{w}} none"); return
    r=np.array([t["r"] for t in ts]); gp=r[r>0].sum(); gl=-r[r<0].sum()
    ts=sorted(ts,key=lambda z:z["day"]); eq=pk=dd=0
    for t in ts:
        eq+=t["r"]; pk=max(pk,eq); dd=max(dd,pk-eq)
    print(f"  {nm:<{w}} {len(r):5d} {(r>0).sum():5d}W {(r<0).sum():5d}L {100*(r>0).mean():6.1f}% "
          f"PF {(gp/gl if gl else 99):5.2f} RR {np.mean([t['rr'] for t in ts]):5.2f} "
          f"risk ${np.mean([t['risk'] for t in ts]):7.2f} avgR {r.mean():+.3f} "
          f"totR {r.sum():+8.1f} DD {dd:5.1f}")
HDR=(f"  {'variant':<34} {'n':>5} {'W':>6} {'L':>6} {'win%':>7} {'PF':>8} {'RR':>8} "
     f"{'risk':>12} {'avgR':>7} {'totR':>9} {'DD':>7}")
print("="*126); print("I. DOES THE CONFIDENCE FILTER PAY?  entry at the box edge, stop the 2.0 edge behind, target the 2.0 edge")
print("="*126); print(HDR)
for c in (0.0,0.05,0.10,0.15,0.20,0.25,0.30):
    rep(f"  entry 0.0R   |pos-.5| >= {c:.2f}", sim(d=0.0, conf=c))
print()
for c in (0.0,0.10,0.15,0.20,0.25,0.30):
    rep(f"  entry 0.504R |pos-.5| >= {c:.2f}", sim(d=0.504, conf=c))
print()
rep("  entry 0.0R   box-breakout only", sim(d=0.0, brk=True))
rep("  entry 0.504R box-breakout only", sim(d=0.504, brk=True))
print()
print("="*126); print("J. MODERN SAMPLE 2023-2026, NET OF A $0.25 ROUND TRIP")
print("="*126); print(HDR)
for c in (0.0,0.10,0.15,0.20,0.25,0.30):
    rep(f"  entry 0.0R  >= {c:.2f}  gross", sim(d=0.0, conf=c, since=2023))
    rep(f"  entry 0.0R  >= {c:.2f}  NET",   sim(d=0.0, conf=c, since=2023, cost=0.25))
print()
print("="*126); print("K. YEAR BY YEAR, the |pos-0.5| >= 0.15 filter at the box edge")
print("="*126); print(HDR)
T=sim(d=0.0, conf=0.15)
for Y in sorted({t["y"] for t in T}): rep(f"  {Y}", [t for t in T if t["y"]==Y])
