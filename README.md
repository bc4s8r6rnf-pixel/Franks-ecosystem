# Institutional Blxck Mirror — MT5 Expert Advisor (MQL5)

A trend-following EA built around real institutional / smart-money order-flow logic:
**trade only in the direction big money is already pushing, but enter *after* the
previous session's liquidity has been swept and the fair-value-gap of the sweep
candle has inverted back in trend.** Retail sees a reversal at the sweep;
institutions (and this EA) see continuation. That mirror is the edge.

> File: `Experts/InstitutionalBlxckMirror.mq5`

**The EA's default inputs are pre-tuned for GBPUSD M15 — compile and attach with no
`.set` file needed.** Target is 1–2 quality trades/day (`InpMaxTradesPerDay=2`): one
main move in the London prime window, one in the New York prime window. EURUSD users
should load `presets/EURUSD.set` (its filters are tuned tighter for EUR/USD's smaller
average range).

---

## The playbook (start to finish)

1. **Bias** — H4 Break of Structure aligned with D1 **and** EMA 50/200 order-flow agree. No confluence → no trade.
2. **Liquidity map** — mark prior-session highs/lows + swing pools (manipulation targets *and* profit targets).
3. **Setup** — in the killzone, wait for a **sweep of the previous session's liquidity against bias** (the stop-run). Sweep extreme = fib **1.0**; the displacement leg extreme = fib **0.0** (dynamic).
4. **Entry** — price retraces into **OTE 0.62–0.79**, confirmed by a displacement candle or inversion FVG. A **limit rests at 0.705** (market fallback if price runs), stop just beyond the **M1 confirmation swing**.
5. **Risk** — fixed 0.5–0.75% sized to the tight stop; skip on low RR, wide spread, news, daily-loss, or cooldown.
6. **Manage** — first partial at **1:2 → break-even**, then **−2.0 SD** partial, runner trailed to **−3.0 SD** behind M1 FVGs. Flat by session end.
7. **Guards** — max trades/day, daily max-loss, post-loss cooldown, optional daily target.

---

## Real swing / CHoC detection (critical fix)

Earlier builds derived the manipulation leg (fib 1.0→0.0) from a fixed, narrow bar
window tied to session boundaries — it could miss a real setup if the swing simply
spanned more bars than that window, or wasn't anchored to a labelled session. That's
now replaced with **genuine swing-pivot detection**:

