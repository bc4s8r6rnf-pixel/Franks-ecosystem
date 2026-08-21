"""v22: does YESTERDAY'S structure add anything to today's call?"""
import pickle, numpy as np, dirlab
B,S = pickle.load(open("bs.pkl","rb"))
L=[s for s in S if s.lab is not None]
for s in L:
    s.f=None
    for i in range(s.lo,s.hi+1):
        if B[i].h>=s.up or B[i].l<=s.dn: s.f=B[i].t; break
IDX={id(s):k for k,s in enumerate(L)}

def feats(k):
    """previous-day structure, all known before today's lane opens."""
    s=L[k]; p=L[k-1]; R=s.R
    ii=dirlab.win(B,s,4,4.25)
    if not ii or (s.f is not None and s.f<=B[ii[0]].t): return None
    px=B[ii[0]].o
    ph=max(B[i].h for i in range(p.lo,p.hi+1)); pl=min(B[i].l for i in range(p.lo,p.hi+1))
    po=B[p.lo].o; pc=B[p.hi].c; prng=ph-pl
    d={}
    d["pos_zone"]=(px-s.dn)/(s.up-s.dn)
    d["conf"]=abs(d["pos_zone"]-.5)
    d["call"]=1 if d["pos_zone"]>.5 else 0
    # --- yesterday's shape -----------------------------------------
    d["p_close_pos"]  = (pc-pl)/max(1e-9,prng)          # 0 = closed on the low
    d["p_body"]       = (pc-po)/max(1e-9,prng)
    d["p_rng_R"]      = prng/R
    d["p_rng_exp"]    = prng/max(1e-9, np.mean([max(B[i].h for i in range(L[j].lo,L[j].hi+1))
                                  -min(B[i].l for i in range(L[j].lo,L[j].hi+1))
                                  for j in range(max(0,k-6),k-1)])) if k>6 else 1.0
    d["p_hit"]        = 1.0 if p.lab==1 else -1.0 if p.lab==0 else 0.0
    # how far past its zone did yesterday run?
    if p.lab==1:   d["p_over"]=(ph-p.up)/R
    elif p.lab==0: d["p_over"]=(p.dn-pl)/R
    else:          d["p_over"]=0.0
    # --- today's price against yesterday's structure ---------------
    d["v_p_high"] = (px-ph)/R
    d["v_p_low"]  = (px-pl)/R
    d["v_p_close"]= (px-pc)/R
    d["v_p_mid"]  = (px-(ph+pl)/2)/R
    d["in_p_rng"] = (px-pl)/max(1e-9,prng)
    # did we sweep yesterday's high or low before the call?
    sw=0.0
    for i in range(s.lo, ii[0]):
        if B[i].h>=ph: sw=1.0; break
        if B[i].l<=pl: sw=-1.0; break
    d["sweep_pd"]=sw
    # --- box vs box -------------------------------------------------
    d["box_shift"]=((s.bh+s.bl)/2-(p.bh+p.bl)/2)/R
    d["box_ovlp"] =(min(s.bh,p.bh)-max(s.bl,p.bl))/R
    d["R_ratio"]  =R/max(1e-9,p.R)
    d["inside"]   =1.0 if (s.bh<=p.bh and s.bl>=p.bl) else 0.0
    # --- yesterday's UNTOUCHED zone edge ----------------------------
    if p.lab==1:   miss=p.dn
    elif p.lab==0: miss=p.up
    else:          miss=None
    d["miss_side"]= 0.0 if miss is None else (1.0 if miss>px else -1.0)
    d["miss_dist"]= 0.0 if miss is None else abs(miss-px)/R
    # --- streak of prior labels -------------------------------------
    st=0
    for j in range(k-1,max(-1,k-6),-1):
        if L[j].lab is None or (st and L[j].lab!=L[k-1].lab): break
        st+=1
    d["streak"]=st*d["p_hit"]
    return d, s.lab, s.y

ROWS=[r for r in (feats(k) for k in range(10,len(L))) if r]
NAMES=[n for n in ROWS[0][0] if n not in ("call",)]
X=np.array([[r[0][n] for n in NAMES] for r in ROWS],float)
X=np.nan_to_num(X,nan=0,posinf=0,neginf=0)
y=np.array([r[1] for r in ROWS],int); yr=np.array([r[2] for r in ROWS],int)
call=np.array([r[0]["call"] for r in ROWS],int); conf=np.array([r[0]["conf"] for r in ROWS])
print(f"undecided-at-04:00 rows {len(y)}   04:00 call {100*(call==y).mean():.2f}%")

def rank(v):
    o=np.argsort(v,kind="mergesort"); r=np.empty(len(v),float); r[o]=np.arange(1,len(v)+1)
    sv=v[o]; i=0
    while i<len(sv):
        j=i
        while j+1<len(sv) and sv[j+1]==sv[i]: j+=1
        if j>i: r[o[i:j+1]]=(i+1+j+1)/2
        i=j+1
    return r
def AUC(v,t):
    n1=t.sum(); n0=len(t)-n1
    return .5 if n1==0 or n0==0 else (rank(v)[t==1].sum()-n1*(n1+1)/2)/(n1*n0)

