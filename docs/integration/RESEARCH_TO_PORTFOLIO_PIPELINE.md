# Research to Portfolio Pipeline

Status: draft for the Qlib + PyPortfolioOpt integration phase.

## Purpose

This document defines the research-only pipeline from cleaned daily market data to portfolio target weights.

The pipeline is intentionally narrow:

- daily only
- research only
- no live execution
- no direct broker order path
- no minute data in this phase

## End-to-End Flow

1. Read cleaned daily data and manifests from the QuantStation data lake.
2. Validate the data against the Qlib export contract.
3. Export a Qlib-compatible research dataset.
4. Run the Qlib workflow only if the optional dependencies are installed.
5. Import `pred_score` into a QuantStation-owned research score artifact.
6. Build daily expected returns from imported scores.
7. Build covariance from past daily returns only.
8. Optimize long-only target weights with PyPortfolioOpt.
9. Persist portfolio run artifacts.
10. Feed the result back into the normal research, backtest, and promotion-gate path.

## Required Evidence

Every run must preserve the following lineage:

- `data_version`
- `strategy_version`
- `params`
- `cost_model`
- `slippage_model`
- `commit_hash`

This metadata is part of reproducibility and must not be omitted from the experiment record.

## Boundary Conditions

The pipeline must not bypass the existing QuantStation gate stack.

It must not:

- call the broker directly
- emit orders directly from Qlib
- emit orders directly from PyPortfolioOpt
- write ledger entries
- declare paper readiness
- declare live readiness
- use future data
- implicitly download missing data

The only acceptable downstream handoff is into the existing internal research, backtest, risk, and promotion flow.

## Artifact Layout

Expected run-scoped outputs:

- `artifacts/qlib_runs/<run_id>/`
- `artifacts/portfolio_runs/<portfolio_run_id>/`

Those directories hold adapter-owned research artifacts only. They are not execution state.

## Promotion Semantics

Qlib output is research evidence.

PyPortfolioOpt output is a target-weight proposal.

Neither output may skip the internal event-driven backtest, cost stress, walk-forward checks, or promotion gate. Any later paper review must still be handled by the existing platform boundary.

## Phase Limit

This phase stops at research and portfolio construction.

It does not introduce:

- paper-trading submission
- live-trading submission
- minute-bar processing
- order routing changes
- execution-path rewiring
