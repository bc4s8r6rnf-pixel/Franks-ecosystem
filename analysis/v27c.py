import pickle, numpy as np, bisect
exec(open("v27_htf.py").read().split('print("="*112)')[0])
MT5,_=pickle.load(open("bs.pkl","rb")); TV=pickle.load(open("tv.pkl","rb"))
CACHE={}
def prep(B,tag):
    if tag in CACHE: return CACHE[tag]
    S=sessions(B); T=trends(h4(B)); ends=[r["end"] for r in T]
    CACHE[tag]=[(s, T[bisect.bisect_left(ends,s.day.timestamp())-1]
                 if bisect.bisect_left(ends,s.day.timestamp())-1>=0 else None) for s in S]
    return CACHE[tag]
def stack(tag,B,mode="px_e50",since=None,cost=0.0,maxbook=None,heatstop=None):
    S=prep(B,tag)
    if since: S=[(s,t) for s,t in S if s.y>=since]
    book=[]; regime=0; closes=[]; trades=0; maxopen=0; heats=[]; blown=0
    for s,tr in S:
        d=0 if tr is None else tr[mode]
        if regime==0: regime=d
        if regime!=0 and (d==regime or d==0):
            if maxbook is None or len(book)<maxbook:
                book.append((regime,B[s.lo].o,s.R,s.day)); trades+=1
        maxopen=max(maxopen,len(book))
        for i in range(s.lo,s.hi+1):
            if not book: break
            opp=s.dn if regime>0 else s.up
            h=sum(sd*((B[i].l-p) if sd>0 else (p-B[i].h)) for sd,p,_,_ in book)
            unit=np.mean([r for _,_,r,_ in book])
            if heatstop is not None and h < -heatstop*unit*len(book):
                px=B[i].c
                closes.append(dict(pnl=sum(sd*(px-p)-cost for sd,p,_,_ in book),
                                   n=len(book), R=unit, px=px, day=s.day, forced=True))
                heats.append(h/unit); book=[]; regime=-regime; break
            if (B[i].l<=opp) if regime>0 else (B[i].h>=opp):
                closes.append(dict(pnl=sum(sd*(opp-p)-cost for sd,p,_,_ in book),
                                   n=len(book), R=unit, px=opp, day=s.day, forced=False))
                heats.append(h/unit); book=[]; regime=-regime; break
    return closes, trades, maxopen, heats
def summarise(nm, closes, trades, maxopen, heats, w=26):
    if not closes: print(f"  {nm:<{w}} nothing"); return
    pnl=np.array([c["pnl"] for c in closes])
    # normalise: P&L per unit expressed in that book's own R
    rr=np.array([c["pnl"]/(c["R"]*c["n"]) for c in closes])
    eq=np.cumsum(rr); pk=np.maximum.accumulate(eq); dd=float((pk-eq).max())
    top=np.sort(rr)[::-1]
    share=100*top[:3].sum()/max(1e-9, rr[rr>0].sum())
    print(f"  {nm:<{w}} closes {len(rr):4d} ({int((rr>0).sum()):3d}W/{int((rr<0).sum()):3d}L "
          f"{100*(rr>0).mean():5.1f}%)  totR {rr.sum():+8.1f}  R/close {rr.mean():+6.3f}  "
          f"maxDD {dd:6.1f}R  stack {maxopen:2d}  worst heat {min(heats) if heats else 0:+7.2f}R  "
          f"top3 = {share:5.1f}% of gains")
print("="*152)
print("C. THE SAME BOOK, MEASURED IN R INSTEAD OF DOLLARS  (each close divided by its own")
print("   average 9pm range x book size, so 2004 and 2026 are comparable)")
print("="*152)
for nm,tag,B_,since in (("MT5 2004-2026","m",MT5,None),("MT5 2014+","m",MT5,2014),
                        ("MT5 2020+","m",MT5,2020),("MT5 2024+","m",MT5,2024),
                        ("FX May-Aug 2026","t",TV,None)):
    print(f"\n  --- {nm} ---")
    for m in MODES:
        summarise(f"  4H {m}", *stack(tag,B_,mode=m,since=since))
print("\n"+"="*152)
print("D. HOW CONCENTRATED IS THE PROFIT?  (4H px_e50, full history)")
print("="*152)
cl,tr,mo,ht=stack("m",MT5,mode="px_e50")
rr=np.array([c["pnl"]/(c["R"]*c["n"]) for c in cl])
o=np.argsort(rr)[::-1]
print(f"  {len(rr)} book closes, total {rr.sum():+.1f} R")
print(f"  best 1  {rr[o[0]]:+7.1f} R   best 5 {rr[o[:5]].sum():+7.1f} R   "
      f"best 10 {rr[o[:10]].sum():+7.1f} R   best 25 {rr[o[:25]].sum():+7.1f} R")
print(f"  remove the best 10 closes -> total {rr.sum()-rr[o[:10]].sum():+.1f} R")
print(f"  remove the best 25 closes -> total {rr.sum()-rr[o[:25]].sum():+.1f} R")
print(f"  median close {np.median(rr):+.3f} R   mean {rr.mean():+.3f} R")
print(f"\n  the ten biggest wins:")
for i in o[:10]:
    print(f"    {cl[i]['day'].date()}  book of {cl[i]['n']:2d}  {rr[i]:+7.1f} R")
print("\n"+"="*152)
print("E. CAN CAPPING THE BOOK OR STOPPING THE HEAT FIX IT?  (4H px_e50)")
print("="*152)
for cap in (1,2,3,5,8,None):
    summarise(f"  max stack {cap}", *stack("m",MT5,mode="px_e50",maxbook=cap))
print()
for hs in (2,4,8,15,None):
    summarise(f"  heat stop {hs}R/unit", *stack("m",MT5,mode="px_e50",heatstop=hs))
