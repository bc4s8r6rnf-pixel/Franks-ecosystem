import pickle, numpy as np, collections, dirlab, math
exec(open("v25_dualote.py").read().split('print("="*136)')[0])

def brk(since=2024, until=2027, h0=0.0, h1=24.0, cost=0.0, hold=2*96,
        stopmul=None, tgtmul=None, needcall=False, conf=0.0):
    out=[]
    for s in S:
        if not (since <= s.day.year < until): continue
        R=s.R; U=s.bh+2*R; L=s.bl-2*R; span=U-L
        lE=L+E62*span; sE=U-E62*span
        idx=[i for i in range(s.lo,s.hi+1)
             if h0 <= (B[i].t-s.day.timestamp())/3600.0 < h1]
        if not idx: continue
        px0=B[idx[0]].o
        if px0<=lE or px0>=sE: continue
        tap=0; fill=None; ent=np.nan
        for m in idx:
            if B[m].l<=lE and B[m].h>=sE: tap=-99; break
            if B[m].l<=lE: tap,ent,fill=-1,lE,m; break
            if B[m].h>=sE: tap,ent,fill= 1,sE,m; break
        if tap in (0,-99) or fill is None: continue
        side = -1 if tap<0 else 1                 # breakout: follow the tap
        if needcall or conf>0:
            ii=dirlab.win(B,s,4,4.25)
            if not ii: continue
            px=B[ii[0]].o; pz=(px-L)/span
            if conf>0 and abs(pz-.5)<conf: continue
            if needcall and (1 if pz>.5 else -1)!=side: continue
        stop = (s.bh if side<0 else s.bl) if stopmul is None else ent - side*stopmul*R
        tgt  = (L if side<0 else U)      if tgtmul  is None else ent + side*tgtmul*R
        risk=abs(ent-stop)
        if risk<=0 or (side>0 and tgt<=ent) or (side<0 and tgt>=ent): continue
        rr=abs(tgt-ent)/risk
        end=min(len(B)-1,fill+hold); r=None
        for k in range(fill,end+1):
            b=B[k]
            if (b.l<=stop) if side>0 else (b.h>=stop): r=-1.0; break
            if (b.h>=tgt) if side>0 else (b.l<=tgt): r=rr; break
        if r is None: r=side*(B[end].c-ent)/risk
        out.append(dict(r=r-(cost/risk if cost else 0),rr=rr,risk=risk,day=s.day.date(),
                        y=s.day.year,why="filled"))
    return out
def sig(res):
    ts=[t for t in res if t.get("r") is not None]
    r=np.array([t["r"] for t in ts]); w=(r>0).mean()
    rr=np.mean([t["rr"] for t in ts]); need=1/(1+rr)
    se=math.sqrt(need*(1-need)/len(r))
    return w*100, need*100, (w-need)/se

print("="*136)
print("H. THE BREAKOUT VERSION, FULL HISTORY, WITH COSTS AND A SIGNIFICANCE TEST")
print("="*136)
print(HDR)
for a,b,nm in ((2004,2027,"2004-2026 all"),(2004,2014,"2004-2013"),(2014,2020,"2014-2019"),
               (2020,2024,"2020-2023"),(2024,2027,"2024-2026")):
    rep(f"  {nm} gross", brk(since=a,until=b))
    rep(f"  {nm} net $0.25", brk(since=a,until=b,cost=.25))
for a,b,nm in ((2004,2027,"2004-2026"),(2024,2027,"2024-2026")):
    w,n,z=sig(brk(since=a,until=b))
    print(f"\n  {nm}: win {w:.1f}%  break-even needs {n:.1f}%  z {z:+.2f}  "
          f"{'significant' if abs(z)>1.96 else 'INSIDE NOISE'}")

print("\n"+"="*136)
print("I. THE 00:00-08:00 WINDOW, STRESSED BY ERA")
print("="*136)
print(HDR)
for a,b,nm in ((2004,2014,"2004-2013"),(2014,2020,"2014-2019"),(2020,2024,"2020-2023"),
               (2024,2027,"2024-2026"),(2004,2027,"all")):
    rep(f"  {nm} gross", brk(since=a,until=b,h0=0,h1=8))
    rep(f"  {nm} net $0.25", brk(since=a,until=b,h0=0,h1=8,cost=.25))
w,n,z=sig(brk(since=2004,until=2027,h0=0,h1=8))
print(f"\n  win {w:.1f}%  needs {n:.1f}%  z {z:+.2f}  "
      f"{'significant' if abs(z)>1.96 else 'INSIDE NOISE'}")

print("\n"+"="*136)
print("J. REFINEMENTS  (2024-2026)")
print("="*136)
print(HDR)
rep("  breakout, as is", brk())
rep("  + only if it agrees with the call", brk(needcall=True))
rep("  + confidence >= 0.15", brk(conf=.15))
rep("  + confidence >= 0.25", brk(conf=.25))
print()
for sm in (0.5,0.75,1.0,1.5):
    rep(f"  stop {sm:.2f} R from entry", brk(stopmul=sm))
print()
for tm in (0.75,1.0,1.5,2.0,3.0):
    rep(f"  target {tm:.2f} R from entry", brk(tgtmul=tm))
print()
for y in range(2024,2027):
    rep(f"  {y}", brk(since=y,until=y+1,h0=0,h1=8))

print("\n"+"="*136)
print("K. THE REFINEMENTS, LOOK-AHEAD REMOVED  -  zones armed at 04:00, filter read at 04:00")
print("="*136)
print("  In section J the filter was read at 04:00 but the fill could happen at 02:00,")
print("  so the filter was told what price did after the entry. Arming at 04:00 fixes it.")
print()
print(HDR)
for a,b,nm in ((2024,2027,"2024-2026"),(2004,2027,"2004-2026")):
    rep(f"  {nm} breakout, armed 04:00", brk(since=a,until=b,h0=4,h1=24))
    rep(f"  {nm}  + agrees with the call", brk(since=a,until=b,h0=4,h1=24,needcall=True))
    rep(f"  {nm}  + confidence >= 0.15", brk(since=a,until=b,h0=4,h1=24,conf=.15))
    rep(f"  {nm}  + confidence >= 0.25", brk(since=a,until=b,h0=4,h1=24,conf=.25))
    rep(f"  {nm}  + call + conf >= 0.15 net", brk(since=a,until=b,h0=4,h1=24,
                                                  needcall=True,conf=.15,cost=.25))
    print()
print("  and the leaky versions from J, for comparison:")
rep("  2024-26 conf>=0.25 armed 00:00 (LEAKY)", brk(conf=.25))
