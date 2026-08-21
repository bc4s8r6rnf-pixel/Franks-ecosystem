import pickle, numpy as np, dirlab
B,S = pickle.load(open("bs.pkl","rb"))
MAXHOLD=2*96
def mkt(conf=0.0, stopmode="zone", stopR=1.0, tgt=2.0, h0=4, since=2005, cost=0.0):
    """market entry at h0, no waiting."""
    out=[]
    for s in S:
        if s.day.year<since: continue
        R=s.R; up=s.bh+2*R; dn=s.bl-2*R
        ii=dirlab.win(B,s,h0,h0+.25)
        if not ii: continue
        i0=ii[0]; px=B[i0].o; pz=(px-dn)/(up-dn)
        if abs(pz-.5)<conf: continue
        side=1 if pz>.5 else -1
        Bt=(s.bh+tgt*R) if side>0 else (s.bl-tgt*R)
        if (side>0 and Bt<=px) or (side<0 and Bt>=px): continue
        if stopmode=="zone":  A = dn if side>0 else up
        elif stopmode=="box": A = (s.bl-0.5*R) if side>0 else (s.bh+0.5*R)
        else:                 A = px - side*stopR*R
        risk=abs(px-A)
        if risk<=0: continue
        rr=abs(Bt-px)/risk
        end=min(len(B)-1,i0+MAXHOLD); r=None
        for k in range(i0,end+1):
            b=B[k]
            if (b.l<=A) if side>0 else (b.h>=A): r=-1.0; break
            if (b.h>=Bt) if side>0 else (b.l<=Bt): r=rr; break
        if r is None: r=side*(B[end].c-px)/risk
        out.append(dict(r=r-cost/risk,rr=rr,risk=risk,day=s.day.date(),y=s.day.year))
    return out
def rep(nm,ts,w=36):
    if not ts: print(f"  {nm:<{w}} none"); return
    r=np.array([t["r"] for t in ts]); gp=r[r>0].sum(); gl=-r[r<0].sum()
    ts=sorted(ts,key=lambda z:z["day"]); eq=pk=dd=0
    for t in ts: eq+=t["r"]; pk=max(pk,eq); dd=max(dd,pk-eq)
    print(f"  {nm:<{w}} {len(r):5d} {(r>0).sum():5d}W {(r<0).sum():5d}L {100*(r>0).mean():6.1f}% "
          f"PF {(gp/gl if gl else 99):5.2f} RR {np.mean([t['rr'] for t in ts]):5.2f} "
          f"risk ${np.mean([t['risk'] for t in ts]):7.2f} avgR {r.mean():+.3f} "
          f"totR {r.sum():+8.1f} DD {dd:5.1f}")
HDR=(f"  {'variant':<36} {'n':>5} {'W':>6} {'L':>6} {'win%':>7} {'PF':>8} {'RR':>8} "
     f"{'risk':>12} {'avgR':>7} {'totR':>9} {'DD':>7}")
print("="*128);print("L. MARKET ENTRY AT 04:00 (no waiting) x CONFIDENCE FILTER, stop = the 2.0 edge behind")
print("="*128);print(HDR)
for c in (0.0,0.10,0.15,0.20,0.25,0.30,0.35):
    rep(f"  market 04:00  |pos-.5| >= {c:.2f}", mkt(conf=c))
print("\n  stop a fixed multiple of the 9pm range instead:")
for sm,lab in (("box","stop 0.5R past the far box edge"),):
    for c in (0.0,0.15,0.25,0.30):
        rep(f"  {lab} >= {c:.2f}", mkt(conf=c, stopmode=sm))
for sr in (0.5,1.0,1.5,2.0):
    rep(f"  fixed stop {sr:.1f}R  |pos-.5| >= 0.25", mkt(conf=0.25, stopmode="fix", stopR=sr))
print("\n"+"="*128);print("M. THE BEST CELL, STRESSED  -  market 04:00, |pos-0.5| >= 0.30")
print("="*128);print(HDR)
T=mkt(conf=0.30)
rep("  all years", T)
T2=sorted(T,key=lambda t:t["day"]); h=len(T2)//2
rep("  first half", T2[:h]); rep("  second half", T2[h:])
for Y in sorted({t["y"] for t in T}): rep(f"  {Y}", [t for t in T if t["y"]==Y])
print("\n  2023+ with a $0.25 round trip:")
rep("  gross", mkt(conf=0.30, since=2023)); rep("  NET", mkt(conf=0.30, since=2023, cost=0.25))
print("\n"+"="*128);print("N. WAIT-FOR-BOX-EDGE vs MARKET, matched on the same high-confidence days (>= 0.30)")
print("="*128);print(HDR)
import importlib.util
spec=importlib.util.spec_from_file_location("p","pnl.py")
rep("  market entry at 04:00", mkt(conf=0.30))
