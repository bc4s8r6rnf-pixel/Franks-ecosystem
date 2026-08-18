# Volatility Scalper — usage

`Experts/VolatilityScalper.mq5`. Standalone; shares no code with Blxck Mirror.

Full design reasoning is in [`VOLATILITY_SCALPER_DESIGN.md`](VOLATILITY_SCALPER_DESIGN.md).
This page is how to run it.

---

## What it actually is

A 24/7 volatility-gated scalper engineered for a **trade shape** — many small wins,
the occasional small loss — rather than for a headline win rate.

Four decisions define it:

**It is mean reversion, not momentum.** High win rates come from fading
over-extension, because price usually reverts. Momentum gives the opposite profile:
few wins, large winners. The EA fades a pullback but only *with* the higher-timeframe
trend, so the reversion has a tailwind rather than fighting one.

**The loss side is truncated deliberately.** The first legs bank at TP1 and the stop
moves to break-even immediately after. That converts a large share of would-be losers
into scratches, and it — not a tight take-profit — is what produces the "lots of small
wins" shape. A tight TP does the opposite (see the design doc's edge-requirement table).

**Volatility is gated in a band, not above a floor.** Too little movement and there is
nothing to capture; too much and it is news or panic, where spreads gap and stops slip.
Both tails are filtered.

**It runs continuously and lets the gates pick the hours.** The ATR baseline is a median
across all hours over several days, so quiet Asian hours cannot read as "volatile
relative to Asia". In practice it goes quiet overnight and wakes for London and NY on
its own, and adapts when sessions shift for DST or holidays.

---

## Start here

1. Compile in MetaEditor (F7). It cannot be compiled in this repo's environment, so
   report any warnings.
2. Attach to an M1 chart of a tight-spread major (GBPUSD or EURUSD).
3. **Leave `InpDryRun = true`.** It evaluates every bar and logs each decision without
   sending a single order.
4. Watch the Experts log for a day or two. You are checking two things:
   - Does it stand down when you would? (Compare `skip:` lines against the chart.)
   - Do the `SIGNAL` lines land where you would actually want to trade?
5. Only then set `InpDryRun = false` on a **demo** account.

`InpVerboseLog` prints the reason every bar is rejected. Noisy by design — that log is
the whole point of the dry run. Turn it off once live.

---

## The gate chain

Evaluated on each closed M1 bar. First failure stands the bar down.

| # | Gate | Rejects when |
|---|------|--------------|
| 1 | Batch already open | One batch at a time |
| 2 | Time gates | Rollover, weekend, news blackout |
| 3 | Risk gates | Daily loss hit, loss-streak pause, drawdown halt |
| 4 | Spread | Over the pip cap, or over `InpMaxSpreadAtr` × ATR |
| 5 | Volatility band | ATR/baseline outside `InpVolMin … InpVolMax` |
| 6 | Regime (ER) | In the chop band between `InpErRange` and `InpErTrend` |
| 7 | Direction | Trend EMA flat, or price outside the setup zone |
| 8 | Over-extension | RSI not stretched enough |
| 9 | Rejection bar | Pullback may still be falling |

### Trend mode — the sandwich zone

```
LONG:    EMA_trend < price < EMA_close      (trend EMA rising)
SHORT:   EMA_close < price < EMA_trend      (trend EMA falling)
```

Being past the close EMA means buying a pullback rather than chasing an extension —
that is where the reward-to-risk comes from. Still being the right side of the trend
EMA bounds that pullback; "past the close EMA" alone is unbounded and catches falling
knives. The zone width is the EMA separation, so it widens with trend strength and
pinches shut as the trend fades: the bot throttles itself with no extra rule. The stop
sits beyond the trend EMA, because if that breaks the reason for the trade is gone.

### Range mode — fade the band

With ER low the market is genuinely rotating, so the fade beats the breakout. This is
what keeps the EA useful outside London and NY without forcing trend logic onto a
market that has no trend.

