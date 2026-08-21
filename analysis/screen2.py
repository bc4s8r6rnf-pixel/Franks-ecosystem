import pickle, numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.inspection import permutation_importance
D = pickle.load(open("dirlab_h4.pkl","rb"))
CALL = pickle.load(open("call2.pkl","rb"))
OPEN4 = set(CALL[4])                       # undecided at 04:00
ks=set(D[0][0])
for r in D: ks &= set(r[0])
NAMES=sorted(ks)
D=[r for r in D if r[3] in OPEN4]
X=np.nan_to_num(np.array([[r[0][n] for n in NAMES] for r in D],float),nan=0,posinf=0,neginf=0)
y=np.array([r[1] for r in D],int); yr=np.array([r[2] for r in D],int)
base=(X[:,NAMES.index("closer_up")]==1).astype(int)
print(f"UNDECIDED-AT-04:00 SAMPLE  rows {len(y)}  up-share {y.mean():.3f}")
print(f"  04:00 call   all {100*(base==y).mean():.2f}%   "
      f"2005-17 {100*(base[yr<=2017]==y[yr<=2017]).mean():.2f}%   "
      f"2018-26 {100*(base[yr>=2018]==y[yr>=2018]).mean():.2f}%")

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
    if n1==0 or n0==0: return .5
    return (rank(v)[t==1].sum()-n1*(n1+1)/2)/(n1*n0)

TR,TE = yr<=2017, yr>=2018
print("\n"+"="*98)
print("C. UNIVARIATE SCREEN ON THE UNDECIDED SAMPLE")
print("="*98)
print(f"  {'feature':<14} {'trainAUC':>9} {'testAUC':>9} {'trainACC':>9} {'testACC':>9}  verdict")
res=[]
for i,n in enumerate(NAMES):
    v=X[:,i]; a1,a2=AUC(v[TR],y[TR]),AUC(v[TE],y[TE])
    best=(0,None,None)
    for q in np.unique(np.quantile(v[TR],np.linspace(.05,.95,19))):
        for sg in (1,-1):
            ac=(((v[TR]*sg)>q*sg).astype(int)==y[TR]).mean()
            if ac>best[0]: best=(ac,q,sg)
    ac1,q,sg=best; ac2=((((v[TE]*sg)>q*sg).astype(int))==y[TE]).mean()
    res.append((n,a1,a2,ac1,ac2))
res.sort(key=lambda r:-abs(r[1]-.5))
for n,a1,a2,ac1,ac2 in res[:24]:
    v="holds" if (a1-.5)*(a2-.5)>0 and abs(a2-.5)>.02 else ("flips" if (a1-.5)*(a2-.5)<0 else "fades")
    print(f"  {n:<14} {a1:9.3f} {a2:9.3f} {100*ac1:8.1f}% {100*ac2:8.1f}%  {v}")

print("\n"+"="*98)
print("D. WALK-FORWARD MODELS ON THE UNDECIDED SAMPLE  (train all prior years, predict next)")
print("="*98)
def wf(mk,purge=5):
    P=np.full(len(y),-1)
    for Y in sorted(set(yr[yr>=2012])):
        tr=yr<Y; te=yr==Y
        if tr.sum()<400: continue
        idx=np.where(tr)[0][:-purge]
        sc=StandardScaler().fit(X[idx]); m=mk().fit(sc.transform(X[idx]),y[idx])
        P[te]=m.predict(sc.transform(X[te]))
    ok=P>=0
    return P,ok
for nm,mk in (("logistic C=0.1",lambda:LogisticRegression(max_iter=2000,C=.1)),
              ("logistic C=1",lambda:LogisticRegression(max_iter=2000,C=1.)),
              ("grad boosting",lambda:HistGradientBoostingClassifier(max_iter=300,learning_rate=.05,
                    max_depth=4,min_samples_leaf=40,random_state=0)),
              ("grad boost deep",lambda:HistGradientBoostingClassifier(max_iter=600,learning_rate=.03,
                    max_depth=8,min_samples_leaf=20,random_state=0)),
              ("random forest",lambda:RandomForestClassifier(n_estimators=500,min_samples_leaf=10,
                    random_state=0,n_jobs=-1))):
    P,ok=wf(mk); b=(base[ok]==y[ok]).mean(); a=(P[ok]==y[ok]).mean()
    n=ok.sum(); se=np.sqrt(b*(1-b)/n)
    print(f"  {nm:<18} n {n:5d}  model {100*a:6.2f}%  call {100*b:6.2f}%  "
          f"delta {100*(a-b):+6.2f}pp  (1 s.e. = {100*se:.2f}pp)")

print("\n"+"="*98)
print("E. PERMUTATION IMPORTANCE, undecided sample, fit 2005-17 -> scored 2018-26")
print("="*98)
sc=StandardScaler().fit(X[TR])
m=HistGradientBoostingClassifier(max_iter=300,learning_rate=.05,max_depth=4,
      min_samples_leaf=40,random_state=0).fit(sc.transform(X[TR]),y[TR])
print(f"  holdout {100*m.score(sc.transform(X[TE]),y[TE]):.2f}%   call {100*(base[TE]==y[TE]).mean():.2f}%")
r=permutation_importance(m,sc.transform(X[TE]),y[TE],n_repeats=15,random_state=0,n_jobs=-1)
for i in np.argsort(-r.importances_mean)[:18]:
    print(f"  {NAMES[i]:<14} {100*r.importances_mean[i]:+8.3f}pp  +/-{100*r.importances_std[i]:5.3f}")
pickle.dump((X,y,yr,NAMES,base,[r[3] for r in D]),open("mat2.pkl","wb"))
