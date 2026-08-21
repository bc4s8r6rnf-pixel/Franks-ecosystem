"""v24 part 2: era splits, costs, and an HONEST version of the missed-days test."""
import pickle, numpy as np, collections
exec(open("v24_anchors.py").read().split('print("\\n"+"="*126)')[0])

print("="*126)
print("X. WHY SECTION W WAS WRONG  -  'the days the 0.62 never filled' is an outcome, not a setup")
print("="*126)
z=[(r,trade(r,"zone",0.62)) for r in ROWS]
miss=[r for r,t in z if t["why"]!="filled"]
hit =[r for r,t in z if t["why"]=="filled"]
def frac_to_target(rs):
    out=[]
    for r in rs:
        s=r["s"]; side=r["side"]; run=0.0
        for m in range(r["i0"],s.hi+1):
            run=max(run, side*(B[m].h-r["px"])/r["R"] if side>0 else side*(B[m].l-r["px"])/r["R"])
        out.append(run)
    return np.array(out)
fm,fh=frac_to_target(miss),frac_to_target(hit)
print(f"  days the zone 0.62 DID fill   n {len(hit):5d}  best run in favour {fh.mean():5.2f} R")
print(f"  days it never filled          n {len(miss):5d}  best run in favour {fm.mean():5.2f} R")
print(f"  -> selecting on 'never filled' selects days that ran away without pulling back.")
print(f"     Any entry nearer to price wins on those days BY CONSTRUCTION. The 80.8% in")
print(f"     section W is that selection, not an edge. Discard it.")

print("\n"+"="*126)
print("Y. EVERY ANCHOR, SPLIT BY ERA, AND NET OF A $0.25 ROUND TRIP")
print("="*126)
def era(res, m):
    return [t for t in res if t.get("r") is not None and m(t["y"])]
print(f"  {'anchor @ fib':<20} {'n':>5} {'ALL PF':>8} {'05-17':>8} {'18-26':>8} {'23-26':>8} "
      f"{'avgR':>8} {'net avgR':>9} {'net PF 23+':>11} {'avg risk':>9}")
def pf(ts, cost=0.0):
    if not ts: return float('nan')
    r=np.array([t["r"]-(cost/t["risk"] if cost else 0) for t in ts])
    gp=r[r>0].sum(); gl=-r[r<0].sum()
    return gp/gl if gl else 99.0
def avg(ts, cost=0.0):
    if not ts: return float('nan')
    return np.mean([t["r"]-(cost/t["risk"] if cost else 0) for t in ts])
best=[]
for fib in (0.62,0.70,0.79):
    for a in NAMES:
        R_=[trade(r,a,fib) for r in ROWS]
        ts=[t for t in R_ if t.get("r") is not None]
        if not ts: continue
        m23=era(R_,lambda y:y>=2023)
        row=(f"  {a+' @ '+format(fib,'.2f'):<20} {len(ts):5d} {pf(ts):8.2f} "
             f"{pf(era(R_,lambda y:y<=2017)):8.2f} {pf(era(R_,lambda y:y>=2018)):8.2f} "
             f"{pf(m23):8.2f} {avg(ts):+8.3f} {avg(ts,0.25):+9.3f} {pf(m23,0.25):11.2f} "
             f"${np.mean([t['risk'] for t in ts]):8.2f}")
        print(row)
        best.append((a,fib,pf(ts),pf(era(R_,lambda y:y>=2018)),pf(m23,0.25),avg(ts,0.25)))
    print()

print("="*126)
print("Z. THE HONEST VERSION  -  split days by how FAR the zone-to-zone entry sits below price")
print("      (knowable at 04:00; nothing here is selected on what happened afterwards)")
print("="*126)
gaps=[]
for r in ROWS:
    A=r["A"]["zone"]; span=r["Bt"]-A
    ent=A+F[0.62]*span
    gaps.append(abs(r["px"]-ent)/r["R"] if ((r["side"]>0 and ent<r["px"]) or
                                            (r["side"]<0 and ent>r["px"])) else 0.0)
gaps=np.array(gaps); qs=np.quantile(gaps,[.25,.5,.75])
print(f"  distance from 04:00 price down to the zone-to-zone 0.62, in R: "
      f"quartiles {qs[0]:.2f} / {qs[1]:.2f} / {qs[2]:.2f}\n")
print(f"  {'bucket':<24} {'anchor':<8} {'n':>5} {'fill%':>7} {'win%':>7} {'PF':>7} {'avgR':>8} {'netR':>8}")
for lo,hi,nm in ((0,qs[0],"Q1 entry nearest"),(qs[0],qs[1],"Q2"),
                 (qs[1],qs[2],"Q3"),(qs[2],99,"Q4 entry furthest")):
    sub=[r for r,g in zip(ROWS,gaps) if lo<=g<hi]
    for a in ("zone","asia","pre","box","swing"):
        R_=[trade(r,a,0.62) for r in sub]
        ts=[t for t in R_ if t.get("r") is not None]
        if len(ts)<40: continue
        r_=np.array([t["r"] for t in ts])
        print(f"  {nm:<24} {a:<8} {len(ts):5d} {100*len(ts)/len(sub):6.1f}% "
              f"{100*(r_>0).mean():6.1f}% {pf(ts):7.2f} {avg(ts):+8.3f} {avg(ts,0.25):+8.3f}")
    print()
