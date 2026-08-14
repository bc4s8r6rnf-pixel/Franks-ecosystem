"""Full research pipeline.

Runs every question in the brief against one dataset and writes the results to
``--out``. Point it at real NQ bars:

    python3 scripts/run_research.py --csv data/nq_1m.csv --tz UTC

or run it on a synthetic null to see what each number looks like with no
phenomenon present (this is the calibration every real result is read against):

    python3 scripts/run_research.py --simulate --days 900
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
from nqproj import data as D
from nqproj import metrics as M
from nqproj import nullmodel, projections as P, strategy as ST
from nqproj import swings as S

SWING_DEFS = [("atr", 3.0), ("atr", 5.0), ("pct", 0.75), ("refrange", 3.0)]


def placebo_points(bs: D.BarSet, n: int, seed: int = 7) -> pd.DataFrame:
    """Random real (time, price) points -- the baseline 'ordinary location'."""
    rng = np.random.default_rng(seed)
    b = bs.bars
    idx = rng.choice(len(b), size=min(n, len(b)), replace=False)
    return pd.DataFrame({"time": b.index[idx], "price": b["close"].to_numpy()[idx]})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    ap.add_argument("--tz", default="UTC", help="timezone the CSV timestamps are written in")
    ap.add_argument("--date-col")
    ap.add_argument("--time-col")
    ap.add_argument("--simulate", action="store_true")
    ap.add_argument("--days", type=int, default=900)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-age-days", type=float, default=10.0)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "out"))
    args = ap.parse_args()

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    report: dict = {}

    # ---- data ------------------------------------------------------------
    if args.simulate:
        bs = nullmodel.simulate(days=args.days, seed=args.seed,
                                vol_seasonality=0.8, df_t=4.0, drift_annual=0.10)
        report["source"] = f"SYNTHETIC NULL (days={args.days}, seed={args.seed})"
    elif args.csv:
        bs = D.load_csv(args.csv, source_tz=args.tz, date_col=args.date_col, time_col=args.time_col)
        report["source"] = f"{args.csv} (tz={args.tz})"
    else:
        ap.error("pass --csv or --simulate")

    print(bs.describe())
    report["dataset"] = bs.describe()
    dq = D.data_quality_report(bs)
    report["data_quality"] = {
        "span_days": dq.attrs["span_days"], "bars": dq.attrs["bars"],
        "gaps_over_2h": dq.attrs["gaps_over_2h"], "gaps_over_24h": dq.attrs["gaps_over_24h"],
        "hours": dq.to_dict("records"),
    }
    print(dq.to_string(index=False))

    # ---- projection map --------------------------------------------------
    refs = P.build_reference_candles(bs)
    zones = P.build_zones(refs)
    path = P.PathIndex.from_barset(bs)
    touches = P.resolve_first_touches(zones, path, max_age_days=args.max_age_days)
    report["reference_candles"] = {"total": int(len(refs)),
                                   **refs["kind"].value_counts().to_dict()}
    print(f"\nreference candles: {len(refs)}   zones: {len(zones)}")

    # ---- Q8: opposite-2.0 -------------------------------------------------
    opp = A.opposite_zone_test(refs, path, k=2.0, windows_hours=(24.0, 72.0, 120.0))
    opp.to_csv(outdir / "opposite_test.csv", index=False)
    report["opposite_2.0"] = A.summarise_opposite_test(opp)
    for kind in ("9PM", "9AM"):
        sub = opp[(opp["kind"] == kind)]
        report[f"opposite_2.0_{kind}"] = A.summarise_opposite_test(sub)
    print("\n-- opposite-2.0 --")
    print(json.dumps(report["opposite_2.0"], indent=1, default=str))

    # ---- touch rates by ladder step --------------------------------------
    tr = touches.groupby("k")["touched"].agg(["mean", "size"]).reset_index()
    tr.to_csv(outdir / "touch_rates.csv", index=False)
    report["touch_rate_by_k"] = tr.to_dict("records")

    # ---- Q13: waypoint vs terminal ---------------------------------------
    beh = A.touch_behaviour(touches, path, forward_hours=48.0)
    beh.to_csv(outdir / "touch_behaviour.csv", index=False)
    if not beh.empty:
        report["behaviour_overall"] = {
            "n": int(len(beh)),
            "terminal_1R_rate": float(beh["terminal_1R"].mean()),
            "terminal_2R_rate": float(beh["terminal_2R"].mean()),
            "median_penetration_R": float(beh["max_penetration_R"].median()),
            "share_penetrating_over_0.5R": float((beh["max_penetration_R"] > 0.5).mean()),
        }
        for by in ("ny_hour", "k", "kind"):
            A.behaviour_by_bucket(beh, by).to_csv(outdir / f"behaviour_by_{by}.csv", index=False)
        print("\n-- terminal vs waypoint --")
        print(json.dumps(report["behaviour_overall"], indent=1))

    # ---- Q12: major swings, several definitions --------------------------
    all_sw = {}
    for mode, k in SWING_DEFS:
        sw = S.detect_swings(bs, mode=mode, k=k, refs=refs)
        if sw.empty:
            continue
        sw = S.label_major(sw, refs, bs)
        all_sw[f"{mode}_{k:g}"] = sw
    report["swing_counts"] = {n: int(len(s)) for n, s in all_sw.items()}
    print("\n-- swings --", report["swing_counts"])

    # ---- Q10/Q11: extensions and confluence at major extremes ------------
    ext_summary, conf_summary = {}, {}
    for name, sw in all_sw.items():
        major = sw[sw.get("major_ge_3R", False)] if "major_ge_3R" in sw else sw
        if len(major) < 20:
            continue
        real = A.extension_at_extremes(major, refs, max_age_days=args.max_age_days, anchor_offset=0)
        plac = pd.concat(
            [A.extension_at_extremes(major, refs, max_age_days=args.max_age_days, anchor_offset=o)
             for o in (-7, -5, 5, 7)],
            ignore_index=True,
        )
        if real.empty or plac.empty:
            continue
        clus = A.extension_clustering(real, plac)
        clus.to_csv(outdir / f"extension_clustering_{name}.csv", index=False)
        ext_summary[name] = {
            "n_major_swings": int(len(major)),
            "real_entropy": clus.attrs.get("real_entropy"),
            "placebo_entropy": clus.attrs.get("placebo_entropy"),
            "max_ratio": float(clus["ratio"].max()) if clus["ratio"].notna().any() else None,
            "ratios": {float(r.ladder_k): (None if not np.isfinite(r.ratio) else float(r.ratio))
                       for r in clus.itertuples()},
        }

        pts = pd.DataFrame({"time": pd.to_datetime(major["end_time"]),
                            "price": major["end_price"].to_numpy(float)})
        cr = A.confluence_at_prices(pts, zones, max_age_days=args.max_age_days)
        cp = A.confluence_at_prices(placebo_points(bs, len(pts)), zones, max_age_days=args.max_age_days)
        if not cr.empty and not cp.empty:
            lift = A.confluence_lift(cr, cp)
            lift.to_csv(outdir / f"confluence_{name}.csv", index=False)
            conf_summary[name] = {
                "lift_by_band": lift.to_dict("records"),
                "real_median_nearest_R": lift.attrs.get("real_median_nearest"),
                "placebo_median_nearest_R": lift.attrs.get("placebo_median_nearest"),
            }

        tod = A.time_of_day_profile(pd.to_datetime(major["end_time"]), bs.bars.index)
        tod.to_csv(outdir / f"time_of_day_{name}.csv", index=False)
        report.setdefault("time_of_day", {})[name] = tod.to_dict("records")

    report["extension_clustering"] = ext_summary
    report["confluence"] = conf_summary
    if ext_summary:
        print("\n-- extension clustering (real vs placebo anchors) --")
        for n, v in ext_summary.items():
            print(f"  {n}: entropy real={v['real_entropy']:.3f} placebo={v['placebo_entropy']:.3f} "
                  f"max ladder ratio={v['max_ratio']}")
    if conf_summary:
        print("\n-- confluence lift at major extremes --")
        for n, v in conf_summary.items():
            print(f"  {n}: " + ", ".join(
                f"{d['band_R']}R lift={d['lift']:.2f}" for d in v["lift_by_band"]))

    # ---- Q9: network transitions -----------------------------------------
    seq = A.touch_sequence(touches)
    trans = A.transition_stats(seq)
    if not trans.empty:
        trans.to_csv(outdir / "transitions.csv", index=False)
        report["transitions"] = trans.to_dict("records")
        print("\n-- network transitions --")
        print(trans.to_string(index=False))

    # ---- Q14/15: strategy -------------------------------------------------
    grid = [ST.Params(max_pen_R=mp, max_hours_beyond=hb, entry_k_min=2.0)
            for mp in (0.75, 1.5, 3.0) for hb in (6.0, 12.0, 24.0)]
    base = ST.run(touches, zones, path, ST.Params())
    if not base.empty:
        base.to_csv(outdir / "trades_insample.csv", index=False)
        report["strategy_all_data"] = M.summarise(base)
        report["strategy_slippage"] = M.slippage_curve(base).to_dict("records")
        by_year = M.by_period(base)
        if not by_year.empty:
            by_year.to_csv(outdir / "trades_by_year.csv")
            report["strategy_by_year"] = by_year.reset_index().to_dict("records")
        print("\n-- strategy (all data, single parameter set) --")
        print(json.dumps(report["strategy_all_data"], indent=1, default=str))

    wf = ST.walk_forward(touches, zones, path, grid)
    if not wf.empty:
        wf.to_csv(outdir / "trades_walkforward.csv", index=False)
        report["strategy_walkforward_oos"] = M.summarise(wf)
        report["strategy_walkforward_slippage"] = M.slippage_curve(wf).to_dict("records")
        print("\n-- strategy (walk-forward, OUT OF SAMPLE ONLY) --")
        print(json.dumps(report["strategy_walkforward_oos"], indent=1, default=str))
    else:
        report["strategy_walkforward_oos"] = {"trades": 0}

    (outdir / "report.json").write_text(json.dumps(report, indent=2, default=str))
    print(f"\nwrote {outdir}/report.json and supporting CSVs")


if __name__ == "__main__":
    main()
