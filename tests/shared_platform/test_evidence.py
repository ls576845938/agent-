from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from quant_shared.evidence import (
    EvidenceBundle,
    EvidenceReference,
    FileEvidenceRepository,
    FreshnessSource,
    assess_freshness,
)


def test_immutable_evidence_is_idempotent_and_conflicts_fail_closed(tmp_path: Path) -> None:
    repository = FileEvidenceRepository(tmp_path)
    first = repository.publish("runs/run-1/evidence.json", {"schema_version": "evidence_v1", "value": 1})
    second = repository.publish("runs/run-1/evidence.json", {"value": 1, "schema_version": "evidence_v1"})
    assert first.sha256 == repository.fingerprint(first.path)
    assert first.already_present is False
    assert second.already_present is True
    with pytest.raises(FileExistsError, match="different bytes"):
        repository.publish("runs/run-1/evidence.json", {"schema_version": "evidence_v1", "value": 2})
    with pytest.raises(ValueError, match="escapes repository root"):
        repository.publish("../outside.json", {"schema_version": "evidence_v1"})


def test_freshness_is_current_head_and_dependency_aware() -> None:
    now = datetime(2026, 7, 23, 12, tzinfo=timezone.utc)
    result = assess_freshness(
        (
            FreshnessSource("missing", False, None),
            FreshnessSource("stale", True, now - timedelta(days=2), code_commit="old"),
            FreshnessSource(
                "consumer",
                True,
                now - timedelta(hours=1),
                code_commit="head",
                dependency_generated_at_utc=(now,),
            ),
            FreshnessSource("future", True, now + timedelta(seconds=1), code_commit="head"),
        ),
        current_head="head",
        evaluated_at_utc=now,
        max_age=timedelta(hours=24),
    )
    assert result.status == "blocked"
    assert result.missing_count == 1
    assert result.stale_count == 1
    assert result.future_count == 1
    assert result.code_commit_mismatch_count == 1
    assert result.dependency_newer_count == 1


def test_evidence_bundle_fingerprint_is_order_stable_for_metadata() -> None:
    now = datetime(2026, 7, 23, tzinfo=timezone.utc)
    reference = EvidenceReference(
        evidence_id="evidence-1",
        path="runs/run-1/report.json",
        sha256="a" * 64,
        schema_version="report_v1",
        generated_at_utc=now,
        code_commit="b" * 40,
    )
    left = EvidenceBundle("bundle-1", now, (reference,), metadata={"b": 2, "a": 1})
    right = EvidenceBundle("bundle-1", now, (reference,), metadata={"a": 1, "b": 2})
    assert left.fingerprint == right.fingerprint
