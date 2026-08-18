# Volatility Scalper — design spec (brand new EA, standalone)

Not built on Blxck Mirror. New file, new logic, new risk model.

Concept as stated: fire a batch of 5 small trades, close each as soon as it is in
profit, immediately re-fire the next batch at a slightly larger lot, ramping size
every winning batch. Only trade when there is volatility.

This document works through which parts of that survive contact with the numbers,
which parts have to change, and what the actual entry logic should be.

---

## 1. The two numbers that decide everything

Before any strategy discussion, two arithmetic facts constrain the design.

### 1.1 A dollar target is a pip target in disguise

GBPUSD, USD account: `1.00 lot = $10/pip`, so `0.01 lot = $0.10/pip`.

| Lot | $/pip | Move needed for $1 | Move needed for $2 |
|-----|-------|--------------------|--------------------|
| 0.01 | $0.10 | **10 pips** | **20 pips** |
| 0.05 | $0.50 | 2 pips | 4 pips |
| 0.10 | $1.00 | 1 pip | 2 pips |

So "$1–2 per trade at the smallest lot" is **not** a small price movement. It is a
10–20 pip move — a normal M15/M30 swing that takes real time and needs real
directional accuracy. The concept contains a hidden assumption that these are the
same thing; they are not.

### 1.2 Round-turn cost sets a hard floor on the target

Typical raw-spread broker, GBPUSD: spread 0.4–1.0 pip, commission ~$7 per round-turn
lot = 0.7 pip equivalent. **All-in cost ≈ 1.1–1.7 pips per trade, call it 1.5.**

| Lot | Gross target | Cost | Cost as % of target | Verdict |
|-----|--------------|------|---------------------|---------|
| 0.01 | 10 pips ($1) | 1.5 pips | 15% | workable |
| 0.05 | 2 pips ($1) | 1.5 pips | 75% | barely survives |
| 0.10 | 1 pip ($1) | 1.5 pips | **150%** | structurally impossible |

The trap: as the lot ramps up, if the **dollar** target stays at $1–2 the **pip**
target shrinks toward the spread and the strategy crosses from viable to
mathematically unwinnable without any visible change in behaviour.

> **Design rule #1: the target is defined in pips (or ATR), never in dollars.**
> Dollars are an output. Ramping lots then increases profit per batch while the
> per-trade edge stays constant.

---

## 2. "Every candle moves at least 10 pips in each direction"

This is the load-bearing premise, and it is not true at scalping timeframes.
Typical GBPUSD ranges:

| TF | Asia | London / NY |
|----|------|-------------|
| M1 | ~0.7 pip | 1.5–3 pips |
| M5 | ~2 pips | 4–7 pips |
| M15 | ~4 pips | 8–14 pips |
| M30 | ~7 pips | 12–20 pips |

A candle that travels 10 pips *both* ways is a ~20 pip range — realistically M30+
in an active session. And "10 pips in each direction" only helps if you enter at
the middle of the range, which is unknowable in advance; enter near the edge and
you get 2 pips one way and 18 the other.

> **Design rule #2: never hardcode a pip figure. Measure it.**
> Every threshold — target, stop, entry spacing, volatility gate — is expressed as
> a multiple of live ATR, so the EA self-scales across pairs, sessions and regimes.
> This also means the bot answers the "is there enough movement?" question from
> data instead of assumption.

---

## 3. The 5-trade batch: making it mean something

Five market orders on one symbol, one direction, same instant, same TP is
**mathematically identical to one trade at 5× the lot — but paying 5× the spread.**
That is a pure, guaranteed loss with no offsetting benefit.

Three ways to make a batch real. Recommended: **A + B together.**

**A. Ladder the entries (spacing).** Place the 5 as staggered limits at
`0.0 / 0.25 / 0.5 / 0.75 / 1.0 × ATR(M5)` against the entry direction. Price
pulling back fills you deeper at a better average price; price running immediately
fills only leg 1 and you still catch the move small. This turns adverse movement
into improved basis instead of pure drawdown — and it is the only version of
"5 trades" that adds anything.

