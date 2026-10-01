from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

import quant_crypto.adapters.btc_runtime_artifact_store as store_module
import quant_crypto.application.btc_current_head_gate_rebuild as rebuild_module
from quant_crypto.adapters.btc_domain_read_model_repository import (
    BTCPublishedDomainReadModelRepository,
)
from quant_crypto.adapters.btc_runtime_artifact_store import (
    ENVIRONMENT_VARIABLE,
    OWNER_MARKER_NAME,
    BTCRuntimeArtifactReader,
    BTCRuntimeArtifactStoreError,
    BTCRuntimeArtifactWriter,
    BTCRuntimeArtifactWriteSession,
    build_btc_runtime_artifact_owner_marker,
)
from quant_crypto.application.btc_current_head_gate_rebuild import (
    CurrentHeadGateRebuildError,
    DEFAULT_EVIDENCE_PATHS,
    DEFAULT_OKX_POINTER_PATH,
    DEFAULT_REBUILD_REPORT_PATH,
    OKX_POINTER_SCHEMA_VERSION,
    evaluate_current_head_gate_evidence,
    rebuild_btc_current_head_gate,
    validate_authoritative_okx_pointer,
)
from quant_crypto.application.btc_gate_snapshot import (
    GateBuildState,
    load_latest_gate_snapshot,
)
from quant_crypto.research.btc_okx_native_promotion_gate import (
    ACTIVE_CRITERIA_LINEAGE_BLOCKER,
    ACTIVE_FAMILY_SCOPE_BLOCKER,
    FROZEN_PREREG_BLOB_SHA256,
    INFORMATION_COVERAGE_BLOCKER,
)
from tests.contracts.test_btc_10s_microstructure_data_contract_report import (
    _prereg,
    _ready_metrics,
)


HEAD = "a" * 40
OTHER_HEAD = "b" * 40
NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
HASH = "c" * 64


def test_missing_external_evidence_publishes_valid_blocked_current_head_snapshot(
    tmp_path: Path,
) -> None:
    source_root, artifact_root, reader, writer = _stores(tmp_path)
    report = rebuild_btc_current_head_gate(
        repo_root=source_root,
        current_head=HEAD,
        generated_at_utc=NOW,
        run_id="btc-g09-missing-evidence",
        state_provider=_stable_state,
        artifact_reader=reader,
        artifact_writer=writer,
    )

    assert report["status"] == "complete_blocked"
    assert report["decision"] == "blocked_fail_closed_no_paper_no_live"
    assert report["quality_checked"] is True
    assert report["research_ready"] is False
    assert report["backtest_ready"] is False
    assert report["promotion_evidence_ready"] is False
    assert all(value is False for value in report["safety"].values())
    assert {
        "btc_okx_native:promotion_evidence_current_head_rebuild_required",
        "btc_okx_native:historical_timestamp_aligned_depth_fill_mapping_missing",
        "btc_okx_native:natural_strategy_runtime_non_flat_fill_sample_missing",
        "btc_okx_native:funding_cashflow_not_observed_in_demo_runtime",
        "btc_okx_native:private_ws_runtime_reconciliation_observation_incomplete",
        "btc_okx_native:25_hour_demo_observation_window_incomplete",
        "btc_okx_native:manual_promotion_approval_missing",
        ACTIVE_FAMILY_SCOPE_BLOCKER,
        INFORMATION_COVERAGE_BLOCKER,
        ACTIVE_CRITERIA_LINEAGE_BLOCKER,
    } == set(report["blockers"])

    latest = load_latest_gate_snapshot(source_root, artifact_reader=reader)
    assert latest["status"] == "valid"
    assert latest["pointer"]["code_commit"] == HEAD
    assert latest["pointer"]["aggregation_batch_id"] == "btc-g09-missing-evidence"
    assert latest["manifest"]["status"] == "complete_immutable_gate_snapshot"
    assert latest["manifest"]["validation_checks"]["all_batch_ids_match"] is True
    assert len(latest["manifest"]["artifacts"]) == 8
    assert (
        report["snapshot_publication"]["run_manifest_sha256"]
        == latest["pointer"]["manifest_sha256"]
    )

    read_model = _read_json(
        reader.resolve(
            "artifacts/btc_domain_read_model/latest/btc_domain_read_model.json"
        )
    )
    assert read_model["source_head"] == HEAD
    assert read_model["aggregation_batch_id"] == "btc-g09-missing-evidence"
    assert read_model["status"] == "blocked"
    assert read_model["decision"] == "blocked_fail_closed_no_paper_no_live"
    assert read_model["current_stage"] == "pending_next_stage_gate"
    assert read_model["required_blockers_preserved"] is True
    assert read_model["required_blockers_missing"] == []
    assert len(read_model["safety"]) == 49
    assert read_model["paper_ready"] is False
    assert read_model["live_ready"] is False
    published = BTCPublishedDomainReadModelRepository(
        repo_root=Path.cwd(),
        artifact_reader=reader,
    ).read_published(source_head=HEAD)
    assert published == read_model
    dashboard = _read_json(
        reader.resolve(
            "artifacts/btc_gate_dashboard/latest/btc_gate_dashboard.json"
        )
    )
    assert dashboard["root_cause_source"] == "promotion_gate_control"
    assert any(
        row["root_cause_id"] == "runtime_ready_waiting_non_flat_sample"
        for row in dashboard["root_cause_matrix"]
    )
    manual = _read_json(
        reader.resolve(
            "artifacts/btc_manual_paper_review_approval/latest/"
            "btc_manual_paper_review_approval_report.json"
        )
    )
    assert manual["manual_approval_recorded"] is False
    assert manual["status"] == "missing_or_invalid_research_only"

    schema = _read_json(
        Path("schemas/btc_current_head_gate_rebuild.schema.json")
    )
    jsonschema.validate(report, schema)


