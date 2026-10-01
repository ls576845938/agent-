# No-Production-Data Engineering Hardening Sprint

## Why The Data Mainline Is Paused

The project currently has no production PIT bundle. US equity data remains
`L1_sample_non_pit`, `promotion_clean=false`, and research-only. Without real
PIT membership, delisting coverage, corporate actions, symbol mapping, and
adjustment replay, the data line cannot move to L4.

## Safe Work Without Production Data

The safe path is engineering hardening that does not claim investment evidence:

- Fixture portfolio event-ledger plumbing.
- No-lookahead and leakage contracts.
- Risk budget and kill switch contracts.
- Artifact lineage health checks.
- Registry failure explanations.
- BTC audit-only boundary checks.
- CI and documentation cleanup.

## Fixture Ledger Role And Limits

The fixture ledger proves that a minimal portfolio chain can carry alpha scores,
targets, rebalance orders, simulated fills, and ledger PnL. It uses embedded
fixture data and remains `source_type=fixture`.

It is not alpha evidence, not production event-ledger validation, not
promotion-ready, and not paper-review evidence.

## No-Lookahead Tests

The no-lookahead tests document timing constraints for factor labels,
walk-forward folds, and portfolio rebalance decisions. They are contract tests
that prevent future refactors from weakening timestamp boundaries.

## Risk And Kill Switch Contracts

Risk budget tests make missing drawdown, position, or exposure limits block
promotion. Kill switch tests verify that default limits are enabled and that
loss or order-failure triggers fail closed.

## Artifact Health Check

The artifact health report checks whether expected artifacts exist, validate
against schemas, avoid path escapes, avoid hash mismatches, and are not stale.
Passing artifact health does not mean promotion-ready.

## Failure Explanations

The global registry now explains why data lineage, factor evidence, portfolio,
BTC, and paper/live are blocked. These explanations are derived from actual
blockers and do not change gate states.

## Not Promotion-Ready

None of this work changes:

- `paper_queue_status=locked`
- `live_status=frozen`
- `candidate_passed_internal_gate=0`
- `promotion_clean=false`
- `current_factor_candidates=[]`

Fixture ledger and artifact health are engineering readiness signals only.

## Next Direction

If no production data is available, continue engineering hardening. If time is
available for data work, return to manual data acquisition or vendor export and
build a real production PIT bundle.
