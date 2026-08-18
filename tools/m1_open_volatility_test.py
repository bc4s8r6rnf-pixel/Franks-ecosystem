#!/usr/bin/env python3
"""
Test the "trade every M1 candle's opening volatility" idea on real data.

The strategy under test, exactly as specified:
  - At each M1 candle open, wait for price to move `trigger` pips off the open
  - Enter in that direction
  - Stop goes behind the candle open (+ a buffer)
  - Take profit `tp` pips from entry, meant to fill before the candle can flip
  - Anything unresolved by the candle close is flattened at the close

It reports the strategy's measured expectancy against two reference points:
the random-walk baseline (what you'd get with no edge at all) and the win rate
you actually need to break even after costs.

Stdlib only - no pip install needed.

USAGE
  python3 tools/m1_open_volatility_test.py bars.csv --pip 0.0001 --cost 1.5

GETTING THE DATA (MetaTrader 5)
  View > Symbols > select symbol > Bars tab > set M1 and a date range > Export.
  Any CSV with date/time/open/high/low/close columns works; the parser sniffs
  the delimiter and header format.

A NOTE ON HONESTY
  OHLC bars do not record the ORDER in which the high and low were made. For
  this strategy that ambiguity is unavoidable and material: entry, stop and
  target can all occur inside a single candle. Rather than pick the flattering
  assumption (which is how this class of idea gets "proven" profitable), every
  ambiguous candle is scored twice - once assuming the worst ordering, once the
  best - and the report brackets the truth between them. Real tick data closes
  the gap; the bracket tells you whether it is worth obtaining.
"""

import argparse
import csv
import math
import statistics
import sys
from collections import defaultdict

WIN, LOSS, SCRATCH = "win", "loss", "scratch"


def sniff_and_load(path):
    """Parse an MT5 or generic OHLC export into (datetime_str, o, h, l, c) rows."""
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        sample = fh.read(8192)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters="\t,;")
            delim = dialect.delimiter
        except csv.Error:
            delim = "\t" if "\t" in sample else ","
        rows = [r for r in csv.reader(fh, delimiter=delim) if r]

    if not rows:
        sys.exit("No rows found in %s" % path)

    header, start = None, 0
    first = [c.strip().lower().strip("<>") for c in rows[0]]
    if any(not _is_number(c) for c in rows[0][:2]) and "open" in " ".join(first):
        header, start = first, 1

    if header:
        idx = {}
        for name in ("date", "time", "open", "high", "low", "close"):
            if name in header:
                idx[name] = header.index(name)
        if not {"open", "high", "low", "close"} <= set(idx):
            sys.exit("Could not find open/high/low/close columns in header: %s" % header)
    else:
        # Positional fallback: [date, time, o, h, l, c] or [datetime, o, h, l, c]
        ncol = len(rows[0])
        if ncol >= 6 and not _is_number(rows[0][1]):
            idx = {"date": 0, "time": 1, "open": 2, "high": 3, "low": 4, "close": 5}
        elif ncol >= 5:
            idx = {"date": 0, "open": 1, "high": 2, "low": 3, "close": 4}
        else:
            sys.exit("Unrecognised CSV layout (%d columns)" % ncol)

    out = []
    for r in rows[start:]:
        try:
            stamp = r[idx["date"]]
            if "time" in idx:
                stamp += " " + r[idx["time"]]
            bar = (
                stamp,
                float(r[idx["open"]]),
                float(r[idx["high"]]),
                float(r[idx["low"]]),
                float(r[idx["close"]]),
            )
        except (ValueError, IndexError):
            continue
        out.append(bar)

    if not out:
        sys.exit("Parsed 0 usable bars from %s" % path)
    return out


def _is_number(s):
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False


def hour_of(stamp):
    """Best-effort hour extraction; returns None if the stamp has no time part."""
    for token in stamp.replace("T", " ").split():
        if ":" in token:
            try:
                return int(token.split(":")[0])
            except ValueError:
                return None
    return None


