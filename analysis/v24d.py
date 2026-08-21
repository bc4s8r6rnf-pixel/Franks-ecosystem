"""v24 part 4: is the selector real, or is it just 'pick the nearest anchor'?"""
import pickle, numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
ROWS,T,CAND=pickle.load(open("v24cache.pkl","rb"))
FIB=0.62
def pf(ts,c=0.0):
    if not ts: return float('nan')
    r=np.array([t["r"]-(c/t["risk"] if c else 0) for t in ts]); gp=r[r>0].sum(); gl=-r[r<0].sum()
    return gp/gl if gl else 99.
def av(ts,c=0.0):
    return float('nan') if not ts else float(np.mean([t["r"]-(c/t["risk"] if c else 0) for t in ts]))
def line(nm,ts,w=30):
    if len(ts)<20: print(f"  {nm:<{w}} n {len(ts)}"); return
    r=np.array([t["r"] for t in ts]); eq=pk=dd=0
    for t in sorted(ts,key=lambda z:z["day"]): eq+=t["r"]; pk=max(pk,eq); dd=max(dd,pk-eq)
    print(f"  {nm:<{w}} {len(r):5d} {100*(r>0).mean():6.1f}% {pf(ts):7.2f} {av(ts):+8.3f} "
          f"{av(ts,.10):+9.3f} {av(ts,.25):+9.3f} ${np.mean([t['risk'] for t in ts]):7.2f} {dd:7.1f}")
HDR=(f"  {'strategy':<30} {'n':>5} {'win%':>6} {'PF':>7} {'avgR':>8} {'net.10':>9} "
     f"{'net.25':>9} {'risk':>8} {'DD':>7}")

# ------- the simple rule: pick whichever anchor sits nearest to price -------
print("="*116)
print("AD. IS THE SELECTOR JUST 'PICK THE NEAREST ANCHOR'?")
print("="*116)
def nearest(i, pool, rank=0):
    r=ROWS[i]
    got=[(a,T[(a,FIB)][i]) for a in pool if T[(a,FIB)][i].get("r") is not None]
    if not got: return None
    got.sort(key=lambda z: abs(r["px"]-r["A"][z[0]]) if r["A"][z[0]] is not None else 9e9)
    return got[min(rank,len(got)-1)][1]
def furthest(i,pool):
    r=ROWS[i]
    got=[(a,T[(a,FIB)][i]) for a in pool if T[(a,FIB)][i].get("r") is not None]
    if not got: return None
    got.sort(key=lambda z: -(abs(r["px"]-r["A"][z[0]]) if r["A"][z[0]] is not None else -1))
    return got[0][1]
print(HDR)
POOL=CAND
line("  nearest anchor",  [t for t in (nearest(i,POOL)  for i in range(len(ROWS))) if t])
line("  2nd nearest",     [t for t in (nearest(i,POOL,1) for i in range(len(ROWS))) if t])
line("  3rd nearest",     [t for t in (nearest(i,POOL,2) for i in range(len(ROWS))) if t])
line("  furthest anchor", [t for t in (furthest(i,POOL)  for i in range(len(ROWS))) if t])
for a in CAND:
    line("  always "+a, [t for t in T[(a,FIB)] if t.get("r") is not None])

# ------- the learned selector, now reported honestly ------------------------
print("\n"+"="*116)
print("AE. THE LEARNED SELECTOR, YEAR BY YEAR  (walk-forward, trained only on prior years)")
print("="*116)
X=[];meta=[]
for i,r in enumerate(ROWS):
    got={a:T[(a,FIB)][i] for a in CAND if T[(a,FIB)][i].get("r") is not None}
    if len(got)<2: continue
    d=lambda a: abs(r["px"]-r["A"][a])/r["R"] if r["A"].get(a) is not None else 0.0
    X.append([r["conf"], r["ratio"] if r["ratio"]==r["ratio"] else 0.0, r["dist"], r["R"],
              d("asia"), d("zone"), d("swing"), d("pre"), d("box"), float(r["side"])])
    meta.append((r["y"], got))
X=np.nan_to_num(np.array(X,float)); yrs=np.array([m[0] for m in meta])
lab=np.array([CAND.index(max(m[1],key=lambda a:m[1][a]["r"])) for m in meta])
sel=[];nb=[]
for Y in sorted(set(yrs[yrs>=2012])):
    tr,te=yrs<Y,yrs==Y
    if tr.sum()<400: continue
    sc=StandardScaler().fit(X[tr])
    m=HistGradientBoostingClassifier(max_iter=250,learning_rate=.05,max_depth=4,
         min_samples_leaf=40,random_state=0).fit(sc.transform(X[tr]),lab[tr])
    for j,pi in zip(np.where(te)[0],m.predict(sc.transform(X[te]))):
        got=meta[j][1]; a=CAND[pi]
        if a in got: sel.append(got[a])
        nb.append(nearest([i for i,r in enumerate(ROWS)][0],CAND) if False else None)
print(HDR)
line("  learned selector", sel)
for Y in sorted({t["y"] for t in sel}):
    line(f"    {Y}", [t for t in sel if t["y"]==Y])

print("\n"+"="*116)
print("AF. SANITY: WHAT DOES A TINY STOP ACTUALLY COST?")
print("="*116)
allt=[t for a in CAND for t in T[(a,FIB)] if t.get("r") is not None]
rk=np.array([t["risk"] for t in allt])
print(f"  risk distribution across every anchor/day: median ${np.median(rk):.2f}   "
      f"25th ${np.percentile(rk,25):.2f}   10th ${np.percentile(rk,10):.2f}")
print(f"  a $0.25 round trip on the median stop = {0.25/np.median(rk):.3f} R")
print(f"\n  {'risk bucket':<22} {'n':>6} {'win%':>7} {'PF':>7} {'avgR':>8} {'net.25':>9}")
for lo,hi in ((0,1),(1,2),(2,3),(3,5),(5,10),(10,999)):
    ts=[t for t in allt if lo<=t["risk"]<hi]
    if len(ts)<50: continue
    r=np.array([t["r"] for t in ts])
    print(f"  ${lo}-{hi if hi<999 else '+':<19} {len(ts):6d} {100*(r>0).mean():6.1f}% "
          f"{pf(ts):7.2f} {av(ts):+8.3f} {av(ts,.25):+9.3f}")
