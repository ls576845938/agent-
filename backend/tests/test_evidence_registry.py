from __future__ import annotations

import json
from pathlib import Path

from quant_us.research.evidence_registry import (
    find_registry_subject_evidence,
    inspect_candidate_evidence,
    inspect_evidence_registry,
    inspect_saved_evidence_registry,
    project_saved_paper_review_evidence,
    rebuild_evidence_registry,
)
from quant_us.monitoring.paper_review_status import inspect_paper_review_status
from quant_us.research.paper_review_bridge import (
    PaperReviewCandidate,
    PaperReviewManager,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_candidate_chain_fixture(
    root: Path,
    *,
    candidate_id: str = "cand_evidence",
    strategy_manifest_id: str = "sman_evidence",
    review_id: str = "prev_evidence",
    data_version: str = "qs-yfinance-AAPL-1d-evidence",
    include_backtest: bool = True,
    include_review: bool = True,
    duplicate_data_manifest: bool = False,
    daily_report_session_id: str | None = None,
) -> dict[str, str]:
    _write_json(
        root / "research" / "candidates" / candidate_id / "candidate.json",
        {
            "candidate_id": candidate_id,
            "experiment_id": "exp_evidence",
            "strategy_id": "momentum",
            "data_version": data_version,
            "promotion_status": "RESEARCH_ONLY",
            "backtest_manifest_path": f"research/backtests/{candidate_id}/run_manifest.json",
            "created_at": "2026-05-09T12:00:00+00:00",
        },
    )
    _write_json(
        root / "research" / "manifests" / strategy_manifest_id / "manifest.json",
        {
            "strategy_candidate_id": strategy_manifest_id,
            "source_candidate_id": candidate_id,
            "source_experiment_id": "exp_evidence",
            "promotion_status": "READY_FOR_PORTFOLIO_SIM",
            "created_at": "2026-05-09T12:10:00+00:00",
        },
    )
    _write_json(
        root / "research" / "pipeline_results" / "pipe_evidence.json",
        {
            "pipeline_id": "pipe_evidence",
            "created_at": "2026-05-09T12:15:00+00:00",
            "status": "completed",
            "paper_review_ready": [candidate_id],
            "promotion_gate_results": {
                candidate_id: {
                    "decision": "READY_FOR_PAPER_REVIEW",
                    "reasons": ["walk_forward_ok"],
                    "warnings": [],
                }
            },
        },
    )
    _write_json(
        root / "manifests" / f"{data_version}.json",
        {
            "data_version": data_version,
            "source": "yfinance",
            "symbol": "AAPL",
            "interval": "1d",
            "quality_score": 97.5,
            "created_at": "2026-05-09T11:55:00+00:00",
        },
    )
    if duplicate_data_manifest:
        _write_json(
            root / "manifests" / f"{data_version}_dup.json",
            {
                "data_version": data_version,
                "source": "sqlite",
                "symbol": "AAPL",
                "interval": "1d",
                "quality_score": 88.0,
                "created_at": "2026-05-09T11:56:00+00:00",
            },
        )
    if include_backtest:
        _write_json(
            root / "research" / "backtests" / candidate_id / "run_manifest.json",
            {
                "run_id": f"run_{candidate_id}",
                "engine": "event_driven",
                "canonical_for_promotion": True,
                "data_version": data_version,
                "commit_hash": "deadbee",
                "created_at": "2026-05-09T12:05:00+00:00",
            },
        )
    daily_report_payload = {
        "report_date": "2026-05-09",
        "generated_at": "2026-05-09T20:00:00+00:00",
        "reconciliation_status": "clean",
        "orders_submitted": 2,
        "kill_switch_triggered": False,
    }
    if daily_report_session_id:
        daily_report_payload["session_id"] = daily_report_session_id
    _write_json(
        root / "daily_reports" / "daily_report_2026-05-09.json",
        daily_report_payload,
    )
    if include_review:
        _write_json(
            root / "research" / "evidence_packs" / "pack_evidence" / "evidence_pack.json",
            {
                "paper_review_id": review_id,
                "candidate_id": candidate_id,
                "created_at": "2026-05-09T12:19:00+00:00",
            },
        )
        PaperReviewManager(data_root=str(root))._save_review(
            PaperReviewCandidate(
                paper_review_id=review_id,
                strategy_manifest_id=strategy_manifest_id,
                portfolio_sim_id="sim_evidence",
                evidence_pack_path=str(
                    root / "research" / "evidence_packs" / "pack_evidence" / "evidence_pack.json"
                ),
                proposed_symbols=["AAPL"],
                proposed_capital=100000.0,
                proposed_risk_envelope={"max_drawdown_pct": 0.1},
                status="PENDING_HUMAN_REVIEW",
                created_at="2026-05-09T12:20:00+00:00",
            )
        )
    return {
        "candidate_id": candidate_id,
        "strategy_manifest_id": strategy_manifest_id,
        "review_id": review_id,
        "data_version": data_version,
    }


def test_approved_paper_review_persists_provenance_and_registry_chain(tmp_path: Path) -> None:
    ids = _write_candidate_chain_fixture(tmp_path)
    manager = PaperReviewManager(data_root=str(tmp_path))

    approved = manager.approve(
        ids["review_id"],
        reviewer="risk_committee",
        reason="promotion gate reviewed manually",
    )
    registry = rebuild_evidence_registry(tmp_path)
    chain = inspect_candidate_evidence(ids["candidate_id"], tmp_path, use_saved=False)

    assert approved.status == "APPROVED_FOR_PAPER_ONLY"
    assert approved.approval is not None
    assert approved.approval.candidate_id == ids["candidate_id"]
    assert approved.approval.commit_hash == "deadbee"
    assert approved.approval.source == "yfinance"
    assert approved.approval.gate_snapshot["decision"] == "READY_FOR_PAPER_REVIEW"
    assert chain.chain_status == "PASS/STABLE"
    assert chain.paper_review.integrity_status == "PASS/STABLE"
    assert chain.paper_review.details["approval"]["reviewer"] == "risk_committee"
    assert chain.paper_review.details["approval"]["candidate_id"] == ids["candidate_id"]
    assert chain.paper_review.details["approval"]["commit_hash"] == "deadbee"
    assert registry["chains"][ids["candidate_id"]]["paper_review"]["details"]["approval"]["source"] == "yfinance"


def test_candidate_chain_marks_missing_backtest_manifest(tmp_path: Path) -> None:
    ids = _write_candidate_chain_fixture(tmp_path, include_backtest=False)

    chain = inspect_candidate_evidence(ids["candidate_id"], tmp_path, use_saved=False)

    assert chain.backtest_manifest.integrity_status == "MISSING"
    assert chain.chain_status == "MISSING"
    assert "backtest_manifest_missing" in chain.notes


def test_saved_registry_change_surfaces_hash_drift_in_candidate_chain(tmp_path: Path) -> None:
    ids = _write_candidate_chain_fixture(tmp_path)
    rebuild_evidence_registry(tmp_path)

    review_path = (
        tmp_path / "research" / "paper_reviews" / ids["review_id"] / "review.json"
    )
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["review_notes"] = "mutated_after_registry_snapshot"
    review_path.write_text(json.dumps(review, indent=2), encoding="utf-8")

    registry = inspect_evidence_registry(
        tmp_path,
        use_saved=True,
        rebuild_if_missing=False,
    )
    chain = inspect_candidate_evidence(
        ids["candidate_id"],
        tmp_path,
        use_saved=True,
        rebuild_if_missing=False,
    )

    assert registry["registry_status"] == "changed"
    assert chain.chain_status == "STALE/CHANGED"
    assert any(note.startswith("hash_changed:paper_review:") for note in chain.notes)


def test_registry_marks_conflicting_data_manifest_and_candidate_chain(tmp_path: Path) -> None:
    ids = _write_candidate_chain_fixture(tmp_path, duplicate_data_manifest=True)

    registry = rebuild_evidence_registry(tmp_path)
    chain = inspect_candidate_evidence(ids["candidate_id"], tmp_path, use_saved=False)
    manifest_rows = registry["evidence"]["data_manifests"]

    assert len(manifest_rows) == 2
    assert all(row["integrity_status"] == "CONFLICT" for row in manifest_rows)
    assert chain.data_manifest.integrity_status == "CONFLICT"
    assert chain.chain_status == "CONFLICT"
    assert any(note.startswith("data_manifest_conflict:") for note in chain.notes)


def test_saved_registry_projection_blocks_missing_without_rebuild(tmp_path: Path) -> None:
    ids = _write_candidate_chain_fixture(tmp_path)
    review_path = (
        tmp_path / "research" / "paper_reviews" / ids["review_id"] / "review.json"
    )
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["status"] = "APPROVED_FOR_PAPER_ONLY"
    review["reviewer"] = "risk_committee"
    review_path.write_text(json.dumps(review, indent=2), encoding="utf-8")
    registry_path = tmp_path / "research" / "evidence_registry.json"

    projection = project_saved_paper_review_evidence(
        tmp_path,
        paper_review_id=ids["review_id"],
    )
    status = inspect_paper_review_status(tmp_path)

    assert projection["allowed"] is False
    assert projection["registry_status"] == "missing"
    assert status.paper_review_entry_allowed is False
    assert status.status == "REGISTRY_MISSING"
    assert not registry_path.exists()


def test_saved_registry_projection_blocks_stale_changed_and_conflict(tmp_path: Path) -> None:
    ids = _write_candidate_chain_fixture(tmp_path)
    manager = PaperReviewManager(data_root=str(tmp_path))
    manager.approve(ids["review_id"], reviewer="risk_committee")
    rebuild_evidence_registry(tmp_path)

    extra_review = (
        tmp_path / "research" / "paper_reviews" / "prev_extra" / "review.json"
    )
    _write_json(
        extra_review,
        {
            "paper_review_id": "prev_extra",
            "status": "APPROVED_FOR_PAPER_ONLY",
            "reviewer": "risk_committee",
            "evidence_pack_path": str(
                tmp_path / "research" / "evidence_packs" / "pack_evidence" / "evidence_pack.json"
            ),
        },
    )
    stale = project_saved_paper_review_evidence(
        tmp_path,
        paper_review_id=ids["review_id"],
    )
    assert stale["allowed"] is False
    assert stale["registry_status"] == "stale"

    extra_review.unlink()
    rebuild_evidence_registry(tmp_path)
    review_path = (
        tmp_path / "research" / "paper_reviews" / ids["review_id"] / "review.json"
    )
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["review_notes"] = "changed_after_registry"
    review_path.write_text(json.dumps(review, indent=2), encoding="utf-8")
    changed = project_saved_paper_review_evidence(
        tmp_path,
        paper_review_id=ids["review_id"],
    )
    assert changed["allowed"] is False
    assert changed["registry_status"] == "changed"

    rebuild_evidence_registry(tmp_path)
    registry_path = tmp_path / "research" / "evidence_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["evidence"]["paper_reviews"][0]["integrity_status"] = "CONFLICT"
    registry_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    conflict = inspect_saved_evidence_registry(tmp_path)
    assert conflict["registry_status"] == "conflict"
    assert conflict["registry_integrity_status"] == "CONFLICT"


def test_saved_registry_projection_allows_approved_review_with_pack(tmp_path: Path) -> None:
    ids = _write_candidate_chain_fixture(tmp_path)
    manager = PaperReviewManager(data_root=str(tmp_path))
    manager.approve(ids["review_id"], reviewer="risk_committee")
    rebuild_evidence_registry(tmp_path)

    projection = project_saved_paper_review_evidence(
        tmp_path,
        paper_review_id=ids["review_id"],
    )
    status = inspect_paper_review_status(tmp_path)

    assert projection["allowed"] is True
    assert projection["reason"] == "ok"
    assert projection["registry_status"] == "present"
    assert status.status == "APPROVED_FOR_PAPER_ONLY"
    assert status.paper_review_entry_allowed is True


def test_registry_subject_index_indexes_candidate_review_backtest_data_and_daily_report(
    tmp_path: Path,
) -> None:
    ids = _write_candidate_chain_fixture(
        tmp_path,
        daily_report_session_id="session_open",
    )

    registry = rebuild_evidence_registry(tmp_path)
    subject_index = registry["subject_index"]

    assert registry["subject_index_schema_version"] == "subject_evidence_index_v1"

    candidate_entry = subject_index["candidate_id"][ids["candidate_id"]][0]
    assert candidate_entry["strategy_manifest_id"] == ids["strategy_manifest_id"]
    assert candidate_entry["paper_review_id"] == ids["review_id"]
    assert candidate_entry["backtest_run_id"] == f"run_{ids['candidate_id']}"
    assert candidate_entry["data_version"] == ids["data_version"]
    assert candidate_entry["paths"]["candidate"].endswith("candidate.json")
    assert candidate_entry["paths"]["paper_review"].endswith("review.json")

    paper_review_entry = subject_index["paper_review_id"][ids["review_id"]][0]
    assert paper_review_entry["candidate_id"] == ids["candidate_id"]

    backtest_entry = subject_index["backtest_run_id"][f"run_{ids['candidate_id']}"][0]
    assert backtest_entry["paths"]["backtest_manifest"].endswith("run_manifest.json")

    data_entry = subject_index["data_version"][ids["data_version"]][0]
    assert data_entry["candidate_id"] == ids["candidate_id"]

    daily_by_date = subject_index["report_date"]["2026-05-09"][0]
    assert daily_by_date["session_id"] == "session_open"
    assert daily_by_date["paths"]["daily_report"].endswith("daily_report_2026-05-09.json")

    daily_by_session = subject_index["session_id"]["session_open"][0]
    assert daily_by_session["report_date"] == "2026-05-09"


def test_find_registry_subject_evidence_reads_saved_subject_index(tmp_path: Path) -> None:
    ids = _write_candidate_chain_fixture(
        tmp_path,
        daily_report_session_id="session_open",
    )
    rebuild_evidence_registry(tmp_path)

    candidate_lookup = find_registry_subject_evidence(
        tmp_path,
        candidate_id=ids["candidate_id"],
    )
    assert candidate_lookup["matched"] is True
    assert candidate_lookup["reason"] == "ok"
    assert candidate_lookup["entries"][0]["paper_review_id"] == ids["review_id"]

    paper_review_lookup = find_registry_subject_evidence(
        tmp_path,
        paper_review_id=ids["review_id"],
    )
    assert paper_review_lookup["matched"] is True
    assert paper_review_lookup["entries"][0]["strategy_manifest_id"] == ids["strategy_manifest_id"]

    backtest_lookup = find_registry_subject_evidence(
        tmp_path,
        backtest_run_id=f"run_{ids['candidate_id']}",
    )
    assert backtest_lookup["matched"] is True
    assert backtest_lookup["entries"][0]["data_version"] == ids["data_version"]

    data_lookup = find_registry_subject_evidence(
        tmp_path,
        data_version=ids["data_version"],
    )
    assert data_lookup["matched"] is True
    assert data_lookup["entries"][0]["candidate_id"] == ids["candidate_id"]

    daily_lookup = find_registry_subject_evidence(
        tmp_path,
        report_date="2026-05-09",
        session_id="session_open",
    )
    assert daily_lookup["matched"] is True
    assert daily_lookup["entries"][0]["entry_kind"] == "daily_report"


def test_find_registry_subject_evidence_uses_report_date_when_session_missing(
    tmp_path: Path,
) -> None:
    _write_candidate_chain_fixture(tmp_path)
    rebuild_evidence_registry(tmp_path)

    daily_lookup = find_registry_subject_evidence(
        tmp_path,
        report_date="2026-05-09",
    )

    assert daily_lookup["matched"] is True
    assert len(daily_lookup["entries"]) == 1
    assert daily_lookup["entries"][0]["session_id"] == ""
    assert daily_lookup["entries"][0]["paths"]["daily_report"].endswith(
        "daily_report_2026-05-09.json"
    )


def test_subject_index_includes_orphan_backtest_and_data_artifacts(tmp_path: Path) -> None:
    data_version = "qs-yfinance-AAPL-1d-orphan"
    run_id = "ubt_orphan"
    _write_json(
        tmp_path / "manifests" / f"{data_version}.json",
        {
            "data_version": data_version,
            "source": "yfinance",
            "symbol": "AAPL",
            "interval": "1d",
            "quality_score": 99.0,
            "created_at": "2026-05-09T11:55:00+00:00",
        },
    )
    _write_json(
        tmp_path / "manifests" / f"run_{run_id}.json",
        {
            "run_id": run_id,
            "engine": "event_driven",
            "canonical_for_promotion": True,
            "data_version": data_version,
            "commit_hash": "deadbee",
            "created_at": "2026-05-09T12:05:00+00:00",
        },
    )
    rebuild_evidence_registry(tmp_path)

    backtest_lookup = find_registry_subject_evidence(
        tmp_path,
        backtest_run_id=run_id,
    )
    data_lookup = find_registry_subject_evidence(
        tmp_path,
        data_version=data_version,
    )

    assert backtest_lookup["matched"] is True
    assert any(entry["entry_kind"] == "backtest_manifest" for entry in backtest_lookup["entries"])
    assert data_lookup["matched"] is True
    assert any(entry["entry_kind"] == "data_manifest" for entry in data_lookup["entries"])


def test_find_registry_subject_evidence_fails_closed_for_unready_registry(
    tmp_path: Path,
) -> None:
    ids = _write_candidate_chain_fixture(tmp_path)

    missing = find_registry_subject_evidence(
        tmp_path,
        candidate_id=ids["candidate_id"],
    )
    assert missing["matched"] is False
    assert missing["registry_status"] == "missing"
    assert missing["entries"] == []

    rebuild_evidence_registry(tmp_path)
    _write_json(
        tmp_path / "research" / "paper_reviews" / "prev_extra" / "review.json",
        {
            "paper_review_id": "prev_extra",
            "status": "APPROVED_FOR_PAPER_ONLY",
            "reviewer": "risk_committee",
            "evidence_pack_path": str(
                tmp_path / "research" / "evidence_packs" / "pack_evidence" / "evidence_pack.json"
            ),
        },
    )
    stale = find_registry_subject_evidence(
        tmp_path,
        candidate_id=ids["candidate_id"],
    )
    assert stale["matched"] is False
    assert stale["registry_status"] == "stale"
    assert stale["entries"] == []

    extra_review = tmp_path / "research" / "paper_reviews" / "prev_extra" / "review.json"
    extra_review.unlink()
    rebuild_evidence_registry(tmp_path)
    review_path = tmp_path / "research" / "paper_reviews" / ids["review_id"] / "review.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["review_notes"] = "changed_after_registry"
    review_path.write_text(json.dumps(review, indent=2), encoding="utf-8")
    changed = find_registry_subject_evidence(
        tmp_path,
        candidate_id=ids["candidate_id"],
    )
    assert changed["matched"] is False
    assert changed["registry_status"] == "changed"
    assert changed["entries"] == []

    rebuild_evidence_registry(tmp_path)
    registry_path = tmp_path / "research" / "evidence_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["evidence"]["paper_reviews"][0]["integrity_status"] = "CONFLICT"
    registry_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    conflict = find_registry_subject_evidence(
        tmp_path,
        candidate_id=ids["candidate_id"],
    )
    assert conflict["matched"] is False
    assert conflict["registry_status"] == "conflict"
    assert conflict["entries"] == []
