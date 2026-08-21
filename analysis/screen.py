import pickle, math, numpy as np
from collections import Counter
D = pickle.load(open("dirlab_h4.pkl","rb"))
ks=set(D[0][0])
for r in D: ks &= set(r[0])
NAMES = sorted(ks)
X = np.array([[r[0][n] for n in NAMES] for r in D], float)
y = np.array([r[1] for r in D], int)
yr= np.array([r[2] for r in D], int)
X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
print(f"rows {len(y)}  feats {len(NAMES)}  {yr.min()}-{yr.max()}  up-share {y.mean():.3f}")

def rankdata(v):
    o = np.argsort(v, kind="mergesort"); r = np.empty(len(v), float)
    r[o] = np.arange(1, len(v)+1)
    # average ties
    sv = v[o]; i = 0
    while i < len(sv):
        j = i
        while j+1 < len(sv) and sv[j+1]==sv[i]: j += 1
        if j > i: r[o[i:j+1]] = (i+1+j+1)/2
        i = j+1
    return r

def AUC(v, t):
    n1 = t.sum(); n0 = len(t)-n1
    if n1==0 or n0==0: return .5
    r = rankdata(v)
    return (r[t==1].sum() - n1*(n1+1)/2)/(n1*n0)

TRN = yr <= 2017; TST = yr >= 2018
print(f"train {TRN.sum()}  test {TST.sum()}")
base = (X[:, NAMES.index("closer_up")] == 1).astype(int)
print(f"\nBASELINE  the 04:00 call")
print(f"  all   {100*(base==y).mean():.2f}%   train {100*(base[TRN]==y[TRN]).mean():.2f}%   test {100*(base[TST]==y[TST]).mean():.2f}%")

print("\n" + "="*100)
print("UNIVARIATE SCREEN  -  ranked by TRAIN auc, then scored on the unseen TEST years")
print("="*100)
print(f"  {'feature':<14} {'trainAUC':>9} {'testAUC':>9} {'trainACC':>9} {'testACC':>9} {'thr':>9}  verdict")
res=[]
for i,n in enumerate(NAMES):
    v = X[:,i]
    a_tr, a_te = AUC(v[TRN], y[TRN]), AUC(v[TST], y[TST])
    # best single split on train
    qs = np.quantile(v[TRN], np.linspace(.05,.95,19))
    best=(0,None,None)
    for q in np.unique(qs):
        for sgn in (1,-1):
            p = ((v[TRN]*sgn) > q*sgn).astype(int)
            ac = (p==y[TRN]).mean()
            if ac > best[0]: best = (ac, q, sgn)
    ac_tr,q,sgn = best
    ac_te = (((v[TST]*sgn) > q*sgn).astype(int)==y[TST]).mean()
    res.append((n, a_tr, a_te, ac_tr, ac_te, q, sgn))
res.sort(key=lambda r: -abs(r[1]-.5))
for n,a_tr,a_te,ac_tr,ac_te,q,sgn in res[:30]:
    ok = "holds" if (a_tr-.5)*(a_te-.5) > 0 and abs(a_te-.5) > .02 else \
         ("flips" if (a_tr-.5)*(a_te-.5) < 0 else "fades")
    print(f"  {n:<14} {a_tr:9.3f} {a_te:9.3f} {100*ac_tr:8.1f}% {100*ac_te:8.1f}% {q:9.3f}  {ok}")
print("\n  ---- the 3-6-9 / Gann battery, in full ----")
for n,a_tr,a_te,ac_tr,ac_te,q,sgn in res:
    if n in ("mod9","mod10","mod50","mod90","mod100","mod360","d_to_90","d_to_100",
             "sq9","sq9_sin","droot","droot369","dow","dom","month","doy9"):
        print(f"  {n:<14} {a_tr:9.3f} {a_te:9.3f} {100*ac_tr:8.1f}% {100*ac_te:8.1f}%")
pickle.dump((X,y,yr,NAMES), open("mat.pkl","wb"))
