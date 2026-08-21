import pickle, numpy as np, bisect
exec(open("v27_htf.py").read().split('print("="*112)')[0])
MT5,_=pickle.load(open("bs.pkl","rb")); TV=pickle.load(open("tv.pkl","rb"))
CACHE={}
def prep(B,tag):
    if tag in CACHE: return CACHE[tag]
    S=sessions(B); T=trends(h4(B)); ends=[r["end"] for r in T]
    CACHE[tag]=[(s,(T[bisect.bisect_left(ends,s.day.timestamp())-1]
        if bisect.bisect_left(ends,s.day.timestamp())-1>=0 else None)) for s in S]
    return CACHE[tag]
def one(tag,B,mode="px_e50",since=None,until=None,cost=0.0,tp=None,maxhold=None):
    """ONE unit at a time. Enter at the lane open in the 4H direction, exit when the
       opposing box trades (or an optional target / time cap)."""
    S=prep(B,tag)
    if since: S=[(s,t) for s,t in S if s.y>=since]
    if until: S=[(s,t) for s,t in S if s.y<until]
    pos=None; out=[]
    for k,(s,tr) in enumerate(S):
        d=0 if tr is None else tr[mode]
        if pos is None and d!=0:
            pos=dict(side=d,px=B[s.lo].o,R=s.R,day=s.day,k=k)
        if pos is None: continue
        sd=pos["side"]
        for i in range(s.lo,s.hi+1):
            opp = s.dn if sd>0 else s.up
            tgt = s.up if sd>0 else s.dn
            if tp and ((B[i].h>=tgt) if sd>0 else (B[i].l<=tgt)):
                out.append(dict(r=sd*(tgt-pos["px"])/pos["R"],day=pos["day"],
                                y=pos["day"].year,hold=k-pos["k"],why="target"))
                pos=None; break
            if (B[i].l<=opp) if sd>0 else (B[i].h>=opp):
                out.append(dict(r=(sd*(opp-pos["px"])-cost)/pos["R"],day=pos["day"],
                                y=pos["day"].year,hold=k-pos["k"],why="opposing box"))
                pos=None; break
        if pos and maxhold and k-pos["k"]>=maxhold:
            out.append(dict(r=(sd*(B[s.hi].c-pos["px"])-cost)/pos["R"],day=pos["day"],
                            y=pos["day"].year,hold=k-pos["k"],why="time"))
            pos=None
    return out
def rep(nm,ts,w=26):
    if not ts: print(f"  {nm:<{w}} none"); return
    r=np.array([t["r"] for t in ts]); gp=r[r>0].sum(); gl=-r[r<0].sum()
    eq=np.cumsum(r); pk=np.maximum.accumulate(eq); dd=float((pk-eq).max())
    print(f"  {nm:<{w}} {len(r):5d} {int((r>0).sum()):5d}W {int((r<0).sum()):5d}L "
          f"{100*(r>0).mean():6.1f}% PF {(gp/gl if gl else 99):5.2f} "
          f"avgR {r.mean():+.3f} medR {np.median(r):+.3f} totR {r.sum():+8.1f} "
          f"maxDD {dd:6.1f}R hold {np.mean([t['hold'] for t in ts]):4.1f}d")
HDR=(f"  {'variant':<26} {'n':>5} {'W':>6} {'L':>6} {'win%':>7} {'PF':>8} {'avgR':>9} "
     f"{'medR':>9} {'totR':>10} {'maxDD':>10} {'hold':>7}")
print("="*140)
print("F. ONE UNIT AT A TIME  -  no stacking. Enter at the lane open in the 4H direction,")
print("   hold until an opposing box trades. This was the only positive cell in section E.")
print("="*140)
print(HDR)
for m in MODES:
    rep(f"  4H {m}", one("m",MT5,mode=m))
print("\n  best definition (px_e50) by era:")
for a,b,nm in ((2004,2010,"2004-2009"),(2010,2015,"2010-2014"),(2015,2020,"2015-2019"),
               (2020,2024,"2020-2023"),(2024,2027,"2024-2026")):
    rep(f"  {nm}", one("m",MT5,mode="px_e50",since=a,until=b))
