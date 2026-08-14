"""Is 21:00 actually special, or just the quietest hour?

The opposite-2.0 statistic mechanically rises as the reference range R shrinks
relative to the volatility that follows it, because the paired boundaries sit
only 5R apart. The 21:00 NY hour is the quietest hour on NQ, so a high rate
there is exactly what a *non*-phenomenon predicts.

This runs the identical test using every hour of the day as the reference
candle. If 21:00 carries genuine structure it must stand out against the
R-versus-rate curve traced by the other 23 hours -- not merely sit high on it.

    python3 scripts/reference_hour_sweep.py --csv data/nq_15m.csv --tz Europe/Helsinki
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nqproj import analysis as A
from nqproj import data as D
from nqproj import nullmodel, projections as P


def refs_for_hour(bs: D.BarSet, hour: int) -> pd.DataFrame:
    P.REF_HOURS[f"H{hour}"] = hour
    return P.build_reference_candles(bs, kinds=(f"H{hour}",))


def sweep(bs: D.BarSet, label: str) -> pd.DataFrame:
    path = P.PathIndex.from_barset(bs)
    daily = (bs.bars["high"].resample("1D").max() - bs.bars["low"].resample("1D").min()).median()

    rows = []
    for hour in range(24):
        refs = refs_for_hour(bs, hour)
        if len(refs) < 100:
            continue
        res = A.opposite_zone_test(refs, path, k=2.0, windows_hours=(72.0, 120.0))
        s = A.summarise_opposite_test(res)
        rows.append(
            {
                "dataset": label,
                "ref_hour": hour,
                "n_refs": int(len(refs)),
                "median_R": float(refs["R"].median()),
                "R_over_daily": float(refs["R"].median() / daily),
                "first_touch_rate": s.get("first_touch_rate"),
                "median_hours_to_first": s.get("median_hours_to_first"),
                "opp_72h": s.get("opposite_within_72h"),
                "opp_120h": s.get("opposite_within_120h"),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--tz", default="Europe/Helsinki")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "out" / "real"))
    args = ap.parse_args()

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    bs = D.load_csv(args.csv, source_tz=args.tz, symbol="NQ")
    real = sweep(bs, "real")

    # Block bootstrap keeps NQ's intraday volatility shape (so the 21:00 hour
    # stays quiet) while destroying any multi-day geometric relationship. If
    # 21:00 still scores high here, the score is a volatility artefact.
    boot = pd.concat(
        [sweep(nullmodel.bootstrap_from_real(bs, block_hours=24.0, seed=s), f"bootstrap{s}")
         for s in (1, 2, 3)],
        ignore_index=True,
    )
    bagg = boot.groupby("ref_hour").agg(
        boot_opp_72h=("opp_72h", "mean"), boot_opp_72h_sd=("opp_72h", "std"),
        boot_opp_120h=("opp_120h", "mean"), boot_median_R=("median_R", "mean"),
    ).reset_index()

    merged = real.merge(bagg, on="ref_hour", how="left")
    merged["excess_72h"] = merged["opp_72h"] - merged["boot_opp_72h"]
    merged.to_csv(outdir / "reference_hour_sweep.csv", index=False)

    print(f"\n{bs.describe()}\n")
    print("Opposite-2.0 within 72h, by reference hour (NY)")
    print("hour  n     medR   R/daily  first%  REAL_72h  BOOT_72h  excess")
    print("-" * 66)
    for r in merged.itertuples():
        star = "  <<< 9PM" if r.ref_hour == 21 else ("  <<< 9AM" if r.ref_hour == 9 else "")
        print(f"{r.ref_hour:>4}  {r.n_refs:<5} {r.median_R:>6.1f} {r.R_over_daily:>7.3f} "
              f"{r.first_touch_rate:>7.2f} {r.opp_72h:>9.3f} {r.boot_opp_72h:>9.3f} "
              f"{r.excess_72h:>+7.3f}{star}")

    # Rank 21:00 against the field on both the raw rate and the bootstrap excess.
    for col in ("opp_72h", "excess_72h"):
        order = merged.sort_values(col, ascending=False).reset_index(drop=True)
        rank = int(order.index[order["ref_hour"] == 21][0]) + 1
        print(f"\n21:00 rank on {col}: {rank} of {len(order)}   "
              f"(top: hours {list(order['ref_hour'].head(4))})")

    c = merged[["median_R", "opp_72h"]].corr().iloc[0, 1]
    print(f"\ncorr(median_R, opp_72h) across hours = {c:.3f}")
    print(f"wrote {outdir}/reference_hour_sweep.csv")


if __name__ == "__main__":
    main()
