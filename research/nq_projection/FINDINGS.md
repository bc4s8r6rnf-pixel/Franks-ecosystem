# Findings — NQ 9PM projection-zone study

**Headline: the phenomenon does not survive testing.** Across 8.9 years of NQ
data, every statistic in the brief lands at, or below, what price with no
projection structure at all produces. The one number that looks like a large
edge — the 9PM opposite-2.0 rate of 53.6% against a 27.5% random-walk baseline —
is fully explained by the 21:00 candle being the quietest hour of the day, and
disappears the moment that is controlled for.

I went looking for the relationship rather than for confirmation, and this is
what the data said. Details and the exact tests below.

---

## Data

| | |
|---|---|
| Instrument | NQ, 15-minute OHLC |
| Span | 2016-11-14 → 2025-10-01 (3,241 days, 206,703 bars) |
| Reference candles | 2,272 × 9PM, 2,278 × 9AM |
| Source timezone | **EET/EEST (`Europe/Helsinki`)** — determined empirically, not assumed |

The file carried no timezone. I identified it from session structure: the CME
17:00 NY maintenance halt lands at server midnight in both US winter and summer,
which requires UTC+2/UTC+3 with DST. Validating candidates by how cleanly the
halt lands on 17:00 NY across all nine years:

| Candidate | Bars left in the 17:00 NY hour (typical hour ≈ 9,100) |
|---|---|
| **`Europe/Helsinki`** | **10** |
| `Etc/GMT-2` | 4,835 (halt smeared across two hours) |
| `Etc/GMT-3` | 4,835 |
| `UTC` | 4,835 |

`Europe/Helsinki` is correct, including the EU/US DST-divergence weeks where
fixed offsets drift by an hour. **If this is wrong, every result below is void** —
worth confirming against your broker's server time.

---

## 1. The central result: 21:00 is not special, it is just quiet

The raw numbers look encouraging at first:

| Reference | Opposite-2.0 within 72h | within 5 days |
|---|---|---|
| **9PM** | **53.6%** | 61.8% |
| 9AM | 14.2% | 21.9% |
| Random-walk null | 25.8% ± 3.7% | 36.5% ± 4.0% |

9PM at 53.6% against a 27.5% null is roughly double — apparently a strong effect,
and apparently vindication that 9PM and 9AM behave differently.

**It is neither.** The opposite boundaries sit `5R` apart, so the rate rises
mechanically as the reference range `R` shrinks relative to the volatility that
follows. The 21:00 hour has a median range of 20.7 points against 71.4 for 09:00
— it is one of the quietest hours on the instrument.

So I ran the identical test using **every hour of the day** as the reference
candle (`scripts/reference_hour_sweep.py`):

```
hour  medR   R/daily   REAL_72h        hour  medR   R/daily   REAL_72h
  23  13.5    0.081      0.669           9   71.4   0.431      0.142  <- 9AM
   0  13.5    0.081      0.664          10   70.5   0.425      0.167
  22  16.5    0.100      0.621          11   55.2   0.333      0.226
   1  17.6    0.106      0.601          15   50.0   0.302      0.250
  19  18.2    0.110      0.586          12   45.0   0.271      0.282
  21  20.7    0.125      0.536  <- 9PM   3   31.6   0.191      0.394
```

- **`corr(median_R, opp_72h) = −0.970`** across the 24 hours.
- **Reference-hour quietness alone explains R² = 0.997** of the cross-hour
  variation in the 72-hour rate.
- Fitting the rate-vs-quietness curve on the *other 22 hours* and predicting
  21:00 gives **53.9%**. Actual: **53.6%**. Residual −0.26 sd.
- 9AM: predicted 15.1%, actual 14.2%, residual −1.05 sd.
- **21:00 ranks 6th of 23 hours.** It is beaten by 23:00, 00:00, 22:00, 01:00
  and 19:00 — every quiet overnight hour.

Against a day-aligned block bootstrap (real NQ bars resampled whole-day so each
bar keeps its hour, preserving the intraday volatility profile while destroying
multi-day geometry), 21:00 shows an excess of **+3.9pp and ranks 5th of 23** —
entirely ordinary among 23 comparisons.

**Both reference candles sit precisely on the curve traced by every other hour.
Neither 9PM nor 9AM carries information beyond the size of its own range.** The
9PM/9AM difference the brief asks about is real as an observation and entirely
explained by range size, with nothing left over.

---

## 2. Everything else, against its null

