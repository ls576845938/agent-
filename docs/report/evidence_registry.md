# Evidence Registry

`paper_review_index` is now a compatibility view over the full research Evidence Registry.
The canonical source of truth is `data/research/evidence_registry.json`; the legacy
`paper_review_index.json` file is kept only for older paper-review readers.

Canonical files:

- `data/research/evidence_registry.json`
- `data/research/paper_review_index.json` (legacy mirror for paper-review status readers)

Indexed evidence types:

- data manifest
- backtest manifest
- promotion result
- strategy manifest
- paper review
- daily report
- paper session manifest
- paper broker adapter startup sync
- ledger reconciliation artifact
- subject index buckets for `candidate_id`, `strategy_manifest_id`, `paper_review_id`, `backtest_run_id`, `data_version`, `report_date`, and `session_id`

Related persisted runtime evidence:

- `paper_ledger/audit/paper_session_manifest.json` (latest paper session manifest)
- `paper_ledger/audit/paper_session_manifests/<session_id>.json` (immutable session history manifest)
- `paper_ledger/audit/paper_broker_adapter_startup_sync.json`
- `paper_ledger/reconciliation/ledger_recon_artifact_<hash>.json`

These artifacts are evidence and audit inputs. They do not authorize paper or live order submission.

Python API:

```python
from quant_us.research.evidence_registry import (
    inspect_candidate_evidence,
    inspect_evidence_registry,
    inspect_saved_evidence_registry,
    find_registry_subject_evidence,
    rebuild_evidence_registry,
)

registry = rebuild_evidence_registry("data")
snapshot = inspect_saved_evidence_registry("data")
chain = inspect_candidate_evidence("cand_123", "data")
subject = find_registry_subject_evidence("data", session_id="sess_123")
```

Integrity metadata:

Every indexed evidence row, and every `EvidenceRef` inside a candidate chain, now carries
stable file-observation fields:

- `schema_version`
- `sha256`
- `size`
- `mtime`
- `observed_at`
- `content_type`

Compatibility fields `size_bytes` and `mtime_ns` are still emitted so older readers that
only consume the pre-v1 row shape keep working.

Status semantics:

- `integrity_status=PASS/STABLE`: evidence exists, hash metadata is observed, and no ambiguity is detected
- `integrity_status=STALE/CHANGED`: linkage is stale, the saved registry drifted, or the artifact changed in place
- `integrity_status=MISSING`: required evidence path or artifact is absent
- `integrity_status=CONFLICT`: more than one artifact claims the same evidence identity with divergent path/hash

Registry note semantics:

- `content_changed:*`: saved snapshot path still exists, but file content or file metadata no longer matches
- `missing_artifact:*`: a path recorded in the saved snapshot is gone
- `stale_snapshot:*`: registry snapshot is incomplete or older than currently indexed evidence

Rebuild behavior:

- read-only gates use the saved registry only and fail closed when the saved registry is missing, stale, changed, or conflicting
- `rebuild_evidence_registry("data")` is the explicit maintenance action that refreshes both canonical and legacy files
- registry rebuild writes are atomic and protected by a registry lock, so readers should observe either the previous complete snapshot or the next complete snapshot
- `inspect_evidence_registry(..., rebuild_if_missing=True)` may rebuild from persisted artifacts and must be treated as a maintenance/rebuild path, not as a readiness, report, or runtime gate path
- if the saved registry is `stale` or `changed`, an explicit rebuild updates both canonical and legacy files
- the compatibility mirror is regenerated from the registry; callers should treat the legacy file as read-only output
- paper-review readers must not trust a saved review when the registry reports `stale` or `changed`;
  they should block and require an explicit registry rebuild first
- readiness, report, promotion, and paper runtime gates consume saved-only registry evidence; they do not silently repair or rebuild missing review evidence at decision time

Candidate traceability:

Each candidate chain records:

- data manifest lineage from `data_version`
- canonical backtest manifest lineage
- latest promotion result from `pipeline_results`
- linked strategy manifest
- latest paper review for that manifest or candidate
- latest daily report snapshot
- `chain_status` plus candidate-local notes when saved evidence drifted, a referenced path disappeared, or a hash changed in place
- integrity metadata for each resolved evidence ref, so callers can surface the exact hash / size / mtime that backed the decision

Manual paper approvals:

- approved reviews now persist an `approval` object under `review.json`
- the approval object records `reviewer`, `reason`, `timestamp`, `candidate_id`, `commit_hash`, `source`, `source_sha256`, and a persisted promotion `gate_snapshot`
- approval evidence remains record-only; paper runtime also requires the approved review to be present in the saved registry with a reviewer and an existing evidence pack

Paper runtime evidence:

- paper runtime writes a latest paper session manifest and a history copy under `audit/paper_session_manifests/<session_id>.json`
- the manifest records `history_artifact_path`, broker backend, submit intent, registry evidence, startup sync status, and no-submit proof
- startup sync wraps the broker adapter boundary before submit paths are considered and remains audit evidence only
- ledger reconciliation artifacts bind `artifact_hash`, `generated_at`, `as_of_utc`, `ledger_artifact_path`, `ledger_hash`, `fills_hash`, `orders_hash`, and `portfolio_snapshots_hash`
- promotion and report surfaces should treat missing ledger reconciliation fields as `MISSING`, not as an implicit pass
