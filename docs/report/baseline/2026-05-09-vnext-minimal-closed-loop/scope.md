# Scope

## Baseline Name

`2026-05-09-vnext-minimal-closed-loop`

## Goal

Document the current P0 closed-loop boundary for QuantStation VNEXT without changing business code.

The baseline is limited to the smallest trustworthy loop that is already represented in the repo:

1. data manifest creation and validation
2. unified backtest evidence
3. canonical research-gate evidence
4. paper-runtime fail-closed behavior
5. surface alignment across README, CLI report commands, and boundary docs

## In Scope

- current docs for the minimal closed loop
- current CLI/report entry points for reading persisted evidence
- current baseline acceptance language
- current report-level evidence map

## Out of Scope

- strategy logic changes
- broker integration changes
- live trading enablement
- automatic paper submission
- new research heuristics
- new backtest logic
- any change under `quant_us/**`, `backend/**`, `tests/**`, `scripts/**`, `pyproject.toml`, or `Makefile`

## Constraint

This baseline must describe only the current system boundary and the current round's target state. It must not imply automated paper trading or automated live trading.
