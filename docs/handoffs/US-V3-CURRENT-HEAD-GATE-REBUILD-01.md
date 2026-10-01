# US-V3-CURRENT-HEAD-GATE-REBUILD-01

## Scope

This goal adds one offline US artifact writer. It does not collect data, read
credentials, connect to broker/private/order endpoints, start paper, write the
paper queue, or submit real orders.

## Serialized rebuild

The required first pass is:

`completion_dependency -> next_action_queue -> operator_unblock_packet ->
completion_audit -> production_line -> portfolio_promotion -> paper_readiness
-> paper_roll -> paper_evaluation -> live_readiness -> domain_read_model`

The four completion artifacts are refreshed once more, serially, after the
downstream reports. This closure pass is required because those reports are
completion inputs; omitting it would publish a stale operator queue.

One exclusive US lock protects the run. The writer records before-images for
every managed `latest` JSON. A builder exception, schema error, wrong-HEAD
claim, timestamp mismatch, unsafe true flag, or final health failure restores
all before-images. No failed builder can advance a latest artifact.

## Artifact identity and health

The authoritative rebuild receipt binds each rebuilt JSON SHA-256 to:

- the full final Git HEAD;
- one generated-at timestamp;
- its schema path;
- its declared input hashes;
- decision and blocker count.

Commit mismatch, expiry, output hash mismatch, or input hash drift is
`stale_blocked`. A schema-valid blocked current-HEAD artifact is consumable
gate evidence and is preferred to a missing or stale artifact. Wrapper success
is recorded separately and never substitutes for the report decision.

## Root blocker taxonomy

The current-HEAD taxonomy keeps at most eight stable root blockers. Repeated
PIT, paper, execution, manual, or artifact-health strings are retained as
`derived_references` and do not become hundreds of independent root blockers.
Each root carries an owner, root cause, next action, and derived-reference
count.

## Integrator wiring

No shared entrypoint changes are required. The integrator should consume:

- `artifacts/us_equity_gate_rebuild/latest/us_equity_current_head_gate_rebuild.json`
- `artifacts/us_equity_gate_rebuild/latest/us_equity_current_head_blocker_taxonomy.json`
- `artifacts/us_equity_strategy_production_line/latest/us_equity_operator_read_model.json`

The CLI is
`py -3 scripts/build_us_equity_current_head_gate_rebuild.py --repo-root .`.
Exit zero means the transactional wrapper completed; consumers must still read
`decision`, `blockers`, `artifact_health`, and the all-false safety object.
