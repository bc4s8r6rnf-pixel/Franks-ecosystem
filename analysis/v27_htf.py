"""
v27: target only the projection box in line with the 4H trend.

  Test A  how often does the trend-side box trade, vs the counter-trend box?
  Test B  stack a position every day in the trend direction, never take profit,
          close the whole book when an opposing box trades.
"""
import csv, pickle, numpy as np
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
NY=ZoneInfo("America/New_York")

class Bar: __slots__=("ny","o","h","l","c","t")

def load_tv(path):
    out=[]
    for r in csv.DictReader(open(path)):
        try: t=int(float(r["time"]))
        except: continue
        b=Bar(); b.t=t; b.ny=datetime.fromtimestamp(t,NY)
        b.o,b.h,b.l,b.c=float(r["open"]),float(r["high"]),float(r["low"]),float(r["close"])
        out.append(b)
    out.sort(key=lambda z:z.t); return out

class Sess: __slots__=("day","bh","bl","R","up","dn","lo","hi","y")
def sessions(B):
    idx={}
    for i,b in enumerate(B): idx.setdefault(b.ny.date(),[]).append(i)
    out=[]; last=B[-1].ny
    for d in sorted(idx):
        an=[i for i in idx[d] if B[i].ny.hour==21]
        if not an: continue
        hi=max(B[i].h for i in an); lo=min(B[i].l for i in an)
        if hi<=lo: continue
        d0=d+timedelta(days=1)
        ls=datetime(d0.year,d0.month,d0.day,tzinfo=NY); le=ls+timedelta(days=1)
        if le>last: continue
        ids=[i for i in range(an[-1]+1,len(B)) if ls<=B[i].ny<le]
        if len(ids)<20: continue
        s=Sess(); s.day=ls; s.bh,s.bl,s.R=hi,lo,hi-lo
        s.up,s.dn=hi+2*s.R, lo-2*s.R; s.lo,s.hi=ids[0],ids[-1]; s.y=ls.year
        out.append(s)
    return out

