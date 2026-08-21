"""
v25: two OTE zones, no direction call at all.

At the activation time both fibs are drawn from the 9pm box projections:

  LONG   1 at the lower 2.0 edge L = boxLow-2R, -0.27 at the upper U = boxHigh+2R
  SHORT  1 at the upper 2.0 edge U,             -0.27 at the lower L

  span = U - L = 5R, so the levels land at fixed places:

    long  0.62 = boxLow  - 0.504 R      long  0.79 = boxLow  - 1.173 R
    short 0.62 = boxHigh + 0.504 R      short 0.79 = boxHigh + 1.173 R

Price taps one zone, that side fires, the other is deleted. Stop on the 1
(the 2.0 edge behind), target the -0.27 (the opposing 2.0 edge). 2.34:1.
"""
import pickle, numpy as np, collections, dirlab
B,S=pickle.load(open("bs.pkl","rb"))
E62=(1-0.62)/1.27      # 0.29921
E79=(1-0.79)/1.27      # 0.16535

def sim(since=2024, until=2027, h0=0.0, h1=24.0, deep=0.62, be=None, cost=0.0,
        already="skip", hold=2*96, eol=False):
    """
    h0/h1   hours from lane open (midnight NY) the zones are armed
    deep    which fib inside the zone is the working limit order
    be      move the stop to entry once this many DOLLARS are in favour
    already what to do if price is beyond the trigger when the zones arm
    eol     True = close at the end of the lane instead of holding
    """
    out=[]
    for s in S:
        if not (since <= s.day.year < until): continue
        R=s.R; U=s.bh+2*R; L=s.bl-2*R; span=U-L
        e=E62 if deep==0.62 else E79
        longEnt  = L + e*span
        shortEnt = U - e*span
        idx=[i for i in range(s.lo,s.hi+1)
             if h0 <= (B[i].t - s.day.timestamp())/3600.0 < h1]
        if not idx: out.append(dict(r=None,why="no window")); continue
        px0=B[idx[0]].o
        if px0 <= longEnt or px0 >= shortEnt:
            if already=="skip": out.append(dict(r=None,why="already in a zone")); continue
        side=0; fill=None; ent=np.nan
        for m in idx:
            hitL = B[m].l <= longEnt
            hitS = B[m].h >= shortEnt
            if hitL and hitS:                       # one bar tags both - unresolvable
                out.append(dict(r=None,why="both tagged in one bar")); side=-99; break
            if hitL: side, ent, fill = 1, longEnt, m; break
            if hitS: side, ent, fill = -1, shortEnt, m; break
        if side==-99: continue
        if fill is None: out.append(dict(r=None,why="neither zone tapped")); continue
        stop = L if side>0 else U
        tgt  = U if side>0 else L
        risk = abs(ent-stop)
        if risk<=0: out.append(dict(r=None,why="no risk")); continue
        rr = abs(tgt-ent)/risk
        end = s.hi if eol else min(len(B)-1, fill+hold)
        r=None; live=stop; moved=False; mfe=0.0
        for k in range(fill, end+1):
            b=B[k]
            if (b.l<=live) if side>0 else (b.h>=live):
                r = 0.0 if moved else -1.0; break
            if (b.h>=tgt) if side>0 else (b.l<=tgt): r=rr; break
            fav = (b.h-ent) if side>0 else (ent-b.l)
            mfe = max(mfe, fav)
            if be is not None and not moved and fav >= be:
                live = ent; moved = True
        if r is None: r = side*(B[end].c-ent)/risk
        out.append(dict(r=r-(cost/risk if cost else 0.0), rr=rr, risk=risk, side=side,
                        day=s.day.date(), y=s.day.year, why="filled", mfe=mfe/risk,
                        moved=moved))
    return out

