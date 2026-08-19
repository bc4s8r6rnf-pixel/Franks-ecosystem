# 9pm Anchor-Candle Deviation Zones — finding the real sequence

## Why this exists

The observation: the 21:00 (9pm) H1 candle sets a range. Deviation zones are
projected above and below it (2.0–2.5×). Price then spends the next session
working between them. Sometimes both zones get tapped in a day; sometimes one
side goes and the other waits until tomorrow or the day after; and price
*seems* to travel toward whichever zone it is closest to around the New York
open.

Every one of those is a testable claim. None of them can be settled by looking
at a chart — on an H1 chart covering two months, each zone is a few pixels tall
and the candles overlap them. Reading a per-day hit sequence off a screenshot
is guesswork with a confidence problem. So this script measures it instead, on
your own broker's data, and prints the sample count next to every number.

**Run it, then read the tables below in order.** Each one either confirms a
piece of the idea or kills it.

## Running it

1. Copy `Scripts/CandleRangeZoneSequence.mq5` into `MQL5/Scripts/`, compile
   (F7) in MetaEditor.
2. Open an **H1 chart** of the symbol and scroll back far enough to load
   history — the script can only read bars the terminal actually has. A year
   of H1 is ~6,000 bars; check Tools → Options → Charts → "Max bars in chart".
3. Drag the script onto the chart. Inputs appear.
4. Set `InpServerToNYOffset` first. **Get this wrong and every table is
   garbage.** Broker GMT+3, NY on EDT (GMT−4) → NY = server − 7 → enter `-7`.
   Same convention as the EA.
5. Set `InpZoneMode` to match your RXWLES boxes (see below).
6. Run. Output goes to the Experts log, plus
   `MQL5/Files/zone_sequence_report.txt` and a per-session CSV.

To compare instruments in one pass, put them in `InpSymbols`:
`NAS100,XAUUSD,GBPUSD`. A behaviour that survives on all three is structural.
One that shows up on a single symbol is that symbol's character, or noise.

### Matching the zone geometry

"2 to 2.5 deviations" means different levels depending on the anchor the
indicator projects from. All three are supported:

| `InpZoneMode` | Upper zone | Lower zone |
|---|---|---|
| 0 `MIDPOINT` | `mid + N·R` | `mid − N·R` |
| 1 `OPPOSITE` (default) | `low + N·R` | `high − N·R` |
| 2 `BOUNDARY` | `high + N·R` | `low − N·R` |

Verify before trusting anything: open the CSV, take the first row, and compare
`u1`/`u2`/`l2`/`l1` against the boxes your indicator drew on that date. If they
don't line up, change the mode and re-run. Everything downstream depends on
this.

## Reading the output

### 1. Base rates
How often a session taps both zones, one only, or neither. This sets the
ceiling on everything else. If "neither" is large, the zones are too far out
for the current volatility regime and no entry model will save it.

### 2. Sequence — yesterday vs today
The 5×5 transition matrix. This is the "sequence" in its raw form. Read across
a row. **Any row with n < 20 is noise, not a pattern** — the script prints n so
you can see which rows you're allowed to believe.

### 3. First tap given yesterday
The row you'd actually trade off. The `skew` column is the edge over a coin
flip. Under ~5 points, there's nothing there.

### 4. Hypothesis 1 — rotation
After a one-sided day, does the *other* side go first the next day? Above ~57%
with n > 60 is a genuine edge. 45–55% means the rotation idea is a story.

### 5. Hypothesis 2 — proximity at the NY open
Does price go to the zone it was nearest at the NY reference hour? The split by
**proximity gap** is the important part: if the effect is real, accuracy should
*climb* as one zone gets relatively closer. A flat column means proximity is
not doing the work — price was simply nearer to the zone it was already heading
for, which is not a signal you can trade.

### 6. Hypothesis 3 — streak exhaustion
After N consecutive one-sided days in the same direction, does the run continue
or flip? Watch n collapse as N grows; by 3–4 days there usually isn't enough
data to conclude anything.

### 7. Timing
NY hour of the first tap. This tells you when to be at the screen, and whether
a "New York open" entry is even the right clock — if the mass of first taps
lands in the London hours, the NY entry is late by construction.