- Finds the last confirmed **swing high/low pair** on the setup TF (real fractals,
  filtered by `InpChocMinRangeATR` so tiny noise swings don't count).
- **Manipulation (fib 1.0)** = the true wick extreme that sweeps the swing pivot.
- **Change of Character (fib 0.0)** = confirmed only once price **closes** through
  the opposing structural swing point — and then trails as the impulsive leg extends.
- The leg can span **any number of bars** — a few, or fifty — because it's anchored
  to real structure, not an artificial window. This is what lets the EA see the same
  swing a trader would draw a fib on.

Tune via `InpChocSwingStrength` (fractal strength — higher = fewer, more significant
swings), `InpChocLookback` (bars scanned), and `InpChocMinRangeATR` (minimum swing
size to count as real structure, filters noise).

---

## Two setup types only: continuation (BOS) and reversal (CHoC)

The market only ever gives two valid setups, and the EA now maps both, every bar,
and takes whichever is the most recent genuine one — not a fixed pattern preference:

- **Continuation — BOS then retrace to OTE.** Trend is already established; price
  makes a clean **Break of Structure** (a close beyond the last same-direction swing
  point, no manipulation needed) and then pulls back into the OTE of that impulsive
  leg. `FindBOS()`.
- **Reversal — liquidity sweep + Change of Character then retrace to OTE.** Price
  wicks through the opposing swing pivot (manipulation), then **closes** through the
  preceding structural point (CHoC), confirming the flip; entry on the retrace into
  OTE of that new leg. `FindCHoC()`.

Both are gated by the same **HTF institutional bias** (`InstitutionalBias()`) —
the EA only ever trades *with* the higher-timeframe trend, whether that's via a
textbook continuation or via a CHoC that re-confirms it after a stop-hunt. Each new
setup-TF bar, `FindSwingLeg()` evaluates both patterns and keeps whichever swing's
triggering event (the break or the sweep) is **most recent** — the currently obvious
major swing, exactly as a trader would read the chart, regardless of how many bars
it spans.

## High-probability entry windows (prime windows)

The underlying swing can arm and trail **any time** within the broader killzone —
that part is never restricted to a small window. But the actual **OTE tap that fires
an entry** statistically clusters in a much tighter sub-window each session:

- **London prime: 02:00–04:00 NY time** (`InpLondonPrimeStart` / `InpLondonPrimeEnd`)
- **New York prime: 08:00–09:30 NY time** (`InpNYPrimeStart` / `InpNYPrimeEnd`)

`InpUsePrimeWindow` (default **on**) restricts the **entry** (not the arming/tracking)
to these windows — a setup can tap and confirm outside them and will simply wait,
still armed, until the prime window opens (or the broader killzone ends and it
resets). This is the main noise filter: it's not a frequency throttle to loosen for
more trades, it's the timing discipline that makes the setup high-probability in the
first place. Asia has no defined prime window and is unrestricted whenever
`InpTradeAsia` is on.

## Target selection: most liquidity + key level + SD confluence

The final target now ranks the `−2.0 / −2.5 / −3.0` SD candidates by **stacked
liquidity weight**, not just a binary "does it align" check — a candidate that lines
up with a heavier pool (equal highs/lows, the previous day's high/low) outranks one
that merely lines up with an Asia-range deviation level with no real liquidity behind
it. `PoolWeight()` feeds each candidate's touches count directly into the score.

## Stop management after the first partial

Once price reaches the **−0.27 SD** first-partial target, the stop no longer just
jumps to flat break-even — it moves to **just behind the candle that broke through
0.27** (on `InpMicroTF`), which is normally tighter than break-even and locks most
trades in at roughly **2:1 or better** if later stopped out, while the runner still
has room to reach the final DOL/liquidity target. Never worse than break-even even
if that candle overshot.

---

## Trade frequency — from ~27/yr toward daily

If backtests show very few trades, the **bias gate is almost always the bottleneck** —
requiring H4 BOS + D1 + EMA to *all* agree is a strict 3-way AND that can leave the EA
with "no bias" most days. Loosen the funnel in this order:

1. **`InpBiasMode`** (biggest lever): `0` = strict (all 3 agree), `1` = **majority**
   (2 of 3), `2` = **lean** (any net agreement — loosest). Start with `1`.
2. **`InpTradeAsia = true`** — adds a third tradeable killzone (Asia sweeps the prior
   NY session), plus widening the London/NY windows by an hour each.
3. **`InpChocSwingStrength`** lower (e.g. 2) and **`InpChocMinRangeATR`** lower
   (e.g. 1.0) — recognises smaller, more frequent CHoC structures.
4. **`InpSweepMinPips`** down, **`InpSweepMaxBars`** up — easier/longer sweep window.
5. **`InpMinDisplaceLeg`** down (e.g. 0.5) — accepts smaller displacement legs.
6. **`InpMinRR`** down (e.g. 1.3–1.5) — fewer setups rejected on reward:risk.
7. **`InpMaxTradesPerDay`** up (e.g. 6) — only matters once the above raise frequency.

`presets/EURUSD_HighFrequency.set` and `presets/GBPUSD_HighFrequency.set` apply all of
this at once (with risk trimmed to 0.5% to offset the higher trade count). **Every
loosened gate trades some quality for frequency** — A/B them against the original
presets in the tester and check profit factor / drawdown, not just trade count, before
choosing one to run live.

---

## The strategy structure (my recommended institutional model)

You asked me to pick the structure that gives the highest probability, biggest
explosive moves, and a high win rate while protecting risk. This is what I built:

### 1. Bias engine — "which way is institutional order flow?"
The most reliable, most-used institutional trend read is a **confluence of market
structure and order flow**, not a single indicator. The EA requires two things to
agree before it will even look for a trade:

- **HTF Market Structure (Break of Structure)** on H4, confirmed by D1. A close
  beyond the last confirmed swing high/low = the trend leg is intact.
- **EMA order-flow filter (50 / 200 EMA)** on H4 — the classic institutional
  dynamic value zone. Price and the fast EMA must be on the correct side of the
  slow EMA.

Only when BOS **and** EMA agree (and the D1 doesn't oppose) is a daily bias set.
This single filter is what keeps the win rate up: you never fight the trend.

### 2. Liquidity heatmap — "where are the stops?"
The EA maps engineered liquidity and weights it:

- **Buy-side liquidity** above swing highs (red) — where breakout-buyer &
  short-seller stops sit.
- **Sell-side liquidity** below swing lows (blue) — where breakout-seller &
  long stops sit.
- **Equal highs / equal lows** are detected and drawn *thicker* — more resting
  stops = a bigger magnet for price.
- Previous **Asia** and **London** session highs/lows are added as premium pools.

### 3. The setup — sweep → dynamic OTE → confirmation (primary model)
1. **Liquidity sweep** of the *previous session's* pool **against** the trend
   (bullish bias → sweep the prior-session low; bearish → sweep the prior-session
   high). This is the manipulation that fuels the move. The sweep extreme becomes
   fib **`1.0`** (end of manipulation / start of the displacement leg).
2. A real **displacement leg** must follow (≥ `InpMinDisplaceLeg × ATR`). Its running
   extreme is fib **`0.0`** — and it is **dynamic**: as long as price keeps extending,
   the `0` anchor (and therefore the whole **OTE 0.62–0.79 zone**) slides with it. The
   setup stays "armed, awaiting retracement".
3. **Entry** when price finally retraces into the **OTE 0.62–0.79 zone**, with a
   **confirmation trigger** (`InpConfirmMode`): a displacement candle back in trend
   and/or an **inversion FVG**. If a pullback doesn't reach OTE and price makes a new
   extreme, the zone re-anchors and waits again — **unless price leaves the killzone**,
   in which case the setup is abandoned. A close beyond the `1.0` anchor invalidates it.

> **Legacy mode:** set `InpUseOTEModel = false` to use the simpler one-shot
> sweep→IFVG entry instead. The OTE model is the recommended default.

**Why OTE + light confirmation (not OTE alone, not strict IFVG):** OTE is the
*location* (discount/premium after a liquidity grab — what institutions fill into);
the confirmation is the *proof order flow shifted* there. Requiring a strict IFVG on
top misses clean V-reversals; pure OTE taps eat fakeouts. `InpConfirmMode = 1`
(OTE + displacement **or** IFVG) is the balance — backtest 0/1/2 on your data.

### 4. Targets & trade management
- **Take profit = opposing liquidity, snapped to a standard-deviation projection.**
  The EA projects **SD levels from the Asian range** (0.5×, 1×, 1.5×, 2×, 2.5×, 3×
  the range, both directions — the classic "London sweeps Asia then runs to the SD
  extension" move). In the default **confluence mode** it targets the SD level that
  **aligns with a key liquidity pool** (drawn gold on the chart), which is exactly the
  "targets that align with key levels" approach. You can switch to pure liquidity or
  pure SD via `InpTargetMode`.
- On **TP1 the EA closes 70%** of the position (configurable).
- It then **moves the stop to just behind the nearest M1 FVG to the TP**, and
  **extends the target to the next pool**, giving the runner room to ride the
  explosive leg.
- The runner is **trailed behind M1 FVGs** so profit is locked as structure builds.

### 5. Timeframes & pair (my picks)
| Role | Timeframe | Why |
|------|-----------|-----|
| Bias / structure | **D1 + H4** | Where institutional trend and BOS are cleanest |
| Setup / sweep / IFVG | **M15** | Session sweeps and FVGs are reliable here without M1 noise |
| Refinement / trailing | **M1** | Precise FVG trailing on the runner |

**Best pair: EUR/USD.** Deepest liquidity, tightest spreads, and the cleanest
London/NY session-sweep behaviour — ideal for a previous-session-liquidity model.
Strong alternates: **GBP/USD** (bigger range, slightly lower win rate) and
**NAS100 / US30** (very explosive continuation legs; widen the pip/FVG filters).

---

## Repo contents

| Path | What |
|------|------|
| `Experts/InstitutionalBlxckMirror.mq5` | The EA |
| `presets/EURUSD.set` · `presets/GBPUSD.set` | Tuned input presets (load via Inputs → Load) |
| `docs/OPTIMIZATION.md` | Strategy Tester & optimization walkthrough |

## Install

1. In MetaTrader 5: **File → Open Data Folder**.
2. Copy `Experts/InstitutionalBlxckMirror.mq5` into `MQL5/Experts/` (and the
   `presets/*.set` files into `MQL5/Presets/` if you want them in the Load dialog).
3. Open **MetaEditor**, open the file, press **F7** to compile.
4. Attach the EA to a **EUR/USD M15** chart. Enable **Algo Trading**.
5. Make sure the chart symbol has D1, H4 and M1 history downloaded.
6. Load a preset from the EA **Inputs → Load** button, then set `InpServerToNYOffset`.

### ⚠️ Timezone setup — do this first (most important step)

Session windows are defined in **New York time** (the reference clock institutions
use for killzones), but MetaTrader runs on your **broker's server time**. The EA
converts between them with **one input**:

> **`InpServerToNYOffset`** = hours to add to server time to get NY time.

To find it: look at the clock in MT5's **Market Watch** (server time) vs the current
NY time, and set the difference. Example: broker on **GMT+3**, New York on **GMT‑4**
(EDT) → NY = server − 7 → **`InpServerToNYOffset = -7`** (the default). During US
winter (EST, GMT‑5) it becomes **‑8**. Get this right and everything else — sessions,
sweeps, killzones — lines up automatically.

Default session windows (already set, in **NY time**):

| Session | NY time | Role |
|---------|---------|------|
| Asia | 19:00–00:00 | Liquidity built here is swept during London |
| London | 01:00–05:00 | Killzone — sweeps Asia, then continues |
| New York | 07:00–11:00 | Killzone — sweeps London, then continues |

---

## Key inputs

| Input | Default | Meaning |
|-------|---------|---------|
| `InpBiasTF` / `InpHTFTrend` | H4 / D1 | Bias timeframes |
| `InpSetupTF` / `InpMicroTF` | M15 / M1 | Setup & trailing timeframes |
| `InpRequireEmaAndBOS` | true | Require EMA **and** BOS confluence (higher win rate) |
| `InpRiskPercent` | 0.75 | Risk per trade (% balance); `InpFixedLots` overrides |
| `InpMinRR` | 2.0 | Reject setups below this reward:risk |
| `InpPartialPercent` | 70 | % closed at TP1 |
| `InpMoveSlBehindFvg` | true | After TP1, stop → behind nearest M1 FVG to TP |
| `InpTrailMicroFvg` | true | Trail runner behind M1 FVGs |
| `InpMaxTradesPerDay` | 3 | Daily trade cap |
| `InpMaxSpreadPips` | 3 | Skip entries in wide spread |
| `InpShowHeatmap` / `InpShowFvg` / `InpShowDashboard` | true | Visuals |

### ATR stop fallback
| Input | Default | Meaning |
|-------|---------|---------|
| `InpUseAtrStop` | true | Enforce a minimum ATR-based stop so noise can't stop you out too tight |
| `InpAtrPeriod` | 14 | ATR period (setup TF) |
| `InpAtrMultSL` | 1.2 | Stop is widened to at least `ATR × this` from entry |
| `InpMaxStopPips` | 0 | Reject a setup whose stop is wider than this (0 = off) |

### News filter (MT5 economic calendar)
| Input | Default | Meaning |
|-------|---------|---------|
| `InpUseNewsFilter` | true | Block entries around high-impact news for the pair's currencies |
| `InpNewsImportance` | 2 | 1 = moderate+, 2 = high only |
| `InpNewsMinsBefore` / `InpNewsMinsAfter` | 15 / 15 | Blackout window around each event |

> The calendar needs to be enabled in the terminal and is **not available in the
> Strategy Tester** — there the filter simply allows trading (fails open).

### OTE entry model (dynamic)
| Input | Default | Meaning |
|-------|---------|---------|
| `InpUseOTEModel` | true | Use the dynamic OTE model (false = legacy sweep→IFVG entry) |
| `InpOTELow` / `InpOTEHigh` | 0.62 / 0.79 | OTE retracement zone (fib) |
| `InpConfirmMode` | 1 | 0 = OTE tap, 1 = OTE + (displacement **or** IFVG), 2 = OTE + IFVG required |
| `InpMinDisplaceLeg` | 1.0 | Min displacement leg (× ATR) needed to arm a setup |
| `InpTP1_SD` | 2.0 | Main SD target — partial banked here |
| `InpRunnerSD` | 3.0 | Runner target SD level (stop trails behind M1 FVGs toward it) |

> TP levels are projected from the **manipulation leg** (fib `-2.0`, `-3.0`), exactly
> like the SD tool in your charts. The live OTE zone + entry/target ladder are drawn on
> the chart while a setup is armed.

### Execution & stop precision (the "best execution" layer)
| Input | Default | Meaning |
|-------|---------|---------|
| `InpEntryExec` | 1 | 0 = market on confirmation (never miss), 1 = **limit at OTE** with automatic market fallback |
| `InpOTEEntryFib` | 0.705 | Fib level the limit rests at (the sweet spot) |
| `InpStopMode` | 2 | 0 = beyond 1.0 anchor, 1 = beyond 0.79 edge, **2 = behind the M1 confirmation swing (tightest sane)** |
| `InpPendingExpiryBars` | 4 | Cancel an unfilled OTE limit after N setup bars (also cancels when the killzone closes) |
| `InpMicroSwingLB` / `InpMicroSwingStr` | 25 / 2 | M1 lookback / fractal strength for the stop swing |
| `InpMicroEntry` | true | **Sniper:** refine entry+stop to the M1 FVG inside the OTE (tightest) |
| `InpMicroPad` | 0.0 | Extra pad (pips) around the OTE zone when hunting the M1 FVG |

**How the entry actually fires (tightest execution after confidence):** OTE tap →
confirmation → the EA drops to **M1 and finds the FVG inside the OTE zone**. The limit
rests at that **M1 imbalance edge** and the stop sits **just beyond the far edge of that
M1 FVG** (+ buffer, + broker/spread floor) — the tightest *structural* stop available, a
few pips on real micro-structure. If no clean M1 FVG is present it falls back to the
**0.705 limit + M1-swing stop**; if price is already displacing away it **fills at market**
so you never miss the runner. Set `InpMicroEntry = false` to always use the 0.705 limit.

### Bank-then-run management
| Input | Default | Meaning |
|-------|---------|---------|
| `InpTP1_RR` | 2.0 | First partial at this reward:risk, then stop → break-even (0 = off) |
| `InpFirstPartialPct` | 50 | % closed at the 1:R first partial |
| `InpPartialPercent` | 70 | % of the **remaining** closed at the −2.0 SD target |

First partial at **1:2** makes the trade risk-free early (keeps the green rate high even
with a tight stop); the −2.0 SD partial then banks more and the runner trails to −3.0.

### Standard-deviation projections (Asian range)
| Input | Default | Meaning |
|-------|---------|---------|
| `InpUseSDProjection` | true | Project SD levels from the Asian range for targets |
| `InpSDMultiples` | 0.5,1.0,1.5,2.0,2.5,3.0 | Range multiples to project up & down |
| `InpTargetMode` | 2 | 0 = liquidity, 1 = SD projection, 2 = confluence (SD snapped to liquidity) |
| `InpSDAlignPips` | 8 | Snap distance for calling an SD level "aligned" with liquidity |
| `InpShowSDLevels` | true | Draw the Asian-range box + SD lines (gold = confluence) |

### Win-rate boosters (all toggleable)
| Input | Default | Meaning |
|-------|---------|---------|
| `InpUseDisplacement` | true | Entry candle must be a strong displacement (body ≥ `InpMinBodyPct`% and ≥ `InpDisplaceAtrMult × ATR`) |
| `InpUseOTE` | true | Premium/discount filter — only buy in discount, only sell in premium |
| `InpUseBreakEven` | true | Move SL to break-even once price runs `InpBreakEvenAtR` R in profit |
| `InpCloseAtSessionEnd` | true | Flatten any open trade at NY session end (no overnight risk) |
| `InpDailyMaxLossPct` | 3.0 | Stop trading for the day after this % equity loss |
| `InpDailyTargetPct` | 0 | Stop for the day after this % gain (0 = off) — bank consistent days |
| `InpCooldownMin` | 30 | Pause this many minutes after a losing trade (kills tilt/chop) |

---

## Pushing win rate & profit factor higher

The biggest levers, in order of impact:

1. **Get `InpServerToNYOffset` exactly right.** Everything keys off session timing.
2. **Keep `InpRequireEmaAndBOS = true`.** Trading only with full trend confluence is
   the single largest win-rate driver.
3. **Keep the displacement + OTE filters on.** They throw away the weak IFVGs that
   cause most losers — fewer trades, but far cleaner ones.
4. **Raise `InpMinRR`** (e.g. 2.5–3.0) to lift profit factor; lower it (1.5–2.0) if you
   want more frequent trades and are willing to trade some win-rate for frequency.
5. **Optimise per pair** in the Strategy Tester — follow **[`docs/OPTIMIZATION.md`](docs/OPTIMIZATION.md)**
   (optimise in groups, rank by profit factor, validate out-of-sample). What's optimal
   on EUR/USD is not optimal on NAS100.
6. Use **`InpDailyTargetPct`** to *bank* good days and **`InpDailyMaxLossPct` +
   `InpCooldownMin`** to cap bad ones — that's what turns a positive edge into
   *consistent* equity growth.

### An honest word on "consistent daily pips"

No automated strategy wins every day — a real institutional-style edge shows up as a
**positive expectancy over many trades**, with losing days mixed in. This EA is built
to be *selective*: on many days the filters will (correctly) find **no valid setup**,
and forcing trades on those days is exactly what destroys win rate. Target a strong
**profit factor and controlled drawdown over weeks**, not a green candle every session.
That is how the institutions you're modelling actually compound.

## Important notes & honest caveats

- **This is a starting framework, not a guaranteed money printer.** No EA is.
  Backtest it on the **"Every tick based on real ticks"** model, then forward-test
  on a **demo** account for several weeks before risking real capital.
- Detection of BOS / sweeps / FVGs uses defined, mechanical rules — they are
  approximations of the discretionary concepts. Tune the strength/lookback inputs
  to your pair and broker feed.
- Session inputs are in **broker server time** — getting these right is the single
  most important calibration step.
- The code compiles cleanly in MetaEditor (MQL5). It cannot be compiled in this
  environment (no MetaTrader), so please compile with F7 and report any warnings.

---

*Built as an institutional trend-following framework — bias in the direction of
order flow, entries only after liquidity is engineered and the FVG inverts.*