def stat(res):
    ts=[t for t in res if t.get("r") is not None]
    if not ts: return None
    r=np.array([t["r"] for t in ts]); gp=r[r>0].sum(); gl=-r[r<0].sum()
    eq=pk=dd=0
    for t in sorted(ts,key=lambda z:z["day"]): eq+=t["r"]; pk=max(pk,eq); dd=max(dd,pk-eq)
    return dict(n=len(r), W=int((r>0).sum()), L=int((r<0).sum()), B=int((r==0).sum()),
                win=100*(r>0).mean(), pf=(gp/gl if gl else 99.0),
                rr=float(np.mean([t["rr"] for t in ts])),
                risk=float(np.mean([t["risk"] for t in ts])),
                avg=float(r.mean()), tot=float(r.sum()), dd=dd)
def rep(nm,res,w=34):
    st=stat(res)
    if st is None: print(f"  {nm:<{w}} no trades"); return
    print(f"  {nm:<{w}} {st['n']:4d} {st['W']:4d}W {st['L']:4d}L {st['B']:3d}BE "
          f"{st['win']:6.1f}% PF {st['pf']:5.2f} RR {st['rr']:5.2f} risk ${st['risk']:6.2f} "
          f"avgR {st['avg']:+.3f} totR {st['tot']:+7.1f} DD {st['dd']:5.1f}")
HDR=(f"  {'variant':<34} {'n':>4} {'W':>5} {'L':>5} {'BE':>5} {'win%':>7} {'PF':>8} "
     f"{'RR':>8} {'risk':>11} {'avgR':>9} {'totR':>10} {'DD':>8}")

print("="*136)
print("A. THE RULE AS SPECIFIED  -  zones armed at midnight, 2024 to 2026-01-30")
print("="*136)
print(HDR)
rep("  0.62 trigger, hold to target", sim())
rep("  0.79 trigger (deeper)",        sim(deep=0.79))
rep("  0.62, flat at end of lane",    sim(eol=True))
print()
c=collections.Counter(t["why"] for t in sim())
print("  what happens on the days with no trade:")
for k,v in c.most_common(): print(f"    {k:<26} {v}")

print("\n"+"="*136)
print("B. WHEN ARE THE ZONES ARMED?  (hours from midnight NY)")
print("="*136)
print(HDR)
for h0,h1,nm in ((0,24,"00:00 - 24:00  all day"),(0,12,"00:00 - 12:00"),
                 (0,8,"00:00 - 08:00  pre-NY only"),(2,12,"02:00 - 12:00"),
                 (3,11,"03:00 - 11:00"),(7,16,"07:00 - 16:00  NY session"),
                 (8,12,"08:00 - 12:00  NY morning"),(8,16,"08:00 - 16:00"),
                 (4,12,"04:00 - 12:00"),(0,4,"00:00 - 04:00"),
                 (6,10,"06:00 - 10:00"),(9,13,"09:00 - 13:00"),(12,20,"12:00 - 20:00")):
    rep(f"  {nm}", sim(h0=h0,h1=h1))

print("\n"+"="*136)
print("C. BREAK-EVEN FILTER  -  move the stop to entry once this much is in favour")
print("="*136)
print(HDR)
rep("  no break-even", sim())
for d in (5,10,15,20,25,30,40,50):
    rep(f"  BE after ${d} ({d*10} pips)", sim(be=float(d)))

print("\n"+"="*136)
print("D. WITH COSTS, AND THE SAME RULE ON THE FULL HISTORY")
print("="*136)
print(HDR)
rep("  2024-2026  gross", sim())
rep("  2024-2026  net $0.25", sim(cost=0.25))
rep("  2024-2026  net $0.50", sim(cost=0.50))
for a,b in ((2004,2027),(2004,2014),(2014,2020),(2020,2024),(2024,2027)):
    rep(f"  {a}-{min(b,2026)} gross", sim(since=a,until=b))
print()
for y in range(2024,2027):
    rep(f"  {y}", sim(since=y,until=y+1))
