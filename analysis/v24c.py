"""v24 part 3: is there a per-day rule for choosing the anchor?"""
import pickle, numpy as np, collections
exec(open("v24_anchors.py").read().split('print("\\n"+"="*126)')[0])
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
CAND=["zone","box","asia","london","pre","swing","prevd"]
FIB=0.62
T={a:[trade(r,a,FIB) for r in ROWS] for a in CAND}
def pf(ts,c=0.0):
    if not ts: return float('nan')
    r=np.array([t["r"]-(c/t["risk"] if c else 0) for t in ts]); gp=r[r>0].sum(); gl=-r[r<0].sum()
    return gp/gl if gl else 99.
def av(ts,c=0.0):
    return float('nan') if not ts else np.mean([t["r"]-(c/t["risk"] if c else 0) for t in ts])

print("="*120)
print("AA. THE ORACLE  -  if you picked the best anchor every day with perfect hindsight")
print("="*120)
orc=[]; fixed={a:[] for a in CAND}
for i,r in enumerate(ROWS):
    got={a:T[a][i] for a in CAND if T[a][i].get("r") is not None}
    if not got: continue
    for a,t in got.items(): fixed[a].append(t)
    orc.append(max(got.values(), key=lambda t:t["r"]))
print(f"  {'strategy':<26} {'n':>5} {'win%':>7} {'PF':>7} {'avgR':>8} {'net avgR':>9}")
print(f"  {'ORACLE (hindsight)':<26} {len(orc):5d} "
      f"{100*np.mean([t['r']>0 for t in orc]):6.1f}% {pf(orc):7.2f} {av(orc):+8.3f} {av(orc,.25):+9.3f}")
for a in CAND:
    print(f"  {'always '+a:<26} {len(fixed[a]):5d} "
          f"{100*np.mean([t['r']>0 for t in fixed[a]]):6.1f}% {pf(fixed[a]):7.2f} "
          f"{av(fixed[a]):+8.3f} {av(fixed[a],.25):+9.3f}")
print("\n  The oracle is the ceiling a perfect per-day selector could reach. Anything a")
print("  real rule achieves must sit between 'always <best fixed>' and the oracle.")

print("\n"+"="*120)
print("AB. CAN A MODEL LEARN THE CHOICE?  walk-forward, trained only on prior years")
print("="*120)
FE=["conf","ratio","dist","R"]
X=[];Ymat=[];meta=[]
for i,r in enumerate(ROWS):
    got={a:T[a][i] for a in CAND if T[a][i].get("r") is not None}
    if len(got)<2: continue
    X.append([r["conf"], r["ratio"] if r["ratio"]==r["ratio"] else 0.0, r["dist"], r["R"],
              abs(r["px"]-r["A"]["asia"])/r["R"] if r["A"]["asia"] else 0.0,
              abs(r["px"]-r["A"]["zone"])/r["R"],
              abs(r["px"]-(r["A"]["swing"] or r["px"]))/r["R"], float(r["side"])])
    Ymat.append({a:(got[a]["r"] if a in got else np.nan) for a in CAND})
    meta.append((r["y"], got))
X=np.nan_to_num(np.array(X,float)); yrs=np.array([m[0] for m in meta])
lab=np.array([CAND.index(max([a for a in CAND if a in m[1]],
              key=lambda a:m[1][a]["r"])) for m in meta])
print(f"  rows {len(X)}   features: conf, box/yesterday, distance to target, R, "
      f"anchor distances, side")
sel=[]; bench=[]
for Y in sorted(set(yrs[yrs>=2012])):
    tr,te=yrs<Y,yrs==Y
    if tr.sum()<400: continue
    sc=StandardScaler().fit(X[tr])
    m=HistGradientBoostingClassifier(max_iter=250,learning_rate=.05,max_depth=4,
         min_samples_leaf=40,random_state=0).fit(sc.transform(X[tr]),lab[tr])
    p=m.predict(sc.transform(X[te]))
    for j,pi in zip(np.where(te)[0],p):
        got=meta[j][1]; a=CAND[pi]
        sel.append(got[a] if a in got else got[max(got,key=lambda z:0)])
        if "asia" in got: bench.append(got["asia"])
print(f"\n  {'strategy':<26} {'n':>5} {'win%':>7} {'PF':>7} {'avgR':>8} {'net avgR':>9}")
print(f"  {'learned selector':<26} {len(sel):5d} {100*np.mean([t['r']>0 for t in sel]):6.1f}% "
      f"{pf(sel):7.2f} {av(sel):+8.3f} {av(sel,.25):+9.3f}")
print(f"  {'always asia (same years)':<26} {len(bench):5d} "
      f"{100*np.mean([t['r']>0 for t in bench]):6.1f}% {pf(bench):7.2f} {av(bench):+8.3f} "
      f"{av(bench,.25):+9.3f}")

print("\n"+"="*120)
print("AC. THE ONE SURVIVING CELL  -  asia anchor, 0.62, days the zone entry sits nearest price")
print("="*120)
gaps=[]
for r in ROWS:
    A=r["A"]["zone"]; ent=A+F[0.62]*(r["Bt"]-A)
    gaps.append(abs(r["px"]-ent)/r["R"] if ((r["side"]>0 and ent<r["px"]) or
                (r["side"]<0 and ent>r["px"])) else 0.0)
gaps=np.array(gaps); q1=np.quantile(gaps,.25)
print(f"  bucket = zone-to-zone 0.62 sits less than {q1:.2f} R below the 04:00 price\n")
print(f"  {'period':<16} {'n':>5} {'win%':>7} {'PF':>7} {'avgR':>8} "
      f"{'net $0.10':>10} {'net $0.25':>10} {'avg risk':>9} {'DD':>7}")
sub=[T["asia"][i] for i,g in enumerate(gaps) if g<q1 and T["asia"][i].get("r") is not None]
for nm,f_ in (("all",lambda y:True),("2005-2017",lambda y:y<=2017),
              ("2018-2026",lambda y:y>=2018),("2023-2026",lambda y:y>=2023)):
    ts=[t for t in sub if f_(t["y"])]
    if len(ts)<30: continue
    r_=np.array([t["r"] for t in ts]); eq=pk=dd=0
    for t in sorted(ts,key=lambda z:z["day"]): eq+=t["r"]; pk=max(pk,eq); dd=max(dd,pk-eq)
    print(f"  {nm:<16} {len(ts):5d} {100*(r_>0).mean():6.1f}% {pf(ts):7.2f} {av(ts):+8.3f} "
          f"{av(ts,.10):+10.3f} {av(ts,.25):+10.3f} ${np.mean([t['risk'] for t in ts]):8.2f} {dd:7.1f}")
print("\n  layered with the confidence score:")
for c in (0.0,0.10,0.15,0.20):
    ts=[t for t in sub if t["conf"]>=c]
    if len(ts)<40: continue
    r_=np.array([t["r"] for t in ts])
    print(f"    conf >= {c:.2f}   n {len(ts):5d}  win {100*(r_>0).mean():5.1f}%  PF {pf(ts):5.2f}  "
          f"avgR {av(ts):+.3f}  net$0.25 {av(ts,.25):+.3f}")