**B. Stagger the exits (scale-out).** Each leg gets its own TP:
`0.75 / 1.0 / 1.5 / 2.0 / 3.0 × R`. Legs 1–2 bank almost immediately (this is the
"secure it as soon as it's green" feel the concept wants), while legs 4–5 pay for
the losing batches. Section 5 shows why this is what makes the whole thing solvent.

**C. Five uncorrelated symbols.** Sounds like diversification; mostly is not — FX
majors run 0.7–0.9 correlated, so 5 major pairs long USD is one trade with extra
commission. Only worth it across genuinely different buckets (one FX major, one
index, one metal), and it needs a correlation cap.

**One batch is one position for risk purposes.** Size the *batch* to the risk
budget, then divide by 5 — not 5 × full size.

---

## 4. Does direction matter, or is volatility enough?

This is the central question, and the arithmetic answers it cleanly.

Break-even win rate, net of 1.5 pips cost:

| TP | SL | Net win | Net loss | Win rate needed |
|----|----|---------|----------|-----------------|
| 8 | 12 | 6.5 | 13.5 | **67.5%** |
| 10 | 10 | 8.5 | 11.5 | **57.5%** |
| 15 | 10 | 13.5 | 11.5 | **46.0%** |

The "close it the instant it's green" instinct produces the top row: a tight TP
against a wider stop, needing ~**68% accuracy just to break even**. Volatility
alone is directionally symmetric — it gives you 50%, and costs take you below it.
Those missing ~18 points have to come from somewhere, and the only place they come
from is **being on the right side.**

> **Volatility is the permission filter — it decides *whether* to trade.
> Direction is the edge — it decides *which way*. You need both. Volatility
> without direction is just paying spread faster.**

The second thing that table shows: letting some of the position run (bottom row)
collapses the required win rate from 68% to 46%. That is why the scale-out ladder
in §3B is not a nicety — it is what makes the batch mathematically solvent.

And the failure mode to design against is not low volatility, it is **volatility
without persistence** — violent chop that trips stops in both directions. That is
the specific thing the regime filter below exists to detect and avoid.

---

## 5. Entry logic — EMA trend-following, volatility-gated, running 24/7

The model: **one tight EMA defines the side, price must be on that side with room to
spare, volatility decides whether the bot is live at all.** Runs continuously; the
gates decide when it actually fires.

### 5.1 The EMA stack — two EMAs, two different jobs

| Role | TF | EMA | Job |
|------|----|-----|-----|
| **Trend EMA** | M15 | EMA(100) | Directional bias. Decides which side is allowed at all |
| **Close EMA** | M1 | EMA(21) | Entry trigger. Price must be on the *far* side of it |

(Periods are starting points to be optimised, not settled values.)

The two EMAs do opposite jobs on purpose, and that is the whole idea:

- The **trend EMA** says *long only* or *short only*.
- The **close EMA** says *not yet* until price pulls back against that direction.

Both are just price levels, so mixing timeframes is fine — they get compared against
the same current price.

### 5.2 The entry condition: the sandwich zone

Bias long, and you only enter when price is **under** the close EMA — but still
**above** the trend EMA. Price sits sandwiched between them:

```
LONG:    EMA_trend  <  price  <  EMA_close        and EMA_trend rising
SHORT:   EMA_close  <  price  <  EMA_trend        and EMA_trend falling
```

That single line is the strategy. Each half does necessary work:

- `price < EMA_close` — you are buying a **pullback**, not chasing an extension.
  This is what makes the reward-to-risk work: at the pullback the stop sits maybe
  0.5 x ATR away with the swing target 1.5-2 x ATR out. The same trade chased above
  the close EMA has the same target and a 2 x ATR stop — identical thesis, roughly a
  quarter of the R:R.
- `price > EMA_trend` — the pullback is still **inside** the trend. This is the half
  that stops it being a falling-knife catcher. "Under the close EMA" on its own is
  unbounded: price could be 5 x ATR below with the trend already dead, and the
  condition still reads true.

