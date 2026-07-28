# Strategy Tester & Optimization Guide — Institutional Blxck Mirror

This EA is discretion-modelled, so **calibration matters more than raw optimization**.
Follow this order — the first two steps decide 80% of your results.

---

## 0. Before you touch the tester

1. **Set `InpServerToNYOffset` correctly** (see README). If the sessions are wrong,
   every backtest below is meaningless.
2. **Download history**: Ctrl+U → download D1, H4, M15, M1 for your symbol.
3. Load the matching preset (`presets/EURUSD.set` or `presets/GBPUSD.set`) from the
   EA **Inputs → Load** button, then adjust.

---

## 1. Correct tester settings

| Setting | Value | Why |
|---------|-------|-----|
| Model | **Every tick based on real ticks** | The IFVG/sweep logic is wick-sensitive |
| Period | **M15** (the setup TF) | EA self-manages other TFs |
| Deposit / Leverage | realistic for your account | affects lot sizing |
| Optimization | **Disabled** for the first pass | eyeball behaviour first |
| Dates | ≥ 12 months, include trending **and** ranging regimes | avoid curve-fitting to one regime |

> The **news filter is disabled inside the tester** (no calendar) — that's expected.
> Test with it off, then keep it **on** in live/demo.

---

## 2. First pass — sanity, not profit

Run once with the preset. Open **Results → Chart** and confirm:

- Entries only fire in the London/NY killzones (NY-time).
- Longs come after a **sweep of the previous session's low**; shorts after a high sweep.
- TP lands on liquidity / SD-projection confluence (gold lines).
- SL sits beyond the sweep extreme (or the ATR floor).

If entries look wrong, fix **timing/structure inputs**, not the risk numbers.

---

## 3. Optimize in the right order (one group at a time)

Optimizing everything at once overfits. Do these passes, keeping the best of each:

### Pass A — Structure / timing (biggest edge)
| Input | Range | Step |
|-------|-------|------|
| `InpSwingStrength` | 2 – 4 | 1 |
| `InpStructLookback` | 40 – 90 | 10 |
| `InpSweepMinPips` | 0.3 – 2.0 | 0.1 |
| `InpSweepMaxBars` | 5 – 12 | 1 |

### Pass B — Entry quality (win rate)
| Input | Range | Step |
|-------|-------|------|
| `InpMinFvgPips` | 0.3 – 2.0 | 0.1 |
| `InpMinBodyPct` | 45 – 70 | 5 |
| `InpDisplaceAtrMult` | 0.3 – 1.0 | 0.1 |

### Pass C — Targets / RR (profit factor)
| Input | Range | Step |
|-------|-------|------|
| `InpMinRR` | 1.5 – 3.5 | 0.25 |
| `InpTargetMode` | 0 – 2 | 1 |
| `InpSDAlignPips` | 4 – 20 | 2 |
| `InpAtrMultSL` | 0.8 – 2.0 | 0.1 |

### Pass D — Management
| Input | Range | Step |
|-------|-------|------|
| `InpPartialPercent` | 50 – 85 | 5 |
| `InpBreakEvenAtR` | 0.5 – 1.5 | 0.25 |

---

## 4. Choose the winner by the right metric

Do **not** sort by net profit. Rank by, in order:

1. **Profit factor** ≥ 1.5 (ideally > 1.8)
2. **Recovery factor** and low **max drawdown %**
3. **Expected payoff** > 0 with a **reasonable trade count** (enough samples)
4. Win rate is secondary — a 45% win rate at 2.5R beats 70% at 1R.

Beware any result with very few trades or a single monster winner — that's a fit,
not an edge.

---

## 5. Validate out-of-sample (the step most people skip)

1. Optimize on, say, Jan–Sep.
2. Run the single best set **unchanged** on Oct–Dec (data it never saw).
3. If it holds up, forward-test on a **demo account** for several weeks.
4. Only then consider small live risk (`InpRiskPercent` 0.25–0.5 to start).

---

## 6. Realistic expectations

A robust set should show a **positive expectancy across many trades with controlled
drawdown**, not a win every day. If a preset only looks good on one symbol, one
period, or with news off — it's overfit. Consistency comes from the daily guards
(`InpDailyMaxLossPct`, `InpDailyTargetPct`, `InpCooldownMin`) turning a real edge
into steady compounding, not from squeezing the backtest.
