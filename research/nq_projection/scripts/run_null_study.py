"""Null-model calibration of the projection-zone statistics.

Runs the exact reconstruction described in section 8 of the brief against
synthetic price series that contain no projection phenomenon by construction.
Whatever rate the null produces is the floor any real result must clear before
it means anything.

    python3 scripts/run_null_study.py [--reps N] [--days N] [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nqproj import analysis as A
from nqproj import nullmodel, projections as P
from nqproj import swings as S

# Each scenario keeps the random-walk core and perturbs one realistic property,
# so a rate that survives all of them is a property of the geometry, not of the
# particular way the noise was generated.
SCENARIOS = {
    "gbm_baseline":      dict(sigma_annual=0.22),
    "gbm_low_vol":       dict(sigma_annual=0.12),
    "gbm_high_vol":      dict(sigma_annual=0.40),
    "fat_tails_t4":      dict(sigma_annual=0.22, df_t=4.0),
    "vol_seasonality":   dict(sigma_annual=0.22, vol_seasonality=0.8),
    "bull_drift_15pct":  dict(sigma_annual=0.22, drift_annual=0.15),
    "seasonal_fat_bull": dict(sigma_annual=0.22, df_t=4.0, vol_seasonality=0.8, drift_annual=0.12),
}


def run_one(seed: int, days: int, **kw) -> dict:
    bs = nullmodel.simulate(days=days, seed=seed, **kw)
    refs = P.build_reference_candles(bs)
    path = P.PathIndex.from_barset(bs)

    res = A.opposite_zone_test(refs, path, k=2.0, windows_hours=(24.0, 72.0, 120.0))
    out = A.summarise_opposite_test(res)

    # Same question, split by reference-candle kind: the brief warns 9AM and 9PM
    # may differ, so the null needs to show whether they differ on noise alone.
    for kind in ("9PM", "9AM"):
        sub = res[(res["kind"] == kind) & res["first_side"].notna()]
        if len(sub):
            out[f"{kind}_opposite_within_72h"] = float(sub["within_72h"].mean())
            out[f"{kind}_first_touch_n"] = int(len(sub))

    # How often is the 2.0-2.5 band merely passed through?
    zones = P.build_zones(refs, ladder=(2.0, 2.5, 3.0, 4.0, 5.0))
    touches = P.resolve_first_touches(zones, path, max_age_days=10.0)
    for k in (2.0, 2.5, 3.0, 4.0, 5.0):
        sel = touches[touches["k"] == k]
        out[f"touch_rate_k{k:g}"] = float(sel["touched"].mean()) if len(sel) else np.nan

    beh = A.touch_behaviour(touches[touches["k"].isin([2.0, 2.5])], path, forward_hours=48.0)
    if not beh.empty:
        out["null_terminal_1R_rate"] = float(beh["terminal_1R"].mean())
        out["null_terminal_2R_rate"] = float(beh["terminal_2R"].mean())
        out["null_median_penetration_R"] = float(beh["max_penetration_R"].median())
        out["null_reclaim_rate"] = float(beh["reclaimed"].mean())

    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=12)
    ap.add_argument("--days", type=int, default=900)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "out"))
    args = ap.parse_args()

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    rows = []
    for name, kw in SCENARIOS.items():
        for rep in range(args.reps):
            r = run_one(seed=hash((name, rep)) % (2**31), days=args.days, **kw)
            r["scenario"] = name
            r["rep"] = rep
            rows.append(r)
            print(f"  {name} rep{rep}: 72h={r.get('opposite_within_72h', float('nan')):.3f} "
                  f"120h={r.get('opposite_within_120h', float('nan')):.3f}", flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(outdir / "null_study_raw.csv", index=False)

    metrics = [c for c in df.columns if c not in ("scenario", "rep")]
    summary = df.groupby("scenario")[metrics].agg(["mean", "std"])
    summary.to_csv(outdir / "null_study_summary.csv")

    key = ["opposite_within_72h", "opposite_within_120h", "opposite_within_24h",
           "first_touch_rate", "median_hours_to_first"]
    print("\n" + "=" * 78)
    print("NULL MODEL — strict opposite-2.0 reconstruction (no phenomenon present)")
    print("=" * 78)
    for name in SCENARIOS:
        d = df[df["scenario"] == name]
        bits = [f"{k.replace('opposite_within_', '')}={d[k].mean():.3f}±{d[k].std():.3f}"
                for k in key if k in d.columns]
        print(f"{name:20s} " + "  ".join(bits))

    pooled = df[df["scenario"].isin(["gbm_baseline", "fat_tails_t4", "vol_seasonality",
                                     "seasonal_fat_bull", "bull_drift_15pct"])]
    print("\nPooled realistic nulls:")
    for k in ("opposite_within_72h", "opposite_within_120h"):
        v = pooled[k]
        print(f"  {k:26s} mean={v.mean():.4f}  sd={v.std():.4f}  "
              f"range=[{v.min():.3f}, {v.max():.3f}]")

    (outdir / "null_headline.json").write_text(json.dumps(
        {k: {"mean": float(pooled[k].mean()), "sd": float(pooled[k].std()),
             "min": float(pooled[k].min()), "max": float(pooled[k].max())}
         for k in ("opposite_within_72h", "opposite_within_120h")}, indent=2))
    print(f"\nwrote {outdir}/null_study_raw.csv, null_study_summary.csv, null_headline.json")


if __name__ == "__main__":
    main()
