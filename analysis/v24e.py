import pickle, numpy as np
ROWS,T,CAND=pickle.load(open("v24cache.pkl","rb"))
def pf(ts,c=0.0):
    r=np.array([t["r"]-(c/t["risk"] if c else 0) for t in ts]); gp=r[r>0].sum(); gl=-r[r<0].sum()
    return gp/gl if gl else 99.
def av(ts,c=0.0): return float(np.mean([t["r"]-(c/t["risk"] if c else 0) for t in ts]))
print("="*112)
print("AG. WHY 'NEAREST' AND 'FURTHEST' IN AD WERE ALSO CONTAMINATED")
print("="*112)
fills={a:sum(1 for t in T[(a,0.62)] if t.get("r") is not None) for a in CAND}
print("  Those rankings only ever chose among anchors ALREADY KNOWN TO HAVE FILLED.")
print("  On a day where the far anchor never filled, 'furthest' silently fell through to")
print("  a nearer one that did - i.e. it was told the answer. Same defect as section W.")
print(f"  fill counts: " + "  ".join(f"{a} {v}" for a,v in fills.items()))
print("\n"+"="*112)
print("AH. STOP BUFFER BEYOND THE 1 ANCHOR  -  asia anchor, 0.62 entry")
print("="*112)
print(f"  {'buffer':<22} {'n':>5} {'win%':>7} {'RR':>7} {'PF':>7} {'avgR':>8} {'net.25':>9} {'risk':>8}")
import dirlab
B,S=pickle.load(open("bs.pkl","rb"))
FE=(1-0.62)/1.27; MAX=192
def runbuf(buf, anchor="asia", fib=0.62, sub=None):
    out=[]
    for i,r in enumerate(ROWS):
        if sub is not None and i not in sub: continue
        A=r["A"].get(anchor)
        if A is None: continue
        side=r["side"]; R=r["R"]
        Bt=r["A"]["zone"]; Bt = (r["px"] + 0)  # placeholder
        # rebuild target: opposing 2.0 edge
        z=r["A"]["zone"]
        Bt = z + (1 if side>0 else -1)*0  # zone is the anchor side; target is opposite
        Bt = r["px"] + side*r["dist"]*R
        span=Bt-A
        if (side>0 and span<=0) or (side<0 and span>=0): continue
        ent=A+((1-fib)/1.27)*span; stop=A-side*buf*R
        if (side>0 and ent>=r["px"]) or (side<0 and ent<=r["px"]): continue
        risk=abs(ent-stop)
        if risk<=0: continue
        rr=abs(Bt-ent)/risk
        s=r["day"]
        idx=[j for j,q in enumerate(S) if q.day.date()==s]
        if not idx: continue
        sess=S[idx[0]]
        i0=next((m for m in range(sess.lo,sess.hi+1) if B[m].ny.hour>=4), None)
        if i0 is None: continue
        fill=next((m for m in range(i0,sess.hi+1) if B[m].l<=ent<=B[m].h),None)
        if fill is None: continue
        end=min(len(B)-1,fill+MAX); res=None
        for m in range(fill,end+1):
            b=B[m]
            if (b.l<=stop) if side>0 else (b.h>=stop): res=-1.0; break
            if (b.h>=Bt) if side>0 else (b.l<=Bt): res=rr; break
        if res is None: res=side*(B[end].c-ent)/risk
        out.append(dict(r=res,rr=rr,risk=risk,day=s,y=r["y"],conf=r["conf"]))
    return out
for buf in (0.0,0.1,0.25,0.5):
    ts=runbuf(buf)
    if ts:
        rv=np.array([t["r"] for t in ts])
        print(f"  {buf:.2f} R beyond the 1{'':<6} {len(ts):5d} {100*(rv>0).mean():6.1f}% "
              f"{np.mean([t['rr'] for t in ts]):7.2f} {pf(ts):7.2f} {av(ts):+8.3f} "
              f"{av(ts,.25):+9.3f} ${np.mean([t['risk'] for t in ts]):7.2f}")