def simulate(bars, pip, trigger, buffer_, tp, cost, pessimistic):
    """
    Walk the bars and score each trade.

    `pessimistic` selects how ambiguous candles resolve. When both the target and
    the stop are reachable inside one candle, OHLC cannot say which came first;
    pessimistic=True calls it a loss, pessimistic=False calls it a win. The same
    switch resolves which side triggered first when the candle moved `trigger`
    pips both ways off the open.
    """
    results = []
    for stamp, o, h, l, c in bars:
        trig = trigger * pip
        up_fired = h >= o + trig
        dn_fired = l <= o - trig
        if not (up_fired or dn_fired):
            continue

        if up_fired and dn_fired:
            # Both sides triggered - ordering unknown. Under the pessimistic
            # reading we take the side that then reversed through its stop.
            direction = -1 if pessimistic else 1
        else:
            direction = 1 if up_fired else -1

        if direction > 0:
            entry = o + trig
            stop = o - buffer_ * pip
            target = entry + tp * pip
            hit_tp = h >= target
            hit_sl = l <= stop
        else:
            entry = o - trig
            stop = o + buffer_ * pip
            target = entry - tp * pip
            hit_tp = l <= target
            hit_sl = h >= stop

        if hit_tp and hit_sl:
            outcome = LOSS if pessimistic else WIN
        elif hit_tp:
            outcome = WIN
        elif hit_sl:
            outcome = LOSS
        else:
            outcome = SCRATCH

        if outcome == WIN:
            gross = tp
        elif outcome == LOSS:
            gross = -(trigger + buffer_)
        else:
            gross = direction * (c - entry) / pip

        results.append((stamp, outcome, gross, gross - cost))
    return results


def report(results, bars, pip, trigger, buffer_, tp, cost, label):
    if not results:
        print("  %s: no trades triggered" % label)
        return None

    n = len(results)
    wins = sum(1 for r in results if r[1] == WIN)
    losses = sum(1 for r in results if r[1] == LOSS)
    scratches = n - wins - losses
    gross = sum(r[2] for r in results)
    net = sum(r[3] for r in results)

    print("  %s" % label)
    print("    trades              %d" % n)
    print("    win / loss / scratch  %d / %d / %d   (%.1f%% win)"
          % (wins, losses, scratches, 100.0 * wins / n))
    print("    gross expectancy    %+.3f pips/trade" % (gross / n))
    print("    net expectancy      %+.3f pips/trade   (after %.2f pip cost)"
          % (net / n, cost))
    print("    total net           %+.1f pips over the sample" % net)
    return net / n


