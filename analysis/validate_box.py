"""Compare MY computed 2.0 edges against the ones exported from the user's chart."""
import csv, pickle
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
NY=ZoneInfo("America/New_York")
P="/root/.claude/uploads/986dcf13-ec74-53a1-b424-6a3e3047f197/830a2bc9-FX_XAUUSD_15_8a5ec.csv"
rows=[]
for r in csv.DictReader(open(P)):
    try: t=int(float(r["time"]))
    except: continue
    u=r.get("Upper 2.0 R edge","").strip(); d=r.get("Lower 2.0 R edge","").strip()
    rows.append((datetime.fromtimestamp(t,NY), float(r["open"]),float(r["high"]),
                 float(r["low"]),float(r["close"]),
                 float(u) if u else None, float(d) if d else None))
rows.sort(key=lambda x:x[0])
print(f"chart export: {len(rows)} bars   {rows[0][0]}  ->  {rows[-1][0]}")
have=[r for r in rows if r[5] is not None]
print(f"bars carrying zone edges: {len(have)}")

# their edges, one pair per lane
lanes={}
for r in have:
    key=(r[0]-timedelta(hours=0)).date() if r[0].hour>=0 else None
    lanes.setdefault(r[0].date(),set()).add((round(r[5],2),round(r[6],2)))
print(f"\ndistinct (upper, lower) pairs per calendar day, from THEIR indicator:")
for d in sorted(lanes)[:14]:
    v=sorted(lanes[d])
    print(f"  {d}  {len(v)} pair(s)  " + "  ".join(f"[{a} / {b}]" for a,b in v[:3]))

# now rebuild the 21:00 box from the SAME file and derive my edges
idx={}
for i,r in enumerate(rows): idx.setdefault(r[0].date(),[]).append(i)
print(f"\n{'lane (NY)':<12} {'my 21:00 box':<22} {'my R':>7} {'my 2.0 upper':>13} "
      f"{'their upper':>12} {'diff':>8} {'my 2.0 lower':>13} {'their lower':>12} {'diff':>8}")
n=0; du=[]; dl=[]
for d in sorted(idx):
    an=[i for i in idx[d] if rows[i][0].hour==21]
    if not an: continue
    hi=max(rows[i][2] for i in an); lo=min(rows[i][3] for i in an)
    if hi<=lo: continue
    R=hi-lo; mu=hi+2*R; ml=lo-2*R
    nxt=d+timedelta(days=1)
    theirs=sorted(lanes.get(nxt,[]))
    if not theirs: continue
    tu,tl=theirs[0]
    du.append(mu-tu); dl.append(ml-tl); n+=1
    if n<=12:
        print(f"{str(nxt):<12} {lo:.2f}-{hi:.2f}{'':<6} {R:7.2f} {mu:13.2f} {tu:12.2f} "
              f"{mu-tu:+8.2f} {ml:13.2f} {tl:12.2f} {ml-tl:+8.2f}")
if n:
    import statistics as st
    print(f"\nmatched lanes: {n}")
    print(f"  upper edge difference: median {st.median(du):+.2f}   "
          f"mean {st.mean(du):+.2f}   max |{max(abs(x) for x in du):.2f}|")
    print(f"  lower edge difference: median {st.median(dl):+.2f}   "
          f"mean {st.mean(dl):+.2f}   max |{max(abs(x) for x in dl):.2f}|")
    ok=sum(1 for a,b in zip(du,dl) if abs(a)<0.5 and abs(b)<0.5)
    print(f"  lanes where both edges agree within $0.50: {ok}/{n} ({100*ok/n:.0f}%)")