| Statistic | Real | Null | Verdict |
|---|---|---|---|
| 2.0 zone touched within 10d | 73.8% | 74% | identical |
| 2.5 / 3.0 / 5.0 touched | 69.5% / 65.1% / 50.3% | 70% / 65% / 49% | identical |
| Median penetration past the level | **3.22 R** (9PM: **5.15 R**) | 2.44 R | **worse than noise** |
| Reclaim within 48h | 99.8% | ~100% | no information |
| Terminal-zone rate | **9.0%** | 11.1% | **below noise** |
| Best conditional cell (by hour / k / kind) | 11.6% | 11.1% | at noise |
| Confluence lift at major extremes | 1.01–1.05× | 1.03–1.14× | at or below noise |
| Extension clustering vs placebo anchors | entropy 4.297 | placebo 4.287 | *less* clustered than placebo |

Reading the important ones:

- **The zones have less holding power than a random walk.** Median penetration
  past a touched level is 3.22R — for 9PM zones, 5.15R. 78–88% of touches are
  pass-throughs. Your section-7 instinct that "2.5 is not a reliable hard stop"
  is correct and understated: entry at 2.0–2.5 with a stop beyond 2.5 fails
  because the level exerts no restraining influence at all.
- **A reclaim carries no information.** It happens 99.8% of the time within 48
  hours, on real data and on noise alike.
- **No confluence effect.** Independent projections clustering at a price does
  not raise reversal probability above what random price points show. Tested
  continuously in normalised distance, against placebo points, across four
  swing definitions.
- **No clustering beyond 2.5.** The normalised extension distribution of major
  swing extremes is marginally *flatter* than its placebo — the ladder values
  (2.5, 3.0, 3.5, 4.0…) have no special status.
- **The network is not sequential.** 57.7% of zone-to-zone transitions jump to a
  different reference candle and 20.4% skip ladder steps; there is no orderly
  progression through projection layers.

## 3. The strategy

The section-14 state machine (destination → expansion → failure → reclaim →
enter → stop beyond the extreme → target from the network), on all data:

- **7,019 trades, 43.5% win rate, −0.104 R average, profit factor 0.817**
- Walk-forward, out-of-sample only: 3,064 trades, **PF 0.876, −0.071 R**
- **Negative in all ten years** (PF 0.76–0.85) — not a regime problem
- Before costs. At 0.05R slippage: PF 0.741

This is a broad plateau of uniformly negative expectancy, not a near-miss
needing better parameters.

## 4. What is real, but not a projection finding

Major swing extremes do concentrate in the US morning — 10:00–11:00 NY carries
3.5× its share of market time, 06:00–09:30 carries 1.75×, while 21:00–03:00 runs
at 0.3×. This is the ordinary liquidity and volatility profile of the session. It
is not evidence for the projection map, and it is available without any of this
geometry.

---

## Honest limitations

- **15-minute bars.** Touch order, penetration depth and reclaim timing are
  resolved to 15 minutes. Finer data would sharpen section 13 but cannot rescue
  a statistic sitting exactly on its null.
- **Swing extremes are timestamped on hourly pivots**, so the 09:30–10:00 bucket
  in `time_of_day_*.csv` is structurally empty — extremes land on exact hours.
  The brief's specific interest in 09:30–10:00 needs swings detected on the 15m
  series; the reported 0 for that bucket is an artefact, not a measurement.
- **Contract rollover is not handled.** If the series is not back-adjusted,
  roll dates inject artificial gaps. This would add noise, not manufacture the
  null results above.
- Absence of evidence at this resolution is not proof of absence. But the
  effects tested are not subtle-and-buried; several point the *wrong way*.

## What I would not spend more time on

The unconditional geometry, the confluence hypothesis, and the failed-expansion
entry are all tested and negative. The conditional question I flagged as most
promising before data arrived — whether penetration depth, reclaim speed and
time-of-day jointly separate terminal zones from waypoints — is also tested: the
best cell in the entire conditional table reaches 11.6% against an 11.1% noise
baseline.

If you want to keep going, the honest next step is a different hypothesis, not a
refinement of this one. The engine is general — `REF_HOURS` takes any hour, the
ladder is configurable, and every statistic computes its own null — so testing a
new idea is cheap.

---

## Reproducing

```bash
cd research/nq_projection
python3 tests/test_core.py                                                   # 8 tests
python3 scripts/run_research.py --csv data/nq_15m.csv --tz Europe/Helsinki   # full study
python3 scripts/reference_hour_sweep.py --csv data/nq_15m.csv --tz Europe/Helsinki
python3 scripts/run_null_study.py --reps 8                                   # synthetic nulls
```

Price data is gitignored. Results land in `out/real/`; the synthetic null
baselines quoted above are committed in `out/null_study_raw.csv`.
