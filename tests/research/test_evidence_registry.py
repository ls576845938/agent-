from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _write_candidate(root: Path, candidate_id: str = "cand_1") -> Path:
    path = root / "research" / "candidates" / candidate_id / "candidate.json"
    _write_json(
        path,
        {
            "candidate_id": candidate_id,
            "data_version": "dv_1",
            "experiment_id": "exp_1",
        },
    )
    return path


def _write_manifest_with_review(root: Path, manifest_id: str, candidate_id: str) -> None:
    _write_json(
        root / "research" / "manifests" / manifest_id / "manifest.json",
        {
            "strategy_candidate_id": manifest_id,
            "source_candidate_id": candidate_id,
            "source_experiment_id": f"exp_{candidate_id}",
            "promotion_status": "PAPER_REVIEW_CANDIDATE",
            "paper_review_id": "prev_001",
            "paper_review_evidence_pack_path": str(
                root / "research" / "evidence_packs" / "psim_001" / "evidence_pack.json"
            ),
            "paper_review_candidate_path": str(
                root / "research" / "evidence_packs" / "psim_001" / "evidence_pack.json#sections.paper_review_candidate"
            ),
            "paper_review_candidate_status": "READY_FOR_REVIEW",
            "paper_review_blocking_reasons": [],
        },
    )


def _write_pending_review(root: Path) -> None:
    _write_json(
        root / "research" / "paper_reviews" / "prev_001" / "review.json",
        {
            "paper_review_id": "prev_001",
            "strategy_manifest_id": "sm_1",
            "portfolio_sim_id": "psim_001",
            "evidence_pack_path": str(
                root / "research" / "evidence_packs" / "psim_001" / "evidence_pack.json"
            ),
            "source_candidate_ids": ["cand_1", "cand_2"],
            "evidence_gate_status": "READY_FOR_REVIEW",
            "evidence_gate_blocking_reasons": [],
            "proposed_symbols": ["SPY", "QQQ"],
            "proposed_capital": 101000.0,
            "proposed_risk_envelope": {"max_drawdown_pct": 0.1},
            "status": "PENDING_HUMAN_REVIEW",
            "created_at": "2026-05-10T00:00:00+00:00",
        },
    )


def test_rebuilt_saved_registry_has_usable_subject_index(tmp_path: Path) -> None:
    from quant_us.research.evidence_registry import (
        find_registry_subject_evidence,
        inspect_saved_evidence_registry,
        rebuild_evidence_registry,
    )

    _write_candidate(tmp_path)

    registry = rebuild_evidence_registry(tmp_path)
    saved = inspect_saved_evidence_registry(tmp_path)
    lookup = find_registry_subject_evidence(tmp_path, candidate_id="cand_1")

    assert registry["subject_index_schema_version"] == "subject_evidence_index_v1"
    assert saved["registry_status"] == "present"
    assert saved["registry_integrity_status"] == "PASS/STABLE"
    assert "cand_1" in saved["subject_index"]["candidate_id"]
    assert lookup["matched"] is True
    assert lookup["reason"] == "ok"


def test_saved_registry_count_mismatch_is_diagnostic_when_artifacts_are_unchanged(
    tmp_path: Path,
) -> None:
    from quant_us.research.evidence_registry import (
        inspect_saved_evidence_registry,
        rebuild_evidence_registry,
    )

    _write_candidate(tmp_path)
    rebuild_evidence_registry(tmp_path)
    registry_path = tmp_path / "research" / "evidence_registry.json"
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload["counts"]["candidate_count"] = 999
    registry_path.write_text(json.dumps(payload), encoding="utf-8")

    saved = inspect_saved_evidence_registry(tmp_path)

    assert saved["registry_status"] == "present"
    assert saved["registry_integrity_status"] == "PASS/STABLE"
    assert "stale_snapshot:count_mismatch:candidate_count" in saved["registry_notes"]


def test_saved_registry_missing_subject_index_is_stale_until_rebuilt(
    tmp_path: Path,
) -> None:
    from quant_us.research.evidence_registry import (
        find_registry_subject_evidence,
        inspect_saved_evidence_registry,
        rebuild_evidence_registry,
    )

    _write_candidate(tmp_path)
    rebuild_evidence_registry(tmp_path)
    registry_path = tmp_path / "research" / "evidence_registry.json"
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload.pop("subject_index", None)
    payload.pop("subject_index_schema_version", None)
    registry_path.write_text(json.dumps(payload), encoding="utf-8")

    stale = inspect_saved_evidence_registry(tmp_path)
    lookup = find_registry_subject_evidence(tmp_path, candidate_id="cand_1")
    rebuilt = rebuild_evidence_registry(tmp_path)
    fresh = inspect_saved_evidence_registry(tmp_path)

    assert stale["registry_status"] == "stale"
    assert stale["registry_integrity_status"] == "STALE/CHANGED"
    assert "stale_snapshot:subject_index_schema_missing_or_mismatch" in stale["registry_notes"]
    assert lookup["matched"] is False
    assert lookup["reason"] == "registry_not_ready:stale:STALE/CHANGED"
    assert rebuilt["subject_index"]["candidate_id"]["cand_1"]
    assert fresh["registry_status"] == "present"


def test_report_registry_stale_output_includes_rebuild_command(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from quant_us.cli import cmd_report_evidence_registry
    from quant_us.research.evidence_registry import rebuild_evidence_registry

    _write_candidate(tmp_path)
    rebuild_evidence_registry(tmp_path)
    registry_path = tmp_path / "research" / "evidence_registry.json"
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload.pop("subject_index", None)
    payload.pop("subject_index_schema_version", None)
    registry_path.write_text(json.dumps(payload), encoding="utf-8")

    cmd_report_evidence_registry(argparse.Namespace(data_root=str(tmp_path)))

    output = capsys.readouterr().out
    assert "registry_state: STALE (stale)" in output
    assert (
        f"rebuild_command: quant-us research evidence-registry-rebuild --data-root {tmp_path}"
        in output
    )


def test_registry_captures_pending_review_candidate_ids_and_manifest_review_links(
    tmp_path: Path,
) -> None:
    from quant_us.research.evidence_registry import (
        inspect_saved_evidence_registry,
        rebuild_evidence_registry,
    )

    _write_candidate(tmp_path, "cand_1")
    _write_candidate(tmp_path, "cand_2")
    _write_manifest_with_review(tmp_path, "sm_1", "cand_1")
    _write_pending_review(tmp_path)

    rebuild_evidence_registry(tmp_path)
    saved = inspect_saved_evidence_registry(tmp_path)

    manifest_row = saved["evidence"]["strategy_manifests"][0]
    review_row = saved["evidence"]["paper_reviews"][0]

    assert manifest_row["details"]["paper_review_id"] == "prev_001"
    assert manifest_row["details"]["paper_review_candidate_status"] == "READY_FOR_REVIEW"
    assert review_row["details"]["candidate_id"] == "cand_1"
    assert review_row["details"]["source_candidate_ids"] == ["cand_1", "cand_2"]
    assert review_row["details"]["evidence_gate_status"] == "READY_FOR_REVIEW"
