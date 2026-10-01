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

## Orchestration Entry Point

The repo now provides a single orchestration module for the research-to-execution consistency check:

`python -m quant_us.research.orchestration.research_execution_pipeline`

The orchestration layer reuses the existing adapter outputs instead of rebuilding them from scratch:

1. import Qlib `pred_score` into `research_model_scores.parquet`
2. compile the Qlib lineage manifest
3. build expected returns and covariance
4. optimize portfolio target weights
5. import target weights into internal `TargetPosition` artifacts
6. run the canonical event-driven backtest through the risk gate
7. run cost-stress scenarios on the same target-position path
8. run walk-forward slices on the same target-position path
9. emit a pipeline result manifest and evidence pack

Outputs are written under:

- `artifacts/research_execution_runs/<pipeline_run_id>/pipeline_result_manifest.json`
- `artifacts/research_execution_runs/<pipeline_run_id>/evidence_pack.json`

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

The orchestration layer fails closed when it cannot prove the target-weight path reached the internal risk gate correctly. Examples:

- no target positions were generated
- no risk checks were observed
- any risk rejection occurred
- any pending order intents remained at the end of the run
- imported score data versions do not match the cleaned-bar manifests used for replay

## Phase Limit

This phase stops at research and portfolio construction.

It does not introduce:

- paper-trading submission
- live-trading submission
- minute-bar processing
- order routing changes
- execution-path rewiring
