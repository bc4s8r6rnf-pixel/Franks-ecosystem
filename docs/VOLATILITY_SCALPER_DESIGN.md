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

## 5. Entry logic — regime first, then direction

The single highest-value component. Run this gate chain each M1 close; every stage
must pass or the bot stands down.

### Stage 1 — Volatility gate (permission to trade)
```
ATR(14, M5) > 1.2 × median(ATR(14, M5), last 200 bars)
```
Relative to its own recent baseline, so it self-calibrates per pair and session.
No absolute pip numbers.

### Stage 2 — Regime classifier (which strategy is even valid)
Kaufman Efficiency Ratio over 20 bars of M5:
```
ER = |close[0] - close[20]| / Σ |close[i] - close[i+1]|
```
This is the key filter — it separates *directional* expansion from *chop*, which
raw ATR cannot do (both look identical to ATR).

| ER | Regime | Action |
|----|--------|--------|
| > 0.35 | Trending expansion | **Momentum continuation** — trade with direction only |
| < 0.15 | Clean range | **Mean reversion** — fade the band edges, both ways |
| 0.15–0.35 | Chop | **Stand down** — no trade |

That middle band is where high volatility exists but has no persistence. It is
where this style of bot dies, and refusing to trade it is most of the edge.

### Stage 3 — Direction (trending regime only)
Keep it robust, not clever:
- H1 EMA(50) slope over last 10 bars — sign gives bias
- M15 structure agrees (higher highs + higher lows, or the inverse)
- Both agree → trade that direction only. Disagree → no trade.

In the ranging regime, direction comes from location instead: sell the upper
Bollinger/Keltner edge, buy the lower, only while ER confirms the range is holding.

### Stage 4 — Execution gates (any one blocks entry)
- Spread ≤ `min(1.5 × median spread, hard cap)` — real volatility arrives *with*
  wide spreads, so this gate fires exactly when you most want to trade. It is
  still right.
- Session: London 08:00–11:00 and NY 13:00–16:00 UK. No Asia, no Friday after
  16:00, no Sunday open.
- News blackout ±10 min around high-impact events.
- Not already in an open batch.

---

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

## 7. Risk architecture (non-negotiable)

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

## 8. Broker realities to handle in code

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

## 9. Honest summary

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

## 10. Build order

1. Regime engine standalone (ATR gate + ER classifier + direction) — log signals
   only, no trading, and verify the classifier against real charts first
2. Risk/sizing module (base lot, ramp state machine, all caps and resets)
3. Batch executor (ladder placement, per-leg TP/SL, netting/hedging branch)
4. Batch lifecycle (fill tracking, close detection, ramp advance/reset)
5. Session/news/spread gates
6. Backtest on real ticks, ≥12 months, across trending *and* ranging regimes
7. Forward-test on demo before anything else
