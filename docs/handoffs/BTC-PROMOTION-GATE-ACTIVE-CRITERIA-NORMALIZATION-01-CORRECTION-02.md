# BTC Promotion Gate Active Criteria Normalization 01 Correction 02

## Scope

This append-only correction removes the legacy static blocker contract from
the current-HEAD BTC domain read model. It does not change the legacy next-stage
orchestrator, collect data, publish runtime artifacts, restart services, access
credentials, or call private/order/live endpoints.

## Single canonical blocker authority

The current-head gate evaluation is the only authority for active blockers.
The read-model builder sends that list through the existing canonical alias and
deduplication path, then records the resulting ordered structured blocker codes
as `required_blockers`.

The metadata contract remains fail-closed:

- `required_blocker_count` equals the canonical list length;
- `required_blockers_sha256` hashes the exact ordered list;
- codes are non-empty and unique;
- `required_blockers_missing=[]`;
- `required_blockers_preserved=true`;
- required codes and structured blocker codes are ordered exact matches.

No `REQUIRED_BLOCKERS` or `QUALITY_L2_REQUIRED_BLOCKERS` list is imported or
accepted by the builder or published repository.

## Strict published read

The repository resolves both the domain read model and promotion-gate report
from the same immutable snapshot manifest. It verifies the direct file hashes,
current source head, aggregation batch, and then requires the read-model
required/structured blockers to equal the gate artifact blockers exactly.

An extra stale blocker, removal, replacement, reordering, duplicate, hash
mismatch, direct-file drift, missing gate entry, or gate identity mismatch
fails closed. The existing alias/deduplication semantics remain unchanged.

## Safety and delivery boundary

The 49-field published safety contract remains entirely false. Promotion,
paper, live, private, order, broker, OMS, real-order, transfer, and withdraw
permissions remain disabled. Independent integration, current-main artifact
and read-model rebuild, backend restart, and current-main verification remain
required after this producer handoff.
