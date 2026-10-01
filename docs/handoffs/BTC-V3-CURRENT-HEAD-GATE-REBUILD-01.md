# BTC-V3-CURRENT-HEAD-GATE-REBUILD-01

## Scope

This goal adds an offline, BTC-owned reconstruction boundary for the
current-HEAD promotion decision, dashboard and domain read model. It does not
collect data, read credentials, connect to private/order endpoints, start Demo
or paper execution, or write a paper queue.

## Authoritative input

The only OKX-native latest pointer accepted by this rebuild is:

`artifacts/btc_okx_native_backtest_evidence/latest_manifest.json`

The pointer must bind one immutable manifest and one immutable evidence file to
the same full `source_code_commit`, `run_id` and `data_version`. File SHA-256,
immutable URI/version and input-lineage SHA-256 values are verified before the
pointer can count as current-HEAD evidence. A missing or invalid pointer is
represented by a structured blocker; it is never replaced by mutable SQLite or
another worktree's files.

## Transaction and concurrency contract

The builder:

1. acquires the existing exclusive BTC gate writer lock;
2. fingerprints only explicit BTC source pathspecs and exact evidence inputs;
3. evaluates the authoritative pointer and external evidence;
4. builds gate, dashboard and domain read model in memory;
5. validates full-HEAD, run and fail-closed safety invariants;
6. stages all three JSON outputs before replacing any latest file;
7. publishes the immutable gate-run manifest and latest pointer last.

An exception before publication does not update latest outputs. A structurally
valid blocked decision may publish; wrapper exit success does not mean
promotion, paper or live readiness.

## Evidence-driven blockers

The evaluator independently checks:

- current-HEAD OKX-native manifest/evidence lineage;
- timestamp-aligned L2 depth-fill mapping;
- a current natural non-flat sample;
- observed funding cashflow;
- private-WS reconciliation observation;
- the 30/60-day observation window;
- current manual approval.

Missing, stale, wrong-HEAD or incomplete evidence keeps its blocker. Fixture,
historical and diagnostic reports cannot clear promotion evidence.

## Outputs

- `artifacts/btc_promotion_gate_control/latest/btc_promotion_gate_control_report.json`
- `artifacts/btc_perpetual_execution_evidence/latest/btc_perpetual_execution_evidence_report.json`
- `artifacts/btc_manual_paper_review_approval/latest/btc_manual_paper_review_approval_report.json`
- `artifacts/btc_paper_candidate_packet/latest/btc_paper_candidate_packet_report.json`
- `artifacts/btc_paper_readiness/latest/btc_paper_readiness_report.json`
- `artifacts/btc_gate_dashboard/latest/btc_gate_dashboard.json`
- `artifacts/btc_gate_report_consistency/latest/btc_gate_report_consistency_report.json`
- `artifacts/btc_domain_read_model/latest/btc_domain_read_model.json`
- `artifacts/btc_gate_runs/latest_pointer.json`
- `artifacts/btc_current_head_gate_rebuild/latest/btc_current_head_gate_rebuild_report.json`

All artifact outputs are generated evidence and remain outside the Git
deliverable. The committed deliverable is the BTC application service, CLI,
schema, contract tests and this wiring/operations note.

## Readiness and safety

`quality_checked`, `research_ready`, `backtest_ready` and
`promotion_evidence_ready` are separate fields. A blocked current-HEAD
reconstruction is `quality_checked` only.

The following remain false regardless of structural rebuild success:

- promotion, paper and paper-queue writes;
- live and live unlock;
- private, order and broker access;
- real orders and withdrawal.