TR,TE=yr<=2017,yr>=2018
print("\n"+"="*100)
print("O. PREVIOUS-DAY FEATURES, univariate, ranked by train AUC")
print("="*100)
print(f"  {'feature':<14} {'trainAUC':>9} {'testAUC':>9} {'trainACC':>9} {'testACC':>9}  verdict")
out=[]
for i,n in enumerate(NAMES):
    v=X[:,i]; a1,a2=AUC(v[TR],y[TR]),AUC(v[TE],y[TE])
    best=(0,None,None)
    for q in np.unique(np.quantile(v[TR],np.linspace(.05,.95,19))):
        for sg in (1,-1):
            ac=(((v[TR]*sg)>q*sg).astype(int)==y[TR]).mean()
            if ac>best[0]: best=(ac,q,sg)
    ac1,q,sg=best; ac2=(((v[TE]*sg)>q*sg).astype(int)==y[TE]).mean()
    out.append((n,a1,a2,ac1,ac2))
out.sort(key=lambda r:-abs(r[1]-.5))
for n,a1,a2,ac1,ac2 in out:
    v="HOLDS" if (a1-.5)*(a2-.5)>0 and abs(a2-.5)>.03 else ("flips" if (a1-.5)*(a2-.5)<0 else "flat")
    print(f"  {n:<14} {a1:9.3f} {a2:9.3f} {100*ac1:8.1f}% {100*ac2:8.1f}%  {v}")

print("\n"+"="*100)
print("P. DO THEY ADD CONFLUENCE?  accuracy of the 04:00 call, split by each prev-day feature")
print("="*100)
print(f"  {'feature / split':<30} {'n lo':>6} {'acc lo':>8} {'n hi':>6} {'acc hi':>8} {'gap':>8} {'2018-26 gap':>12}")
for i,n in enumerate(NAMES):
    if n in ("conf","pos_zone"): continue
    v=X[:,i]; m=np.median(v)
    lo,hi=v<=m,v>m
    if lo.sum()<100 or hi.sum()<100: continue
    al,ah=(call[lo]==y[lo]).mean(),(call[hi]==y[hi]).mean()
    l2,h2=lo&TE,hi&TE
    g2=(call[h2]==y[h2]).mean()-(call[l2]==y[l2]).mean()
    print(f"  {n:<30} {lo.sum():6d} {100*al:7.2f}% {hi.sum():6d} {100*ah:7.2f}% "
          f"{100*(ah-al):+7.2f}pp {100*g2:+11.2f}pp")

print("\n"+"="*100)
print("Q. AGREEMENT: does yesterday's UNTOUCHED zone edge point the same way as today's call?")
print("="*100)
ms=X[:,NAMES.index("miss_side")]
agree=((ms>0)&(call==1))|((ms<0)&(call==0))
have=ms!=0
for nm,m in (("call agrees with the unfilled edge",have&agree),
             ("call opposes the unfilled edge",have&~agree),
             ("yesterday reached neither",~have)):
    if m.sum()<20: continue
    print(f"  {nm:<38} n {m.sum():5d} ({100*m.mean():4.1f}%)  acc {100*(call[m]==y[m]).mean():6.2f}%   "
          f"2018-26 {100*(call[m&TE]==y[m&TE]).mean():6.2f}%")
print("\n  layered on the confidence filter (|pos-0.5| >= 0.15):")
c=conf>=.15
for nm,m in (("agrees with unfilled edge",c&have&agree),("opposes",c&have&~agree)):
    print(f"  {nm:<38} n {m.sum():5d}  acc {100*(call[m]==y[m]).mean():6.2f}%   "
          f"2018-26 {100*(call[m&TE]==y[m&TE]).mean():6.2f}%")

print("\n"+"="*100)
print("R. WALK-FORWARD: 04:00 call + all 19 previous-day features vs the call alone")
print("="*100)
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
XA=np.column_stack([X, call])
for nm,mk in (("logistic",lambda:LogisticRegression(max_iter=2000,C=.1)),
              ("grad boosting",lambda:HistGradientBoostingClassifier(max_iter=300,learning_rate=.05,
                    max_depth=4,min_samples_leaf=40,random_state=0)),
              ("random forest",lambda:RandomForestClassifier(n_estimators=500,min_samples_leaf=10,
                    random_state=0,n_jobs=-1))):
    P=np.full(len(y),-1)
    for Y in sorted(set(yr[yr>=2012])):
        tr,te=yr<Y,yr==Y
        if tr.sum()<400: continue
        idx=np.where(tr)[0][:-5]
        sc=StandardScaler().fit(XA[idx]); m=mk().fit(sc.transform(XA[idx]),y[idx])
        P[te]=m.predict(sc.transform(XA[te]))
    ok=P>=0; b=(call[ok]==y[ok]).mean(); a=(P[ok]==y[ok]).mean()
    print(f"  {nm:<16} n {ok.sum():5d}  model {100*a:6.2f}%  call {100*b:6.2f}%  delta {100*(a-b):+6.2f}pp"
          f"  (1 s.e. {100*np.sqrt(b*(1-b)/ok.sum()):.2f}pp)")
