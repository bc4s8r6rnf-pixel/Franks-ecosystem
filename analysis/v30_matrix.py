"""v30: entry x stop x target matrix, for the dropdown labels."""
import numpy as np, pickle, math, csv
exec(open("v28_anchors.py").read().split('def rep(')[0])
TV=load_tv("/root/.claude/uploads/986dcf13-ec74-53a1-b424-6a3e3047f197/830a2bc9-FX_XAUUSD_15_8a5ec.csv")
MT5,_=pickle.load(open("bs.pkl","rb"))
# VWAP straight from the chart export
VW={}
for r in csv.DictReader(open("/root/.claude/uploads/986dcf13-ec74-53a1-b424-6a3e3047f197/830a2bc9-FX_XAUUSD_15_8a5ec.csv")):
    try: t=int(float(r["time"]))
    except: continue
    v=(r.get("VWAP") or "").strip()
    if v: VW[t]=float(v)
def lv(A,T,f): return A+(1-f)/1.27*(T-A)
def run(B,R_,entry,stop,tgtmul,pad=0.0,useVW=False):
    out=[]
    for r in R_:
        s=r["s"]
        if r["i0"] is None: continue
        px=B[r["i0"]].o
        side=1 if (s.up-px)<(px-s.dn) else -1
        T=(s.bh+tgtmul*s.R) if side>0 else (s.bl-tgtmul*s.R)
        A=r["pvL"] if side>0 else r["pvH"]
        if A is None: continue
        z=(s.up if side>0 else s.dn)   # the 2.0 edge the fib is built to
        span=z-A
        if (side>0 and span<=0) or (side<0 and span>=0): continue
        # ---- entry -----------------------------------------------------
        if entry=="box":   ent = s.bl if side>0 else s.bh
        elif entry=="vwap":
            ent=None
        else:              ent = lv(A,z,float(entry))
        # ---- stop ------------------------------------------------------
        if stop=="box":    stp = (s.bl - pad) if side>0 else (s.bh + pad)
        elif stop=="vwap": stp = None
        else:              stp = lv(A,z,float(stop))
        idx=range(r["i0"], s.hi+1)
        fill=None
        for m in idx:
            e = ent
            if useVW or entry=="vwap":
                e = VW.get(B[m].t)
                if e is None: continue
            if e is None: continue
            if B[m].l<=e<=B[m].h:
                fill=m; ent=e; break
            if entry not in ("vwap",) and ((side>0 and e>=px) or (side<0 and e<=px)): break
        if fill is None: continue
        if stop=="vwap":
            v=VW.get(B[fill].t)
            if v is None: continue
            stp = v - side*pad
        risk=abs(ent-stp)
        if risk<=0 or (side>0 and T<=ent) or (side<0 and T>=ent): continue
        rr=abs(T-ent)/risk
        end=min(len(B)-1,fill+MAX); res=None
        for m in range(fill,end+1):
            b=B[m]
            if (b.l<=stp) if side>0 else (b.h>=stp): res=-1.0; break
            if (b.h>=T) if side>0 else (b.l<=T): res=rr; break
        if res is None: res=side*(B[end].c-ent)/risk
        out.append(dict(r=res,rr=rr,risk=risk,day=s.day.date()))
    return out
def line(nm,ts,w=34):
    if len(ts)<5: print(f"  {nm:<{w}} n {len(ts)}"); return
    r=np.array([t["r"] for t in ts]); gp=r[r>0].sum(); gl=-r[r<0].sum()
    rr=np.mean([t["rr"] for t in ts]); need=1/(1+rr)
    z=((r>0).mean()-need)/math.sqrt(need*(1-need)/len(r))
    print(f"  {nm:<{w}} {len(r):4d} {100*(r>0).mean():6.1f}% PF {(gp/gl if gl else 99):5.2f} "
          f"RR {rr:5.2f} z {z:+5.2f} avgR {r.mean():+.3f} totR {r.sum():+8.1f}")
H=f"  {'variant':<34} {'n':>4} {'win%':>7} {'PF':>8} {'RR':>8} {'z':>7} {'avgR':>9} {'totR':>9}"
for tag,B in (("MT5 2004-2026",MT5),("OANDA window 2026",TV)):
    R_=build(B)
    print("="*104); print(f"  {tag}  -  anchor P, stop 0.95, target 2.0"); print("="*104); print(H)
    for e,nm in (("0.62","entry fib 0.62"),("0.70","entry fib 0.70"),("0.79","entry fib 0.79"),
                 ("box","entry origin-box edge")):
        line(f"  {nm}", run(B,R_,e,"0.95",2.0))
    print(f"\n  target 2.5 instead:")
    for e,nm in (("0.62","entry fib 0.62"),("0.70","entry fib 0.70"),("0.79","entry fib 0.79"),
                 ("box","entry origin-box edge")):
        line(f"  {nm}", run(B,R_,e,"0.95",2.5))
    print(f"\n  stop variants, entry fib 0.79, target 2.0:")
    for st,pd,nm in (("0.88",0,"stop fib 0.88"),("0.95",0,"stop fib 0.95"),("1.0",0,"stop the 1 anchor"),
                     ("box",0.5,"stop box edge + $0.50"),("box",1.0,"stop box edge + $1.00")):
        line(f"  {nm}", run(B,R_,"0.79",st,2.0,pad=pd))
    print()
print("="*104); print("  VWAP variants - only the chart export carries a VWAP column"); print("="*104)
R_=build(TV); print(H)
line("  entry VWAP tap, stop 0.95", run(TV,R_,"vwap","0.95",2.0))
for pd in (2.0,5.0,8.0):
    line(f"  entry VWAP, stop VWAP -${pd:.0f}", run(TV,R_,"vwap","vwap",2.0,pad=pd))