### 8. Excursion
How far price travels in deviation units, and how often the *far* edge (2.5) is
reached versus the *near* edge (2.0). If the far edge is reached materially
less often, take profit at the near edge and stop donating the difference.

### 9. Carry-forward — the important one
A zone that was never reached on its own session does not expire at the close.
It sits in the book as an untouched ("virgin") level. This table compares the
respect rate of today's fresh zone (age 0) against untouched zones from 1, 2, 3
… days ago.

**If the respect rate climbs with age, older untouched zones are the better
levels and today's fresh zone is the weaker one.** That inverts the whole
approach: you'd be trading the old zone and treating the fresh one as a
waypoint.

The follow-up table handles the specific case of *"blasted straight through
today's upper zone and respected the upper zone from two days ago"* — when a
fresh zone is blown through, how often does price then reach the next virgin
older zone, and how often is it rejected there. That is the sequence question
worth answering, because it tells you what the target is on a breakout day
instead of leaving you fading a level that was never going to hold.

## The entry models

Six rule sets, all **pre-specified** — chosen from the stated hypotheses before
seeing the results, not fitted to whatever the data happened to favour. That
distinction is the whole reason to trust the output.

| # | Rule | Entry | Target | Stop |
|---|---|---|---|---|
| 1 | NY open → nearest zone | NY ref bar open | near edge of that zone | `InpStopR` × range |
| 2 | Fade the first tap | near edge of the tapped zone | opposite zone's near edge | beyond the tapped zone's far edge |
| 3 | Nearest **and** opposite of yesterday's single side | NY ref bar open | near edge | `InpStopR` × range |
| 4 | Nearest **and** decisive proximity gap | NY ref bar open | near edge | `InpStopR` × range |
| 5 | Opposite of yesterday, ignoring proximity | NY ref bar open | near edge | `InpStopR` × range |
| 6 | Break of today's zone → old virgin zone | break of the far edge | old virgin zone's near edge | back inside today's zone |

**Model 5 is the control for model 3.** If 3 doesn't beat 5, the NY proximity
read is adding nothing and you can drop it from the process entirely. That
comparison is the single most useful line in the output.

Same-bar target-and-stop is always scored as a **loss**. H1 bars can't resolve
the order, and optimism there is how backtests lie.

Costs are not modelled. Subtract your spread and commission per trade before
believing any expectancy figure. A model showing +0.05R average is dead once
NAS100 spread is charged against it.

## Known limits

- **H1 resolution.** A single bar that tapped both zones has no readable order.
  Those sessions are flagged `ambiguous` in the CSV, the order is inferred from
  the candle's direction, and model 2 skips them outright rather than guessing.
- **DST.** `InpServerToNYOffset` is a fixed number. Across a DST change the NY
  hour drifts by one. For a long lookback, run the periods separately, or
  accept a small amount of smearing in the timing table.
- **Session definition.** Anchor candle close → `InpSessionEndHourNY` the next
  day (default 16:00 NY). Sessions with fewer than 8 bars (holidays, half
  days) and the still-running session at the right edge are dropped, so they
  can't masquerade as "neither zone reached".
- **In-sample.** Everything above is measured on the same history it's
  describing. Before sizing up, re-run on a period you didn't look at — split
  the lookback in half and check the numbers hold on the second half.

---

## The zone book — deciphering the *order*

Treating today's zone as the object of interest is almost certainly the wrong
frame. What exists at any moment is a **book of live levels**: every zone from
the last N sessions that price has never reached. Price works through that
book. "Blasted through today's upper zone and respected the one from two days
ago" isn't an anomaly — it's the book being consumed in an order that today's
zone doesn't determine.

So the real question is: **given the live book at the start of a session, what
rule selects the zone consumed first?** That's a ranking problem, and ranking
problems can be reverse-engineered.

### How the book is built

At each session start, every zone from the last `InpBookDays` sessions is
included if:

- price has **never reached its near edge** since it was created (virgin), and
- it sits **in front of** the reference price — a zone price has already passed
  is behind it, not a destination.

Each live zone carries four features:

