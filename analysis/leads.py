import pickle, numpy as np, dirlab
X,y,yr,NAMES,base,days = pickle.load(open("mat2.pkl","rb"))
CALL = pickle.load(open("call2.pkl","rb"))
pz = X[:,NAMES.index("pos_zone")]; conf = np.abs(pz-0.5)
print("="*104)
print("F. CONFIDENCE  -  accuracy as a function of how lopsided the 04:00 call is")
print("="*104)
print(f"  {'|pos-0.5| bucket':<22} {'n':>5} {'kept%':>7} {'ALL':>8} {'2005-17':>9} {'2018-26':>9} {'2023-26':>9}")
edges=[0,.05,.10,.15,.20,.25,.35,1]
for a,b in zip(edges,edges[1:]):
    m=(conf>=a)&(conf<b)
    f=lambda k: 100*(base[m&k]==y[m&k]).mean() if (m&k).sum()>15 else float('nan')
    print(f"  {a:.2f} - {b:.2f}{'':<12} {m.sum():5d} {100*m.mean():6.1f}% {f(yr>0):7.2f}% "
          f"{f(yr<=2017):8.2f}% {f(yr>=2018):8.2f}% {f(yr>=2023):8.2f}%")
print("\n  cumulative: trade only when the call is at least this lopsided")
print(f"  {'min |pos-0.5|':<22} {'n':>5} {'kept%':>7} {'ALL':>8} {'2005-17':>9} {'2018-26':>9} {'2023-26':>9}")
for a in (0,.05,.075,.10,.125,.15,.20,.25,.30):
    m=conf>=a
    f=lambda k: 100*(base[m&k]==y[m&k]).mean() if (m&k).sum()>15 else float('nan')
    print(f"  >= {a:.3f}{'':<13} {m.sum():5d} {100*m.mean():6.1f}% {f(yr>0):7.2f}% "
          f"{f(yr<=2017):8.2f}% {f(yr>=2018):8.2f}% {f(yr>=2023):8.2f}%")

print("\n"+"="*104)
print("G. THE 00:00 + 03:00 + 04:00 AGREEMENT RULE, YEAR BY YEAR")
print("="*104)
ds=set(CALL[0])&set(CALL[3])&set(CALL[4])
rows=[(d,CALL[4][d][0],CALL[4][d][1],CALL[4][d][2],
       len({CALL[h][d][0] for h in (0,3,4)})==1) for d in sorted(ds)]
print(f"  {'yr':>5} {'all n':>6} {'all acc':>9} {'agree n':>8} {'agree acc':>10} {'disagree acc':>13}")
for Y in sorted({r[3] for r in rows}):
    A=[r for r in rows if r[3]==Y]; G=[r for r in A if r[4]]; Dg=[r for r in A if not r[4]]
    f=lambda R: 100*np.mean([p==t for _,p,t,_,_ in R]) if R else float('nan')
    print(f"  {Y:5d} {len(A):6d} {f(A):8.2f}% {len(G):8d} {f(G):9.2f}% {f(Dg):12.2f}%")
G=[r for r in rows if r[4]]
print(f"\n  overall: agree n={len(G)} ({100*len(G)/len(rows):.1f}% of days) "
      f"acc {100*np.mean([p==t for _,p,t,_,_ in G]):.2f}%   "
      f"vs 04:00 alone {100*np.mean([p==t for _,p,t,_,_ in rows]):.2f}%")

print("\n"+"="*104)
print("H. OTHER DIRECTION THEORIES, tested head-to-head against the 04:00 call")
print("="*104)
B,S = pickle.load(open("bs.pkl","rb"))
L=[s for s in S if s.lab is not None]
for s in L:
    s.f=None
    for i in range(s.lo,s.hi+1):
        if B[i].h>=s.up or B[i].l<=s.dn: s.f=B[i].t; break
def evaluate(fn, nm):
    rec=[]
    for s in L:
        ii=dirlab.win(B,s,4,4.25)
        if not ii or (s.f is not None and s.f<=B[ii[0]].t): continue
        p=fn(s,B,ii[0])
        if p is None: continue
        rec.append((p,s.lab,s.y))
    if not rec: print(f"  {nm:<40} no signal"); return
    p=np.array([r[0] for r in rec]); t=np.array([r[1] for r in rec]); yy=np.array([r[2] for r in rec])
    f=lambda m: 100*(p[m]==t[m]).mean() if m.sum()>20 else float('nan')
    print(f"  {nm:<40} {len(p):5d} {100*len(p)/2487:6.1f}% {f(yy>0):7.2f}% "
          f"{f(yy<=2017):8.2f}% {f(yy>=2018):8.2f}% {f(yy>=2023):8.2f}%")
