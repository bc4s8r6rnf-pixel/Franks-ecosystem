import dirlab, pickle, numpy as np, math, os
if os.path.exists("bs.pkl"):
    B,S = pickle.load(open("bs.pkl","rb"))
else:
    B = dirlab.load('data_XAU_15m_2004_2026.csv'); S = dirlab.sessions(B)
    pickle.dump((B,S), open("bs.pkl","wb"))
L = [s for s in S if s.lab is not None]
print(f"{len(L)} labelled sessions  {L[0].day.date()} -> {L[-1].day.date()}\n")

HOURS = [-6,-5.5,-5,-4.5,-4,-3.5,-3,-2.5,-2,-1.5,-1,-0.5,0,0.5,1,1.5,2,2.5,3,3.5,4,
         4.5,5,5.5,6,6.5,7,7.5,8,8.5,9,9.5,10,11,12]
def clock(h):
    t = (24+h) % 24
    return f"{int(t):02d}:{int(round((t%1)*60)):02d}"

print("="*104)
print("A. 'WHICHEVER ZONE IS CLOSER' EVALUATED AT EVERY CLOCK TIME")
print("="*104)
print(f"  {'NY time':>8} {'n':>5} {'ALL':>8} {'2005-17':>9} {'2018-26':>9} {'2023-26':>9}  {'note':<22}")
CALL = {}
for h in HOURS:
    p=[];t=[];yy=[]
    for s in L:
        ii = dirlab.win(B, s, h, h+0.25)
        if not ii: continue
        px = B[ii[0]].o
        p.append(1 if (s.up-px) < (px-s.dn) else 0); t.append(s.lab); yy.append(s.y)
    p=np.array(p); t=np.array(t); yy=np.array(yy)
    CALL[h]=(p,t,yy)
    f=lambda m: 100*(p[m]==t[m]).mean() if m.sum() else float('nan')
    note = "<- the current call" if h==4 else ("6pm open" if h==-6 else
           ("3am open" if h==3 else ("midnight / lane open" if h==0 else "")))
    print(f"  {clock(h):>8} {len(p):5d} {f(np.ones(len(p),bool)):7.2f}% {f(yy<=2017):8.2f}% "
          f"{f(yy>=2018):8.2f}% {f(yy>=2023):8.2f}%  {note:<22}")

print("\n" + "="*104)
print("B. AGREEMENT FILTER  -  only trade when several clocks agree")
print("="*104)
print(f"  {'clocks':<34} {'n kept':>7} {'kept%':>7} {'ALL':>8} {'2018-26':>9} {'2023-26':>9}")
def agree(hs):
    ps = [CALL[h][0] for h in hs]; t = CALL[hs[0]][1]; yy = CALL[hs[0]][2]
    n = min(len(x) for x in ps); ps=[x[:n] for x in ps]; t=t[:n]; yy=yy[:n]
    a = np.all([x==ps[0] for x in ps], 0)
    return ps[0], t, yy, a
for hs,nm in (([-6,4],"18:00 + 04:00"), ([0,4],"00:00 + 04:00"), ([3,4],"03:00 + 04:00"),
              ([-3,4],"21:00 + 04:00"), ([-6,0,4],"18:00 + 00:00 + 04:00"),
              ([0,3,4],"00:00 + 03:00 + 04:00"), ([-6,-3,0,3,4],"18/21/00/03/04"),
              ([4,6],"04:00 + 06:00"), ([4,8],"04:00 + 08:00"),
              ([0,4,8],"00:00 + 04:00 + 08:00"), ([3,6,9],"03:00 + 06:00 + 09:00")):
    p,t,yy,a = agree(hs)
    f=lambda m: 100*(p[m]==t[m]).mean() if m.sum() else float('nan')
    print(f"  {nm:<34} {a.sum():7d} {100*a.mean():6.1f}% {f(a):7.2f}% "
          f"{f(a&(yy>=2018)):8.2f}% {f(a&(yy>=2023)):8.2f}%")
p4,t4,y4 = CALL[4]
print(f"  {'(no filter, 04:00 alone)':<34} {len(p4):7d} {100.0:6.1f}% {100*(p4==t4).mean():7.2f}% "
      f"{100*(p4[y4>=2018]==t4[y4>=2018]).mean():8.2f}% {100*(p4[y4>=2023]==t4[y4>=2023]).mean():8.2f}%")
pickle.dump(CALL, open("call.pkl","wb"))