def main():
    ap = argparse.ArgumentParser(
        description="Test the every-M1-candle opening-volatility scalp on real bars.")
    ap.add_argument("csv", help="M1 OHLC export")
    ap.add_argument("--pip", type=float, default=0.0001,
                    help="Price change of one pip (0.0001 majors, 0.01 JPY, default 0.0001)")
    ap.add_argument("--cost", type=float, default=1.5,
                    help="All-in round-turn cost in pips: spread + commission (default 1.5)")
    ap.add_argument("--trigger", type=float, default=1.0,
                    help="Pips off the open that count as 'first directional move' (default 1.0)")
    ap.add_argument("--buffer", type=float, default=0.5,
                    help="Pips beyond the candle open for the stop (default 0.5)")
    ap.add_argument("--tp", type=float, default=2.0,
                    help="Take profit in pips from entry (default 2.0)")
    args = ap.parse_args()

    bars = sniff_and_load(args.csv)
    pip = args.pip

    print("=" * 72)
    print("M1 OPENING-VOLATILITY SCALP - measured on %d bars" % len(bars))
    print("  %s  ->  %s" % (bars[0][0], bars[-1][0]))
    print("=" * 72)

    # ---- 1. Is there actually enough movement in an M1 candle? -------------
    ranges = [(h - l) / pip for _, o, h, l, c in bars]
    bodies = [abs(c - o) / pip for _, o, h, l, c in bars]
    print("\n1. CANDLE SIZE - is there room to scalp?")
    print("   median M1 range     %.2f pips" % statistics.median(ranges))
    print("   mean M1 range       %.2f pips" % statistics.fmean(ranges))
    print("   median M1 body      %.2f pips" % statistics.median(bodies))
    over = 100.0 * sum(1 for r in ranges if r >= 20) / len(ranges)
    print("   candles >= 20 pips  %.2f%%   (a 20-pip range is '10 pips each way')" % over)

    by_hour = defaultdict(list)
    for (stamp, o, h, l, c), rng in zip(bars, ranges):
        hr = hour_of(stamp)
        if hr is not None:
            by_hour[hr].append(rng)
    if by_hour:
        print("\n   median range by hour (server time):")
        for hr in sorted(by_hour):
            vals = by_hour[hr]
            bar = "#" * int(round(statistics.median(vals) * 4))
            print("     %02d:00  %5.2f pips  %s" % (hr, statistics.median(vals), bar))

    # ---- 2. Does a directional move continue or revert? --------------------
    rets = [(bars[i][4] - bars[i - 1][4]) / pip for i in range(1, len(bars))]
    if len(rets) > 2:
        m = statistics.fmean(rets)
        num = sum((rets[i] - m) * (rets[i - 1] - m) for i in range(1, len(rets)))
        den = sum((r - m) ** 2 for r in rets)
        rho = num / den if den else 0.0
        follow = statistics.fmean(
            [abs(rets[i]) * (1 if rets[i] * rets[i - 1] > 0 else -1)
             for i in range(1, len(rets))])
        print("\n2. DOES THE MOVE CONTINUE? - the premise of the strategy")
        print("   lag-1 autocorrelation of M1 returns   %+.4f" % rho)
        print("     (positive = momentum continues, negative = it reverts)")
        print("   'follow last candle' gross edge       %+.3f pips/trade" % follow)
        print("   'follow last candle' net edge         %+.3f pips/trade" % (follow - args.cost))

    # ---- 3. The strategy itself, bracketed -------------------------------
    span = args.tp + args.trigger + args.buffer
    print("\n3. THE STRATEGY  (trigger %.1f / stop-behind-open %.1f / tp %.1f pips)"
          % (args.trigger, args.trigger + args.buffer, args.tp))
    pess = simulate(bars, pip, args.trigger, args.buffer, args.tp, args.cost, True)
    opt = simulate(bars, pip, args.trigger, args.buffer, args.tp, args.cost, False)
    lo = report(pess, bars, pip, args.trigger, args.buffer, args.tp, args.cost,
                "pessimistic ordering (ambiguous candles = loss)")
    print()
    hi = report(opt, bars, pip, args.trigger, args.buffer, args.tp, args.cost,
                "optimistic ordering (ambiguous candles = win)")

    if lo is not None and hi is not None:
        print("\n   >> true value lies between %+.3f and %+.3f pips/trade" % (lo, hi))
        if hi < 0:
            print("   >> NEGATIVE even under the most flattering assumption.")
        elif lo < 0:
            print("   >> Sign is undetermined by OHLC alone - needs tick data to settle.")

    # ---- 4. The edge requirement ------------------------------------------
    sl = args.trigger + args.buffer
    p_rw = sl / (args.tp + sl)
    p_be = (sl + args.cost) / (args.tp + sl)
    print("\n4. THE EDGE YOU MUST SUPPLY")
    print("   random-walk win rate       %.1f%%   (no edge, no costs)" % (100 * p_rw))
    print("   break-even win rate        %.1f%%   (after %.2f pip cost)" % (100 * p_be, args.cost))
    print("   directional edge required  %.1f percentage points" % (100 * (p_be - p_rw)))
    print("   (this equals cost / (tp + sl) = %.2f / %.2f)" % (args.cost, args.tp + sl))

    print("\n   same requirement at other trade sizes:")
    print("     %-14s %-10s %-10s %s" % ("tp/sl (pips)", "span", "rand win", "edge needed"))
    for t, s in ((2, 1.5), (4, 4), (8, 12), (15, 10), (20, 20), (50, 50)):
        print("     %-14s %-10.1f %-10.1f %.1f pts"
              % ("%g / %g" % (t, s), t + s, 100 * s / (t + s), 100 * args.cost / (t + s)))
    print("\n   Tighter trades need MORE edge, not less: the requirement is")
    print("   cost/(tp+sl), so shrinking the trade inflates it. Note that time")
    print("   never enters the formula - a target filling 'too fast for the")
    print("   candle to flip' does not change the arithmetic.")

    # ---- 5. Cost budget ---------------------------------------------------
    triggered = len(pess)
    rate = triggered / len(bars)
    per_day = rate * 1440
    print("\n5. COST BUDGET")
    print("   %.1f%% of candles trigger -> ~%.0f trades/day at 24h" % (100 * rate, per_day))
    print("   cost burn  ~%.0f pips/day" % (per_day * args.cost))
    daily = statistics.fmean(ranges) * 1440 / 10.0
    print("   for scale, this instrument's daily range is on the order of %.0f pips" % daily)
    print("   -> you pay roughly %.1fx the whole daily range in costs each day"
          % (per_day * args.cost / max(daily, 1e-9)))
    print()


if __name__ == "__main__":
    main()
