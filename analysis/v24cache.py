import pickle, numpy as np
exec(open("v24_anchors.py").read().split('print("\\n"+"="*126)')[0])
CAND=["zone","box","asia","london","pre","swing","prevd"]
OUT={}
for fib in (0.62,0.70,0.79):
    for a in CAND:
        OUT[(a,fib)]=[trade(r,a,fib) for r in ROWS]
slim=[dict(y=r["y"],day=r["day"],conf=r["conf"],ratio=r["ratio"],dist=r["dist"],
           R=r["R"],side=r["side"],px=r["px"],
           A={k:v for k,v in r["A"].items()}) for r in ROWS]
pickle.dump((slim,OUT,CAND),open("v24cache.pkl","wb"))
print("cached", len(slim))