def test_read_model_without_aggregation_batch_id_is_not_published(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, artifact_root, reader, writer = _stores(tmp_path)
    original_build_read_model = rebuild_module._build_read_model

    def build_read_model_without_batch(**kwargs: object) -> dict[str, object]:
        payload = original_build_read_model(**kwargs)
        payload.pop("aggregation_batch_id")
        return payload

    monkeypatch.setattr(
        rebuild_module,
        "_build_read_model",
        build_read_model_without_batch,
    )

    with pytest.raises(
        CurrentHeadGateRebuildError,
        match=(
            "btc_current_head_gate_output_validation_failed:"
            "all_batch_ids_match"
        ),
    ):
        rebuild_btc_current_head_gate(
            repo_root=source_root,
            current_head=HEAD,
            generated_at_utc=NOW,
            run_id="btc-g09-read-model-batch-missing",
            state_provider=_stable_state,
            artifact_reader=reader,
            artifact_writer=writer,
        )

    assert not (
        reader.resolve("artifacts/btc_gate_runs/latest_pointer.json")
    ).exists()


def test_read_model_without_strict_published_semantics_is_not_published(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, artifact_root, reader, writer = _stores(tmp_path)
    original_build_read_model = rebuild_module._build_read_model

    def build_read_model_with_legacy_stage(**kwargs: object) -> dict[str, object]:
        payload = original_build_read_model(**kwargs)
        payload["current_stage"] = "waiting_for_natural_non_flat_sample"
        return payload

    monkeypatch.setattr(
        rebuild_module,
        "_build_read_model",
        build_read_model_with_legacy_stage,
    )

    with pytest.raises(
        CurrentHeadGateRebuildError,
        match=(
            "btc_current_head_gate_output_validation_failed:"
            "read_model_contract_valid"
        ),
    ):
        rebuild_btc_current_head_gate(
            repo_root=source_root,
            current_head=HEAD,
            generated_at_utc=NOW,
            run_id="btc-g09-read-model-legacy-stage",
            state_provider=_stable_state,
            artifact_reader=reader,
            artifact_writer=writer,
        )

    assert not (
        reader.resolve("artifacts/btc_gate_runs/latest_pointer.json")
    ).exists()


def test_valid_current_head_evidence_retires_only_evidence_driven_blockers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, artifact_root, reader, writer = _stores(tmp_path)
    monkeypatch.setattr(
        rebuild_module,
        "load_frozen_active_criteria_prereg",
        lambda _repo_root, *, current_head: (
            _prereg(),
            FROZEN_PREREG_BLOB_SHA256,
        ),
    )
    pointer = _write_valid_pointer(reader, head=HEAD)
    common = {
        "source_head": HEAD,
        "generated_at_utc": NOW.isoformat(),
        "data_version": "btc-okx-immutable-v1",
        "run_id": "evidence-run-1",
        "params_hash": HASH,
        "output_hash": HASH,
        "input_hashes": {"immutable://btc/l2/v1": HASH},
        "evidence_class": "promotion_evidence",
        "promotion_evidence_ready": True,
    }
    _write_json(
        reader.resolve(DEFAULT_EVIDENCE_PATHS["active_criteria"]),
        _active_criteria(pointer),
    )
    _write_json(
        reader.resolve(DEFAULT_EVIDENCE_PATHS["l2_batch"]),
        {
            **common,
            "schema_version": "btc_okx_l2_depth_observation_batch_v2",
            "depth_gate_progress_after": {"gate_ready": True},
        },
    )
    _write_json(
        reader.resolve(DEFAULT_EVIDENCE_PATHS["fill_mapping"]),
        {
            **common,
            "schema_version": "btc_depth_slippage_fill_mapping_report_v2",
            "strategy_fill_mapping_verified": True,
            "depth_integrity": {"valid_for_mapping": True},
        },
    )
    _write_json(
        reader.resolve(DEFAULT_EVIDENCE_PATHS["nonflat"]),
        {
            **common,
            "schema_version": "btc_nonflat_evidence_autocapture_v1",
            "sample_origin": "current_natural_observation",
            "nodes": [{"node_id": "01-signal"}],
            "audit_dag": {"valid": True},
            "funding_cashflow_observed": True,
            "private_ws_observed": True,
        },
    )
    _write_json(
        reader.resolve(DEFAULT_EVIDENCE_PATHS["observation_window"]),
        {
            "schema_version": "btc_demo_observation_accumulator_v3",
            "source_head": HEAD,
            "generated_at_utc": NOW.isoformat(),
            "authority": "authorized_okx_demo_accumulator",
            "evidence_class": "authorized_okx_demo_observation_window",
            "required_observation_hours": 25,
            "observation_hours": 25,
            "window_25h_complete": True,
            "strategy_version": "btc-trend@1",
            "data_version": "btc-okx-immutable-v1",
            "runtime_version": "btc-demo-runtime-v1",
            "runtime_run_id": "demo-run-1",
            "ledger_integrity": {"valid": True},
            "readiness": {"observation_window_ready": True},
            "version_policy": {
                "cross_head_accumulation_allowed": False,
                "cross_strategy_version_accumulation_allowed": False,
                "cross_data_version_accumulation_allowed": False,
                "cross_runtime_version_accumulation_allowed": False,
                "cross_runtime_run_accumulation_allowed": False,
            },
            "blockers": [],
            "safety": {
                "promotion_enabled": False,
                "paper_enabled": False,
                "live_enabled": False,
            },
        },
    )
    _write_json(
        reader.resolve(DEFAULT_EVIDENCE_PATHS["manual_approval"]),
        {
            "source_head": HEAD,
            "generated_at_utc": NOW.isoformat(),
            "manual_approval_recorded": True,
            "blockers": [],
        },
    )

    report = rebuild_btc_current_head_gate(
        repo_root=source_root,
        current_head=HEAD,
        generated_at_utc=NOW,
        run_id="btc-g09-valid-evidence",
        state_provider=_stable_state,
        artifact_reader=reader,
        artifact_writer=writer,
    )

    assert report["blockers"] == []
    assert report["promotion_evidence_ready"] is True
    assert report["safety"]["paper_allowed"] is False
    assert report["safety"]["live_allowed"] is False
    assert report["safety"]["private_endpoint_allowed"] is False
    assert report["safety"]["order_endpoint_allowed"] is False


def test_read_model_blockers_are_exactly_the_current_gate_canonical_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, artifact_root, reader, writer = _stores(tmp_path)
    monkeypatch.setattr(
        rebuild_module,
        "load_frozen_active_criteria_prereg",
        lambda _repo_root, *, current_head: (
            _prereg(),
            FROZEN_PREREG_BLOB_SHA256,
        ),
    )
    pointer = _write_valid_pointer(reader, head=HEAD)
    active = _active_criteria(pointer)
    active["measured_metrics"]["information_by_horizon"]["10s"][
        "eligible_labeled_windows"
    ] = 0
    active["measured_metrics"]["information_by_horizon"]["10s"][
        "autocorrelation_adjusted_ess"
    ] = 0.0
    _write_json(
        reader.resolve(DEFAULT_EVIDENCE_PATHS["active_criteria"]),
        active,
    )

    report = rebuild_btc_current_head_gate(
        repo_root=source_root,
        current_head=HEAD,
        generated_at_utc=NOW,
        run_id="btc-g09-seven-canonical-blockers",
        state_provider=_stable_state,
        artifact_reader=reader,
        artifact_writer=writer,
    )
    read_model = _read_json(
        reader.resolve(
            "artifacts/btc_domain_read_model/latest/btc_domain_read_model.json"
        )
    )
    blocker_codes = [row["code"] for row in read_model["blockers"]]

    assert len(report["blockers"]) == 7
    assert blocker_codes == report["blockers"]
    assert read_model["required_blockers"] == report["blockers"]
    assert read_model["required_blocker_count"] == 7
    assert read_model["required_blockers_missing"] == []
    assert read_model["required_blockers_preserved"] is True
    assert len(blocker_codes) == len(set(blocker_codes))
    assert not {
        "btc_okx_public_ws_primary_connection_reset_10054",
        "runtime_pointer_immutable_snapshot_not_published",
        "manifest_quality_status_not_pass",
        "btc_okx_native:active_criteria_pointer_lineage_mismatch",
    }.intersection(blocker_codes)


def test_pointer_wrong_head_and_evidence_hash_mismatch_fail_closed(
    tmp_path: Path,
) -> None:
    source_root, artifact_root, reader, writer = _stores(tmp_path)
    pointer = _write_valid_pointer(reader, head=OTHER_HEAD)
    pointer["evidence"]["sha256"] = "0" * 64
    _write_json(reader.resolve(DEFAULT_OKX_POINTER_PATH), pointer)

    result = validate_authoritative_okx_pointer(
        repo_root=source_root,
        current_head=HEAD,
        artifact_reader=reader,
    )

    assert result["status"] == "blocked_fail_closed"
    assert "pointer:source_code_commit_wrong_head" in result["validation_errors"]
    assert "evidence:sha256_mismatch" in result["validation_errors"]
    assert result["promotion_evidence_ready"] is False
    assert all(value is False for value in result["safety"].values())


@pytest.mark.parametrize(
    "failure_mode",
    (
        "forged_uri",
        "missing_file",
        "hash_mismatch",
        "manifest_membership_mismatch",
        "producer_role_mismatch",
    ),
)
def test_pointer_data_steward_attestation_is_resolved_and_identity_bound(
    tmp_path: Path,
    failure_mode: str,
) -> None:
    source_root, artifact_root, reader, writer = _stores(tmp_path)
    pointer = _write_valid_pointer(reader, head=HEAD)
    manifest_path = reader.resolve(pointer["manifest"]["path"])
    evidence_path = reader.resolve(pointer["evidence"]["path"])
    manifest = _read_json(manifest_path)
    evidence = _read_json(evidence_path)
    lineage = pointer["input_lineage"][0]
    attestation_path = reader.resolve(lineage["path"])

    if failure_mode == "forged_uri":
        forged = {
            **lineage,
            "uri": "immutable://btc/okx/forged-attestation",
            "path": "artifacts/forged/data-steward-attestation.json",
            "sha256": "f" * 64,
        }
        pointer["input_lineage"] = [dict(forged)]
        manifest["input_lineage"] = [dict(forged)]
        evidence["input_lineage"] = [dict(forged)]
    elif failure_mode == "missing_file":
        attestation_path.unlink()
    elif failure_mode == "hash_mismatch":
        for payload in (pointer, manifest, evidence):
            payload["input_lineage"][0]["sha256"] = "0" * 64
    elif failure_mode == "manifest_membership_mismatch":
        manifest["input_lineage"][0]["uri"] = (
            "immutable://btc/okx/different-attestation"
        )
    elif failure_mode == "producer_role_mismatch":
        attestation = _read_json(attestation_path)
        attestation["producer_role"] = "btc_developer"
        _write_json(attestation_path, attestation)
        actual_sha = _sha256(attestation_path)
        for payload in (pointer, manifest, evidence):
            payload["input_lineage"][0]["sha256"] = actual_sha

    _write_json(manifest_path, manifest)
    _write_json(evidence_path, evidence)
    pointer["manifest"]["sha256"] = _sha256(manifest_path)
    pointer["evidence"]["sha256"] = _sha256(evidence_path)
    _write_json(reader.resolve(DEFAULT_OKX_POINTER_PATH), pointer)

    result = validate_authoritative_okx_pointer(
        repo_root=source_root,
        current_head=HEAD,
        artifact_reader=reader,
    )

    assert result["status"] == "blocked_fail_closed"
    assert any("attestation" in error for error in result["validation_errors"])
    assert result["verified_data_steward_attestation"] == {}
    assert result["promotion_evidence_ready"] is False


def test_readiness_classes_remain_distinct_when_only_pointer_is_valid(
    tmp_path: Path,
) -> None:
    source_root, artifact_root, reader, writer = _stores(tmp_path)
    _write_valid_pointer(reader, head=HEAD)
    pointer = validate_authoritative_okx_pointer(
        repo_root=source_root,
        current_head=HEAD,
        artifact_reader=reader,
    )

    evaluation = evaluate_current_head_gate_evidence(
        current_head=HEAD,
        generated_at_utc=NOW,
        pointer_validation=pointer,
        evidence={},
    )

    assert evaluation["quality_checked"] is True
    assert evaluation["research_ready"] is False
    assert evaluation["backtest_ready"] is False
    assert evaluation["promotion_evidence_ready"] is False
    assert evaluation["blockers"]


def test_builder_failure_before_publication_leaves_latest_outputs_untouched(
    tmp_path: Path,
) -> None:
    source_root, artifact_root, reader, writer = _stores(tmp_path)
    def fail() -> None:
        raise RuntimeError("injected_builder_failure")

    with pytest.raises(RuntimeError, match="injected_builder_failure"):
        rebuild_btc_current_head_gate(
            repo_root=source_root,
            current_head=HEAD,
            generated_at_utc=NOW,
            run_id="btc-g09-failed",
            state_provider=_stable_state,
            before_publish=fail,
            artifact_reader=reader,
            artifact_writer=writer,
        )

    assert not (
        reader.resolve("artifacts/btc_gate_runs/latest_pointer.json")
    ).exists()
    assert not (
        reader.resolve(
            "artifacts/btc_promotion_gate_control/latest/"
            "btc_promotion_gate_control_report.json"
        )
    ).exists()
    assert not (
        reader.resolve(
            "artifacts/btc_gate_dashboard/latest/btc_gate_dashboard.json"
        )
    ).exists()
    assert not (
        reader.resolve(
            "artifacts/btc_domain_read_model/latest/btc_domain_read_model.json"
        )
    ).exists()
    assert not (
        reader.resolve(
            "artifacts/btc_paper_readiness/latest/"
            "btc_paper_readiness_report.json"
        )
    ).exists()


def test_existing_writer_lock_stops_overlapping_rebuild(
    tmp_path: Path,
) -> None:
    source_root, artifact_root, reader, writer = _stores(tmp_path)

    with writer.exclusive():
        with pytest.raises(
            BTCRuntimeArtifactStoreError,
            match="btc_runtime_artifact_writer_lock_held",
        ):
            rebuild_btc_current_head_gate(
                repo_root=source_root,
                current_head=HEAD,
                generated_at_utc=NOW,
                run_id="btc-g09-lock-conflict",
                state_provider=_stable_state,
                artifact_reader=reader,
                artifact_writer=writer,
            )


def test_rebuild_report_write_failure_preserves_previous_pointer_bytes_and_hash(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_root, artifact_root, reader, writer = _stores(tmp_path)
    rebuild_btc_current_head_gate(
        repo_root=source_root,
        current_head=HEAD,
        generated_at_utc=NOW,
        run_id="btc-g09-old-pointer",
        state_provider=_stable_state,
        artifact_reader=reader,
        artifact_writer=writer,
    )
    pointer_path = reader.resolve(
        "artifacts/btc_gate_runs/latest_pointer.json"
    )
    pointer_before = pointer_path.read_bytes()
    pointer_hash_before = hashlib.sha256(pointer_before).hexdigest()
    real_write_json = BTCRuntimeArtifactWriteSession.write_json_atomic

    def fail_rebuild_report_write(self, logical_path, payload):
        if Path(logical_path) == DEFAULT_REBUILD_REPORT_PATH:
            raise OSError("injected_rebuild_report_write_failure")
        return real_write_json(self, logical_path, payload)

    monkeypatch.setattr(
        store_module.BTCRuntimeArtifactWriteSession,
        "write_json_atomic",
        fail_rebuild_report_write,
    )

    with pytest.raises(
        OSError,
        match="injected_rebuild_report_write_failure",
    ):
        rebuild_btc_current_head_gate(
            repo_root=source_root,
            current_head=HEAD,
            generated_at_utc=NOW,
            run_id="btc-g09-report-write-failed",
            state_provider=_stable_state,
            artifact_reader=reader,
            artifact_writer=writer,
        )

    assert pointer_path.read_bytes() == pointer_before
    assert hashlib.sha256(pointer_path.read_bytes()).hexdigest() == (
        pointer_hash_before
    )
    assert not reader.resolve(
        "artifacts/btc_gate_runs/btc-g09-report-write-failed"
    ).exists()


def test_rebuild_report_validation_failure_preserves_previous_pointer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_root, artifact_root, reader, writer = _stores(tmp_path)
    rebuild_btc_current_head_gate(
        repo_root=source_root,
        current_head=HEAD,
        generated_at_utc=NOW,
        run_id="btc-g09-old-validation-pointer",
        state_provider=_stable_state,
        artifact_reader=reader,
        artifact_writer=writer,
    )
    pointer_path = reader.resolve(
        "artifacts/btc_gate_runs/latest_pointer.json"
    )
    pointer_before = pointer_path.read_bytes()
    report_path = reader.resolve(DEFAULT_REBUILD_REPORT_PATH)
    report_before = report_path.read_bytes()

    def fail_validation(**_kwargs):
        raise CurrentHeadGateRebuildError(
            "injected_rebuild_report_validation_failure"
        )

    monkeypatch.setattr(
        rebuild_module,
        "_validate_rebuild_report_for_publish",
        fail_validation,
    )

    with pytest.raises(
        CurrentHeadGateRebuildError,
        match="injected_rebuild_report_validation_failure",
    ):
        rebuild_btc_current_head_gate(
            repo_root=source_root,
            current_head=HEAD,
            generated_at_utc=NOW,
            run_id="btc-g09-report-validation-failed",
            state_provider=_stable_state,
            artifact_reader=reader,
            artifact_writer=writer,
        )

    assert pointer_path.read_bytes() == pointer_before
    assert report_path.read_bytes() == report_before
    assert not reader.resolve(
        "artifacts/btc_gate_runs/btc-g09-report-validation-failed"
    ).exists()


@pytest.mark.parametrize("mismatch", ["artifact_root", "repository_identity"])
def test_rebuild_rejects_mismatched_reader_writer_store(
    tmp_path: Path,
    mismatch: str,
) -> None:
    source_root, artifact_root, reader, writer = _stores(tmp_path)
    if mismatch == "artifact_root":
        other_root = tmp_path / "other-runtime-artifacts"
        other_root.mkdir()
        _write_json(
            other_root / OWNER_MARKER_NAME,
            build_btc_runtime_artifact_owner_marker(
                reader.repository_identity
            ),
        )
        reader = BTCRuntimeArtifactReader(
            source_repo_root=source_root,
            artifact_root=other_root.resolve(),
            repository_identity=reader.repository_identity,
            worktree_roots=(source_root,),
        )
    else:
        reader = BTCRuntimeArtifactReader(
            source_repo_root=source_root,
            artifact_root=reader.artifact_root,
            repository_identity="sha256:" + "b" * 64,
            worktree_roots=(source_root,),
        )

    with pytest.raises(
        CurrentHeadGateRebuildError,
        match="btc_current_head_gate_artifact_store_mismatch",
    ):
        rebuild_btc_current_head_gate(
            repo_root=source_root,
            current_head=HEAD,
            generated_at_utc=NOW,
            run_id=f"btc-g09-mismatch-{mismatch}",
            state_provider=_stable_state,
            artifact_reader=reader,
            artifact_writer=writer,
        )


def _write_valid_pointer(
    reader: BTCRuntimeArtifactReader,
    *,
    head: str,
) -> dict:
    run_root = reader.resolve(
        "artifacts/btc_okx_native_backtest_evidence/runs/evidence-run-1"
    )
    manifest_path = run_root / "manifest.json"
    evidence_path = run_root / "evidence.json"
    attestation_path = run_root / "data-steward-attestation.json"
    identity = {
        "source_code_commit": head,
        "run_id": "evidence-run-1",
        "data_version": "btc-okx-immutable-v1",
        "dataset_id": "btc-okx-native-backtest-evidence",
        "aggregate_sha256": "c" * 64,
        "manifest_identity": "btc-okx-native-backtest-manifest-v1",
    }
    _write_json(
        attestation_path,
        {
            **identity,
            "schema_version": "btc_okx_native_data_steward_attestation_v1",
            "producer_role": "data_steward",
            "immutable_uri": (
                "immutable://btc/okx/backtest/evidence-run-1/attestation"
            ),
        },
    )
    attestation_lineage = {
        "kind": "data_steward_attestation",
        "uri": "immutable://btc/okx/backtest/evidence-run-1/attestation",
        "path": reader.logical_path(attestation_path).as_posix(),
        "sha256": _sha256(attestation_path),
        "producer_role": "data_steward",
    }
    _write_json(
        manifest_path,
        {
            **identity,
            "schema_version": "btc_okx_native_backtest_manifest_v1",
            "immutable_uri": "immutable://btc/okx/backtest/evidence-run-1",
            "immutable_version": "btc-okx-immutable-v1",
            "input_lineage": [dict(attestation_lineage)],
        },
    )
    _write_json(
        evidence_path,
        {
            **identity,
            "schema_version": "btc_okx_native_backtest_evidence_v1",
            "status": "quality_checked",
            "input_lineage": [dict(attestation_lineage)],
        },
    )
    pointer = {
        "schema_version": OKX_POINTER_SCHEMA_VERSION,
        **identity,
        "immutable_uri": "immutable://btc/okx/backtest/evidence-run-1",
        "immutable_version": "btc-okx-immutable-v1",
        "manifest": {
            "path": reader.logical_path(manifest_path).as_posix(),
            "sha256": _sha256(manifest_path),
        },
        "evidence": {
            "path": reader.logical_path(evidence_path).as_posix(),
            "sha256": _sha256(evidence_path),
        },
        "input_lineage": [dict(attestation_lineage)],
    }
    _write_json(reader.resolve(DEFAULT_OKX_POINTER_PATH), pointer)
    return pointer


def _active_criteria(pointer: dict[str, object]) -> dict[str, object]:
    prereg = _prereg()
    semantic = hashlib.sha256(
        json.dumps(
            prereg,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    lineage = pointer["input_lineage"][0]
    return {
        "schema_version": "btc_promotion_gate_active_criteria_v1",
        "source_head": HEAD,
        "generated_at_utc": NOW.isoformat(),
        "active_strategy_family": "micro_breakout",
        "active_horizon": "10s",
        "run_id": pointer["run_id"],
        "data_version": pointer["data_version"],
        "immutable_manifest_sha256": pointer["manifest"]["sha256"],
        "immutable_evidence_sha256": pointer["evidence"]["sha256"],
        "data_steward_attestation": dict(lineage),
        "prereg_semantic_sha256": semantic,
        "prereg_blob_sha256": FROZEN_PREREG_BLOB_SHA256,
        "preregistration": prereg,
        "measured_metrics": _ready_metrics(),
    }


def _stable_state(
    _root: Path,
    _inputs: list[Path],
) -> GateBuildState:
    return GateBuildState(
        code_commit=HEAD,
        dirty_status_hash=HASH,
        dirty_paths=(),
        source_input_hash=HASH,
        watched_input_hash=HASH,
        input_snapshot_hash=HASH,
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stores(
    tmp_path: Path,
) -> tuple[
    Path,
    Path,
    BTCRuntimeArtifactReader,
    BTCRuntimeArtifactWriter,
]:
    source_root = tmp_path / "source-worktree"
    source_root.mkdir()
    artifact_root = tmp_path / "runtime-artifacts"
    artifact_root.mkdir()
    repository_identity = "sha256:" + "a" * 64
    _write_json(
        artifact_root / OWNER_MARKER_NAME,
        build_btc_runtime_artifact_owner_marker(repository_identity),
    )
    kwargs = {
        "source_repo_root": source_root,
        "environment": {ENVIRONMENT_VARIABLE: str(artifact_root)},
        "repository_identity": repository_identity,
        "worktree_roots": (source_root,),
    }
    return (
        source_root,
        artifact_root,
        BTCRuntimeArtifactReader.from_environment(**kwargs),
        BTCRuntimeArtifactWriter.from_environment(**kwargs),
    )
