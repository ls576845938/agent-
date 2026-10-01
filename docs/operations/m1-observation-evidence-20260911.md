# M1 observation evidence publication

## Decision

The offline M1 sealed research evidence was published as immutable shared data:

- Dataset: `m1-trend-environment-acceptance`
- Version: `m1-okx-59f5eb861-20260911`
- Schema: `m1_research_observation_acceptance_v1`
- Readiness: `quality_checked`
- Quality status: `pass_with_research_only_warnings`
- Published files: 160
- Published bytes: 56,134,415
- Aggregate SHA-256: `593eb9f893c280703b26423f00a4eaff62542152110ebff1dd5b5ad69061bcde`
- Committed manifest content SHA-256 (`git show` bytes): `2aab7e1e031acf094ce7a827d324102050344d27246443cac7acb574dd5c3f2a`
- Storage selector: `datasets/m1-trend-environment-acceptance/m1-okx-59f5eb861-20260911`

This is a sealed research evidence projection, not a complete working-directory mirror and not a recoverable MLflow training database. It preserves all files covered by every Qlib run seal and the Alpha Factory seal, plus the acceptance document, the original source inventory, and explicit projection metadata.

It is not `research_ready`, `backtest_ready`, or `promotion_evidence_ready`. It does not unlock promotion, paper, private, order, or live behavior.

## Identity and scope

- Role: `data_steward`
- Change risk: `promotion_evidence`
- Producer/computation commit recorded in the shared-data manifest: `59f5eb86132fd0e386d1d4e733c9fbc53ff80d7e`
- Publication worktree base: `59f5eb86132fd0e386d1d4e733c9fbc53ff80d7e`
- Source logical id: `m1-research-acceptance-20260911-01`
- No business code, strategy, risk, OMS, service, schema contract, or permission surface changed.

The Git commit that archives this manifest/report is publication metadata only. It must not be represented as the computation commit; the evidence was computed by `59f5eb86132fd0e386d1d4e733c9fbc53ff80d7e`.

## Source integrity evidence

- `m1_acceptance.json`: `d7b1278480adae33ff48b8f08c1aa5a2393275a65ab78663e4a81775d12af78b` (matched the approved hash).
- `m1_inventory.json`: `65433604d9566b7f03d638aba696c8d549e2a94293b9c6f56a6a46a7ac89f63d` (matched the approved hash).
- Inventory closure: all 179 declared files existed, no undeclared source file existed after excluding the inventory itself, and every SHA-256 matched.
- Inventory payload: 179 files, 64,462,322 bytes, aggregate `bb2a43bb159019128597d8d4e8331c7e7717931d0a00e3ed9fb895dd718ddbbb` using the publisher's path/NUL/hash/NUL/bytes/newline aggregation.
- Full source including `m1_inventory.json`: 180 files, 64,487,421 bytes, aggregate `e222e22b8b5550b4b36b7ff4187f5d43b032cbe16502cb38d847ef44dc66591b`.
- Six Qlib sealed runs passed file-by-file `read_sealed_evidence` validation.
- Source-input lineage resolved to `m1-okx-factory-input`; its canonical JSON seal digest is `d5c446445c8d36787c685080a49d06440e071afb10a089c8043576eec24e6c2e` and all four Factory fold identities/evidence references matched it.
- All four Factory fold sidecars were completed and matched their Qlib seals.
- Alpha Factory service reconstruction returned `integrity_status=passed` and exactly matched the acceptance detail.
- Ordinary Qlib observation evidence contains 15,840 observations: 15,573 `observed` and 267 warmup `unknown`.
- Factory decision is `rejected`; it is not a nominated candidate and cannot advance a gate.

## Projection contract

The source contains five `mlflow.db` files. A direct source-directory publication correctly failed closed with `shared_mutable_database_not_allowed:mlflow.db`; no partial target was created. Under the ticket author's explicit projection authorization, a new task-owned staging directory was then built without changing the source.

Projection selection is deterministic:

1. Include each Qlib `run_seal.json` and every file named by that seal.
2. Include Alpha Factory `seal.json` and every file named by that seal.
3. Include `m1_acceptance.json`.
4. Include the original `m1_inventory.json`, explicitly marked as the source inventory rather than the projection/published file list.
5. Add `projection_metadata.json`, SHA-256 `4d8fa01dbaa337a2928914cd438885ddfe2c9cd29de21831d31f157410091faa`, which records the projection schema, exclusions, preserved capabilities, limitations, and false safety flags.

The projection preserves 159 byte-identical source files and adds one metadata file. It excludes 21 ancillary source files: five `mlflow.db` files, ten unsealed MLflow `label.pkl`/`pred.pkl` files, two writer guards, two fallback-reason files, and two unsealed CSV exports. No sealed file is excluded. The published projection supports sealed-reader validation, model/prediction/evidence inspection, and source/factory lineage verification, but not MLflow database recovery or training resume.

## Validation

- Direct source publication failure-first check: passed (the prohibited databases were rejected).
- Projection check: 160 files total, 159 byte-identical source files, 21 declared exclusions, zero database suffixes, and exclusion set exactly equal to source minus projection.
- Projection Qlib check: six sealed runs passed `read_sealed_evidence`.
- Projection Factory check: reconstructed `integrity_status=passed`, exact acceptance-detail match, `decision=rejected`.
- Shared-data publication: `status=published`, 160 files, 56,134,415 bytes, aggregate `593eb9f893c280703b26423f00a4eaff62542152110ebff1dd5b5ad69061bcde`.
- Manifest resolve with full file hashing: `status=resolved`, `consumer_read_only=true`.
- External `_dataset_manifest.json` and the worktree manifest file both hash to `90a38743624113b06f3cfe4ac4bf34b973810ae39cf75938357b15b8e8df21ed`. Git's line-ending normalization stores the committed manifest object with content SHA-256 `2aab7e1e031acf094ce7a827d324102050344d27246443cac7acb574dd5c3f2a`; the handoff binds this committed-object hash.

No network access, training, service start, credentials, private endpoint, order endpoint, or live surface was used. Frontend/API/browser acceptance was intentionally not run by this publication ticket.

## Known gaps and gate state

- `historical_reconstructed_availability`
- `factory_candidate_rejected`
- `canonical_publication_and_browser_acceptance_pending`
- `not_execution_evidence`
- The projection is not a complete MLflow workspace and cannot restore/resume the omitted training databases.

All of `promotion`, `paper`, `live`, `private`, `order`, `real_order`, `transfer`, `withdraw`, `execution_permission`, and `runtime_observed` remain false. The immutable manifest and its handoff are stable data/evidence selectors only; they do not unlock any gate.
