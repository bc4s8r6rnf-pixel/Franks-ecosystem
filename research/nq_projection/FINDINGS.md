# Findings — NQ 9PM projection-zone study

**Status: no real NQ data was reachable in this environment, so nothing here is a
result about Nasdaq.** What *is* here is a calibration of the study's own
statistics against null models, which turns out to settle one of the brief's
central questions without needing price data at all.

Read section 1 first. It changes what the rest of the research programme should
be aimed at.

---

## 0. The data blocker (stated plainly)

The session's egress policy denies every market-data host tried
(`query1.finance.yahoo.com`, `stooq.com`, `data.nasdaq.com`, `cmegroup.com`
— all 403 at the proxy), and GitHub access is scoped to this repository alone,
so no dataset could be pulled from elsewhere either.

Consequently **every empirical question in the brief — the swing map, the
confluence hypothesis, the network state-space, the strategy expectancy — is
unanswered.** The engine to answer them is built, tested and committed; it needs
a CSV. See `README.md` for the exact data contract.

I have not estimated, inferred, or filled in any of those numbers.

---

## 1. The opposite-2.0 statistic is fully explained by a random walk

This is the most important finding available, and it is a negative one.

Brief section 8 reports a strict reconstruction giving **~28% within 72 hours**
and **~36% within five days** for "first 2.0 boundary touched → paired opposite
2.0 boundary of the same candle reached".

I ran that identical reconstruction against synthetic price series that contain
**no projection phenomenon by construction** — driftless random walks on a CME
session calendar, stressed across volatility levels, fat tails, intraday
volatility seasonality, and bull drift (`scripts/run_null_study.py`, 8 reps ×
7 scenarios × 900 days).

| | 72 hours | 5 days |
|---|---|---|
| Your reconstruction | ~28% | ~36% |
| **Null model (no phenomenon)** | **25.8% ± 3.7%** | **36.5% ± 4.0%** |
| Closed-form barrier probability | 28.2% | 40.0% |

Three independent routes — your measurement, my simulation, and the analytic
first-passage probability — land on the same number.

**Why.** The paired opposite boundaries sit `(H + 2R) − (L − 2R) = 5R` apart.
For a driftless Brownian path the expected 1-hour range is `σ_h·√(8/π) ≈ 1.60σ_h`,
so 5R ≈ **8σ_h**. Reaching a barrier 8σ_h away inside ~55 tradeable hours has
probability `2Φ(−8/√55) ≈ 0.28`. The statistic is a restatement of how far
eight standard deviations is — the reference candle contributes nothing.

**Conclusion.** The correction in section 8 was right, and its implication is
stronger than the brief allows for. This is not evidence that the phenomenon is
"a different pairing" or "a rotation to another candle's zone". It is a number
with **no signal in it at all**. The 60–70% figure was the thing worth chasing;
28% is the null. Any replacement hypothesis has to be tested against these
baselines, not against zero.

---

## 2. Null baselines for the other headline observations

Same synthetic nulls, same code path. These are the floors real data must clear.
Several of the brief's "preliminary observations" sit at or below them.

| Statistic | Null value (no phenomenon) | What it means for the brief |
|---|---|---|
| 2.0 zone touched within 10 days | **74%** | "Price frequently reaches these zones" is not evidence of anything. Noise does this. |
| 2.5 zone touched | 70% | as above |
| 3.0 / 4.0 / 5.0 touched | 65% / 56% / 49% | the ladder is reached routinely on noise |
| Median penetration beyond the touched level | **2.2–2.6 R** | **Directly confirms your section-7 warning, and explains it**: "price frequently exceeds 2.5 substantially before reversing" is a property of random walks. Entry at 2.0–2.5 with a stop beyond 2.5 is structurally wrong *because the level has no holding power*, not because the stop is slightly too tight. |
| Reclaim of the level within 48h | **~100%** | A reclaim on its own carries no information whatsoever. The failed-expansion idea only survives if the *speed* and *penetration depth* qualifiers do the work — untested. |
| "Terminal zone" rate (reversal ≥1R after penetration ≤0.5R) | **11%** | Real data must beat 11% for a terminal/waypoint distinction to exist. |
| Confluence lift at major swing extremes vs random price points | **1.03–1.14×** | The confluence hypothesis needs to clear ~1.15× before it is distinguishable from noise. |
| Extension clustering at ladder values vs placebo anchors | ratio up to **1.15×**, entropy identical | Apparent clustering at 2.0/2.5/3.0 arises at this magnitude with no phenomenon present. |

### The 9AM / 9PM asymmetry can be manufactured by volatility alone

Under the null **with intraday volatility seasonality switched on**, the two
reference candles diverge with no phenomenon present:

- 9PM opposite-2.0 rate: **25.8%**
- 9AM opposite-2.0 rate: **17.6%**

The 9AM candle sits in a higher-volatility window, so its R is larger relative to
subsequent movement, and its projections are proportionally harder to reach. The
brief is right that 9AM and 9PM should not be assumed interchangeable — but an
observed difference between them is **not** evidence of different behaviour until
it is compared against a seasonality-matched null. This engine does that
comparison automatically.

---

## 3. The strategy engine does not manufacture edge on noise

Sanity check, not a result: the section-14 state machine
(destination → expansion → failure → reclaim → enter → stop beyond extreme →
target from the network) run over synthetic random-walk data returns
**profit factor 0.86, average −0.11R over 2,514 trades**.

That is the correct outcome. An engine that showed positive expectancy on a
driftless random walk would have a lookahead bug. This one doesn't.

---

## 4. What this implies for the research programme

Three suggestions, offered as conclusions from the calibration rather than
instructions:

1. **Retire the opposite-zone hypothesis in its current form.** Not "look for a
   different pairing" — the measurement itself has no discriminating power at
   these distances and horizons.

2. **Every future claim needs its null attached.** Touch rates, penetration
   depths, reclaim rates and confluence counts are all high on pure noise. The
   pipeline computes the null alongside the real number for exactly this reason;
   `--simulate` and `bootstrap_from_real` exist so the comparison is one command.

3. **The most promising untested item is the *conditional* one.** Everything
   unconditional in the brief is at or near its null. What has not been tested —
   and cannot be, without data — is whether penetration depth, reclaim *speed*,
   and time-of-day jointly separate the 11% terminal cases from the 89%
   waypoints. That is where any real edge would have to live, and it is the
   first thing this engine should be pointed at when data arrives.

---

## Reproducing

```bash
cd research/nq_projection
python3 tests/test_core.py                       # 7 correctness tests
python3 scripts/run_null_study.py --reps 8       # the section-1 table
python3 scripts/run_research.py --simulate       # full pipeline, null baselines
```

Outputs land in `out/`. Raw per-replication figures are in
`out/null_study_raw.csv`.