| Feature | Meaning |
|---|---|
| **proximity** | distance to the near edge, in units of *today's* range |
| **staleness** | how many sessions old the zone is |
| **confluence** | how many live zones stack within `InpClusterTolR` of it |
| **anchor bias** | whether it's on the side the 9pm candle closed toward |

Confluence is the "connection between multiple previous days' zones" — when
day-1, day-3 and day-5 all project a level into the same band, that band is one
thick level, not three thin ones. It's counted by price only, not by side:
price doesn't care which night a level came from.

### The tables

**Book size / consumed.** How many live zones exist, how many get taken per
session. If the book is usually 1–2 deep there's no ordering problem to solve;
if it's 6–10 deep, order is everything.

**Where the first-consumed zone sat in the nearest-first ordering.** The
crux. If it's overwhelmingly rank 1, the rule is just proximity and there's
nothing more to find — stop here. If it's spread across ranks 2, 3, 4, then
something other than distance is choosing, and the rest of the output is worth
reading.

**Age and confluence of the first zone consumed.** Reported as a *rate*, not a
count — age 0 is live every session and age 9 isn't, so raw counts would lie. A
flat rate across ages means age is irrelevant. A rate that climbs with age means
the book genuinely is a queue and old untouched levels get priority.

**Rule tournament.** Eleven candidate ordering rules scored against each other
and against chance:

| Rule | The idea being tested |
|---|---|
| nearest in price | pure proximity — the null hypothesis |
| nearest, scaled by the zone's own range | proximity, volatility-adjusted per zone |
| oldest first (FIFO) | the book is a queue |
| newest first (LIFO) | fresh levels dominate |
| widest / tightest anchor candle | zone significance scales with its 9pm range |
| biggest cluster | confluence is the magnet |
| cluster first, nearest as tiebreak | confluence with a proximity tiebreak |
| side the 9pm candle closed toward | the anchor candle itself carries the bias |
| opposite side to the last consumed | rotation across the book |
| same side as the last consumed | price runs the book outward before turning |

Scored on **top-1 accuracy** (how often the rule's first pick was the zone
actually taken first) and **MRR** — mean reciprocal rank, where 1.00 means it
always ranked the winner first and 0.50 means it typically ranked it second.
The `CHANCE` row is a random pick from the same book. A rule that doesn't
clearly beat it is decoration.

**Formula search.** A weighted score over the four features:

```
score = w0·proximity + w1·staleness + w2·confluence + w3·anchor-bias
```

Weights are swept over a grid on the **first half** of history, then scored on
the **second half**, which the search never saw. Read the test column and
ignore the train column — train accuracy always looks good, that's what fitting
does.

- **Test barely above chance** → there is no stable formula; the consumption
  order is mostly path-dependent and you should trade the level-respect
  statistics instead of trying to predict which level goes first.
- **Test clearly above chance and close to train** → the weights are the thing
  you were looking for. The signs tell you the mechanism: `staleness +0.5` means
  old untouched zones get priority; `confluence +1.0` means stacked zones are
  the magnet; `proximity` near zero would mean distance barely matters, which
  would be the genuinely surprising result.

**Second zone given the first.** Whether the book gets worked outward in one
direction (same-side dominance) or ping-ponged (opposite-side dominance). This
is the "bounces between upper and lower" behaviour, measured.

### How an algorithm running this would actually behave

Worth holding in mind while reading the output, because it constrains what
results are even plausible:

- **Inventory depletion.** A level is consumed once. Anything driving price
  toward unfilled levels stops caring about them afterwards — which is why
  virgin-only is the right filter and why re-tests aren't the same event.
- **Volatility normalisation.** Distances only compare across days in units of
  range, never in raw points. A 40-point gap is far on a quiet night and
  nothing on a loud one. Every distance in this script is normalised.
- **Clustering beats recency.** If levels are magnets, thickness matters more
  than freshness — which is exactly what the confluence weight tests.
- **Path dependence.** Which zone gets hit first partly determines what's still
  live afterwards, so the book is a state machine, not a static ranking. This
  is the main reason the test-half accuracy can come in low even when the idea
  is broadly right.