print(f"  {'theory':<40} {'n':>5} {'cover':>6} {'ALL':>8} {'2005-17':>9} {'2018-26':>9} {'2023-26':>9}")
evaluate(lambda s,B,i: 1 if (s.up-B[i].o)<(B[i].o-s.dn) else 0, "the 04:00 call (baseline)")
evaluate(lambda s,B,i: 1 if B[i].o>s.bh else (0 if B[i].o<s.bl else None), "box breakout side (skip if inside)")
evaluate(lambda s,B,i: 1 if s.bc>s.bo else 0, "9pm candle body direction")
evaluate(lambda s,B,i: 0 if s.bc>s.bo else 1, "9pm candle body, inverted")
def asiasweep(s,B,i):
    q=dirlab.ohlc(B,dirlab.win(B,s,-5,0))
    if not q: return None
    for j in dirlab.win(B,s,0,4):
        if B[j].h>=q[1]: return 0            # swept highs -> reversal down
        if B[j].l<=q[2]: return 1
    return None
evaluate(asiasweep, "Asia sweep -> reverse (ICT style)")
evaluate(lambda s,B,i: (1-asiasweep(s,B,i)) if asiasweep(s,B,i) is not None else None,
         "Asia sweep -> continue")
evaluate(lambda s,B,i: 1 if s.lab is not None and B[i].o>B[s.lo].o else 0, "up since midnight")
def unmit(s,B,i):
    px=B[i].o; k=L.index(s) if False else None
    return None
def prevcont(s,B,i,PREV={}):
    return None
def since18(s,B,i):
    w=dirlab.win(B,s,-6,-5.5)
    return None if not w else (1 if B[i].o > B[w[0]].o else 0)
evaluate(since18, "up since the 18:00 open")
evaluate(lambda s,B,i: 1 if B[i].o > s.bc else 0, "above / below the 9pm close")
def london(s,B,i):
    q=dirlab.ohlc(B,dirlab.win(B,s,2,4))
    return None if not q else (1 if q[3]>q[0] else 0)
evaluate(london, "London 02:00-04:00 direction")
def lanedir(s,B,i):
    q=dirlab.ohlc(B,dirlab.win(B,s,0,4))
    return None if not q else (1 if q[3]>q[0] else 0)
evaluate(lanedir, "00:00-04:00 direction")
PREV={}
for k,s in enumerate(L): PREV[s.day.date()]=(L[k-1].lab if k else None)
evaluate(lambda s,B,i: PREV.get(s.day.date()), "yesterday's zone repeats")
evaluate(lambda s,B,i: (None if PREV.get(s.day.date()) is None else 1-PREV[s.day.date()]),
         "yesterday's zone alternates")
def unmit(s,B,i):
    """head for the nearest projection edge left untouched in the last 10 days"""
    px=B[i].o; k=IDX[s.day.date()]; bu=bd=None
    for j in range(max(0,k-10),k):
        z=L[j]
        for lvl in (z.up,z.dn):
            if any(B[m].l<=lvl<=B[m].h for m in range(z.lo,min(len(B),s.lo))): continue
            if lvl>px: bu=lvl if bu is None else min(bu,lvl)
            else:      bd=lvl if bd is None else max(bd,lvl)
    if bu is None and bd is None: return None
    if bu is None: return 0
    if bd is None: return 1
    return 1 if (bu-px)<(px-bd) else 0
IDX={s.day.date():k for k,s in enumerate(L)}
evaluate(unmit, "nearest unmitigated prior zone edge")
def combo(s,B,i):
    px=B[i].o; pz=(px-s.dn)/(s.up-s.dn)
    return None if abs(pz-.5)<0.15 else (1 if pz>.5 else 0)
evaluate(combo, "04:00 call, only if |pos-0.5| >= 0.15")
def combo2(s,B,i):
    px=B[i].o; pz=(px-s.dn)/(s.up-s.dn)
    return None if abs(pz-.5)<0.25 else (1 if pz>.5 else 0)
evaluate(combo2, "04:00 call, only if |pos-0.5| >= 0.25")
