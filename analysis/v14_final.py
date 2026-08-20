#!/usr/bin/env python3
"""v14: the whole v2.1 rule set in one configurable engine, every knob swept."""
import sys
from v3_intraday import load, sessions, pct

D = dict(call=4, cut=14, lvl=2.5, pull=0.05, buf=1.0, maxrng=40.0,
         lock=True, cutopp=True, cutbelow=0.25, be=None, maxhold=5*96)

def simulate(bars, S, **kw):
    c = dict(D); c.update(kw)
    lvl = c["lvl"] - c["pull"]
    plan = {}
    for s in S:
        ci = next((i for i in range(s.lo, s.hi+1) if bars[i].ny.hour >= c["call"]), None)
        if ci is None: continue
        if c["maxrng"] and s.rng >= c["maxrng"]: continue
        u1, l2 = s.rhigh + lvl*s.rng, s.rlow - lvl*s.rng
        px = bars[ci].o
        side = 1 if (u1-px) < (px-l2) else -1
        proj = u1 if side > 0 else l2
        stop = (s.rlow-c["buf"]) if side > 0 else (s.rhigh+c["buf"])
        if any(((bars[m].h>=proj) if side>0 else (bars[m].l<=proj)) for m in range(s.lo,ci+1)):
            continue
        dead = next((i for i in range(ci,s.hi+1) if bars[i].ny.hour >= c["cut"]), None)
        if dead is None: continue
        plan[ci] = dict(day=s.day.date(), side=side, proj=proj, stop=stop, dead=dead)

    book, pending, done = [], None, []
    for i, b in enumerate(bars):
        keep = []
        for p in book:
            if (b.l<=p["stop"]) if p["side"]>0 else (b.h>=p["stop"]):
                p["r"] = 0.0 if p.get("armed") else -1.0
                p["exit"]=i; done.append(p); continue
            if c["be"] and not p.get("armed"):
                lvl_be = p["ent"] + p["side"]*c["be"]*abs(p["tgt"]-p["ent"])
                if (b.h>=lvl_be) if p["side"]>0 else (b.l<=lvl_be):
                    p["armed"]=True; p["stop"]=p["ent"]
            if (b.h>=p["tgt"]) if p["side"]>0 else (b.l<=p["tgt"]):
                p["r"]=p["rr"]; p["exit"]=i; done.append(p); continue
            if i-p["in"] > c["maxhold"]:
                p["r"]=p["side"]*(b.c-p["ent"])/p["risk"]; p["exit"]=i; done.append(p); continue
            keep.append(p)
        book = keep

        if i in plan:
            pl = plan[i]
            if c["cutopp"]:
                cut = [p for p in book if p["side"] != pl["side"]
                       and p["side"]*(b.o-p["ent"])/p["risk"] <= c["cutbelow"]]
                for p in cut:
                    p["r"] = p["side"]*(b.o-p["ent"])/p["risk"]; p["exit"]=i; done.append(p)
                book = [p for p in book if p not in cut]
            if (not book) or (not c["lock"]):
                pending = dict(pl); pending["armed_at"] = i

        if pending is not None:
            side, proj, stop = pending["side"], pending["proj"], pending["stop"]
            if i > pending["dead"]:
                pending = None
            elif i >= pending["armed_at"]:
                if ((b.l<=stop) if side>0 else (b.h>=stop)) or \
                   ((b.h>=proj) if side>0 else (b.l<=proj)):
                    pending = None
                elif b.vwap is not None and b.l <= b.vwap <= b.h:
                    risk = abs(b.vwap-stop)
                    if risk > 0:
                        book.append(dict(day=pending["day"], side=side, ent=b.vwap,
                            stop=stop, tgt=proj, risk=risk,
                            rr=abs(proj-b.vwap)/risk, **{"in": i}))
                    pending = None
    return done

def stat(ts):
    r=[t["r"] for t in ts]
    gp=sum(x for x in r if x>0); gl=-sum(x for x in r if x<0)
    w=sum(1 for x in r if x>0); l=sum(1 for x in r if x<0)
    eq=pk=dd=0
    for t in sorted(ts,key=lambda z:z["exit"]):
        eq+=t["r"]; pk=max(pk,eq); dd=max(dd,pk-eq)
    return len(r),w,l,pct(w,len(r)),(gp/gl if gl else 99),sum(r)/len(r),sum(r),dd

def row(nm,ts,w=30):
    n,W,L,wr,pf,a,t,dd = stat(ts)
    print(f"  {nm:<{w}} {n:3d} {W:3d}W {L:2d}L {wr:6.1f}%  PF {pf:5.2f}  "
          f"avgR {a:+.2f}  totR {t:+6.1f}  DD {dd:4.1f}")

def main():
    bars=load(sys.argv[1]); S=sessions(bars)
    print("="*94); print("  v2.1 - every knob swept against the full rule set"); print("="*94)
    row("  v2.1 as shipped", simulate(bars,S))
    for name,key,vals in (
        ("call hour","call",(3,4,5,6)),
        ("entry cutoff","cut",(10,11,12,14,16)),
        ("zone edge","lvl",(2.0,2.25,2.4,2.5,2.6,2.75)),
        ("target pull-in (R)","pull",(0.0,0.02,0.05,0.10,0.20)),
        ("stop buffer ($)","buf",(0.0,0.25,0.50,1.0,2.0)),
        ("range filter ($)","maxrng",(None,35.0,40.0,45.0,50.0)),
        ("cut-below threshold (R)","cutbelow",(0.0,0.25,0.5,1.0)),
        ("break-even at % of target","be",(None,0.4,0.5,0.75)),
    ):
        print(f"\n  {name}:")
        for v in vals:
            row(f"    {v}", simulate(bars,S,**{key:v}))
    print("\n  switches:")
    row("    lock off", simulate(bars,S,lock=False))
    row("    opposing cut off", simulate(bars,S,cutopp=False))

if __name__=="__main__": main()