The zone between them **is** the entry zone, and it has a genuinely useful property:
its width is the EMA separation, which widens in a strong trend and narrows as the
trend weakens. Strong trend -> wide zone -> more room to fill. Weakening trend ->
zone pinches shut -> the bot stops trading by itself, with no extra rule.

**This is exactly where the 5-order ladder belongs.** Space the 5 limits across the
sandwich zone, deepest leg near the trend EMA. A shallow pullback fills 1-2 legs; a
deep one fills all 5 at a much better average price. The batch concept and the
pullback concept fit together with nothing left over.

**Stop placement follows from the thesis:** just beyond the trend EMA (plus a
buffer). If the trend EMA breaks, the reason for the trade is gone — that is the
natural invalidation, not an arbitrary pip count.

### 5.2b Two things the EMA pair still needs

**Slope, not just order.** Price above a *flat* trend EMA is a range, and ranges are
where EMA systems get chopped up. Require real slope, ATR-normalised so it means the
same on every pair:

```
(EMA_trend[0] - EMA_trend[10]) / ATR  >  slopeThreshold      (~0.15 to start)
```

**Rejection before firing.** Price under the close EMA in an uptrend is either a
pullback or the start of the reversal, and at the moment of entry they look
identical. Do not fire on the zone alone — wait for evidence the pullback is
finishing: an M1 bar closing back up through the close EMA, or a lower wick
rejecting from the zone. Costs a pip or two of entry price and removes a large
share of the losers.

### 5.3 Volatility gate (permission to trade)

```
ATR(14, M5) > 1.2 x median(ATR(14, M5), last 5 trading days, all hours)
```

Baseline across **all hours**, not a trailing 200 bars. This matters for 24/7: a
rolling short baseline re-centres on whatever session it is in, so dead Asian hours
look "volatile relative to Asia" and the gate opens on 1-pip noise. A multi-day,
all-hours baseline keeps the threshold anchored to what is actually worth trading.

### 5.4 Regime classifier (is the volatility directional?)

ATR cannot tell expansion from chop — both raise it. Kaufman Efficiency Ratio can:

```
ER = |close[0] - close[20]| / SUM |close[i] - close[i+1]|      (20 bars, M5)
```

| ER | Regime | Action |
|----|--------|--------|
| > 0.35 | Trending expansion | **Trade** the EMA pullback model above |
| < 0.15 | Clean range | Stand down (or a separate fade model, later) |
| 0.15-0.35 | Chop | **Stand down** |

The middle band is volatile but not persistent — it is where an EMA system takes its
worst losses, and it is the single most valuable thing to filter out. Note that ER
and the EMA slope check are testing the same underlying idea from two angles;
running both is deliberate belt-and-braces.

### 5.5 Running 24/7 — let the gates pick the hours

Running continuously is fine, and it is better than hardcoding session windows,
because the volatility gate selects sessions *automatically* and adapts when
sessions shift (DST, holidays, changed volatility regimes). In practice the bot will
naturally go quiet through the Asian session and wake for London and NY without
being told to. Four things still need explicit handling:

- **Rollover (~22:00 GMT).** Spreads routinely blow out to 10-50 pips for several
  minutes at daily rollover. This is the single most dangerous window for a scalper
  and the volatility gate will not save you — ATR looks normal, the spread does not.
  **Hard block ~21:45-22:15 GMT**, plus the spread gate below.
- **Weekend.** FX closes Friday ~22:00 GMT and gaps on the Sunday open. Flatten
  before Friday close, do not hold over, do not trade the first ~30 min Sunday.
  ("24/7" is really 24/5 unless the symbol is crypto, which genuinely does run 24/7
  and where this model transfers with retuned ATR multiples.)
- **Spread gate.** `spread <= min(1.5 x median spread, hard cap)`. Real volatility
  arrives *with* wide spreads, so this fires exactly when you most want to trade. It
  is still right — a 1.5-pip cost model does not survive a 6-pip spread.