def h4(B):
    """4H bars anchored to 00:00 NY, plus the index of the last CLOSED 4H bar."""
    buck={}
    for i,b in enumerate(B):
        k=(b.ny.date(), b.ny.hour//4)
        buck.setdefault(k,[]).append(i)
    keys=sorted(buck)
    bars=[]
    for k in keys:
        ii=buck[k]
        bars.append(dict(k=k, o=B[ii[0]].o, h=max(B[i].h for i in ii),
                         l=min(B[i].l for i in ii), c=B[ii[-1]].c,
                         end=B[ii[-1]].t, start=B[ii[0]].t))
    return bars

def ema(v,n):
    k=2/(n+1); o=[]; e=None
    for x in v:
        e=x if e is None else x*k+e*(1-k); o.append(e)
    return o

def trends(H4):
    c=[b["c"] for b in H4]; h=[b["h"] for b in H4]; l=[b["l"] for b in H4]
    e20,e50,e200=ema(c,20),ema(c,50),ema(c,200)
    # supertrend on 4H
    atr=[]; pr=None; tr=[]
    for i,b in enumerate(H4):
        t=b["h"]-b["l"] if pr is None else max(b["h"]-b["l"],abs(b["h"]-pr),abs(b["l"]-pr))
        tr.append(t); pr=b["c"]
    a=ema(tr,10)
    st=[]; d=1; up=dn=None
    for i,b in enumerate(H4):
        mid=(b["h"]+b["l"])/2; u=mid+3*a[i]; lo_=mid-3*a[i]
        up = u if up is None else (min(u,up) if c[i-1]<=up else u)
        dn = lo_ if dn is None else (max(lo_,dn) if c[i-1]>=dn else lo_)
        if d>0 and c[i]<dn: d=-1
        elif d<0 and c[i]>up: d=1
        st.append(d)
    out=[]
    for i in range(len(H4)):
        out.append(dict(k=H4[i]["k"], end=H4[i]["end"],
            ema2050 = 1 if e20[i]>e50[i] else -1,
            px_e50  = 1 if c[i]>e50[i] else -1,
            px_e200 = 1 if c[i]>e200[i] else -1,
            stack   = 1 if (e20[i]>e50[i]>e200[i]) else (-1 if (e20[i]<e50[i]<e200[i]) else 0),
            super_  = st[i],
            struct  = 1 if (i>=6 and h[i-1]>max(h[i-6:i-1]) ) else (-1 if (i>=6 and l[i-1]<min(l[i-6:i-1])) else 0)))
    return out

def build(B):
    S=sessions(B); H=h4(B); T=trends(H)
    # for each session, the trend from the last 4H bar CLOSED before the lane opens
    for s in S:
        t0=s.day.timestamp()
        cur=None
        for r in T:
            if r["end"] < t0: cur=r
            else: break
        s_tr = cur
        yield s, s_tr

MODES=["ema2050","px_e50","px_e200","stack","super_","struct"]

def testA(B, name):
    S=list(build(B))
    print(f"\n  --- {name}   {len(S)} lanes  {S[0][0].day.date()} -> {S[-1][0].day.date()} ---")
    print(f"  {'4H trend definition':<22} {'n':>5} {'trend box':>11} {'counter box':>12} "
          f"{'trend FIRST':>12} {'neither':>9}")
    for m in MODES:
        n=tb=cb=tf=nb=0
        for s,tr in S:
            if tr is None or tr[m]==0: continue
            d=tr[m]; n+=1
            tgt = s.up if d>0 else s.dn
            opp = s.dn if d>0 else s.up
            ht=hc=False; first=None
            for i in range(s.lo,s.hi+1):
                if not ht and ((B[i].h>=tgt) if d>0 else (B[i].l<=tgt)):
                    ht=True; first=first or "t"
                if not hc and ((B[i].l<=opp) if d>0 else (B[i].h>=opp)):
                    hc=True; first=first or "c"
            tb+=ht; cb+=hc; tf+= (first=="t"); nb+= (not ht and not hc)
        if n:
            print(f"  {m:<22} {n:5d} {100*tb/n:10.1f}% {100*cb/n:11.1f}% "
                  f"{100*tf/n:11.1f}% {100*nb/n:8.1f}%")

print("="*112)
print("A. HOW OFTEN DOES THE BOX IN LINE WITH THE 4H TREND TRADE?")
print("="*112)
MT5,_=pickle.load(open("bs.pkl","rb"))
TV=load_tv("/root/.claude/uploads/986dcf13-ec74-53a1-b424-6a3e3047f197/830a2bc9-FX_XAUUSD_15_8a5ec.csv")
testA(TV,"FX_XAUUSD 15m, the chart you mark up (May-Aug 2026)")
testA(MT5,"MT5 XAU 15m, 2004-2026")
pickle.dump(TV,open("tv.pkl","wb"))

print("\n"+"="*124)
print("B. THE STACKING BOOK  -  add one unit a day in the trend direction, never take profit,")
print("   close the whole book the moment an opposing box trades")
print("="*124)

def stack(B, mode="ema2050", entry="open", flip="box", since=None, cost=0.0):
    """flip: 'box' = regime flips when an opposing box trades (4H only sets the first
       direction and gates new entries); 'htf' = regime is purely the 4H trend."""
    S=list(build(B))
    if since: S=[(s,t) for s,t in S if s.y>=since]
    book=[]; realised=0.0; regime=0; trades=0; closes=0
    peak=0.0; dd=0.0; maxopen=0; maxheat=0.0; eq=[]; wins=0; losses=0
    Rs=[]
    for s,tr in S:
        d = 0 if tr is None else tr[mode]
        if flip=="htf": regime = d
        elif regime==0: regime = d
        if regime!=0 and (flip=="htf" or d==regime or d==0):
            i0=s.lo
            px=B[i0].o if entry=="open" else B[next((i for i in range(s.lo,s.hi+1)
                          if B[i].ny.hour>=4), s.lo)].o
            book.append((regime,px,s.R)); trades+=1; Rs.append(s.R)
        maxopen=max(maxopen,len(book))
        for i in range(s.lo,s.hi+1):
            if not book: break
            opp = s.dn if regime>0 else s.up
            hit = (B[i].l<=opp) if regime>0 else (B[i].h>=opp)
            heat = sum(sd*(B[i].l-p if sd>0 else p-B[i].h) for sd,p,_ in book)
            maxheat=min(maxheat,heat)
            if hit:
                pnl=sum(sd*(opp-p) - cost for sd,p,_ in book)
                realised+=pnl; closes+=1
                wins += pnl>0; losses += pnl<0
                book=[]; regime=-regime
                break
        eq.append(realised)
        peak=max(peak,realised); dd=max(dd,peak-realised)
    open_pnl = 0.0
    return dict(trades=trades, closes=closes, realised=realised, dd=dd,
                maxopen=maxopen, maxheat=maxheat, wins=wins, losses=losses,
                avgR=np.mean(Rs) if Rs else 0, n=len(S))
def show(nm,r,w=30):
    print(f"  {nm:<{w}} units {r['trades']:5d}  book closes {r['closes']:4d} "
          f"({r['wins']}W/{r['losses']}L)  P&L ${r['realised']:+10.2f}  "
          f"per unit ${r['realised']/max(1,r['trades']):+7.2f}  maxDD ${r['dd']:8.2f}  "
          f"max stack {r['maxopen']:3d}  worst heat ${r['maxheat']:+9.2f}")

for nm,B_,since in (("MT5 2004-2026",MT5,None),("MT5 2020+",MT5,2020),
                    ("MT5 2024+",MT5,2024),("FX 2026 (your chart)",TV,None)):
    print(f"\n  --- {nm} ---")
    for m in MODES:
        show(f"  4H {m}", stack(B_,mode=m,since=since))
    show("  pure box flip (no 4H)", stack(B_,mode="ema2050",flip="box",since=since))
    show("  regime = raw 4H trend", stack(B_,mode="ema2050",flip="htf",since=since))
