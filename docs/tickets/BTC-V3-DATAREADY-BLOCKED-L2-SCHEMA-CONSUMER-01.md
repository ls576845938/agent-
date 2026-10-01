# BTC-V3-DATAREADY-BLOCKED-L2-SCHEMA-CONSUMER-01

## Scope and boundary

This ticket starts from
`2ae2ec7eb52cc0a9898af039f70648fa0ca609f2` in the planner-created sparse
worktree and branch
`agent/btc_developer/btc-v3-dataready-blocked-l2-schema-consumer-01`.
The first Git command in the worktree confirmed
`core.sparseCheckout=true`.

The declared source touch set was initially clean:

- `scripts/build_btc_dataready_consumption_report.py`;
- `tests/contracts/test_btc_dataready_consumer.py`;
- this ticket;
- the append-only producer handoff directory for this exact ticket.

There were no overlapping dirty paths or ownership conflicts. This ticket
does not modify `quant_crypto/data/dataready_consumer.py`, shared schemas,
shared-data payloads, SQLite, `data/**`, `artifacts/**`, or latest pointers.
It performs no network collection and no private, order, paper, or live
action.

## Discovery-only blocked L2 contract

The report builder recognizes
`data_schema=btc_okx_l2_blocked_attestation_v1` only when all of the following
are true:

- the requested dataset is exactly
  `btc-okx-timestamp-aligned-public-l2-history`;
- the schema name is an exact match;
- `quality_status=blocked`;
- `blockers` is a non-empty list of non-empty strings.

This is a discovery-only allowlist. It permits the committed manifest to be
passed to the existing core consumer but does not resolve or read the blocked
L2 shared payload. The core consumer still accepts only
`btc_okx_l2_dataready_attestation_v1`, so it truthfully retains
`manifest_data_schema_mismatch`, `manifest_quality_status_not_pass`, and the
original L2 blockers. Unknown schemas, use of the blocked schema by Kline,
`quality_status=pass`, and empty blockers all fail discovery with
`committed_manifest_schema_invalid:<dataset_id>`.

## Failure-first and exact-selector evidence

Before the implementation change, the focused tests ended with
`1 failed, 2 passed`; the remaining failure was the exact blocked L2 schema
being rejected by committed discovery. After implementation and the final
four-case split, the focused subset passed `4 passed`.

The CLI was run with all four exact selectors from the ticket and
`--now 2026-07-26T16:30:00Z`. Its output was written only to a unique system
temporary directory. The pre-commit acceptance report returned exit `2` and
had SHA-256
`7fb1e4b70c6f3d01d3fafab940336bab6fc47c6710566160f8392866efb2fa71`.
It is temporary test evidence, not a committed artifact or promotion
evidence.

Observed report facts:

- `status=blocked`;
- `decision=block_dataready_consumption_fail_closed`;
- Kline manifest status `pass`;
- Kline physical data status `pass`, with no physical blockers;
- Kline aggregate
  `e000f25f293c688a14f1cbe43d1eb0e4ef182f25c264e8dea8d90578cc9cd8a4`;
- L2 manifest status `blocked`, not missing and not discovery-schema-invalid;
- L2 blockers include `manifest_data_schema_mismatch`,
  `manifest_quality_status_not_pass`, and all eight source blockers;
- overall blocker count `13`, unique blocker count `13`;
- every readiness flag is false.

## Verification

- Failure-first focused subset: expected red, then `4 passed`.
- Full DataReady consumer contracts: `51 passed`.
- DataReady, Kline immutable exporter, OKX L2 immutable exporter, and public
  collector baseline: `142 passed`.
- The same baseline plus shared-data governance tests: `146 passed`.
- `py -3 -m compileall -q` for the builder and consumer contract test: pass.
- Builder CLI `--help`: exit `0`, all four selectors present.
- Scoped `git diff --check`: pass.

Every pytest command used a unique system temporary directory and
`-p no:cacheprovider`.

## Governance evidence and remaining blockers

Read:

- `AGENTS.md`;
- `docs/knowledge/README.md`;
- `docs/knowledge/00_codex_rules/quant_system_non_negotiables.md`;
- `docs/agent_playbooks/shared_pitfalls.md`;
- `docs/agent_playbooks/btc_developer_pitfalls.md`;
- the role-routed data, research, portfolio/risk, OMS, architecture,
  monitoring/replay, crypto market structure, exchange SRE/security, and BTC
  trend rule files.

Catalog hash:
`568cf9c4f4d96d1cff4d331f29b69ec40ad28b6c13156d542c586ef5d8314a11`.

Active pitfall IDs:
`GOV-CONCURRENCY-001`, `GOV-DIRTY-001`, `GOV-HANDOFF-001`,
`GOV-PITFALL-001`, `GOV-ROOT-001`, `GOV-STORAGE-001`,
`QSYS-GATE-001`, `QSYS-SECURITY-001`, `GOV-PROMPT-001`, and
`GOV-WINDOWS-001`.

Team Context remained discovery-only, reported no integration candidates and
`invalid_handoffs=0`. No other worktree's uncommitted files were consumed.
The selected Kline and blocked L2 manifests are committed objects on the base
history; the blocked L2 manifest is not a readiness upgrade.

The real timestamp-aligned L2 history and 30-natural-day requirement remain
blocked, along with the manifest's other truthful L2 blockers. This ticket
does not rebuild a promotion artifact. `quality_checked=false`,
`research_ready=false`, `backtest_ready=false`,
`promotion_evidence_ready=false`, `promotion=false`, `paper=false`,
`live=false`, `private=false`, `order=false`, `broker=false`,
`withdraw=false`, `network=false`, `secret=false`, `demo=false`,
`paper_queue=false`, and `real_order=false`.
