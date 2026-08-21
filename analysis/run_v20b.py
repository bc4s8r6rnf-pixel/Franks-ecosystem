import sys, collections, math, random
from mt5_load import load_mt5
import v3_intraday as V3
from v3_intraday import pct
import v20_zone2zone as V20
PATH="/root/.claude/uploads/986dcf13-ec74-53a1-b424-6a3e3047f197/d7136efe-XAU_15m_data.csv"
bars=load_mt5(PATH,since=2015); S=V3.sessions(bars)
HDR=(f"  {'variant':<30} {'n':>5} {'W':>6} {'L':>6} {'win%':>7} "
     f"{'PF':>8} {'RR':>8} {'risk':>12} {'avgR':>6} {'totR':>9} {'DD':>7}")
print("="*108);print("5. LOOK-AHEAD REMOVED  -  fill may not precede the 04:00 call");print("="*108)
print(HDR)
for h0,h1 in ((8,11),(0,14),(0,24),(4,24),(4,12)):
    V20.rep(f"  zone {h0:02d}:00-{h1:02d}:00", V20.run(bars,S,anchor="zone",h0=h0,h1=h1))
for h0,h1 in ((8,11),(0,24),(4,24)):
    V20.rep(f"  asia {h0:02d}:00-{h1:02d}:00", V20.run(bars,S,anchor="asia",h0=h0,h1=h1))
print()
print("="*108);print("6. THE ADAPTIVE ANCHOR  -  'Asia close by -> zone edge, Asia far -> Asia'");print("="*108)
print(HDR)
for sep in (0.05,0.10,0.15,0.20,0.30,0.50):
    V20.rep(f"  auto sep {sep:.2f}", V20.run(bars,S,anchor="auto",sep=sep))
V20.rep("  near (shallowest of 3)", V20.run(bars,S,anchor="near"))
V20.rep("  far  (deepest of 3)",    V20.run(bars,S,anchor="far"))
print()
print("="*108);print("7. IS +2.2pp REAL?  -  binomial test against the 29.94% break-even");print("="*108)
for nm,kw in (("zone 08-11",dict(anchor="zone")),("zone 04-24",dict(anchor="zone",h0=4,h1=24)),
              ("auto 0.15",dict(anchor="auto")),("near",dict(anchor="near"))):
    ts=[t for t in V20.run(bars,S,**kw) if t["r"] is not None]
    n=len(ts); w=sum(1 for t in ts if t["r"]>0); p=1/(1+2.34)
    se=math.sqrt(p*(1-p)/n); z=(w/n-p)/se
    print(f"  {nm:<14} n {n:5d}  win {pct(w,n):5.1f}%  need {p*100:.1f}%  "
          f"edge {(w/n-p)*100:+5.2f}pp  z {z:+5.2f}  "
          f"{'significant' if abs(z)>1.96 else 'INSIDE NOISE'}")
print()
print("="*108);print("8. WITH COSTS  -  $0.25 round trip on the modern sample (2023+)");print("="*108)
print(HDR)
for nm,kw in (("zone 08-11",dict(anchor="zone")),("zone 04-24",dict(anchor="zone",h0=4,h1=24)),
              ("auto 0.15",dict(anchor="auto"))):
    ts=[t for t in V20.run(bars,S,**kw) if t["r"] is not None and t["day"].year>=2023]
    for t in ts: t["r"]=t["r"]-0.25/t["risk"]
    V20.rep(f"  {nm} net", ts)
    gross=[t for t in V20.run(bars,S,**kw) if t["r"] is not None and t["day"].year>=2023]
    V20.rep(f"  {nm} gross", gross)
