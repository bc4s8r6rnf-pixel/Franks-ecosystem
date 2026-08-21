import dirlab, pickle, numpy as np
B,S = pickle.load(open("bs.pkl","rb"))
L = [s for s in S if s.lab is not None]
# when did the winning zone first trade?
for s in L:
    s.f = None
    for i in range(s.lo, s.hi+1):
        if B[i].h >= s.up or B[i].l <= s.dn: s.f = B[i].t; break

def clock(h):
    t=(24+h)%24; return f"{int(t):02d}:{int(round((t%1)*60)):02d}"
HOURS=[-6,-3,0,1,2,3,3.5,4,4.5,5,5.5,6,6.5,7,7.5,8,8.5,9,9.5,10,11,12,13]

print("="*112)
print("A2. THE SAME SWEEP, BUT ONLY ON SESSIONS STILL UNDECIDED AT THAT CLOCK TIME")
print("="*112)
print(f"  {'NY time':>8} {'live':>5} {'still open':>11} {'ALL':>8} {'2005-17':>9} {'2018-26':>9} {'2023-26':>9}")
CALL={}
for h in HOURS:
    rec=[]
    for s in L:
        ii = dirlab.win(B, s, h, h+0.25)
        if not ii: continue
        dt = B[ii[0]].t
        if s.f is not None and s.f <= dt: continue        # already resolved -> not tradeable
        px = B[ii[0]].o
        rec.append((s.day.date(), 1 if (s.up-px)<(px-s.dn) else 0, s.lab, s.y))
    CALL[h]={d:(p,t,y) for d,p,t,y in rec}
    p=np.array([r[1] for r in rec]); t=np.array([r[2] for r in rec]); yy=np.array([r[3] for r in rec])
    f=lambda m: 100*(p[m]==t[m]).mean() if m.sum() else float('nan')
    print(f"  {clock(h):>8} {len(p):5d} {100*len(p)/len(L):10.1f}% {f(np.ones(len(p),bool)):7.2f}% "
          f"{f(yy<=2017):8.2f}% {f(yy>=2018):8.2f}% {f(yy>=2023):8.2f}%")

print("\n" + "="*112)
print("B2. AGREEMENT FILTER, joined on the session date (not positionally)")
print("="*112)
print(f"  {'clocks':<30} {'n kept':>7} {'kept%':>7} {'ALL':>8} {'2018-26':>9} {'2023-26':>9}")
def ag(hs):
    ds = set(CALL[hs[0]])
    for h in hs[1:]: ds &= set(CALL[h])
    keep=[d for d in ds if len({CALL[h][d][0] for h in hs})==1]
    base=[CALL[hs[-1]][d] for d in sorted(ds)]
    kept=[CALL[hs[-1]][d] for d in sorted(keep)]
    return base, kept
for hs,nm in (([-6,4],"18:00 + 04:00"),([0,4],"00:00 + 04:00"),([3,4],"03:00 + 04:00"),
              ([-3,4],"21:00 + 04:00"),([0,3,4],"00:00 + 03:00 + 04:00"),
              ([4,6],"04:00 + 06:00"),([4,8],"04:00 + 08:00"),([4,6,8],"04 + 06 + 08"),
              ([3,6,9],"03:00 + 06:00 + 09:00"),([6,8],"06:00 + 08:00")):
    base,kept = ag(hs)
    f=lambda R,m: 100*np.mean([p==t for p,t,y in R if m(y)]) if any(m(y) for _,_,y in R) else float('nan')
    print(f"  {nm:<30} {len(kept):7d} {100*len(kept)/max(1,len(base)):6.1f}% "
          f"{f(kept,lambda y:1):7.2f}% {f(kept,lambda y:y>=2018):8.2f}% {f(kept,lambda y:y>=2023):8.2f}%")
pickle.dump(CALL, open("call2.pkl","wb"))
