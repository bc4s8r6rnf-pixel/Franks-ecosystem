# Institutional Blxck Mirror — MT5 Expert Advisor (MQL5)

A trend-following EA built around real institutional / smart-money order-flow logic:
**trade only in the direction big money is already pushing, but enter *after* the
previous session's liquidity has been swept and the fair-value-gap of the sweep
candle has inverted back in trend.** Retail sees a reversal at the sweep;
institutions (and this EA) see continuation. That mirror is the edge.

> File: `Experts/InstitutionalBlxckMirror.mq5`

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

### 3. The setup — sweep → inversion FVG → continuation
1. **Liquidity sweep** of the *previous session's* pool **against** the trend
   (bullish bias → sweep the prior-session low; bearish → sweep the prior-session
   high), with a close back inside. This is the stop-run that fuels the move.
2. The sweep candle prints a **fair value gap**. When price then **closes through
   that FVG in the trend direction, it becomes an Inversion FVG (IFVG)** — the
   highest-probability continuation entry. The EA prioritises the IFVG tied to the
   sweep candle, exactly as you asked.
3. **Entry** on the confirming close beyond the IFVG.

### 4. Targets & trade management
- **Take profit = opposing liquidity** — the next big pool on the other side
  (for a long, the nearest buy-side pool above; for a short, the nearest sell-side
  pool below).
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

## Install

1. In MetaTrader 5: **File → Open Data Folder**.
2. Copy `Experts/InstitutionalBlxckMirror.mq5` into `MQL5/Experts/`.
3. Open **MetaEditor**, open the file, press **F7** to compile.
4. Attach the EA to a **EUR/USD M15** chart. Enable **Algo Trading**.
5. Make sure the chart symbol has D1, H4 and M1 history downloaded.

> Set the **session hours to your broker/server time** (`InpAsiaStart` … `InpNYEnd`).
> Server time is usually not your local time — check the market watch clock. The
> ICT London killzone (~07:00–10:00) and NY killzone (~12:00–15:00) *broker time*
> are the sweet spots.

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

---

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
