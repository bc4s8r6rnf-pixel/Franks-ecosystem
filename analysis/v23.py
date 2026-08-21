"""v23: (1) the range-ratio x confidence grid  (2) the 0.62-0.70 retracement band"""
import pickle, numpy as np, dirlab
B,S=pickle.load(open("bs.pkl","rb"))
L=[s for s in S if s.lab is not None]
for s in L:
    s.f=None
    for i in range(s.lo,s.hi+1):
        if B[i].h>=s.up or B[i].l<=s.dn: s.f=B[i].t; break
REC=[]
for k in range(2,len(L)):
    s=L[k]; p=L[k-1]
    ii=dirlab.win(B,s,4,4.25)
    if not ii or (s.f is not None and s.f<=B[ii[0]].t): continue
    px=B[ii[0]].o; pz=(px-s.dn)/(s.up-s.dn)
    ph=max(B[i].h for i in range(p.lo,p.hi+1)); pl=min(B[i].l for i in range(p.lo,p.hi+1))
    REC.append(dict(conf=abs(pz-.5), call=1 if pz>.5 else 0, lab=s.lab, y=s.y,
                    rr=s.R/max(1e-9,ph-pl)))
C=np.array([r["conf"] for r in REC]); RR=np.array([r["rr"] for r in REC])
OK=np.array([r["call"]==r["lab"] for r in REC]); Y=np.array([r["y"] for r in REC])
print(f"n {len(REC)}   base {100*OK.mean():.2f}%")
qs=np.quantile(RR,[.25,.5,.75])
print("\n"+"="*104)
print("S. CONFLUENCE GRID  -  today's 9pm box vs yesterday's full range  x  how lopsided the call is")
print("="*104)
print(f"  box/prevRange quartiles: {qs[0]:.3f} {qs[1]:.3f} {qs[2]:.3f}")
print(f"\n  {'':<22}" + "".join(f"{lab:>17}" for lab in
      ("conf<0.10","0.10-0.20","0.20-0.30","conf>=0.30")))
cb=[(0,.10),(.10,.20),(.20,.30),(.30,9)]
rb=[(0,qs[0]),(qs[0],qs[1]),(qs[1],qs[2]),(qs[2],99)]
rlab=["box smallest","","","box largest"]
for j,(a,b) in enumerate(rb):
    row=f"  Q{j+1} {a:.2f}-{b if b<9 else 9.99:.2f} {rlab[j]:<8}"
    for c0,c1 in cb:
        m=(RR>=a)&(RR<b)&(C>=c0)&(C<c1)
        row += f"{(100*OK[m].mean() if m.sum()>25 else float('nan')):11.1f}% n{m.sum():<4d}" if m.sum() else f"{'-':>17}"
    print(row)
print("\n  the two ingredients on their own:")
for nm,m in (("box/prevRange bottom quartile", RR<qs[0]), ("box/prevRange top quartile", RR>=qs[2])):
    print(f"    {nm:<32} n {m.sum():5d}  all {100*OK[m].mean():6.2f}%  2018-26 {100*OK[m&(Y>=2018)].mean():6.2f}%")
print("\n  best combined cell, stressed by era:")
best=(RR>=qs[1])&(C>=.15)
for per,m in (("all",Y>0),("2005-2017",Y<=2017),("2018-2026",Y>=2018),("2023-2026",Y>=2023)):
    q=best&m
    print(f"    box above median AND conf>=0.15   {per:<10} n {q.sum():5d}  acc {100*OK[q].mean():6.2f}%")
for per,m in (("all",Y>0),("2005-2017",Y<=2017),("2018-2026",Y>=2018),("2023-2026",Y>=2023)):
    q=(RR<qs[1])&(C<.15)&m
    print(f"    box below median AND conf<0.15    {per:<10} n {q.sum():5d}  acc {100*OK[q].mean():6.2f}%")

