# BTC-V3-APPLICATION-SERVICE-BOUNDARY-01

## Boundary outcome

BTC research closure and Demo runtime orchestration now live under
`quant_crypto/application`. Backend service modules are compatibility facades
that compose concrete infrastructure and preserve the existing API imports.

- `CryptoClosureService` owns the data-integrity, candidate validation,
  promotion-gate and research-evidence workflow.
- `BtcDemoRuntimeService` owns catalog/readiness, runtime delegation and
  read-only observation orchestration.
- Application code receives research, promotion, market-data, runtime,
  observation and evidence dependencies through ports.
- Closure evidence is staged through a unit of work and published only after
  the application operation succeeds.
- The file adapter uses temporary files plus atomic replacement and removes
  already-installed outputs if a multi-file commit fails.

No `quant_shared`, `quant_us`, schema, enum, frontend, API router or
`backend/app/api/app_factory.py` file was modified.

## Characterized compatibility contract

Before production code was changed, tests locked the existing synchronous
closure API behavior:

- successful requests keep the response schema and request mapping;
- service `ValueError` remains HTTP 400;
- order/live-related extra fields remain HTTP 422 before the service is called.

Existing background-task, Demo runtime API, closure service, architecture,
shared-boundary, exchange-runtime and gate-snapshot regressions remain green.

## Repository and UoW contract

`ClosureEvidenceUnitOfWork` exposes:

- `stage_candidate_evidence(run_id_prefix, payload)`;
- `commit()`;
- `rollback()`.

The application creates one UoW per closure call. Any application or commit
exception invokes rollback. A previously published run identity is immutable
and repeated staging returns the existing path without overwriting it.

Downstream research/backtest engines remain behind `ResearchBacktestPort`;
their own ledger and manifest transaction contracts are not reimplemented by
this Goal.

## Shared-entry wiring contract

No shared-entry edit is required for this delivery:

1. `backend/app/core/deps.py` continues importing the two existing backend
   service symbols.
2. Those service symbols are now thin composition facades over the BTC
   application services.
3. `backend/app/api/app_factory.py` continues to parse validated requests,
   call the injected service and map the response/error without BTC business
   logic changes.

If an integrator later replaces the facade construction, it must preserve the
current constructor defaults, route schemas, HTTP 400/422 behavior, task
progress callback semantics and all false safety flags.

## Explicit exclusions and gates

- The unrelated, unintegrated
  `quant_crypto/application/btc_backtest_identity.py` change was not read,
  modified or included.
- No network collection, secret access, exchange/private/order/live endpoint,
  Demo order, paper queue or broker call was made.
- This is an engineering boundary delivery only:
  `quality_checked=true`, while `research_ready=false`,
  `backtest_ready=false`, `promotion_evidence_ready=false`,
  `paper_ready=false` and `live_ready=false`.
