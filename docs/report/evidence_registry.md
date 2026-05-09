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

Python API:

```python
from quant_us.research.evidence_registry import (
    inspect_candidate_evidence,
    inspect_evidence_registry,
    rebuild_evidence_registry,
)

registry = rebuild_evidence_registry("data")
snapshot = inspect_evidence_registry("data")
chain = inspect_candidate_evidence("cand_123", "data")
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

- if the saved registry is missing, `inspect_evidence_registry(..., rebuild_if_missing=True)` rebuilds it from persisted artifacts
- if the saved registry is `stale` or `changed`, rebuild updates both canonical and legacy files
- the compatibility mirror is regenerated from the registry; callers should treat the legacy file as read-only output
- paper-review readers must not trust a saved review when the registry reports `stale` or `changed`;
  they should rebuild from the underlying artifacts first

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
- approval evidence remains record-only; it does not auto-enter paper trading
