import math
from mt5_load import load_mt5
import v3_intraday as V3
from v3_intraday import pct
import v20_zone2zone as V20
PATH="/root/.claude/uploads/986dcf13-ec74-53a1-b424-6a3e3047f197/d7136efe-XAU_15m_data.csv"
bars=load_mt5(PATH,since=2015); S=V3.sessions(bars)
HDR=(f"  {'variant':<30} {'n':>5} {'W':>6} {'L':>6} {'win%':>7} "
     f"{'PF':>8} {'RR':>8} {'risk':>12} {'avgR':>6} {'totR':>9} {'DD':>7}")

print("="*108)
print("9. WHAT THE ZONE-TO-ZONE FIB ACTUALLY IS")
print("="*108)
for s in S[:4]:
    R=s.rng; up=s.rhigh+2*R; dn=s.rlow-2*R
    ent=dn+V20.ENT*(up-dn)
    print(f"  {s.day.date()}  box {s.rlow:.2f}-{s.rhigh:.2f}  R ${R:.2f}"
          f"   0.62 entry {ent:.2f}   = boxLow - {(s.rlow-ent)/R:.3f} R")

print("\n  algebra:  A = low-2R, B = high+2R, span = 5R")
print("            entry = A + 0.2992 x 5R = low - 0.504 R")
print("            risk  = 1.496 R    reward = 3.504 R    -> 2.34:1")
print("  The fib is not adaptive. It is always half a 9pm-box-range beyond the box.")

print()
print("="*108)
print("10. SWEEPING THAT ENTRY DEPTH DIRECTLY  (stop stays on the 2.0 edge)")
print("="*108)
print(HDR)
def depth(bars,S,d,h0=4,h1=24,tgt=2.0):
    out=[]
    for s in S:
        R=s.rng; up=s.rhigh+2.0*R; dn=s.rlow-2.0*R
        ci=s.call; px=bars[ci].o
        side=1 if (up-px)<(px-dn) else -1
        B=(s.rhigh+tgt*R) if side>0 else (s.rlow-tgt*R)
        A=dn if side>0 else up
        ent=(s.rlow-d*R) if side>0 else (s.rhigh+d*R)
        risk=abs(ent-A)
        if risk<=0 or (side>0 and B<=ent) or (side<0 and B>=ent):
            out.append(dict(r=None)); continue
        rr=abs(B-ent)/risk
        idx=[i for i in range(max(s.lo,ci),s.hi+1) if h0<=bars[i].ny.hour<h1]
        fill=next((m for m in idx if bars[m].l<=ent<=bars[m].h),None)
        if fill is None: out.append(dict(r=None)); continue
        end=min(len(bars)-1,fill+V20.MAXHOLD); r=None
        for k in range(fill,end+1):
            b=bars[k]
            if (b.l<=A) if side>0 else (b.h>=A): r=-1.0; break
            if (b.h>=B) if side>0 else (b.l<=B): r=rr; break
        if r is None: r=side*(bars[end].c-ent)/risk
        out.append(dict(r=r,rr=rr,risk=risk,why="filled",day=s.day.date(),side=side))
    return out
for d in (0.0,0.25,0.504,0.75,1.0,1.25,1.5):
    V20.rep(f"  entry boxEdge -{d:.3f}R", depth(bars,S,d))

print()
print("="*108)
print("11. SPLIT SAMPLE on the best cell (zone 04-24) - fit half vs unseen half")
print("="*108)
print(HDR)
res=[t for t in V20.run(bars,S,anchor="zone",h0=4,h1=24) if t["r"] is not None]
res.sort(key=lambda t:t["day"]); mid=len(res)//2
V20.rep("  first half",res[:mid]); V20.rep("  second half",res[mid:])
print(f"  split at {res[mid]['day']}")
for y in range(2015,2027):
    sub=[t for t in res if t["day"].year==y]
    if sub: V20.rep(f"  {y}",sub)

print()
print("="*108)
print("12. 'far' ANCHOR (deepest of zone/asia/prev) - year by year")
print("="*108)
print(HDR)
f=[t for t in V20.run(bars,S,anchor="far") if t["r"] is not None]
n=len(f); w=sum(1 for t in f if t["r"]>0); p=1/3.34
z=(w/n-p)/math.sqrt(p*(1-p)/n)
V20.rep("  all",f); print(f"  edge {(w/n-p)*100:+.2f}pp  z {z:+.2f}  "
      f"{'significant' if abs(z)>1.96 else 'INSIDE NOISE'}")
for y in range(2015,2027):
    sub=[t for t in f if t["day"].year==y]
    if sub: V20.rep(f"  {y}",sub)

print()
print("="*108)
print("13. HOLDING THE 0.504R ENTRY BUT MOVING THE TARGET (stop stays on the 2.0 edge)")
print("="*108)
print(HDR)
for tgt in (0.5,1.0,1.5,2.0,2.5,3.0):
    V20.rep(f"  target {tgt:.1f} projection", depth(bars,S,0.504,tgt=tgt))

print()
print("="*108)
print("14. THE SAME, 2023 ONWARD ONLY  -  does any cell survive the modern market?")
print("="*108)
print(HDR)
for d in (0.0,0.25,0.504,0.75,1.0,1.25):
    sub=[t for t in depth(bars,S,d) if t["r"] is not None and t["day"].year>=2023]
    V20.rep(f"  entry -{d:.3f}R  gross",sub)
    net=[dict(t,r=t["r"]-0.25/t["risk"]) for t in sub]
    V20.rep(f"  entry -{d:.3f}R  net $0.25",net)
