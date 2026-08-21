"""v26: count the 'already in a zone' days, and sweep the activation time."""
import pickle, numpy as np, collections, dirlab
B,S=pickle.load(open("bs.pkl","rb"))
E62=(1-0.62)/1.27; E79=(1-0.79)/1.27

def sim(since=2024, until=2027, h0=0.0, h1=24.0, mode="revert", already="market",
        cost=0.0, hold=2*96):
    """already: skip | market (enter at the window open) | edge (wait for the 0.62 again)"""
    out=[]
    for s in S:
        if not (since <= s.day.year < until): continue
        R=s.R; U=s.bh+2*R; L=s.bl-2*R; span=U-L
        lo62=L+E62*span; lo79=L+E79*span      # long zone: lo79 (deep) .. lo62 (near)
        hi62=U-E62*span; hi79=U-E79*span      # short zone
        idx=[i for i in range(s.lo,s.hi+1)
             if h0 <= (B[i].t-s.day.timestamp())/3600.0 < h1]
        if not idx: continue
        px0=B[idx[0]].o
        tap=0; fill=None; ent=np.nan; how="tap"
        # --- was a zone already live when the window opened? ---------------
        inLong  = lo79 <= px0 <= lo62
        inShort = hi62 <= px0 <= hi79
        past    = px0 < lo79 or px0 > hi79
        if inLong or inShort or past:
            if already=="skip":
                out.append(dict(r=None,why="already in a zone")); continue
            if already=="market":
                tap = -1 if (inLong or px0<lo79) else 1
                ent, fill, how = px0, idx[0], "open inside"
            else:
                lvl = lo62 if (inLong or px0<lo79) else hi62
                tap = -1 if (inLong or px0<lo79) else 1
                f=next((m for m in idx if B[m].l<=lvl<=B[m].h),None)
                if f is None: out.append(dict(r=None,why="never came back")); continue
                ent, fill, how = lvl, f, "returned"
        else:
            for m in idx:
                if B[m].l<=lo62 and B[m].h>=hi62:
                    tap=-99; break
                if B[m].l<=lo62: tap,ent,fill=-1,lo62,m; break
                if B[m].h>=hi62: tap, ent,fill= 1,hi62,m; break
            if tap==-99: out.append(dict(r=None,why="both in one bar")); continue
            if fill is None: out.append(dict(r=None,why="neither tapped")); continue
        side = (1 if tap<0 else -1) if mode=="revert" else (-1 if tap<0 else 1)
        if mode=="revert":
            stop = L if side>0 else U
            tgt  = U if side>0 else L
        else:
            stop = s.bl if side>0 else s.bh
            tgt  = U if side>0 else L
        risk=abs(ent-stop)
        if risk<=0 or (side>0 and tgt<=ent) or (side<0 and tgt>=ent):
            out.append(dict(r=None,why="degenerate")); continue
        rr=abs(tgt-ent)/risk
        end=min(len(B)-1,fill+hold); r=None
        for k in range(fill,end+1):
            b=B[k]
            if (b.l<=stop) if side>0 else (b.h>=stop): r=-1.0; break
            if (b.h>=tgt) if side>0 else (b.l<=tgt): r=rr; break
        if r is None: r=side*(B[end].c-ent)/risk
        out.append(dict(r=r-(cost/risk if cost else 0),rr=rr,risk=risk,day=s.day.date(),
                        y=s.day.year,why="filled",how=how))
    return out
def rep(nm,res,w=36,sel=None):
    ts=[t for t in res if t.get("r") is not None and (sel is None or t.get("how")==sel)]
    if not ts: print(f"  {nm:<{w}} no trades"); return
    r=np.array([t["r"] for t in ts]); gp=r[r>0].sum(); gl=-r[r<0].sum()
    eq=pk=dd=0
    for t in sorted(ts,key=lambda z:z["day"]): eq+=t["r"]; pk=max(pk,eq); dd=max(dd,pk-eq)
    print(f"  {nm:<{w}} {len(r):4d} {int((r>0).sum()):4d}W {int((r<0).sum()):4d}L "
          f"{100*(r>0).mean():6.1f}% PF {(gp/gl if gl else 99):5.2f} RR "
          f"{np.mean([t['rr'] for t in ts]):5.2f} risk ${np.mean([t['risk'] for t in ts]):6.2f} "
          f"avgR {r.mean():+.3f} totR {r.sum():+7.1f} DD {dd:5.1f}")
HDR=(f"  {'variant':<36} {'n':>4} {'W':>5} {'L':>5} {'win%':>7} {'PF':>8} {'RR':>8} "
     f"{'risk':>11} {'avgR':>9} {'totR':>10} {'DD':>8}")

print("="*132)
print("A. THE 'ALREADY IN A ZONE' DAYS NOW COUNT  -  2024 to 2026-01-30")
print("="*132)
print(HDR)
for md in ("revert","break"):
    print(f"\n  --- {md} ---")
    rep("  skip them (what I ran before)", sim(mode=md, already="skip"))
    rep("  count them, enter at the open", sim(mode=md, already="market"))
    rep("  count them, wait for the 0.62", sim(mode=md, already="edge"))
    rep("     ...of which: opened inside", sim(mode=md, already="market"), sel="open inside")
    rep("     ...of which: normal taps",   sim(mode=md, already="market"), sel="tap")

print("\n"+"="*132)
print("B. ACTIVATION TIME  -  including the days that open inside a zone")
print("="*132)
for md in ("revert","break"):
    print(f"\n  --- {md} ---")
    print(HDR)
    for h0,nm in ((0,"00:00 midnight"),(2,"02:00"),(3,"03:00"),(4,"04:00"),(7,"07:00"),
                  (8,"08:00 NY open"),(9,"09:00"),(9.5,"09:30 NY equities open"),
                  (10,"10:00"),(13,"13:00")):
        rep(f"  armed {nm}", sim(mode=md, h0=h0, already="market"))

print("\n"+"="*132)
print("C. NY-OPEN VERSIONS ACROSS ERAS, AND NET OF COSTS")
print("="*132)
print(HDR)
for md in ("revert","break"):
    print(f"\n  --- {md}, armed 08:00 NY ---")
    for a,b,nm in ((2004,2014,"2004-2013"),(2014,2020,"2014-2019"),(2020,2024,"2020-2023"),
                   (2024,2027,"2024-2026"),(2004,2027,"all")):
        rep(f"  {nm} gross", sim(mode=md,h0=8,since=a,until=b,already="market"))
    rep("  2024-26 net $0.25", sim(mode=md,h0=8,since=2024,already="market",cost=.25))

print("\n"+"="*132)
print("D. WHAT MY 2026 SAMPLE ACTUALLY IS")
print("="*132)
d26=[s for s in S if s.day.year==2026]
print(f"  sessions in the file for 2026: {len(d26)}")
if d26: print(f"  first {d26[0].day.date()}   last {d26[-1].day.date()}")
print(f"  file's final bar: {B[-1].ny}")
print("  -> the year you backtested by hand is almost entirely absent from my data.")
