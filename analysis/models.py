import pickle, numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.inspection import permutation_importance
X,y,yr,NAMES = pickle.load(open("mat.pkl","rb"))
BI = NAMES.index("closer_up")
base = (X[:,BI]==1).astype(int)

def wf(make, cols=None, name="", purge=5):
    """expanding-window walk-forward: train on everything before year Y, predict Y."""
    cols = list(range(X.shape[1])) if cols is None else cols
    P = np.full(len(y), -1); years = sorted(set(yr[yr>=2012]))
    for Y in years:
        tr = yr < Y; te = yr == Y
        if tr.sum() < 500: continue
        idx = np.where(tr)[0][:-purge] if purge else np.where(tr)[0]
        m = make()
        Xtr = X[idx][:,cols]; sc = StandardScaler().fit(Xtr)
        m.fit(sc.transform(Xtr), y[idx])
        P[te] = m.predict(sc.transform(X[te][:,cols]))
    ok = P >= 0
    return P, ok, (P[ok]==y[ok]).mean()

print("="*96)
print("WALK-FORWARD  -  train on every prior year, predict the next.  2012-2026 out of sample")
print("="*96)
mods = [
  ("logistic (all 86)",   lambda: LogisticRegression(max_iter=2000, C=0.1), None),
  ("logistic (C=1)",      lambda: LogisticRegression(max_iter=2000, C=1.0), None),
  ("grad boosting",       lambda: HistGradientBoostingClassifier(max_iter=300, learning_rate=.05,
                                     max_depth=4, min_samples_leaf=40, random_state=0), None),
  ("grad boosting deep",  lambda: HistGradientBoostingClassifier(max_iter=600, learning_rate=.03,
                                     max_depth=8, min_samples_leaf=20, random_state=0), None),
  ("random forest",       lambda: RandomForestClassifier(n_estimators=400, min_samples_leaf=10,
                                     random_state=0, n_jobs=-1), None),
]
store={}
for nm, mk, cols in mods:
    P, ok, acc = wf(mk, cols, nm)
    store[nm]=(P,ok)
    b = (base[ok]==y[ok]).mean()
    print(f"  {nm:<22} n {ok.sum():5d}   model {100*acc:6.2f}%   04:00 call {100*b:6.2f}%   "
          f"delta {100*(acc-b):+6.2f}pp")

print("\n  by year (grad boosting vs the 04:00 call)")
P,ok = store["grad boosting"]
print(f"  {'yr':>5} {'n':>5} {'model':>8} {'call':>8} {'delta':>8}   {'agree':>7}")
for Y in sorted(set(yr[ok])):
    m = ok & (yr==Y)
    a=(P[m]==y[m]).mean(); b=(base[m]==y[m]).mean()
    print(f"  {Y:5d} {m.sum():5d} {100*a:7.2f}% {100*b:7.2f}% {100*(a-b):+7.2f}pp  "
          f"{100*(P[m]==base[m]).mean():6.1f}%")

print("\n" + "="*96)
print("PERMUTATION IMPORTANCE  -  fit 2005-2017, scored on 2018-2026")
print("="*96)
tr, te = yr<=2017, yr>=2018
sc = StandardScaler().fit(X[tr])
m = HistGradientBoostingClassifier(max_iter=300, learning_rate=.05, max_depth=4,
                                   min_samples_leaf=40, random_state=0).fit(sc.transform(X[tr]), y[tr])
print(f"  holdout accuracy {100*m.score(sc.transform(X[te]), y[te]):.2f}%   "
      f"04:00 call {100*(base[te]==y[te]).mean():.2f}%")
r = permutation_importance(m, sc.transform(X[te]), y[te], n_repeats=12, random_state=0, n_jobs=-1)
o = np.argsort(-r.importances_mean)
print(f"  {'feature':<14} {'drop in acc':>12} {'+/-':>7}")
for i in o[:22]:
    print(f"  {NAMES[i]:<14} {100*r.importances_mean[i]:11.3f}pp {100*r.importances_std[i]:6.3f}")
print("  ... 3-6-9 / Gann block:")
for i in o:
    if NAMES[i] in ("mod9","mod90","mod360","sq9","sq9_sin","droot","droot369","d_to_90","doy9","dow"):
        print(f"  {NAMES[i]:<14} {100*r.importances_mean[i]:11.3f}pp {100*r.importances_std[i]:6.3f}")
