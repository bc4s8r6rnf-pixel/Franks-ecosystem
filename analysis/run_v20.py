#!/usr/bin/env python3
"""Driver for v20 zone-to-zone fib."""
import sys, collections
from mt5_load import load_mt5, add_vwap
import v3_intraday as V3
from v3_intraday import pct
import v20_zone2zone as V20

PATH = sys.argv[1] if len(sys.argv) > 1 else \
    "/root/.claude/uploads/986dcf13-ec74-53a1-b424-6a3e3047f197/d7136efe-XAU_15m_data.csv"

bars = load_mt5(PATH, since=2015)
S = V3.sessions(bars)
print(f"bars {len(bars)}  sessions {len(S)}  "
      f"{S[0].day.date()} -> {S[-1].day.date()}\n")

HDR = (f"  {'variant':<30} {'n':>5} {'W':>6} {'L':>6} {'win%':>7} "
       f"{'PF':>8} {'RR':>8} {'risk':>12} {'avgR':>6} {'totR':>9} {'DD':>7}")

def why(res):
    c = collections.Counter(t["why"] for t in res)
    return "   ".join(f"{k} {v}" for k, v in c.most_common())

print("=" * 108)
print("1. THE FULL MATRIX  -  entry window 08:00-11:00 NY, stop exactly on the anchor")
print("=" * 108)
print(HDR)
ALL = {}
for dm in ("call", "prem"):
    for an in ("zone", "asia", "prev"):
        r = V20.run(bars, S, anchor=an, dirmode=dm)
        ALL[(dm, an)] = r
        V20.rep(f"{dm:<5} {an}", r)
    print()

print("why no trade:")
for k, v in ALL.items():
    print(f"  {k[0]:<5} {k[1]:<6} {why(v)}")

print()
print("=" * 108)
print("2. YEAR BY YEAR  -  the two that are anywhere near break-even")
print("=" * 108)
for dm, an in (("call", "zone"), ("call", "asia"), ("prem", "zone")):
    print(f"\n  {dm} / {an}")
    print(HDR)
    res = ALL[(dm, an)]
    for y in range(2015, 2027):
        sub = [t for t in res if t["r"] is not None and t["day"].year == y]
        if sub: V20.rep(f"  {y}", sub)

print()
print("=" * 108)
print("3. STOP BUFFER  -  pushing the stop past the anchor (buf in R of the 9pm box)")
print("=" * 108)
for dm, an in (("call", "zone"), ("call", "asia")):
    print(f"\n  {dm} / {an}")
    print(HDR)
    for buf in (0.0, 0.1, 0.25, 0.5, 0.75, 1.0):
        V20.rep(f"  buf {buf:.2f}R", V20.run(bars, S, anchor=an, dirmode=dm, buf=buf))

print()
print("=" * 108)
print("4. ENTRY WINDOW  -  when the 0.62 is allowed to fill (NY hours)")
print("=" * 108)
for dm, an in (("call", "zone"), ("call", "asia")):
    print(f"\n  {dm} / {an}")
    print(HDR)
    for h0, h1 in ((8, 11), (8, 10), (7, 12), (8, 14), (9, 12), (0, 14), (0, 24), (4, 24)):
        V20.rep(f"  {h0:02d}:00-{h1:02d}:00",
                V20.run(bars, S, anchor=an, dirmode=dm, h0=h0, h1=h1))
