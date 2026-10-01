# US-V3-DOMAIN-READ-MODEL-01 integrator wiring

The producer delivery is US-only. It deliberately does not modify
`backend/app/api/app_factory.py`, shared API schemas, `App.tsx`,
`shared-types.ts`, Team Context code, or global Workbench code.

## Backend wiring

In the integrator-owned `app_factory.py`:

1. Import `build_us_equity_domain_read_model_router`.
2. Construct `USCommittedEvidenceRepository(repo_root=settings.repo_root)`.
3. Construct `USDomainReadModelService` with the repository and a current Git
   HEAD resolver.
4. Include the router with prefix `/api`, using the existing
   `verify_api_key`.

The registered surface must contain only
`GET /api/research/us-equity/domain-read-model`. POST/PUT/PATCH/DELETE must
remain 405. Do not add builder, sync, backtest, paper, reset, broker, or order
callbacks.

## Frontend and Team Context

`USEquityWorkspace` already renders the US-local operator evidence view in a
separate zone above the retained legacy research controls. No `App.tsx` or
shared frontend type wiring is needed.

Current main already declares the exact US Team Context candidate path:

`artifacts/us_equity_strategy_production_line/latest/us_equity_operator_read_model.json`

After all integration commits are final, run:

```text
py -3 scripts/build_us_equity_domain_read_model.py --repo-root .
```

Then run Team Context and assert `us_equity` has
`freshness=current_head` and does not report `domain_read_model_missing`.
The expected domain status is still `blocked`; this is correct and must not be
converted into promotion, paper, or live readiness.

## Integration verification

Run the US domain contract, backend API contract node added by the integrator,
frontend lint/build/smoke, and the US domain Playwright E2E. Rebuild the
projection after the final integration commit so `source_head` matches the
actual integrated HEAD.
