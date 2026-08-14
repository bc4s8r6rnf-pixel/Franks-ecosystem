# NQ projection-zone research engine

Independent quantitative investigation of the 9PM/9AM hourly-range projection
geometry on Nasdaq/NQ.

**Read [`FINDINGS.md`](FINDINGS.md) first** — it contains the one result that is
already settled (the opposite-2.0 statistic is indistinguishable from a random
walk) and the null baselines every other statistic must be read against.

No real market data was reachable in the environment this was built in, so the
empirical questions are **unanswered, not answered negatively**. Supply a CSV and
the whole study runs.

---

## Data contract

One OHLC file. Intraday granularity matters: reference candles are hourly, but
touch order, penetration depth and reclaim timing are measured on the base
timeframe, so **1-minute is strongly preferred**, 5-minute is workable, and
hourly bars will collapse most of the section-13 behaviour measurements.

Required columns (case-insensitive, common aliases accepted):

```
timestamp, open, high, low, close[, volume]
```

Or a split date/time pair via `--date-col` / `--time-col`.

**The timezone of the file's timestamps must be stated** with `--tz` — it is not
guessed. Get it wrong and every reference candle is the wrong hour, which
invalidates the entire study silently. Everything is converted to
`America/New_York` and reference candles are cut on NY wall-clock hours, so DST
is handled by the tz database rather than a fixed offset.

Coverage: the 21:00 and 09:00 NY hours must be populated. Several years is
wanted — the walk-forward needs at least train + test spans (default 2y + 1y).

```bash
python3 scripts/run_research.py --csv data/nq_1m.csv --tz UTC
```

A data-quality audit prints first (bar count, session gaps, how many days
actually have a usable 9PM and 9AM candle). Check it before reading any result.

---

## What gets computed

| Brief section | Where |
|---|---|
| 1 — projection construction (H+kR / L−kR) | `projections.build_zones` |
| 3 — persistent zones, lifespan by age | `resolve_first_touches`, `active_zones_at` |
| 5 — time of day, bucketed **and** exposure-normalised | `analysis.time_of_day_profile` |
| 8 — strict opposite-2.0 reconstruction | `analysis.opposite_zone_test` |
| 9 — network transitions between zones | `analysis.touch_sequence`, `transition_stats` |
| 10 — normalised extension distribution beyond 2.5 | `analysis.extension_at_extremes` |
| 11 — confluence vs placebo price points | `analysis.confluence_at_prices`, `confluence_lift` |
| 12 — objective major swings, four definitions | `swings.detect_swings`, `label_major` |
| 13 — penetration / reclaim / terminal vs waypoint | `analysis.touch_behaviour` |
| 14 — failed-expansion state machine | `strategy.run` |
| 15 — full risk reporting, walk-forward, slippage | `metrics`, `strategy.walk_forward` |

Honours the section-16 simplicity constraint: price, time, reference ranges,
their projections, midnight and NY open. No indicators, no ML.

## Design decisions that protect the result

- **No lookahead.** Zones activate only when their candle *closes*
  (`activate = ref_time + 1h`); `active_zones_at` filters the map to what was
  knowable at that instant; stops are placed at the extreme that had already
  printed. Tested in `tests/test_core.py`.
- **Placebo comparisons are built in, not optional.** Extension clustering is
  measured against anchor-shifted placebos, and confluence against random real
  price points, because both statistics are large on pure noise.
- **Nulls run through the identical code path.** `--simulate` and
  `nullmodel.bootstrap_from_real` feed synthetic series into the same functions,
  so a real number and its null are never computed two different ways.
- **Walk-forward reports test windows only** — parameters are selected in-sample
  per fold and the returned trades are out-of-sample by construction.
- **Speed.** Running max/min are monotone, so first touch of any level is a
  binary search; a reference candle's whole ladder shares one pass.

## Layout

```
nqproj/
  data.py         loading, NY normalisation, quality audit
  projections.py  reference candles, zone ladder, PathIndex first-touch
  swings.py       volatility-normalised zigzag, major-swing labelling
  analysis.py     the research questions
  strategy.py     failed-expansion state machine, walk-forward
  metrics.py      R-based performance reporting
  nullmodel.py    synthetic nulls + block bootstrap
scripts/
  run_research.py    full pipeline on real or synthetic data
  run_null_study.py  null calibration of the headline statistics
tests/test_core.py   correctness tests (projection maths, touch, DST, lookahead)
```

## Known limitations

- Zones are horizontal price levels; no session-VWAP or time-decay weighting.
- `transition_stats` de-duplicates touches within 1 hour, since a dense ladder
  otherwise records level spacing rather than genuine rotations. The window is
  a judgement call and results should be checked for sensitivity to it.
- The strategy takes one position at a time and assumes fills at the level;
  `metrics.slippage_curve` is the honest check on that.
- Contract rollover is not handled — supply a continuous back-adjusted series,
  or expect artefacts at roll dates.