- **News blackout.** +/-10 min around high-impact events. Fast, gappy, and
  slippage-prone in both directions.

### 5.6 Full gate chain, evaluated each M1 close

Every stage must pass, in order — first failure stands down:

1. Not in rollover / weekend / news window
2. Spread within limit
3. ATR(M5) above the multi-day baseline — **is there enough movement?**
4. ER > 0.35 — **is the movement going somewhere?**
5. Trend EMA slope above threshold — **is there a real trend?**
6. Price vs trend EMA — **which side am I allowed?**
7. Price inside the sandwich zone (past the close EMA, not past the trend EMA)
8. M1 rejection confirms the pullback is finishing
9. No batch currently open, ramp/risk caps clear
10. -> place the 5-leg ladder across the zone, stop beyond the trend EMA

## 6. The lot ramp — where it is fine and where it kills you

Ramping **up on wins** (anti-martingale) is the safe direction — you risk profit,
not principal. The concept is sound. Two things decide whether it survives.

Model: base 0.01, ramp ×1.15 per winning batch, batch of 5, TP 8 / SL 12.

- Batch profit at lot L: `5 × 8 × L × $10 = 400L` → **$4.00** at 0.01
- Batch loss at lot L: `5 × 12 × L × $10 = 600L` → **$6.00** at 0.01
- After 10 straight winning batches: lot = `0.01 × 1.15^10 ≈ 0.0405`
- Cumulative profit over those 10: `4 × (1.15^10 − 1)/0.15 ≈ **$81**`
- Loss on batch 11 at that size: `600 × 0.0405 ≈ **$24**`

One loss gives back ~30% of ten wins. **That is survivable — provided:**

1. **Every trade has a broker-side hard stop.** Not virtual, not "close it when it
   comes back". Without a stop the loss term is unbounded and no amount of prior
   ramping matters — this is the one change that separates the concept from
   guaranteed eventual ruin.
2. **The ramp resets to base on any losing batch.** Otherwise you carry maximum
   size into the losing streak.
3. **The ramp is capped** — hard step cap (~8 rungs) *and* an equity cap
   (`max lot = risk% of equity / stop distance`), whichever binds first.

Losses cluster (volatility clustering is real), so model 3–4 consecutive losing
batches, not one. With reset-on-loss that is 3–4 × base-size losses — trivial.
Without reset it is 3–4 × peak-size losses — account-ending.

> **The ramp is not the risk. The missing stop is the risk.**

---

## 7. Position sizing — how the lot size should actually grow

This is the part with a settled, correct answer. An expert would not use a
per-batch ramp at all; they would use **fixed-fractional risk off live equity**,
which makes the lot size grow with the account automatically and continuously.

### 7.1 The core formula

```
lots = (equity x riskPercent) / (stopDistancePips x pipValuePerLot)
```

GBPUSD, 1% risk, 10-pip stop, $10/pip per lot:

| Equity | Risk $ | Lots |
|--------|--------|------|
| $500 | $5 | 0.05 |
| $1,000 | $10 | 0.10 |
| $5,000 | $50 | 0.50 |
| $25,000 | $250 | 2.50 |

Two properties matter, and both are the reason this is the standard:

- **It compounds by itself.** No ramp logic, no state machine, no streak counter.
  Equity up 10% -> next trade is 10% bigger. Equity down -> smaller. The growth
  the concept wants is a free side effect of sizing correctly.
- **It normalises across setups.** A 6-pip-stop trade and a 20-pip-stop trade risk
  the *same dollars*. Without this, stop distance silently becomes your position
  sizer and every tight-stop setup is secretly an oversized bet.

### 7.2 Why not also run the win-streak ramp

Because it is a second, uncoordinated growth mechanism stacked on the first, and it
makes the stated risk figure a fiction. Set 1% risk with a x1.15 per-win ramp and an
8-win streak puts you at `1% x 1.15^8 = 3.06%` risk — right at the point where a
losing streak becomes most likely to arrive (volatility clusters). The ramp
concentrates maximum size exactly where the risk of ruin lives.

