# BNF ENIGMA — Institutional Mean-Reversion Scanner

A developer-ready Python research scaffold for detecting BNF-style daily dislocations, rejecting valid repricing events, confirming seller/buyer exhaustion with exchange order flow, and producing only high-conviction mean-reversion setups.

## Important interpretation

The public strategy most commonly attributed to Takashi Kotegawa ("BNF") is based on **daily price divergence from a 25-day moving average**, especially unusually large downside deviations. Public descriptions are incomplete and sometimes inconsistent, so this project treats the BNF rule as the *candidate generator*, not as a fully documented mechanical system.

This code does not claim to reproduce BNF's private process. It creates a testable, modern implementation of the same core idea.

## Design principles

1. **Daily timeframe only for the primary BNF signal**
   - 25-session simple moving average.
   - Percentage divergence from the SMA.
   - Robust z-score of daily returns.
   - ATR-normalised displacement.
   - Cross-sectional percentile within the relevant asset class.

2. **Never buy merely because price is far below the mean**
   - First classify whether the move is probably:
     - emotional / technical,
     - temporary liquidity stress,
     - scheduled macro repricing,
     - company-specific fundamental repricing,
     - structural / regime change,
     - unknown.
   - Fundamental or structural repricing normally vetoes the trade.

3. **Require objective exhaustion**
   - Aggressive sell volume reaches a climax.
   - Price impact per unit of sell volume decreases.
   - Bid replenishment / absorption appears.
   - Order-flow imbalance improves.
   - New lows fail to gain meaningful acceptance.
   - Price reclaims an objective trigger level.

4. **Only surface A-tier candidates**
   - Candidate score >= configured threshold.
   - No hard veto.
   - Minimum reward-to-risk to the 25-day mean.
   - Liquidity and spread checks pass.
   - Event risk lockout passes.
   - Setup is ranked within its asset class.

5. **Use listed futures for order-flow validation**
   - Equities: native exchange data.
   - Indices: ES/NQ/RTY/YM futures.
   - Metals: GC/SI/HG futures.
   - FX: 6E/6B/6J/6A/6C/6S futures as centralised proxies.
   - Spot FX/CFD execution can be mapped to the corresponding futures signal, but broker tick volume must not be treated as true consolidated order flow.

## Recommended production data

- Daily OHLCV and corporate actions: exchange-grade consolidated data.
- News and event metadata: a licensed structured news feed with timestamps, entities, novelty, relevance and sentiment.
- Fundamentals: earnings, guidance, filings, analyst revisions, credit events and corporate actions.
- Macro: official economic calendar plus actual/forecast/previous values.
- Order flow: CME Market-by-Order (MBO) or equivalent full-depth event data.
- Reference mappings: cash symbol ↔ futures proxy ↔ sector ↔ country ↔ currency.

## Pipeline

```text
Universe
  -> Daily BNF displacement candidate
  -> Liquidity / tradability gate
  -> Catalyst collection
  -> Catalyst validity classification
  -> Regime vetoes
  -> Intraday MBO exhaustion engine
  -> Entry trigger
  -> Invalidation and target construction
  -> Probability calibration
  -> Rank and alert only top candidates
```

## Signal lifecycle

### 1. Candidate
Daily close is abnormally far from SMA(25).

### 2. Investigation
The catalyst engine gathers all facts in a configurable window around the sell-off.

### 3. Veto or watch
Structural/fundamental repricing is vetoed. Ambiguous cases remain watch-only.

### 4. Exhaustion armed
Microstructure features show that aggressive sellers are losing marginal impact.

### 5. Entry confirmed
Price reclaims a predefined trigger such as:
- exhaustion-bar midpoint,
- micro-VWAP,
- last lower high,
- opening-range low,
- prior session low after a failed auction.

### 6. Risk plan
- Invalidation: beyond the accepted extreme plus a volatility and liquidity buffer.
- Primary target: conservative partial mean.
- Final target: SMA(25), unless event risk or resistance requires an earlier exit.

## Default scoring

| Component | Weight |
|---|---:|
| 25-day divergence extremity | 20 |
| Robust return anomaly | 10 |
| ATR displacement | 10 |
| Cross-sectional abnormality | 10 |
| Catalyst classified non-structural | 15 |
| Sell-flow climax | 10 |
| Absorption / replenishment | 10 |
| Failed auction / reclaim | 10 |
| Regime suitability | 5 |

Hard vetoes override the score.

## Hard veto examples

- Earnings miss plus material guidance cut.
- Fraud, insolvency, delisting or accounting concern.
- Credit downgrade with widening spreads.
- Regulatory ban or existential litigation.
- Central-bank surprise that changes the rate path.
- Confirmed geopolitical supply shock for the instrument.
- Unresolved data quality.
- Halt, limit state, broken market or extreme spread.
- No order-flow confirmation.
- Reward-to-risk below configured minimum.

## Entry and invalidation

For a long mean-reversion setup:

- `entry`: first valid reclaim after exhaustion.
- `structural_low`: lowest accepted auction price during the dislocation.
- `liquidity_buffer`: max of tick-based buffer, local volatility buffer and order-book noise estimate.
- `stop`: structural_low - liquidity_buffer.
- `target_1`: 0.35–0.50 retracement toward SMA(25).
- `target_2`: anchored VWAP / value node.
- `target_3`: SMA(25), only when regime and event calendar allow.
- Setup is rejected unless target_1 offers acceptable R and target_2/mean offers the configured minimum R.

## Probability policy

Do **not** hard-code claims such as "90% win probability." The production system must train and calibrate probabilities using:
- walk-forward validation,
- purged/embargoed cross-validation,
- asset-class separation,
- transaction costs,
- realistic latency and slippage,
- delisted securities,
- point-in-time news and fundamentals,
- strict out-of-sample periods.

The alert probability should be generated by a calibrated model (isotonic or Platt scaling) and must include sample size and confidence bounds.

## Running the scaffold

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python example_run.py
pytest
```

The included example uses synthetic data and demonstrates the interfaces. It is not a live trading system.

## Acceptance criteria for a quant developer

1. All data are point-in-time and survivorship-bias free.
2. No article published after the decision timestamp can enter a feature.
3. Daily corporate-action adjustments are correct.
4. MBO reconstruction is deterministic and exchange-sequence aware.
5. Every alert is reproducible from an immutable feature snapshot.
6. Every veto has a machine-readable reason code.
7. Costs, spread, slippage and latency are modelled.
8. Backtest uses walk-forward splits with purging and embargo.
9. Probabilities are calibrated separately by asset class and regime.
10. Live and backtest code share the same feature functions.
