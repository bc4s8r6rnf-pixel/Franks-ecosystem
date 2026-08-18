#!/usr/bin/env python3
"""
Expectancy model for VolatilityScalper - what the EA's defaults imply.

This is NOT a backtest and NOT a prediction. It takes the EA's configured
geometry (which is known exactly) and combines it with an assumed outcome
distribution (which is not known at all) to show what the result would be if
the strategy hit those rates.

The geometry is fact. The hit rates are the guess. The point of the tool is to
show how violently the answer swings on that guess, so the number you care
about is identified before you spend a week backtesting.

Usage:
    python3 tools/expectancy_model.py
    python3 tools/expectancy_model.py --atr 6 --cost 1.2 --loss-rate 0.20
"""

import argparse


def batch_outcomes(atr, cost, stop_atr, tp1_atr, tp2_atr, legs, tp1_legs):
    """
    Net pips for each way a batch can end, expressed in 'leg-pips'
    (one leg moving one pip). Every leg is assumed to fill, which is
    conservative on cost and optimistic on the deep legs' fill price.
    """
    stop = stop_atr * atr
    tp1 = tp1_atr * atr
    tp2 = tp2_atr * atr
    runners = legs - tp1_legs
    total_cost = legs * cost

    return {
        # Early legs bank, runner reaches the far target.
        "full_win": tp1_legs * tp1 + runners * tp2 - total_cost,
        # Early legs bank, runner gets stopped at break-even. This is the
        # outcome the design is built around - it is a win, just a small one.
        "partial": tp1_legs * tp1 + runners * 0.0 - total_cost,
        # Stopped out before TP1 is reached. Every leg takes the full stop.
        "full_loss": -legs * stop - total_cost,
        # Time stop fires: flat-ish exit, but the spread was still paid.
        "time_scratch": -legs * (0.15 * stop) - total_cost,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--atr", type=float, default=5.0,
                    help="ATR(14) on the zone TF in pips, during hours the gates allow (default 5)")
    ap.add_argument("--cost", type=float, default=1.5,
                    help="All-in round-turn cost per leg in pips (default 1.5)")
    ap.add_argument("--batches-per-day", type=float, default=5.0)
    ap.add_argument("--days-per-month", type=float, default=21.0)
    ap.add_argument("--risk-pct", type=float, default=0.75,
                    help="InpRiskPercent - risk per batch (default 0.75)")
    # EA defaults
    ap.add_argument("--stop-atr", type=float, default=1.30)
    ap.add_argument("--tp1-atr", type=float, default=1.00)
    ap.add_argument("--tp2-atr", type=float, default=2.50)
    ap.add_argument("--legs", type=int, default=3)
    ap.add_argument("--tp1-legs", type=int, default=2)
    # The assumed distribution
    ap.add_argument("--full-win-rate", type=float, default=0.25)
    ap.add_argument("--partial-rate", type=float, default=0.35)
    ap.add_argument("--loss-rate", type=float, default=0.25)
    a = ap.parse_args()

    scratch_rate = 1.0 - a.full_win_rate - a.partial_rate - a.loss_rate
    if scratch_rate < -1e-9:
        raise SystemExit("full-win + partial + loss rates exceed 1.0")

    o = batch_outcomes(a.atr, a.cost, a.stop_atr, a.tp1_atr, a.tp2_atr,
                       a.legs, a.tp1_legs)

    print("=" * 70)
    print("VolatilityScalper - expectancy model (NOT a backtest)")
    print("=" * 70)
    print("\nGEOMETRY (from the EA's defaults - this part is exact)")
    print("  ATR assumed            %.1f pips" % a.atr)
    print("  stop   %.2f x ATR  =   %.1f pips" % (a.stop_atr, a.stop_atr * a.atr))
    print("  TP1    %.2f x ATR  =   %.1f pips   x %d legs" % (a.tp1_atr, a.tp1_atr * a.atr, a.tp1_legs))
    print("  TP2    %.2f x ATR  =   %.1f pips   x %d legs" % (a.tp2_atr, a.tp2_atr * a.atr, a.legs - a.tp1_legs))
    print("  cost   %.2f pips/leg = %.1f pips per batch" % (a.cost, a.cost * a.legs))

    print("\nOUTCOME VALUES (net leg-pips per batch)")
    for k, label in (("full_win", "full winner  (TP1 legs + runner to TP2)"),
                     ("partial", "partial      (TP1 legs, runner to BE)"),
                     ("full_loss", "full loss    (stopped before TP1)"),
                     ("time_scratch", "time scratch (flattened flat-ish)")):
        print("  %-42s %+7.1f" % (label, o[k]))

    print("\nASSUMED DISTRIBUTION (this is the guess, not a measurement)")
    dist = (("full_win", a.full_win_rate), ("partial", a.partial_rate),
            ("full_loss", a.loss_rate), ("time_scratch", scratch_rate))
    for k, p in dist:
        print("  %-14s %5.1f%%" % (k, 100 * p))
    print("  -> headline 'win rate' (full + partial) = %.0f%%"
          % (100 * (a.full_win_rate + a.partial_rate)))

    exp = sum(o[k] * p for k, p in dist)
    # The EA sizes so a full stop-out of the batch equals risk_pct of equity.
    pct_per_legpip = a.risk_pct / (a.legs * a.stop_atr * a.atr)
    exp_pct = exp * pct_per_legpip
    monthly = exp_pct * a.batches_per_day * a.days_per_month

    print("\nRESULT")
    print("  expectancy       %+.2f leg-pips per batch" % exp)
    print("  as %% of equity    %+.4f%% per batch" % exp_pct)
    print("  %.1f batches/day, %.0f days -> %+.1f%% per month"
          % (a.batches_per_day, a.days_per_month, monthly))

    print("\nSENSITIVITY - the full-loss rate is what decides it")
    print("  (full-win and partial held at %.0f%% / %.0f%%, remainder is time scratch)"
          % (100 * a.full_win_rate, 100 * a.partial_rate))
    print("  %-12s %-16s %-14s %s" % ("loss rate", "leg-pips/batch", "% per batch", "% per month"))
    for lr in (0.15, 0.20, 0.22, 0.25, 0.30, 0.35):
        sr = 1.0 - a.full_win_rate - a.partial_rate - lr
        if sr < 0:
            continue
        e = (o["full_win"] * a.full_win_rate + o["partial"] * a.partial_rate +
             o["full_loss"] * lr + o["time_scratch"] * sr)
        ep = e * pct_per_legpip
        flag = "  <-- default assumption" if abs(lr - a.loss_rate) < 1e-9 else ""
        print("  %-12.0f%% %-16.2f %-14.4f %+.1f%%%s"
              % (100 * lr, e, ep, ep * a.batches_per_day * a.days_per_month, flag))

    print("\n  A 5-point move in the full-loss rate is the difference between")
    print("  a good month and a losing one. That single number - not the win")
    print("  rate, not the target size - is what a backtest needs to pin down,")
    print("  and it is precisely what the ER/volatility filters exist to move.")
    print()


if __name__ == "__main__":
    main()
