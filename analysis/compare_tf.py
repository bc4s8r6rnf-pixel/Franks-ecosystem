#!/usr/bin/env python3
"""
Same engine, same dates, two bar sizes. Any difference is resolution.

Usage: python3 compare_tf.py fine.csv coarse.csv
"""
import sys
from v3_intraday import load, sessions, run, cfg, row, HDR

fine, coarse = load(sys.argv[1]), load(sys.argv[2])
sf, sc = sessions(fine), sessions(coarse)
lo, hi = sf[0].day, sf[-1].day

print("=" * 92)
print(f"  SAME ENGINE, SAME DATES ({lo:%Y-%m-%d} -> {hi:%Y-%m-%d})")
print("  Sample and period are identical, so any gap between the rows is bar size.")
print("=" * 92)
for lbl, c in (("enter at call, box-$2 stop", cfg(buffer=2.0)),
               ("patient, run > 0.5 R", cfg(patient=True, run_thresh=0.5)),
               ("patient, run > 0.25 R", cfg(patient=True, run_thresh=0.25)),
               ("at call, hold to midnight", cfg(buffer=2.0, flat_at_close=False)),
               ("patient, hold to midnight",
                cfg(patient=True, run_thresh=0.5, flat_at_close=False))):
    print(f"\n  {lbl}")
    print(HDR)
    row("   coarse", run(coarse, sc, c, lo, hi))
    row("   fine", run(fine, sf, c, lo, hi))

print("\n" + "=" * 92)
print("  THE FULL COARSE SAMPLE FOR CONTEXT - is the window flattering us?")
print("=" * 92)
print(HDR)
row("at call, box-$2", run(coarse, sc, cfg(buffer=2.0)))
row("patient run > 0.5 R", run(coarse, sc, cfg(patient=True, run_thresh=0.5)))
