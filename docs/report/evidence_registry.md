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

- `sha256`
- `size_bytes`
- `mtime_ns`
- `observed_at`
- `content_type`

These fields are emitted in addition to the v1-compatible row shape, so older readers that
only consume `path`, `status`, `created_at`, `summary`, and `details` keep working.

Status semantics:

- `present`: evidence exists and the chain points to it directly
- `missing`: required evidence path or artifact is absent
- `stale`: evidence exists but the stored linkage is outdated, or the saved registry snapshot is older than source evidence
- `changed`: the saved registry snapshot still points at the same path set, but one or more
  artifacts changed in place (`sha256` / `size_bytes` / `mtime_ns` drift)

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
- integrity metadata for each resolved evidence ref, so callers can surface the exact hash / size / mtime that backed the decision