# ---------------------------------------------------------------- fib band
print("\n"+"="*118)
print("T. THE 0.62-0.70 RETRACEMENT BAND, drawn the moment the engine fires at 04:00")
print("="*118)
def band(f0,f1): return ((1-f0)/1.27, (1-f1)/1.27)
E62,E70=band(.62,.70)[0], band(.62,.70)[1]
print(f"  fib 0.62 sits {100*E62:.2f}% of the way from the 2.0 edge to the opposing 2.0 edge")
print(f"  fib 0.70 sits {100*E70:.2f}%   -> for a BUY the band is boxLow -0.504R .. -0.819R\n")
MAX=2*96
def run(mode="band62", tgt=2.0, conf=0.0, since=2005, cost=0.0, h1=24):
    out=[]
    for s in L:
        if s.y<since: continue
        R=s.R; up=s.bh+2*R; dn=s.bl-2*R
        ii=dirlab.win(B,s,4,4.25)
        if not ii: continue
        i0=ii[0]; px=B[i0].o; pz=(px-dn)/(up-dn)
        if abs(pz-.5)<conf: continue
        side=1 if pz>.5 else -1
        A=dn if side>0 else up
        Bt=(s.bh+tgt*R) if side>0 else (s.bl-tgt*R)
        span=Bt-A if False else ( (up-dn) if side>0 else (dn-up) )
        e62=A+E62*span; e70=A+E70*span
        if   mode=="mkt":    ent=px
        elif mode=="band62": ent=e62
        elif mode=="band70": ent=e70
        else:                ent=(e62+e70)/2
        if mode!="mkt":
            # must still be a retracement from where price is when the engine fires
            if (side>0 and ent>=px) or (side<0 and ent<=px): 
                out.append(dict(r=None,why="band already below price",y=s.y)); continue
        risk=abs(ent-A)
        if risk<=0 or (side>0 and Bt<=ent) or (side<0 and Bt>=ent):
            out.append(dict(r=None,why="degenerate",y=s.y)); continue
        rr=abs(Bt-ent)/risk
        fill=i0 if mode=="mkt" else next((m for m in range(i0,s.hi+1)
                                          if B[m].l<=ent<=B[m].h), None)
        if fill is None: out.append(dict(r=None,why="band never reached",y=s.y)); continue
        end=min(len(B)-1,fill+MAX); r=None
        for k in range(fill,end+1):
            b=B[k]
            if (b.l<=A) if side>0 else (b.h>=A): r=-1.0; break
            if (b.h>=Bt) if side>0 else (b.l<=Bt): r=rr; break
        if r is None: r=side*(B[end].c-ent)/risk
        out.append(dict(r=r-cost/risk,rr=rr,risk=risk,day=s.day.date(),y=s.y,
                        why="filled", edge=side*(px-ent)))
    return out
def rep(nm,res,w=32):
    ts=[t for t in res if t["r"] is not None]
    if not ts: print(f"  {nm:<{w}} none"); return
    r=np.array([t["r"] for t in ts]); gp=r[r>0].sum(); gl=-r[r<0].sum()
    ts2=sorted(ts,key=lambda z:z["day"]); eq=pk=dd=0
    for t in ts2: eq+=t["r"]; pk=max(pk,eq); dd=max(dd,pk-eq)
    print(f"  {nm:<{w}} {len(r):5d} {(r>0).sum():5d}W {(r<0).sum():5d}L {100*(r>0).mean():6.1f}% "
          f"PF {(gp/gl if gl else 99):5.2f} RR {np.mean([t['rr'] for t in ts]):5.2f} "
          f"risk ${np.mean([t['risk'] for t in ts]):7.2f} avgR {r.mean():+.3f} "
          f"totR {r.sum():+8.1f} DD {dd:5.1f}")
HDR=(f"  {'variant':<32} {'n':>5} {'W':>6} {'L':>6} {'win%':>7} {'PF':>8} {'RR':>8} "
     f"{'risk':>12} {'avgR':>7} {'totR':>9} {'DD':>7}")
import collections
print("  HOW OFTEN IS THE BAND EVEN REACHED?")
for md,nm in (("band62","0.62 level"),("band70","0.70 level"),("mid","0.66 midpoint")):
    R_=run(md); c=collections.Counter(t["why"] for t in R_)
    tot=sum(c.values())
    print(f"    {nm:<16} filled {c['filled']:5d} / {tot} = {100*c['filled']/tot:5.1f}%   "
          f"never reached {c['band never reached']:5d} ({100*c['band never reached']/tot:4.1f}%)   "
          f"already past {c['band already below price']:5d} ({100*c['band already below price']/tot:4.1f}%)")
E=[t["edge"] for t in run("band62") if t["r"] is not None]
print(f"\n    when the 0.62 does fill, it improves on the 04:00 market price by "
      f"${np.mean(E):.2f} on average (median ${np.median(E):.2f})")
print(f"\n{HDR}")
for md,nm in (("mkt","market at 04:00"),("band62","enter 0.62"),
              ("mid","enter 0.66"),("band70","enter 0.70")):
    rep(f"  {nm}", run(md))
print("\n  with the confidence filter |pos-0.5| >= 0.15:")
for md,nm in (("mkt","market at 04:00"),("band62","enter 0.62"),("band70","enter 0.70")):
    rep(f"  {nm}", run(md, conf=.15))
print("\n  2023-2026 net of $0.25:")
for md,nm in (("mkt","market at 04:00"),("band62","enter 0.62"),("band70","enter 0.70")):
    rep(f"  {nm} NET", run(md, since=2023, cost=.25))
print("\n  PAIRED TEST - only the days the 0.62 actually filled, market vs 0.62 on those same days")
M={t["day"]:t for t in run("mkt") if t["r"] is not None}
F=[t for t in run("band62") if t["r"] is not None]
days=[t["day"] for t in F if t["day"] in M]
print(HDR)
rep("  market at 04:00 (same days)", [M[d] for d in days])
rep("  enter 0.62      (same days)", [t for t in F if t["day"] in M])
print("\n  0.62 entry, year by year:")
T=[t for t in run("band62") if t["r"] is not None]
for yy in sorted({t["y"] for t in T}):
    rep(f"  {yy}", [t for t in T if t["y"]==yy])