**Pick one sizing rule.** If you want extra aggression on winnings, the disciplined
version is to separate the two pools:

```
risk% = baseRisk + min(profitRisk, realisedProfitThisPeriod / equity x k)
```

Core capital always risks `baseRisk` (say 0.5%); realised profit funds additional
risk up to a cap. Same "press when winning" behaviour, but bounded and explicit
rather than compounding invisibly.

### 7.3 Volatility targeting (what an actual quant desk would add)

Fixed-fractional holds *dollar risk* constant. The upgrade holds *portfolio
volatility* constant:

```
lots = (equity x targetDailyVol%) / (ATR_daily_in_price x contractValue)
```

High-volatility regime -> automatically smaller; quiet regime -> larger. The result
is a materially smoother equity curve than fixed-fractional, because it removes the
regime component from your P&L variance.

Note the interaction with this bot specifically: the volatility gate in section 5
means it *only* trades in expanded volatility, so vol-targeting will systematically
size it down relative to naive fixed-fractional. That is correct, not a bug.

### 7.4 Kelly — as a ceiling, not a sizing rule

```
f* = W - (1 - W) / R          W = win rate, R = avg win / avg loss
```

At W = 0.65 and R = 0.7 (roughly the TP8/SL12 model net of costs):
`f* = 0.65 - 0.35/0.7 = 0.15` -> 15% of capital per trade. Nobody trades this, and
the reason is important: **Kelly assumes W and R are known exactly.** They are
estimates from a finite sample, and overestimating W by a few points sends full
Kelly bust with certainty. Estimation error, not math, is what kills it.

Standard practice is quarter-Kelly or less, which lands back at the familiar
0.5-2%. So use it as a **sanity ceiling**: if intended risk% exceeds half of f*,
the bet is too big regardless of what the backtest says.

### 7.5 De-risking ladder (drawdown handling)

Sizing off raw equity shrinks position size during a drawdown — mathematically
optimal for growth, but recovery is slow because drawdown is asymmetric (down 50%
needs +100% to get back). Sizing off a high-water mark recovers faster but raises
risk of ruin. The prop-desk compromise:

| Drawdown from high-water mark | Risk % |
|-------------------------------|--------|
| 0-5% | 1.0% (full) |
| 5-10% | 0.5% |
| 10-15% | 0.25% |
| > 15% | stop, review |

Size off current equity, but step risk% down through the bands and restore only at
a new high-water mark. This survives the regime the filters failed to detect —
which is the failure mode that actually ends accounts.

### 7.6 Two hard floors nobody mentions until they hit them

**Lot granularity.** Minimum lot 0.01, step 0.01. At 1% risk and a 20-pip stop:

| Equity | Ideal lots | Rounded | Actual risk |
|--------|-----------|---------|-------------|
| $1,000 | 0.05 | 0.05 | 1.0% |
| $300 | 0.015 | 0.01 or 0.02 | 0.67% or 1.33% |
| $100 | 0.005 | 0.01 | **2.0%** |

Below roughly $200-500 the lot step forces you to over-risk on every trade — the
sizing model stops being able to express the risk you asked for. Round *down* and
skip the trade when rounding down gives zero, rather than quietly doubling risk.

**Capacity.** Slippage scales with size. An edge that clears costs at 0.05 lots may
not clear them at 20 lots, because you are no longer a price taker on the top of
book. Scalping edges have the lowest capacity of any strategy family — this one has
a ceiling, and the growth curve flattens well before "keep compounding" suggests.

---

## 8. Win rate vs expectancy — what "profitable" actually requires

"Catches lots of wins" is worth separating from "makes money", because **win rate is
a dial you can set anywhere, and it is nearly orthogonal to profitability.**

Widen the stop and tighten the target and win rate goes up mechanically — a 3-pip TP
against a 60-pip stop wins ~90% of the time and loses money steadily. Every
high-win-rate system is selling the same thing: frequent small gains funded by rare
large losses.

The quantity that decides everything:

```
Expectancy = (W x avgWin) - (L x avgLoss)      per trade, net of costs
```

