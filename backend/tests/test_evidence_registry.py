from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import quant_us.research.evidence_registry as evidence_registry_module
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
    backtest_manifest_path: str | None = None,
    daily_report_session_id: str | None = None,
    ledger_artifact_hash: str = "",
) -> dict[str, str]:
    _write_json(
        root / "research" / "candidates" / candidate_id / "candidate.json",
        {
            "candidate_id": candidate_id,
            "experiment_id": "exp_evidence",
            "strategy_id": "momentum",
            "data_version": data_version,
            "promotion_status": "RESEARCH_ONLY",
            "backtest_manifest_path": (
                backtest_manifest_path
                if backtest_manifest_path is not None
                else f"research/backtests/{candidate_id}/run_manifest.json"
            ),
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
    if ledger_artifact_hash:
        daily_report_payload["ledger_artifact_hash"] = ledger_artifact_hash
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


def _write_runtime_evidence_fixture(
    root: Path,
    *,
    review_id: str,
    review_path: Path,
    session_id: str,
    artifact_hash: str,
    report_date: str = "2026-05-09",
) -> None:
    ledger_root = root / "paper_runtime_ledger"
    session_manifest = {
        "artifact_type": "paper_session_manifest",
        "artifact_version": "paper_session_manifest_v1",
        "session_id": session_id,
        "mode": "paper",
        "runtime_mode": "paper",
        "canonical_runtime": "PaperRuntime",
        "symbols": ["AAPL"],
        "strategy_id": "momentum",
        "paper_broker": "alpaca",
        "broker_backend": "alpaca_paper",
        "submit_orders": False,
        "allow_live_orders": False,
        "registry_evidence_id": review_id,
        "registry_evidence_path": str(review_path),
        "registry_evidence": {
            "allowed": True,
            "reason": "ok",
            "registry_status": "present",
            "registry_integrity_status": "PASS/STABLE",
        },
        "startup_sync_status": {"status": "ok"},
        "created_at": f"{report_date}T20:10:00+00:00",
        "artifact_path": str(ledger_root / "audit" / "paper_session_manifest.json"),
        "history_artifact_path": str(
            ledger_root
            / "audit"
            / "paper_session_manifests"
            / f"{session_id}.json"
        ),
        "no_real_order_submission_proof": {"status": "PASS"},
        "reduce_only": False,
        "halt_reconciliation": False,
        "adapter_contract": {"effective_backend": "alpaca_paper"},
    }
    _write_json(
        ledger_root / "audit" / "paper_session_manifest.json",
        session_manifest,
    )
    _write_json(
        ledger_root / "audit" / "paper_session_manifests" / f"{session_id}.json",
        session_manifest,
    )
    _write_json(
        ledger_root / "audit" / "paper_broker_adapter_startup_sync.json",
        {
            "artifact_type": "paper_broker_adapter_startup_sync",
            "artifact_version": "paper_broker_adapter_startup_sync_v1",
            "mode": "paper",
            "runtime_mode": "paper",
            "canonical_runtime": "PaperRuntime",
            "paper_broker": "alpaca",
            "backend": "alpaca_paper",
            "broker_backend": "alpaca_paper",
            "real_order_submission": False,
            "paper_order_submission": False,
            "contract_version": "paper_adapter_contract_v4",
            "status": "ok",
            "reduce_only": False,
            "halt_reconciliation": False,
            "no_submit_proof": {
                "submit_order_invoked": False,
                "submit_call_count_delta": 0,
            },
            "sync": {
                "sync_account": {"account_id": "paper-account"},
                "sync_positions": {"position_count": 1},
            },
            "timestamp_utc": f"{report_date}T20:05:00+00:00",
        },
    )
    _write_json(
        ledger_root
        / "reconciliation"
        / f"ledger_recon_artifact_{artifact_hash[:16]}.json",
        {
            "artifact_version": "ledger_reconciliation_v1",
            "artifact_hash": artifact_hash,
            "as_of_utc": f"{report_date}T20:00:00+00:00",
            "fills": {
                "duplicate_fill_count": 0,
                "conflict_fill_count": 0,
            },
            "hashes": {
                "ledger_hash": "ledgerhash",
                "fills_hash": "fillshash",
            },
            "pnl": {"net_pnl": 123.45},
            "integrity": {"passed": True},
            "reconciliation": {"summary": {"passed": True}},
        },
    )


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
    assert approved.approval.gate_snapshot["review_queue_entry_allowed"] is True
    assert approved.approval.gate_snapshot["paper_execution_authorized"] is False
    assert approved.approval.gate_snapshot["authorization_scope"] == "human_review_only"
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


def test_registry_marks_stale_when_canonical_data_manifest_missing_but_alternate_exists(
    tmp_path: Path,
) -> None:
    ids = _write_candidate_chain_fixture(tmp_path)
    canonical_path = tmp_path / "manifests" / f"{ids['data_version']}.json"
    alternate_path = tmp_path / "manifests" / f"{ids['data_version']}_alternate.json"
    canonical_payload = json.loads(canonical_path.read_text(encoding="utf-8"))
    canonical_path.unlink()
    alternate_path.write_text(json.dumps(canonical_payload, indent=2), encoding="utf-8")

    chain = inspect_candidate_evidence(ids["candidate_id"], tmp_path, use_saved=False)

    assert chain.data_manifest.status == "stale"
    assert chain.data_manifest.integrity_status == "STALE/CHANGED"
    assert chain.data_manifest.summary == "canonical_data_manifest_missing_but_alternate_found"
    assert alternate_path.as_posix() in chain.data_manifest.details["alternate_paths"]


def test_registry_marks_conflict_for_noncanonical_backtest_manifest_path(
    tmp_path: Path,
) -> None:
    ids = _write_candidate_chain_fixture(
        tmp_path,
        backtest_manifest_path="research/backtests/cand_evidence/alt_run_manifest.json",
    )
    canonical_path = (
        tmp_path / "research" / "backtests" / ids["candidate_id"] / "run_manifest.json"
    )
    alternate_path = canonical_path.with_name("alt_run_manifest.json")
    alternate_path.write_text(canonical_path.read_text(encoding="utf-8"), encoding="utf-8")

    chain = inspect_candidate_evidence(ids["candidate_id"], tmp_path, use_saved=False)

    assert chain.backtest_manifest.status == "conflict"
    assert chain.backtest_manifest.integrity_status == "CONFLICT"
    assert chain.backtest_manifest.summary == "non_canonical_backtest_manifest_path"
    assert chain.backtest_manifest.details["expected_path"] == str(canonical_path)
    assert any(note.startswith("backtest_manifest_conflict:") for note in chain.notes)


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


def test_rebuild_registry_keeps_existing_snapshot_when_atomic_replace_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_candidate_chain_fixture(tmp_path)
    rebuild_evidence_registry(tmp_path)

    registry_path = tmp_path / "research" / "evidence_registry.json"
    original_text = registry_path.read_text(encoding="utf-8")
    original_replace = evidence_registry_module.os.replace

    def fail_registry_replace(src: str | Path, dst: str | Path) -> None:
        if Path(dst) == registry_path:
            raise OSError("forced_replace_failure")
        original_replace(src, dst)

    monkeypatch.setattr(evidence_registry_module.os, "replace", fail_registry_replace)

    try:
        rebuild_evidence_registry(tmp_path)
    except OSError as exc:
        assert "forced_replace_failure" in str(exc)
    else:
        raise AssertionError("expected rebuild_evidence_registry to fail")

    assert registry_path.read_text(encoding="utf-8") == original_text
    assert json.loads(original_text)["schema_version"] == "evidence_registry_v1"
    assert not list((tmp_path / "research").glob(".evidence_registry.json.*.tmp"))
    assert not evidence_registry_module._registry_lock_path(tmp_path).exists()


def test_rebuild_registry_serializes_concurrent_writers_with_lock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_candidate_chain_fixture(tmp_path)
    original_write_json_atomic = evidence_registry_module._write_json_atomic
    registry_path = evidence_registry_module._registry_path(tmp_path)
    first_writer_entered = threading.Event()
    release_first_writer = threading.Event()
    writer_call_count = 0
    errors: list[BaseException] = []

    def blocking_write_json_atomic(path: Path, payload: dict) -> None:
        nonlocal writer_call_count
        if path == registry_path:
            writer_call_count += 1
            if writer_call_count == 1:
                first_writer_entered.set()
                release_first_writer.wait(timeout=2.0)
        original_write_json_atomic(path, payload)

    monkeypatch.setattr(
        evidence_registry_module,
        "_write_json_atomic",
        blocking_write_json_atomic,
    )

    def run_rebuild() -> None:
        try:
            rebuild_evidence_registry(tmp_path)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    first = threading.Thread(target=run_rebuild)
    second = threading.Thread(target=run_rebuild)
    first.start()
    assert first_writer_entered.wait(timeout=2.0)

    second.start()
    time.sleep(0.2)
    assert writer_call_count == 1

    release_first_writer.set()
    first.join(timeout=2.0)
    second.join(timeout=2.0)

    assert not errors
    assert writer_call_count == 2
    assert not first.is_alive()
    assert not second.is_alive()
    assert json.loads(registry_path.read_text(encoding="utf-8"))["schema_version"] == (
        "evidence_registry_v1"
    )
    assert not evidence_registry_module._registry_lock_path(tmp_path).exists()


def test_rebuild_registry_removes_stale_dead_pid_lock(tmp_path: Path) -> None:
    _write_candidate_chain_fixture(tmp_path)
    lock_path = evidence_registry_module._registry_lock_path(tmp_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps(
            {
                "pid": 999_999_999,
                "created_at": "2026-05-09T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    registry = rebuild_evidence_registry(tmp_path)

    assert registry["schema_version"] == "evidence_registry_v1"
    assert not lock_path.exists()


def test_registry_subject_index_includes_runtime_and_ledger_evidence(
    tmp_path: Path,
) -> None:
    artifact_hash = "artifacthash1234567890"
    ids = _write_candidate_chain_fixture(
        tmp_path,
        daily_report_session_id="paper_session_open",
        ledger_artifact_hash=artifact_hash,
    )
    manager = PaperReviewManager(data_root=str(tmp_path))
    manager.approve(ids["review_id"], reviewer="risk_committee")
    review_path = (
        tmp_path / "research" / "paper_reviews" / ids["review_id"] / "review.json"
    )
    _write_runtime_evidence_fixture(
        tmp_path,
        review_id=ids["review_id"],
        review_path=review_path,
        session_id="paper_session_open",
        artifact_hash=artifact_hash,
    )

    registry = rebuild_evidence_registry(tmp_path)
    subject_index = registry["subject_index"]

    assert registry["counts"]["paper_session_manifest_count"] == 2
    assert registry["counts"]["paper_startup_sync_count"] == 1
    assert registry["counts"]["ledger_reconciliation_artifact_count"] == 1

    session_entries = subject_index["session_id"]["paper_session_open"]
    assert {entry["entry_kind"] for entry in session_entries} >= {
        "daily_report",
        "paper_session_manifest",
        "paper_broker_adapter_startup_sync",
        "ledger_reconciliation_artifact",
    }
    session_manifest_entries = [
        entry for entry in session_entries if entry["entry_kind"] == "paper_session_manifest"
    ]
    assert len(session_manifest_entries) == 2
    assert {
        entry["trace"][0]["evidence_id"] for entry in session_manifest_entries
    } == {"paper_session_open:latest", "paper_session_open:history"}

    review_entries = subject_index["paper_review_id"][ids["review_id"]]
    assert any(
        entry["entry_kind"] == "paper_session_manifest"
        and entry["candidate_id"] == ids["candidate_id"]
        for entry in review_entries
    )
    assert any(
        entry["entry_kind"] == "paper_broker_adapter_startup_sync"
        and entry["candidate_id"] == ids["candidate_id"]
        for entry in review_entries
    )

    report_entries = subject_index["report_date"]["2026-05-09"]
    assert any(
        entry["entry_kind"] == "ledger_reconciliation_artifact"
        and entry["paths"]["ledger_reconciliation_artifact"].endswith(
            f"ledger_recon_artifact_{artifact_hash[:16]}.json"
        )
        for entry in report_entries
    )

    session_lookup = find_registry_subject_evidence(
        tmp_path,
        session_id="paper_session_open",
    )
    assert session_lookup["matched"] is True
    assert {
        entry["entry_kind"] for entry in session_lookup["entries"]
    } >= {
        "daily_report",
        "paper_session_manifest",
        "paper_broker_adapter_startup_sync",
        "ledger_reconciliation_artifact",
    }
