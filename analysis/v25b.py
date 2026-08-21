import pickle, numpy as np, collections, dirlab
exec(open("v25_dualote.py").read().split('print("="*136)')[0])

print("="*136)
print("E. WHY IT LOSES  -  which side does the tap put you on?")
print("="*136)
agree=opp=0; A=[]; O=[]
for s in S:
    if s.day.year<2024: continue
    R=s.R; U=s.bh+2*R; L=s.bl-2*R; span=U-L
    lE=L+E62*span; sE=U-E62*span
    idx=[i for i in range(s.lo,s.hi+1)]
    if not idx: continue
    px0=B[idx[0]].o
    if px0<=lE or px0>=sE: continue
    side=0; fill=None
    for m in idx:
        if B[m].l<=lE and B[m].h>=sE: side=-99; break
        if B[m].l<=lE: side,fill=1,m; break
        if B[m].h>=sE: side,fill=-1,m; break
    if side in (0,-99) or fill is None: continue
    # what the 04:00 direction engine said that day
    ii=dirlab.win(B,s,4,4.25)
    if not ii: continue
    px=B[ii[0]].o; call=1 if (U-px)<(px-L) else -1
    (A if call==side else O).append(s.day.date())
print(f"  dual-OTE trades that AGREE with the 04:00 direction call : {len(A):4d} "
      f"({100*len(A)/(len(A)+len(O)):.1f}%)")
print(f"  dual-OTE trades that OPPOSE it                          : {len(O):4d} "
      f"({100*len(O)/(len(A)+len(O)):.1f}%)")
print("\n  Tapping the LOWER zone means price has fallen half a box-range below the box.")
print("  At that moment the lower zone is the nearer one, so your own direction engine")
print("  calls SELL - and this rule makes you BUY. It is a systematic inversion of the")
print("  one component in this project that has a measured 71.5% edge.")

def sim2(since=2024, until=2027, h0=0.0, h1=24.0, mode="revert", tgt="far",
         stopmode="anchor", cost=0.0, hold=2*96):
    out=[]
    for s in S:
        if not (since <= s.day.year < until): continue
        R=s.R; U=s.bh+2*R; L=s.bl-2*R; span=U-L
        lE=L+E62*span; sE=U-E62*span
        idx=[i for i in range(s.lo,s.hi+1)
             if h0 <= (B[i].t-s.day.timestamp())/3600.0 < h1]
        if not idx: continue
        px0=B[idx[0]].o
        if px0<=lE or px0>=sE: continue
        tap=0; fill=None; ent=np.nan
        for m in idx:
            if B[m].l<=lE and B[m].h>=sE: tap=-99; break
            if B[m].l<=lE: tap,ent,fill=-1,lE,m; break     # tapped the LOWER zone
            if B[m].h>=sE: tap,ent,fill= 1,sE,m; break     # tapped the UPPER zone
        if tap in (0,-99) or fill is None: continue
        side = -tap if mode=="revert" else tap     # revert: tap low -> buy
        if mode=="revert":
            side = 1 if tap<0 else -1
        else:
            side = -1 if tap<0 else 1              # break: tap low -> sell
        if side>0:
            target = U if tgt=="far" else (s.bh if tgt=="box" else ent+abs(ent-(L if stopmode=="anchor" else s.bl)))
            stop   = L if stopmode=="anchor" else s.bl
        else:
            target = L if tgt=="far" else (s.bl if tgt=="box" else ent-abs(ent-(U if stopmode=="anchor" else s.bh)))
            stop   = U if stopmode=="anchor" else s.bh
        risk=abs(ent-stop)
        if risk<=0 or (side>0 and target<=ent) or (side<0 and target>=ent): continue
        rr=abs(target-ent)/risk
        end=min(len(B)-1,fill+hold); r=None
        for k in range(fill,end+1):
            b=B[k]
            if (b.l<=stop) if side>0 else (b.h>=stop): r=-1.0; break
            if (b.h>=target) if side>0 else (b.l<=target): r=rr; break
        if r is None: r=side*(B[end].c-ent)/risk
        out.append(dict(r=r-(cost/risk if cost else 0),rr=rr,risk=risk,day=s.day.date(),
                        y=s.day.year,why="filled"))
    return out

print("\n"+"="*136)
print("F. THE INVERSION  -  treat the tap as a BREAKOUT instead of a discount")
print("="*136)
print(HDR)
rep("  revert: tap low -> BUY far edge",  sim2(mode="revert"))
rep("  break:  tap low -> SELL near edge", sim2(mode="break", tgt="far", stopmode="box"))
rep("  break:  stop on the 2.0 anchor",    sim2(mode="break", tgt="far", stopmode="anchor"))
rep("  revert: target the box edge",       sim2(mode="revert", tgt="box"))
rep("  break:  target the box edge",       sim2(mode="break", tgt="box", stopmode="box"))
print("\n  the breakout version on the full history:")
for a,b in ((2004,2014),(2014,2020),(2020,2024),(2024,2027),(2004,2027)):
    rep(f"  break {a}-{min(b,2026)}", sim2(mode="break",tgt="far",stopmode="box",since=a,until=b))
print()
rep("  break 2024-26 net $0.25", sim2(mode="break",tgt="far",stopmode="box",cost=0.25))

print("\n"+"="*136)
print("G. BEST TIME WINDOW FOR THE BREAKOUT VERSION")
print("="*136)
print(HDR)
for h0,h1,nm in ((0,24,"00:00-24:00"),(0,12,"00:00-12:00"),(2,12,"02:00-12:00"),
                 (7,16,"07:00-16:00 NY"),(8,12,"08:00-12:00"),(9,13,"09:00-13:00"),
                 (12,20,"12:00-20:00"),(0,8,"00:00-08:00")):
    rep(f"  {nm}", sim2(mode="break",tgt="far",stopmode="box",h0=h0,h1=h1))
