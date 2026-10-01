# BTC-V3-RUNTIME-ARTIFACT-BOOTSTRAP-AND-POINTER-ATOMICITY-01

## Scope and boundary

This ticket starts from
`42052f44fd43e257052970050c394a3a66e55c51` in the planner-created sparse
worktree and branch
`agent/btc_developer/btc-v3-runtime-artifact-bootstrap-atomicity-01`.
The first Git command in the worktree confirmed
`core.sparseCheckout=true`.

The exact requested planner task id exceeded the governance length limit and
was rejected with `invalid_task_id`; no worktree was created by that failed
attempt. The shortened planner id
`btc-v3-runtime-artifact-bootstrap-atomicity-01` created the dedicated
worktree from the required base. Every declared source path was clean before
editing. There were no overlapping dirty paths or ownership conflicts.

The touch set is limited to the bootstrap CLI, current-HEAD rebuild
orchestration, their contract tests, this ticket, and the append-only
producer handoff. The resolver, shared backend, Team Context, shared schemas,
shared enums, gate-snapshot implementation, SQLite, data and production
artifacts are unchanged. No network collection, private/order/live endpoint,
secret, paper queue, broker or real-order action was performed.

## Explicit bootstrap contract

`scripts/bootstrap_btc_runtime_artifact_root.py` requires both
`--source-repo-root` and `--artifact-root`. Both values must be absolute.
The source must be an existing, non-reparse directory. The artifact root must
either not exist beneath an existing safe parent or already be a strictly
empty directory.

The target must be disjoint from every registered Git worktree. Symlink,
junction and reparse components, resolved-path drift and path escape all fail
closed. The command derives repository identity through
`repository_identity_for_source` and emits the exact marker produced by
`build_btc_runtime_artifact_owner_marker`.

Creation is no-overwrite: the directory uses exclusive creation and the
marker uses `O_CREAT | O_EXCL`. Marker bytes are flushed and `fsync`ed.
Marker-creation failure removes the marker and a root created by the command.
An existing nonempty root, a second bootstrap, and a filesystem error preserve
existing content. Nothing is copied from repo-local or historical artifacts.
Reader and writer construction remain non-provisioning and never create a
missing root or owner marker.

## Current-HEAD pointer atomicity

The current-HEAD rebuild now rejects reader/writer pairs whose exact
`artifact_root` or `repository_identity` differs, before artifact access.

The eight current outputs are written under the existing exclusive writer
session. The immutable snapshot publication is predicted deterministically
from those validated bytes, and the rebuild report is built, validated and
published before snapshot publication. The gate-run publisher performs the
latest-pointer write only after its immutable run directory and manifest are
complete. The report's manifest hash is therefore the same hash recorded in
the resulting latest pointer.

Injected rebuild-report write and validation exceptions leave the prior
pointer bytes and SHA-256 unchanged and do not create the failed run
directory. A snapshot-publication exception restores the previous rebuild
report while retaining the publisher's existing fail-closed pointer
semantics.

## Failure-first and verification evidence

Before implementation:

- bootstrap contracts failed collection with
  `ModuleNotFoundError: No module named
  'scripts.bootstrap_btc_runtime_artifact_root'`;
- current-HEAD contracts reported `3 failed, 6 passed`, covering pointer
  advancement on report-write failure plus reader/writer root and identity
  mismatches.

After implementation:

- bootstrap plus current-HEAD focused contracts: `28 passed`;
- green source/runtime-consumer regression subset: `111 passed`;
- the broader resolver, DataReady, domain read-model, gate snapshot,
  current-HEAD and L2/reconnect suite: `113 passed, 3 failed`;
- all three broader-suite failures are pre-existing static-artifact reads of
  missing
  `artifacts/btc_scalping_readiness/latest/btc_true_scalping_l2_sample_quality_report.json`
  in the sparse/externalized runtime layout, before ticket code executes;
- focused `compileall`: pass;
- bootstrap CLI `--help`: exit `0`;
- bootstrap CLI creation is covered by a subprocess contract test.

The exact expanded command was:

```text
py -3 -m pytest -q -p no:cacheprovider tests/contracts/test_btc_runtime_artifact_store.py tests/contracts/test_btc_dataready_consumer.py tests/contracts/test_btc_domain_read_model.py tests/contracts/test_btc_gate_snapshot.py tests/contracts/test_btc_current_head_gate_rebuild.py tests/contracts/test_btc_true_scalping_l2_sample_quality_report.py tests/contracts/test_btc_true_scalping_ws_order_book_replay_report.py tests/contracts/test_btc_true_scalping_ws_reconnect_resync_policy_report.py
```

The three blocked nodes were:

- `test_btc_true_scalping_l2_sample_quality_schema_valid`;
- `test_current_btc_true_scalping_l2_sample_quality_is_research_only_locked`;
- `test_l2_sample_quality_schema_rejects_unlock`.

Each node failed before ticket implementation code ran, on
`Path.read_text()` for the same absent external-runtime payload:
`artifacts/btc_scalping_readiness/latest/btc_true_scalping_l2_sample_quality_report.json`.
These results are classified only as
`external_runtime_artifact_not_provisioned`; they are neither implementation
failures nor passing evidence.

The shared live safety-boundary test module could not collect in this BTC
sparse worktree because it imports the excluded US package:
`ModuleNotFoundError: No module named 'quant_us'`. The sparse scope was not
expanded and US code was not modified. Every pytest invocation used a unique
system temporary directory and disabled pytest's cache provider. No
production artifact was rebuilt or published.

## Governance evidence and remaining gates

Read:

- `AGENTS.md`;
- `docs/knowledge/README.md`;
- `docs/knowledge/00_codex_rules/quant_system_non_negotiables.md`;
- `docs/agent_playbooks/shared_pitfalls.md`;
- `docs/agent_playbooks/btc_developer_pitfalls.md`;
- `docs/knowledge/05_architecture/domain_architecture_rules.md`;
- `docs/knowledge/05_monitoring_replay/audit_trail.md`;
- `docs/knowledge/09_exchange_api_security/api_key_permission_policy.md`.

Catalog hash:
`568cf9c4f4d96d1cff4d331f29b69ec40ad28b6c13156d542c586ef5d8314a11`.

Active pitfall IDs:
`GOV-CONCURRENCY-001`, `GOV-DIRTY-001`, `GOV-HANDOFF-001`,
`GOV-PITFALL-001`, `GOV-ROOT-001`, `GOV-STORAGE-001`,
`QSYS-GATE-001`, `QSYS-SECURITY-001`, `GOV-PROMPT-001`, and
`GOV-WINDOWS-001`.

Team Context reported zero ready upstreams, available deliveries,
integration candidates and invalid handoffs. The committed resolver handoff
at the required base was validated. No other worktree's uncommitted files or
hard-coded worktree paths were consumed.

This ticket provisions code only; it does not provision a production runtime
root, rebuild evidence or change readiness. The current-HEAD runtime artifact
and manifest remain absent until an operator explicitly runs the bootstrap
and a separately authorized offline rebuild. `promotion=false`,
`paper=false`, `live=false`, `private=false`, `order=false`, `broker=false`,
`withdraw=false`, `network=false`, `secret=false`, `paper_queue=false`, and
`real_order=false` remain fail closed. Funding, mark/index,
liquidation-buffer, venue-filter, OMS lifecycle, reconciliation,
outage/cancel-only, audit-DAG, replay, observation-window and manual-review
blockers remain unchanged.
