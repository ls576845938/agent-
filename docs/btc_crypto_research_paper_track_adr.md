# ADR: BTC Crypto Research/Paper Track Boundary

**Status:** Accepted
**Date:** 2026-06-25
**Owner:** BTC development agent
**Affected Systems:** BTC crypto research, BTC paper validation, BTC artifacts
**Unaffected Systems:** US equity V1 research and production line

---

## Context

BTC now has real research evidence, event-ledger backtests, ledger PnL, cost/funding/fee evidence, manual promotion review, and `live=frozen` guardrails. The remaining risk is boundary confusion: earlier registries and readiness reports could describe the same BTC candidate with different paper states, and BTC artifacts still sit beside US equity artifacts in the same repository.

BTC is not a US equity strategy variant. It is a crypto perpetual research/paper track with 24/7 trading, funding intervals, exchange metadata, venue precision, and crypto-specific market data lineage. It may share repository conventions and high-level quant rules with US equity, but it must not inherit US equity V1 assumptions about trading calendar, corporate actions, universe membership, broker adapter behavior, or provider promotion gates.

This ADR records the BTC boundary before PIT data contracts, evidence-pack aggregation, forecast/portfolio/risk, OMS lifecycle, and replay audit work continue.

---

## Decision

BTC is an independent crypto research/paper track. It has its own state authority, data contract, evidence artifacts, promotion gates, paper lifecycle, and replay/audit path. US equity V1 remains the mainline equity track and is not the authority for BTC paper readiness.

The authoritative BTC state path is:

`research_only -> backtest_validated -> paper_candidate_ready -> paper_review_pending -> paper_observing`

`live_status` remains `frozen` throughout this ADR. This ADR does not authorize live trading.

---

## Boundary Rules

1. BTC artifacts must use BTC-specific schemas, reports, and registries. US equity schemas cannot be used as the BTC source of truth.
2. `btc_current_status` is the BTC state reconciler; it must compare `btc_paper_readiness`, BTC registry, and global registry for contradictions.
3. `btc_paper_readiness` may approve paper observation, but it does not unlock live.
4. BTC registry and global registry must inherit the BTC authoritative paper state instead of recomputing it from generic candidate counts.
5. Research/backtest code must not call exchange, broker, private, or order endpoints.
6. BTC data loaders must treat point-in-time visibility as a domain contract, not an optional report annotation.
7. BTC paper OMS work must be implemented under the BTC execution boundary and cannot reuse US equity broker assumptions without an explicit adapter contract.
8. US equity production-line work may continue independently; BTC changes must avoid editing US equity files unless a shared schema or registry contract explicitly requires it.

---

## Module Ownership

| Module | BTC responsibility | Explicitly not BTC responsibility |
|---|---|---|
| `data` | BTC raw/derived crypto data, PIT visibility, funding, fee tier, exchange info, immutable/versioned manifests | US equity universe, corporate actions, survivorship, equity adjustment policy |
| `research/backtest` | BTC event-ledger research, Signal/Forecast evidence, ledger-derived PnL, cost/funding stress | Broker/exchange order submission |
| `portfolio_risk` | BTC forecast-to-target conversion, crypto exposure/risk budget, cost-aware rebalance checks | Direct strategy optimization without trial registry |
| `oms_execution` | BTC paper order lifecycle, idempotent `client_order_id`, reject/retry/cancel/reconcile | Live trading unlock |
| `monitoring_replay` | BTC artifact DAG, deterministic replay, incidents, state conflict alerts | UI-only summaries without replay evidence |
| `backend/app` | Orchestration and API wiring only | Core BTC quantitative rules |

---

## Required Follow-up Work

This ADR enables the remaining P0/P1/P2 engineering work but does not complete it.

P0 follow-ups:

1. Enforce PIT fields on BTC 1m/resample/funding/fee/exchange_info inputs: `event_time`, `available_time`, `ingested_at`, `processed_at`.
2. Make BTC raw data immutable and derived data versioned with source hash, transform version, parameters, and output hash.
3. Build a BTC evidence-pack aggregator that emits one complete promotion evidence artifact.
4. Add a BTC trial registry for accepted, rejected, and failed candidate configurations.
5. Add no-lookahead and truncation-consistency tests.

P1/P2 follow-ups:

1. Add explicit Forecast/Alpha and BTC portfolio/risk-budget layers before target generation.
2. Add BTC venue rules and cost-aware rebalance checks before order intent generation.
3. Add paper OMS lifecycle and execution-quality metrics.
4. Add BTC audit DAG, replay engine, structured logs, and incident artifacts.

---

## Consequences

Positive:

- BTC paper state has one authority and can be tested for contradictions.
- US equity and BTC can be developed in parallel without treating one system as the other's implicit template.
- Crypto-specific PIT, venue, funding, and 24/7 lifecycle rules have a dedicated home.

Negative:

- Some shared registry code must carry explicit BTC branches until service-layer ports are extracted.
- Existing tests that assumed `pending_review` as the final BTC queue state must distinguish pre-review from approved paper observation.

---

## Non-Goals

- This ADR does not authorize live trading.
- This ADR does not implement PIT enforcement, paper OMS, Forecast/Portfolio/Risk, replay, or incident handling.
- This ADR does not refactor US equity V1.
- This ADR does not make BTC production-ready by itself.