rep("  FX May-Aug 2026", one("t",TV,mode="px_e50"))
print("\n  with a $0.25 round trip:")
rep("  2004-2026 net", one("m",MT5,mode="px_e50",cost=.25))
rep("  2024+ net", one("m",MT5,mode="px_e50",since=2024,cost=.25))
print("\n  taking profit at the trend-side box instead of holding:")
rep("  target the trend box", one("m",MT5,mode="px_e50",tp=True))
print("\n  capping the hold:")
for h in (1,2,3,5,10,None):
    rep(f"  max hold {h} days", one("m",MT5,mode="px_e50",maxhold=h))
print("\n  exit reasons (px_e50, no caps):")
import collections
c=collections.Counter(t["why"] for t in one("m",MT5,mode="px_e50"))
print("   ",dict(c))

print("\n"+"="*140)
print("G. IS IT JUST 'GOLD WENT UP'?  and how concentrated is the tail?")
print("="*140)
def one2(tag,B,mode="px_e50",since=None,until=None):
    S=prep(B,tag)
    if since: S=[(s,t) for s,t in S if s.y>=since]
    if until: S=[(s,t) for s,t in S if s.y<until]
    pos=None; out=[]
    for k,(s,tr) in enumerate(S):
        d=0 if tr is None else tr[mode]
        if pos is None and d!=0: pos=dict(side=d,px=B[s.lo].o,R=s.R,day=s.day,k=k)
        if pos is None: continue
        sd=pos["side"]
        for i in range(s.lo,s.hi+1):
            opp=s.dn if sd>0 else s.up
            if (B[i].l<=opp) if sd>0 else (B[i].h>=opp):
                out.append(dict(r=sd*(opp-pos["px"])/pos["R"],side=sd,day=pos["day"],
                                y=pos["day"].year)); pos=None; break
    return out
T=one2("m",MT5)
for nm,f in (("LONGS only",lambda t:t["side"]>0),("SHORTS only",lambda t:t["side"]<0)):
    ts=[t for t in T if f(t)]
    r=np.array([t["r"] for t in ts]); gp=r[r>0].sum(); gl=-r[r<0].sum()
    print(f"  {nm:<14} n {len(r):5d}  win {100*(r>0).mean():5.1f}%  PF {gp/gl:5.2f}  "
          f"avgR {r.mean():+.3f}  totR {r.sum():+8.1f}")
r=np.array([t["r"] for t in T]); o=np.argsort(r)[::-1]
print(f"\n  all trades: totR {r.sum():+.1f}")
print(f"  best 1 {r[o[0]]:+6.1f}R   best 10 {r[o[:10]].sum():+7.1f}R   "
      f"best 50 {r[o[:50]].sum():+7.1f}R   best 100 {r[o[:100]].sum():+7.1f}R")
print(f"  remove the best 10  -> totR {r.sum()-r[o[:10]].sum():+8.1f}")
print(f"  remove the best 50  -> totR {r.sum()-r[o[:50]].sum():+8.1f}")
print(f"  remove the best 100 -> totR {r.sum()-r[o[:100]].sum():+8.1f}   "
      f"({100*100/len(r):.1f}% of trades carry this much)")
print(f"\n  worst single trade {r.min():+.1f}R    5th percentile {np.percentile(r,5):+.1f}R")
print(f"  loss distribution: median loss {np.median(r[r<0]):+.2f}R  "
      f"worst 1% {np.percentile(r,1):+.1f}R")
print(f"  win  distribution: median win  {np.median(r[r>0]):+.2f}R  "
      f"best 1% {np.percentile(r,99):+.1f}R")
print("\n  by year:")
for y in sorted({t["y"] for t in T}):
    ts=[t for t in T if t["y"]==y]; rr=np.array([t["r"] for t in ts])
    gp=rr[rr>0].sum(); gl=-rr[rr<0].sum()
    print(f"    {y}  n {len(rr):4d}  win {100*(rr>0).mean():5.1f}%  "
          f"PF {(gp/gl if gl else 99):5.2f}  totR {rr.sum():+8.1f}")
