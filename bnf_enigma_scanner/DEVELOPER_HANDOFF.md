# Quant Developer Handoff

## Objective

Build a production-grade, event-aware, order-flow-confirmed mean-reversion scanner inspired by the publicly attributed BNF approach. The system scans a broad universe, but alerts only when all of the following are true:

1. Daily price is exceptionally far below SMA(25).
2. The sell-off is abnormal relative to the instrument and its peers.
3. Point-in-time facts do not indicate permanent fundamental or structural repricing.
4. Exchange order flow shows seller exhaustion, absorption and failed continuation.
5. A defined reclaim creates an executable entry.
6. The structural invalidation is objective.
7. The path back toward the mean provides adequate net reward-to-risk.
8. The setup passes a calibrated out-of-sample probability threshold.

## Non-negotiable constraints

- Candidate timeframe: daily.
- Primary mean: SMA(25), using adjusted prices where appropriate.
- No look-ahead news, fundamentals or corporate-action leakage.
- Full event timestamping and immutable snapshots.
- Futures MBO for FX, indices and metals.
- Native exchange order flow for individual equities.
- No broker CFD volume as a substitute for consolidated order flow.
- No entry from technical oversold status alone.
- Unknown catalyst means no trade.
- Structural/fundamental repricing means no trade.
- No discretionary LLM output can directly place an order.

## Catalyst architecture

Use a multi-stage event engine:

1. Entity resolution.
2. Event extraction.
3. Source deduplication.
4. Novelty and relevance.
5. Scheduled-event matching.
6. Fact hierarchy.
7. Classification.
8. Veto decision.

### Fact hierarchy

Highest severity:
- solvency/default/fraud/delisting;
- earnings/guidance/credit;
- legal/regulatory/existential;
- central-bank or macro surprise;
- sector/commodity supply shock;
- positioning/liquidation/technical;
- unverified social narrative.

### LLM usage

An LLM may summarise evidence and propose an event class, but the final trade gate must be deterministic or produced by a validated model with:
- structured inputs,
- source citations,
- uncertainty,
- audit logs,
- fallback to `UNKNOWN`,
- no trade when confidence is insufficient.

## Order-flow exhaustion specification

Reconstruct:
- best bid/ask;
- depth by level;
- queue additions/cancellations/modifications;
- aggressor-labelled trades;
- sweep events;
- iceberg candidates;
- replenishment;
- microprice;
- short-horizon realised impact.

Features:
- signed trade imbalance;
- cumulative volume delta;
- sell-volume percentile;
- number and depth of bid sweeps;
- marginal price impact per sell contract;
- impact decay across successive sell bursts;
- bid replenishment after aggressive sells;
- cancel-to-add imbalance;
- microprice recovery;
- time spent below prior low;
- traded volume below prior low;
- failed auction;
- reclaim of micro-VWAP;
- divergence between sell flow and price progress;
- hidden-liquidity/iceberg probability.

Exhaustion is valid only when seller aggression remains elevated but:
- downside price progress falls,
- bid liquidity replenishes,
- acceptance below the extreme fails,
- price reclaims a trigger.

## Entry trigger

Long entry can occur only after exhaustion is armed and one of these deterministic triggers fires:

A. micro-VWAP reclaim and hold for N seconds;
B. exhaustion-bar midpoint reclaim;
C. last lower-high break;
D. prior low sweep and close back above;
E. book-imbalance flip plus traded-price reclaim.

Require confirmation persistence to avoid a one-tick false reclaim.

## Invalidation

Use the lowest price with meaningful accepted volume during the exhaustion auction, not merely the visual wick.

Stop buffer:
`max(min_ticks * tick_size, ATR25 * volatility_fraction, book_noise_quantile)`

Cancel before entry if:
- new structural low prints with renewed price impact;
- absorption disappears;
- catalyst changes;
- spread exceeds threshold;
- scheduled event enters lockout window.

## Targets

- T1: 35–50% of distance to SMA(25).
- T2: 65–75% of distance to SMA(25) or anchored VWAP/value node.
- Final: SMA(25), conditional on regime and time horizon.

Backtest both static and path-dependent exits.

## Model validation

Use:
- event-based labels;
- triple-barrier outcomes;
- purged K-fold with embargo;
- rolling walk-forward;
- probability calibration;
- separate models per asset class;
- separate regime buckets;
- transaction-cost model;
- latency model;
- Monte Carlo sequencing;
- false-discovery controls for feature selection.

Primary metrics:
- precision among surfaced alerts;
- expected value net of costs;
- maximum adverse excursion;
- time to target;
- calibration error;
- tail loss;
- alert frequency;
- capacity.

Optimise precision before recall.

## Suggested production services

- `market_data_service`
- `reference_data_service`
- `corporate_actions_service`
- `news_event_service`
- `macro_calendar_service`
- `mbo_reconstruction_service`
- `feature_store`
- `candidate_engine`
- `catalyst_engine`
- `exhaustion_engine`
- `risk_engine`
- `probability_service`
- `alert_service`
- `audit_store`
- `research_backtester`

## Deliverables

1. Data dictionary.
2. Point-in-time dataset builder.
3. MBO reconstruction tests.
4. Candidate scanner.
5. Catalyst classifier and deterministic veto layer.
6. Exhaustion features.
7. Entry/risk engine.
8. Backtest and calibration report.
9. Paper-trading deployment.
10. Live monitoring dashboard and alert audit trail.
