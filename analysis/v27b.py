import pickle, numpy as np, bisect
exec(open("v27_htf.py").read().split('print("="*112)')[0])
MT5,_=pickle.load(open("bs.pkl","rb"))
TV=pickle.load(open("tv.pkl","rb"))
CACHE={}
def prep(B, tag):
    if tag in CACHE: return CACHE[tag]
    S=sessions(B); T=trends(h4(B)); ends=[r["end"] for r in T]
    out=[]
    for s in S:
        j=bisect.bisect_left(ends, s.day.timestamp())-1
        out.append((s, T[j] if j>=0 else None))
    CACHE[tag]=out; return out
def stack(tag, B, mode="ema2050", entry="open", flip="box", since=None, cost=0.0,
          maxbook=None):
    S=prep(B,tag)
    if since: S=[(s,t) for s,t in S if s.y>=since]
    book=[]; realised=0.0; regime=0; trades=0; closes=0
    peak=dd=0.0; maxopen=0; maxheat=0.0; wins=losses=0; Rs=[]
    for s,tr in S:
        d = 0 if tr is None else tr[mode]
        if flip=="htf": regime=d
        elif regime==0: regime=d
        if regime!=0 and (flip=="htf" or d==regime or d==0):
            if maxbook is None or len(book)<maxbook:
                px=B[s.lo].o if entry=="open" else B[next((i for i in range(s.lo,s.hi+1)
                              if B[i].ny.hour>=4), s.lo)].o
                book.append((regime,px)); trades+=1; Rs.append(s.R)
        maxopen=max(maxopen,len(book))
        for i in range(s.lo,s.hi+1):
            if not book: break
            opp = s.dn if regime>0 else s.up
            hit = (B[i].l<=opp) if regime>0 else (B[i].h>=opp)
            h = sum(sd*((B[i].l-p) if sd>0 else (p-B[i].h)) for sd,p in book)
            if h<maxheat: maxheat=h
            if hit:
                pnl=sum(sd*(opp-p)-cost for sd,p in book)
                realised+=pnl; closes+=1; wins+= pnl>0; losses+= pnl<0
                book=[]; regime=-regime; break
        peak=max(peak,realised); dd=max(dd,peak-realised)
    return dict(trades=trades,closes=closes,realised=realised,dd=dd,maxopen=maxopen,
                maxheat=maxheat,wins=wins,losses=losses,n=len(S),
                avgR=float(np.mean(Rs)) if Rs else 0.0)
def show(nm,r,w=28):
    print(f"  {nm:<{w}} units {r['trades']:5d}  closes {r['closes']:4d} "
          f"({r['wins']:3d}W/{r['losses']:3d}L)  P&L ${r['realised']:+10.2f}  "
          f"/unit ${r['realised']/max(1,r['trades']):+7.2f}  maxDD ${r['dd']:9.2f}  "
          f"stack {r['maxopen']:3d}  heat ${r['maxheat']:+10.2f}")
print("="*146)
print("B. THE STACKING BOOK  -  one unit a day in the trend direction, no take profit,")
print("   close the whole book the moment an opposing box trades")
print("="*146)
for nm,tag,B_,since in (("MT5 2004-2026","m",MT5,None),("MT5 2020+","m",MT5,2020),
                        ("MT5 2024+","m",MT5,2024),("FX May-Aug 2026 (your chart)","t",TV,None)):
    print(f"\n  --- {nm} ---")
    for m in MODES:
        show(f"  4H {m}", stack(tag,B_,mode=m,since=since))
    show("  regime = raw 4H trend", stack(tag,B_,mode="ema2050",flip="htf",since=since))