Positive and multiplied by trade count is the entire game. Some worked cases at
1.5 pips cost:

| Model | W | Net avg win | Net avg loss | Expectancy/trade |
|-------|---|-------------|--------------|------------------|
| TP 8 / SL 12 | 70% | 6.5 | 13.5 | **+0.5 pips** |
| TP 8 / SL 12 | 65% | 6.5 | 13.5 | **-0.5 pips** |
| TP 15 / SL 10 | 50% | 13.5 | 11.5 | **+1.0 pips** |

Note the first two rows: **a 5-point drop in win rate flips it from profitable to
losing.** That is what a tight-TP/wide-SL model buys you — a system with no margin
for error, whose profitability lives or dies on the last few points of accuracy.
The third row wins less often and earns twice as much per trade.

This is why the runner legs in section 3B matter more than they look. They are what
moves the system off the knife edge.

---

## 9. Risk architecture (non-negotiable)

| Control | Purpose |
|---------|---------|
| Broker-side SL on every leg | Bounds the loss term. Without this nothing else matters |
| Batch-level max loss | Whole batch flat at X, regardless of individual legs |
| Ramp resets on losing batch | Prevents peak size meeting a losing streak |
| Ramp step cap + equity cap | Bounds geometric growth both ways |
| Base lot as % of equity | Ramp compounds on top, doesn't replace, equity sizing |
| Daily loss cap → stop | Ends bad days |
| Consecutive-loss cap → stop session | Ends bad regimes the filters missed |
| Max spread gate | Blocks the cost blowout |
| Correlation cap (if multi-symbol) | Stops 5 pairs being 1 trade |

---

## 10. Broker realities to handle in code

- **Netting vs hedging accounts** — on netting, 5 orders merge into one position and
  the per-leg TP/SL model silently breaks. Detect and branch, or require hedging.
- **Stop level / freeze level** — many brokers reject stops or TPs closer than
  2–5 pips. A tight TP may be *unplaceable*. Query and clamp.
- **Min lot / lot step** — 0.01 min, 0.01 step is typical. A ×1.15 ramp from 0.01
  rounds to 0.01 for the first two rungs. Ramp on an internal float, round only at
  order send, or steps get silently swallowed.
- **Slippage on batch entry** — 5 orders sent together do not all fill at the quoted
  price during volatility, which is precisely when this bot trades.
- **Execution latency** — a 1–2 pip target and 200ms latency are not compatible.
- Some brokers restrict or penalise scalping outright — worth checking the terms.

---

## 11. Honest summary

What survives from the original concept:
- Ramping size on wins — yes, with reset + caps
- Trading only in volatility — yes, and it should be the primary gate
- Banking small profits quickly — yes, on *part* of the position
- Batches of 5 — yes, but as a **ladder**, not 5 identical clones

What has to change:
- Targets in **ATR/pips**, never dollars, or the edge decays as lots ramp
- **Hard stop on every leg** — the single change that makes it survivable
- **Not all 5 legs exit early** — runners are what pay for the losing batches
- **Direction is required**, not optional — the break-even table leaves no room
- The "10 pips per candle" premise must be **measured live**, not assumed

What this realistically is: a **regime-filtered momentum/mean-reversion scalper
with laddered entries, staggered exits, and anti-martingale sizing.** That is a
legitimate strategy family. It will have losing days and losing weeks. The goal is
positive expectancy over hundreds of trades with controlled drawdown — not a green
result every batch.

---

## 12. Build order

1. Regime engine standalone (ATR gate + ER classifier + direction) — log signals
   only, no trading, and verify the classifier against real charts first
2. Risk/sizing module (base lot, ramp state machine, all caps and resets)
3. Batch executor (ladder placement, per-leg TP/SL, netting/hedging branch)
4. Batch lifecycle (fill tracking, close detection, ramp advance/reset)
5. Session/news/spread gates
6. Backtest on real ticks, ≥12 months, across trending *and* ranging regimes
7. Forward-test on demo before anything else
