# BTC candidate offline entry final independent acceptance

Ticket: `INTEGRATE-BTC-CANDIDATE-OFFLINE-ENTRY-20260925`  
Role: short-lived `integrator`  
Change risk: `unclassified`  
Decision: source integration and independent offline acceptance passed on the
integrator branch at `quality_checked` only

This is not a main integration, deployment, publication, promotion, paper, or
live acceptance.

## Identity and scope

- Registered-main baseline: `9c1dac906f4b4527aa247d14f18497f56e9d8464`.
- Corrected producer source: `6987c757cbca33bbd4a946236120b168eabac5d4`.
- Producer handoff commit: `62800fe3a84a74549b7a61faca6e65feb3826faa`.
- Integrator cherry-picks: source `6a2803ec6`, handoff `2c44139c0`.
- Frozen independent test HEAD:
  `2c44139c0ea63804a0d538b7920e236133e6193d`.
- Branch:
  `agent/integrator/integrate-btc-candidate-offline-entry-20260925`.
- Planner sparse worktree:
  `D:/vibe coding/Obsidian/量化系统/worktrees/integrator-integrate-btc-candidate-offline-entry-20260925`.

The earlier rejection report commit `47a2dca48` and rejected handoff commit
`c0471225d` remain in history unchanged. The corrected source and handoff were
ordinary cherry-picks; no reset, rebase, force, or history rewrite occurred.
This review writes only this report and its later append-only integrated event;
it does not author or modify business behavior.

## Pre-consumption and final integrity

Before cherry-pick, the corrected producer event
`published-btc-candidate-offline-entry-20260925-6987c757c`, its package-runtime
dependency, and the prior rejected event all validated as `status=valid`.
Ancestry passed for `c3a6fb0... -> 6987c757... -> 62800fe3...` and
`3950f16c... -> 6987c757...`. All 32 declared Git-object SHA-256 values matched.
The correction delta contained ten declared paths; its handoff commit added only
the published envelope.

Initial scoped state was clean across 32 deliverables plus this ticket's report
and handoff scopes: 34 checks, `dirty_count=0`. After cherry-pick and all tests,
the integrator combination tree still matched all 32 published hashes, all 34
scopes were clean, and no ticket pytest process remained.

No production artifact, manifest, runtime pointer, candidate, observation data,
or economic ledger was built or changed. Test-only state is under
`D:/vibe coding/Obsidian/量化系统/integration_tmp/INTEGRATE-BTC-CANDIDATE-OFFLINE-ENTRY-20260925-6987/run`
and is not a deliverable.

## Independent identity review

The prior P1 is closed at source `6987c757...`. The complete immutable job seal
is the single authority across start, resume, worker update, stored result,
paged decisions, and result rendering. Independent read-only probes observed:

- missing job seal -> `offline_job_identity_missing_or_invalid`;
- foreign paged decision -> `offline_evidence_identity_mismatch`;
- foreign result with recomputed nested/result hashes ->
  `offline_evidence_identity_mismatch`;
- correctly bound evidence -> `valid=true`.

The frontend compares every authoritative identity field plus the server-issued
identity digest. It does not independently recompute a cryptographic SHA in
JavaScript. No new P0/P1 was found. Conservative PID reuse remains a documented
P2 availability limitation and was not expanded.

## Independent test matrix

Every pytest command used the registered-main canonical `.venv`,
`PYTHONUTF8=1`, `-B -X utf8`, `-p no:cacheprovider`, and a distinct external
`--basetemp`. The worktree used the registered-main `frontend/node_modules`
through a read-only junction; no package install or main-tree write occurred.
No Vite, Playwright web server, worktree frontend, or formal backend service was
started. The lifecycle test's own temporary loopback FastAPI/CLI service was
isolated and ended with its test process.

- Identity failure-first selectors:
  `test_candidate_offline_access.py -k 'complete_cross_job or resume_rechecks'`
  -> `2 passed, 49 deselected` in `8.08s`.
- B remainder, excluding those two selectors:
  access + CLI -> `50 passed, 2 deselected` in `158.01s`.
  Combined non-overlapping B result: `52 passed`. This includes the Node SSR
  contract tests once; their internal subtests are not counted again.
- TypeScript:
  `tsc --noEmit -p frontend/tsconfig.json` -> exit `0`.
- A, offline entry + registered execution:
  `28 passed` in `1083.42s`.
- C, complete four-case lifecycle:
  `4 passed`, 3 dependency warnings, in `843.09s`.
- D1, candidate package runtime + inference:
  `53 passed` in `28.13s`.
- D2, V0 freeze + V1 Donchian offline:
  `34 passed, 1 existing opt-in archive skip` in `16.30s`.
- D3, legacy Qlib policy + V3 Qlib offline:
  `26 passed` in `311.30s`.
- D4, exact IOC/OMS compatibility selectors:
  `17 passed` in `4.81s`.

Unique independent total: `214 passed, 1 existing skip`; no failed test. Producer
counts are not substituted for these results. Full-repository tests, production
deployment, current-main artifact rebuild, browser visual QA, real candidate or
market-data qualification, annual replay, protection-trigger fill execution,
and registered-envelope legal partial opening were not run.

## Decision, remaining blockers, and safety flags

The corrected source is independently accepted for this bounded offline-entry
candidate on the integrator branch. It may be presented to the architect/main
owner for a separate main-integration decision. This report and the integrated
event do not merge main, start services, change environment, or enable any
capability.

Remaining limitations and owners:

- `owner:main_integration`: source is not in main and no deployment/backend
  restart/canonical browser acceptance was performed.
- `owner:factory_evidence`: no qualifying real frozen candidate or observation
  evidence exists; synthetic fixtures are not real-market or promotion evidence.
- `owner:compatibility`: old or incomplete job/result/decision identity envelopes
  remain fail-closed; no migration, evidence rewrite, reseal, or ledger reset.
- `owner:capability`: registered protection trigger execution remains unsupported;
  sampled SL/TP touch durably blocks while preserving position/fills/ledger. The
  registered 0.01 FOK envelope still does not prove legal partial opening.
- `owner:operator`: conservative PID reuse remains a P2 availability limitation.

`demo_control_enabled`, `promotion`, `paper`, `live`, `private`, `order`,
`real_order`, `transfer`, `withdraw`, `execution_permission`,
`runtime_worker_enabled`, and `runtime_observed` all remain false. No secret,
external network, broker, exchange, private, order, or live endpoint was used.

## Governance evidence

Read: `AGENTS.md`, `.codex/agents/integrator.toml`, knowledge README,
non-negotiables, shared pitfalls, cross-agent coordination, delivery risk policy,
source architecture/acceptance reports, and the `quant-agent-preflight`,
`quant-gate-evidence-review`, and `quant-agent-handoff` skills. No raw pitfall log
was bulk-read. There is no separate integrator pitfalls Markdown; the role TOML
and cross-agent coordination contract are the role-specific rules.

Catalog hash:
`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`.

Active IDs:
`GOV-CONCURRENCY-001,GOV-DIRTY-001,GOV-ENGINEERING-CIRCUIT-001,GOV-HANDOFF-001,GOV-OBJECTIVE-001,GOV-PITFALL-001,GOV-ROOT-001,GOV-STORAGE-001,GOV-WORKTREE-001,QSYS-GATE-001,QSYS-SECURITY-001,GOV-PROMPT-001,GOV-WINDOWS-001`.
