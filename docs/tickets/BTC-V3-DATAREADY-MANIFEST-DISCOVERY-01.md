# BTC-V3-DATAREADY-MANIFEST-DISCOVERY-01

## Scope and ceiling

This ticket changes only the BTC DataReady consumption-report entrypoint and
its exact discovery contracts. It does not modify shared-data payloads,
`.agent/data_manifests/**`, `data/**`, `artifacts/**`, mutable databases,
latest pointers, exporter schemas, strategy/risk/OMS/execution code, or
another worktree. It performs no network, private, order, paper, or live
action. Maximum readiness is `quality_checked`.

Base commit:
`97d6448b89ce6029c69b20fbfe2427d99ae083e8`.

Branch:
`agent/btc_developer/btc-v3-dataready-manifest-discovery-01`.

The planner-created worktree passed its first explicit Git command with
`core.sparseCheckout=true`. Initial scoped `safe_status.py` was clean.

## Discovery contract

Automatic discovery now accepts only committed JSON objects under
`.agent/data_manifests/**` that satisfy all of:

- `schema_version=shared_dataset_manifest_v1`;
- the requested BTC `dataset_id`;
- `producer_role=data_steward`;
- the approved K-line or OKX L2 `data_schema`;
- a valid immutable `dataset_version`;
- `storage_relative_path=datasets/<dataset_id>/<dataset_version>`.

An evidence attestation that repeats the dataset ID is ignored because it is
not a shared dataset manifest. This removes the false duplicate condition
without weakening consumer-side physical hash, inventory, freshness, PIT,
sequence, or readiness validation.

Multiple committed immutable versions are valid repository history. When
more than one valid manifest exists and no selection is supplied, discovery
returns
`committed_manifest_selection_required:<dataset_id>` and consumption remains
blocked. It never infers latest from a filename, timestamp, Git order, or
dataset version.

Exact selectors are available independently for snapshot and L2:

```text
--snapshot-manifest-path
--snapshot-dataset-version
--l2-manifest-path
--l2-dataset-version
```

Paths must be normalized repo-relative POSIX JSON paths beneath
`.agent/data_manifests/`; absolute paths, backslashes, traversal, and paths
outside that root are rejected. A supplied path is read only from
`<current HEAD>:<path>`. A supplied version must be a valid immutable
identifier. Path, dataset ID, version, producer, data schema, and storage
identity mismatches fail closed with explicit blockers.

## Failure-first and verification

- Failure-first discovery subset: `4 failed` before implementation, then
  passed.
- Complete DataReady consumer contract file: `47 passed`.
- Combined DataReady, K-line immutable exporter, OKX L2 immutable exporter,
  and public collector regression: `135 passed`.
- Python compile for the builder and consumer contract test: pass.
- Builder CLI `--help`, including all four selectors: pass.
- Scoped `git diff --check`: pass.

All pytest commands used a unique system temporary directory and
`-p no:cacheprovider`. No report artifact, shared payload, manifest, latest
pointer, ledger, or database was generated or changed.

## Governance evidence

Read:

- `AGENTS.md`;
- `docs/knowledge/README.md`;
- `docs/knowledge/00_codex_rules/quant_system_non_negotiables.md`;
- `docs/agent_playbooks/shared_pitfalls.md`;
- `docs/agent_playbooks/btc_developer_pitfalls.md`;
- `docs/knowledge/01_data_layer/data_reliability_rules.md`;
- `docs/knowledge/05_architecture/domain_architecture_rules.md`.

Catalog hash:
`568cf9c4f4d96d1cff4d331f29b69ec40ad28b6c13156d542c586ef5d8314a11`.

Active pitfall IDs:
`GOV-CONCURRENCY-001`, `GOV-DIRTY-001`, `GOV-HANDOFF-001`,
`GOV-PITFALL-001`, `GOV-ROOT-001`, `GOV-STORAGE-001`,
`QSYS-GATE-001`, `QSYS-SECURITY-001`, `GOV-PROMPT-001`, and
`GOV-WINDOWS-001`.

Team Context reported no ready upstream delivery and
`invalid_handoffs=0`; no handoff or another worktree's uncommitted files were
consumed.

This ticket does not rebuild current-HEAD DataReady or promotion artifacts
and cannot attest that an approved real immutable dataset is selected.
`research_ready=false`, `backtest_ready=false`,
`promotion_evidence_ready=false`, `promotion=false`, `paper=false`,
`live=false`, `private=false`, `order=false`, `broker=false`,
`withdraw=false`, `network=false`, `secret=false`, `demo=false`,
`paper_queue=false`, and `real_order=false`.