---

## Sizing

Fixed-fractional off live equity:

```
lots = (equity × risk%) / (stopPips × pipValue)
```

This is what makes the lot size grow with the account — continuously, with no ramp and
no streak counter. Equity up 10% and the next trade is 10% bigger. It also normalises
across setups: a tight-stop and a wide-stop trade risk the same money, so stop distance
never becomes an accidental position sizer.

Lots round **down** to the broker's step, and a size that rounds below the minimum
skips the trade rather than rounding up. Rounding up would silently over-risk, and at
small account balances that is exactly where it does most damage — below roughly
$200–500 the 0.01 step cannot express a 0.75% risk on a typical stop at all.

Risk is cut as drawdown from the high-water mark deepens (`InpUseDerisk`): half at 5%,
quarter at 10%, halt at 15%. Sizing off equity already shrinks positions in a drawdown,
but drawdown is asymmetric — down 50% needs +100% back — so the ladder buys survival
through the regime the filters failed to detect.

---

## Key inputs

| Input | Default | Effect |
|-------|---------|--------|
| `InpDryRun` | **true** | Log signals, send nothing |
| `InpRiskPercent` | 0.75 | Risk per **batch**, split across legs |
| `InpVolMin` / `InpVolMax` | 0.80 / 2.50 | The volatility band |
| `InpErTrend` / `InpErRange` | 0.35 / 0.15 | Regime boundaries; the gap is the chop zone |
| `InpStopAtr` | 1.30 | Stop distance in ATR |
| `InpTp1Atr` / `InpTp2Atr` | 1.00 / 2.50 | Early target / runner target |
| `InpLadderLegs` | 3 | Orders per batch (netting accounts force 1) |
| `InpTp1Legs` | 2 | How many legs take the early target |
| `InpTimeStopMin` | 45 | Flatten a trade going nowhere |
| `InpRolloverHour` | 0 | **Set this to your broker's rollover hour** |

### Tuning order

1. **`InpRolloverHour` first.** Spreads go 10–50 pips wide at rollover while ATR looks
   completely normal, so the volatility gate cannot catch it. Watch the spread on your
   own feed and set the hour to match.
2. **The volatility band next.** Widen `InpVolMin` down if it never trades; pull
   `InpVolMax` down if the losers cluster around data releases.
3. **`InpErTrend` / `InpErRange` after that.** Widening the gap between them trades
   less and cleaner; narrowing it trades more and dirtier. This is the main
   frequency/quality dial.
4. **Leave `InpStopAtr` and the targets alone until the filters are right.** Tightening
   the target to raise the win rate raises the *required* edge, which is the opposite
   of what it looks like it does.

---

## Before trusting a backtest

- Model **"Every tick based on real ticks"** — the entry is wick-sensitive.
- **≥ 12 months**, spanning trending *and* ranging regimes.
- Check the result with the single best trade removed. If it collapses, there is no
  edge, just one lucky trade. (This repo's other EA got caught exactly that way — one
  trade was 96% of the net profit.)
- Test out-of-sample on a period you did not tune against.
- The news filter is **inert in the Strategy Tester** (no calendar data). Expect live
  behaviour to differ around releases.

`tools/m1_open_volatility_test.py` measures candle sizes, autocorrelation and cost drag
on an M1 export from your own broker — worth running before any of this, since it tells
you what your feed and spreads can actually support.

---

## Honest caveats

- **This is a framework with a plausible edge, not a proven one.** Whether it makes
  money is an empirical question, answered by out-of-sample testing on your broker's
  data and nothing else.
- It has not been compiled or backtested here — no MetaTrader in this environment.
  Everything above is design intent, not measured behaviour.
- The batch scoring in `SyncBatchState()` uses account equity to judge a win or loss.
  That is adequate for the streak counter but will misattribute if you trade this
  symbol manually on the same account at the same time.
- Netting accounts collapse the ladder to a single leg. The EA detects this at init and
  says so in the log.
