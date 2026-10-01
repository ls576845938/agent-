from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

from quant_crypto.adapters.btc_runtime_artifact_store import (
    ENVIRONMENT_VARIABLE,
    BTCRuntimeArtifactWriter,
)
from quant_crypto.application import btc_next_stage_current_head_orchestrator as subject
from quant_crypto.application.btc_gate_snapshot import (
    DEFAULT_POINTER_PATH,
    GateBuildState,
)
from scripts import build_btc_next_stage_current_head_orchestrator as cli


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_MANIFEST = Path(
    ".agent/data_manifests/btc-okx-v3-immutable-public-market-evidence/"
    "btc-okx-v3-public-btcusdt-20260727T075929750Z-src311c5ec7.json"
)
DATA_HANDOFF = Path(
    ".agent/handoffs/DATA-BTC-V3-IMMUTABLE-PUBLIC-MARKET-EVIDENCE-01/"
    "integrated-data-btc-v3-immutable-public-market-evidence-01.json"
)
ENGINEERING_HANDOFF = Path(
    ".agent/handoffs/BTC-V3-NEXT-STAGE-ENGINEERING-CLOSURE-02/"
    "integrated-btc-v3-next-stage-engineering-closure-02.json"
)
REAL_L2_MANIFEST = Path(
    ".agent/data_manifests/btc-okx-real-l2-attestation/"
    "btc-okx-real-l2-attestation-20260728T143943Z-746b70207-blocked1.json"
)
QUALITY_L2_MANIFEST = Path(
    ".agent/data_manifests/btc-okx-real-l2-attestation/"
    "btc-okx-real-l2-attestation-20260728T232947Z-e3471caf3-"
    "timestamp-precision07-quality1.json"
)


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _payload(path: Path) -> dict:
    return json.loads((REPO_ROOT / path).read_text(encoding="utf-8"))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_required_blocker_contract_uses_information_and_family_scope() -> None:
    for blockers in (subject.REQUIRED_BLOCKERS, subject.QUALITY_L2_REQUIRED_BLOCKERS):
        serialized = json.dumps(blockers).lower()
        assert "30_natural_days" not in serialized
        assert "open_interest_history_not_verified_diagnostic_partial" not in blockers
        assert subject.INFORMATION_COVERAGE_BLOCKER in blockers
        assert subject.ACTIVE_FAMILY_SCOPE_BLOCKER in blockers
        assert len(blockers) == len(set(blockers))

    aliases = {
        "funding": subject.FUNDING_OBSERVATION_BLOCKER,
        "private_ws": subject.PRIVATE_WS_BLOCKER,
        "non_flat": subject.NATURAL_SAMPLE_BLOCKER,
        "manual": subject.MANUAL_APPROVAL_BLOCKER,
    }
    for canonical in aliases.values():
        assert subject.QUALITY_L2_REQUIRED_BLOCKERS.count(canonical) == 1


@pytest.fixture
def inputs(tmp_path: Path) -> subject.ValidatedInputs:
    paths = [REPO_ROOT / path for path in (DATA_MANIFEST, DATA_HANDOFF, ENGINEERING_HANDOFF)]
    return subject.ValidatedInputs(
        manifest=_payload(DATA_MANIFEST),
        data_handoff=_payload(DATA_HANDOFF),
        engineering_handoff=_payload(ENGINEERING_HANDOFF),
        manifest_path=paths[0],
        data_handoff_path=paths[1],
        engineering_handoff_path=paths[2],
        raw_hashes={
            "data_manifest": _digest(paths[0]),
            "data_integrated_handoff": _digest(paths[1]),
            "engineering_integrated_handoff": _digest(paths[2]),
            "expected_head": hashlib.sha256(_head().encode("ascii")).hexdigest(),
            "real_l2_attestation_manifest": _digest(
                REPO_ROOT / REAL_L2_MANIFEST
            ),
        },
        data_root=tmp_path / "shared-data",
        real_l2_manifest=_payload(REAL_L2_MANIFEST),
        real_l2_manifest_path=REPO_ROOT / REAL_L2_MANIFEST,
        real_l2_receipt={
            "status": "blocked",
            "decision": "blocked",
            "public_ws_attempts": [],
            "sequence": {},
            "controlled_recovery": {},
            "server_clock": {},
            "readiness": {},
            "safety": {},
            "blockers": list(subject.REAL_L2_ATTESTATION_BLOCKERS),
        },
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _quality_attestation() -> dict:
    return {
        "schema_version": "btc_okx_l2_dataready_attestation_v1",
        "dataset_id": "btc-okx-timestamp-aligned-public-l2-history",
        "dataset_version": (
            "btc-okx-real-l2-attestation-20260728T232947Z-e3471caf3-"
            "timestamp-precision07-quality1"
        ),
        "producer_role": "data_steward",
        "source_head": "e3471caf3717cc43f86443543368b1a6b4fa6613",
        "venue": "okx",
        "instrument_id": "BTC-USDT-SWAP",
        "quality_checked": True,
        "promotion_evidence_ready": False,
        "readiness": {
            "backtest_ready": False,
            "promotion_evidence_ready": False,
            "quality_checked": True,
            "research_ready": False,
        },
        "sequence_validation_status": "pass",
        "sequence_gap_count": 0,
        "duplicate_sequence_count": 0,
        "out_of_order_sequence_count": 0,
        "unrecovered_gap_count": 0,
        "clock_offset_attested": True,
        "max_clock_offset_ms": 188.132,
        "max_clock_lag_policy_ms": 2000.0,
        "checksum_policy": subject.QUALITY_L2_CHECKSUM_POLICY,
        "checksum_observed_count": 57,
        "book_record_count": 57,
        "two_sided_snapshot_count": 57,
        "reconnect_count": 2,
        "promotion_blockers": list(
            subject.QUALITY_L2_REQUIRED_BLOCKERS[:5]
        ),
        "guardrails": {
            "broker_call_used": False,
            "database_payload_emitted": False,
            "network_collection_used": False,
            "order_endpoint_used": False,
            "paper_or_live_unlock_allowed": False,
            "private_endpoint_used": False,
            "promotion_unlock_allowed": False,
            "real_order_submitted": False,
            "shared_data_published": False,
            "source_segments_mutated": False,
        },
    }


def _quality_case(
    tmp_path: Path,
    *,
    mutate=None,
) -> tuple[dict, Path]:
    attestation = _quality_attestation()
    if mutate is not None:
        mutate(attestation)
    root = tmp_path / "quality-root"
    path = root / subject.QUALITY_L2_ATTESTATION_PATH
    _write_json(path, attestation)
    manifest = {
        "dataset_id": "btc-okx-real-l2-attestation",
        "dataset_version": attestation["dataset_version"],
        "producer_commit": attestation["source_head"],
        "producer_role": "data_steward",
        "quality_status": subject.QUALITY_L2_MANIFEST_STATUS,
        "readiness_class": "quality_checked",
        "blockers": [
            *attestation["promotion_blockers"],
            *subject.QUALITY_L2_MANIFEST_GUARDRAIL_BLOCKERS,
        ],
        "files": [
            {
                "path": subject.QUALITY_L2_ATTESTATION_PATH,
                "bytes": path.stat().st_size,
                "sha256": _digest(path),
            }
        ],
    }
    return manifest, root


def _fake_paper_builder(
    *,
    repo_root: Path,
    output_dir: Path,
    config_path: Path,
    long_short_observations_path: Path,
    attack_observations_path: Path,
    high_yield_observations_path: Path,
    cost_model_report_path: Path,
    perpetual_evidence_report_path: Path,
    **_: object,
) -> dict:
    for path in (
        config_path,
        long_short_observations_path,
        attack_observations_path,
        high_yield_observations_path,
        cost_model_report_path,
        perpetual_evidence_report_path,
    ):
        assert path.is_file()
        assert str(path).startswith(str(output_dir.parents[1]))
    payload = {
        "schema_version": "legacy_paper_v1",
        "code_commit": _head()[:12],
        "status": "blocked",
        "blockers": ["legacy_paper_blocked"],
    }
    _write_json(output_dir / "btc_perpetual_paper_runtime_replay_report.json", payload)
    _write_json(
        output_dir
        / "btc_perpetual_paper_runtime_replay_oms_session_reconciliation_report.json",
        {
            **payload,
            "positions_receipt_present": False,
            "cash_receipt_present": False,
            "pnl_receipt_present": False,
        },
    )
    return payload


def _fake_strategy_builder(
    *,
    output_dir: Path,
    paper_runtime_replay_report_path: Path,
    gate_dashboard_report_path: Path,
    **_: object,
) -> dict:
    assert paper_runtime_replay_report_path.is_file()
    assert gate_dashboard_report_path.is_file()
    payload = {
        "schema_version": "legacy_strategy_v1",
        "code_commit": _head()[:12],
        "status": "blocked",
        "blockers": ["legacy_strategy_blocked"],
    }
    _write_json(output_dir / "btc_strategy_promotion_readiness_report.json", payload)
    return payload


def _fake_gate_builder(
    *,
    repo_root: Path,
    output_dir: Path,
    source_paths: dict[str, Path],
    **_: object,
) -> dict:
    assert repo_root == REPO_ROOT
    assert source_paths
    assert all(path.is_file() for path in source_paths.values())
    payload = {
        "schema_version": "legacy_gate_v1",
        "code_commit": _head()[:12],
        "status": "blocked",
        "blockers": ["legacy_gate_blocked"],
    }
    _write_json(output_dir / "btc_promotion_gate_control_report.json", payload)
    return payload


def _fake_stage_bundle(*, session, stage_root: Path, inputs) -> Path:
    del inputs
    target = session.resolve(
        stage_root / "inputs/bundle_root/bundles/hermetic-bundle"
    )
    target.mkdir(parents=True, exist_ok=False)
    return target


@pytest.fixture
def hermetic(monkeypatch: pytest.MonkeyPatch, inputs: subject.ValidatedInputs):
    _install_hermetic(monkeypatch, inputs)
    return inputs


def _install_hermetic(
    monkeypatch: pytest.MonkeyPatch,
    inputs: subject.ValidatedInputs,
) -> None:
    monkeypatch.setattr(subject, "_validate_inputs", lambda *args, **kwargs: inputs)
    monkeypatch.setattr(
        subject,
        "resolve_manifest_payload",
        lambda *args, **kwargs: inputs.data_root,
    )
    monkeypatch.setattr(subject, "_stage_selected_bundle", _fake_stage_bundle)
    monkeypatch.setattr(
        subject,
        "_load_real_l2_attestation_receipt",
        lambda **kwargs: inputs.real_l2_receipt,
    )
    monkeypatch.setattr(
        subject,
        "build_btc_perpetual_paper_runtime_replay_report",
        _fake_paper_builder,
    )
    monkeypatch.setattr(
        subject,
        "build_btc_strategy_promotion_readiness_review",
        _fake_strategy_builder,
    )
    monkeypatch.setattr(
        subject,
        "build_btc_promotion_gate_control",
        _fake_gate_builder,
    )


@pytest.fixture
def quality_hermetic(
    monkeypatch: pytest.MonkeyPatch,
    inputs: subject.ValidatedInputs,
    tmp_path: Path,
) -> subject.ValidatedInputs:
    manifest, quality_root = _quality_case(tmp_path)
    receipt = subject._load_real_l2_attestation_receipt(
        manifest=manifest,
        data_root=quality_root,
    )
    quality_inputs = replace(
        inputs,
        real_l2_manifest=manifest,
        real_l2_manifest_path=REPO_ROOT / QUALITY_L2_MANIFEST,
        real_l2_receipt=receipt,
        real_l2_root=quality_root,
        raw_hashes={
            **inputs.raw_hashes,
            "real_l2_attestation_manifest": "a" * 64,
        },
    )
    _install_hermetic(monkeypatch, quality_inputs)
    return quality_inputs


def _run(
    root: Path,
    *,
    run_id: str = "hermetic-run",
    failure_injector=None,
) -> dict:
    return subject.run_btc_next_stage_current_head_orchestrator(
        repo_root=REPO_ROOT,
        expected_head=_head(),
        run_id=run_id,
        data_manifest=DATA_MANIFEST,
        data_integrated_handoff=DATA_HANDOFF,
        engineering_integrated_handoff=ENGINEERING_HANDOFF,
        real_l2_attestation_manifest=REAL_L2_MANIFEST,
        real_l2_attestation_shared_root=REPO_ROOT,
        environment={ENVIRONMENT_VARIABLE: str(root)},
        failure_injector=failure_injector,
    )


def test_committed_old_blocked_and_07_quality_manifests_validate() -> None:
    blocked = subject._validate_inputs(
        REPO_ROOT,
        expected_head=_head(),
        data_manifest=DATA_MANIFEST,
        data_integrated_handoff=DATA_HANDOFF,
        engineering_integrated_handoff=ENGINEERING_HANDOFF,
        real_l2_attestation_manifest=REAL_L2_MANIFEST,
    )
    quality = subject._validate_inputs(
        REPO_ROOT,
        expected_head=_head(),
        data_manifest=DATA_MANIFEST,
        data_integrated_handoff=DATA_HANDOFF,
        engineering_integrated_handoff=ENGINEERING_HANDOFF,
        real_l2_attestation_manifest=QUALITY_L2_MANIFEST,
    )
    assert blocked.real_l2_manifest["quality_status"] == "blocked"
    assert (
        quality.real_l2_manifest["quality_status"]
        == subject.QUALITY_L2_MANIFEST_STATUS
    )


def test_quality_attestation_normalizes_verified_facts(
    tmp_path: Path,
) -> None:
    manifest, root = _quality_case(tmp_path)
    receipt = subject._load_real_l2_attestation_receipt(
        manifest=manifest,
        data_root=root,
    )
    assert receipt["status"] == "quality_checked"
    assert receipt["sequence"]["real_message_count"] == 57
    assert receipt["sequence"]["two_sided"] is True
    assert receipt["sequence"]["sequence_continuity_verified"] is True
    assert receipt["controlled_recovery"]["verified"] is True
    assert receipt["server_clock"]["offset_verified"] is True
    assert receipt["blockers"] == manifest["blockers"]


def test_quality_attestation_hash_tamper_fails_closed(
    tmp_path: Path,
) -> None:
    manifest, root = _quality_case(tmp_path)
    path = root / subject.QUALITY_L2_ATTESTATION_PATH
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(
        subject.BTCNextStageOrchestratorError,
        match="btc_next_stage_orchestrator_real_l2_evidence_hash_mismatch",
    ):
        subject._load_real_l2_attestation_receipt(
            manifest=manifest,
            data_root=root,
        )


@pytest.mark.parametrize(
    "mutate",
    (
        lambda payload: payload.__setitem__("sequence_gap_count", 1),
        lambda payload: payload.__setitem__("max_clock_offset_ms", 2000.1),
        lambda payload: payload["guardrails"].__setitem__(
            "private_endpoint_used", True
        ),
    ),
)
def test_quality_attestation_contract_tamper_fails_closed(
    tmp_path: Path,
    mutate,
) -> None:
    manifest, root = _quality_case(tmp_path, mutate=mutate)
    with pytest.raises(
        subject.BTCNextStageOrchestratorError,
        match="btc_next_stage_orchestrator_real_l2_quality_contract_mismatch",
    ):
        subject._load_real_l2_attestation_receipt(
            manifest=manifest,
            data_root=root,
        )


def test_quality_manifest_status_tamper_fails_closed(
    tmp_path: Path,
) -> None:
    manifest, _ = _quality_case(tmp_path)
    manifest["quality_status"] = "pass"
    with pytest.raises(
        subject.BTCNextStageOrchestratorError,
        match="btc_next_stage_orchestrator_real_l2_manifest_identity_mismatch",
    ):
        subject._validate_real_l2_manifest_identity(manifest)


def test_quality_chain_removes_only_verified_stale_l2_blockers(
    tmp_path: Path,
    quality_hermetic: subject.ValidatedInputs,
) -> None:
    artifact_root = tmp_path / "quality-chain-root"
    result = _run(artifact_root, run_id="quality-chain")
    required = set(subject.QUALITY_L2_REQUIRED_BLOCKERS[:8])
    stale = set(subject.QUALITY_L2_RESOLVED_BLOCKERS)
    for artifact_id in (
        "strategy",
        "oms",
        "ledger",
        "replay",
        "engineering",
        "promotion",
        "gate",
        "orchestrator",
    ):
        payload = json.loads(
            (
                artifact_root
                / Path(*subject.LATEST_PATHS[artifact_id].parts[1:])
            ).read_text(encoding="utf-8")
        )
        assert required.issubset(payload["blockers"]), artifact_id
        assert stale.isdisjoint(payload["blockers"]), artifact_id
        if artifact_id != "engineering":
            assert payload["required_blockers"] == list(
                subject.QUALITY_L2_REQUIRED_BLOCKERS
            ), artifact_id
            assert stale.isdisjoint(
                payload["required_blockers"]
            ), artifact_id
    domain = json.loads(
        (
            artifact_root
            / Path(*subject.LATEST_PATHS["domain"].parts[1:])
        ).read_text(encoding="utf-8")
    )
    domain_codes = {row["code"] for row in domain["blockers"]}
    assert required.issubset(domain_codes)
    assert stale.isdisjoint(domain_codes)
    assert domain["required_blockers"] == list(
        subject.QUALITY_L2_REQUIRED_BLOCKERS
    )
    assert (
        result["real_l2_attestation"]["receipt_sha256"]
        == quality_hermetic.real_l2_manifest["files"][0]["sha256"]
    )


def test_fresh_root_publishes_exact_current_head_blocked_chain(
    tmp_path: Path,
    hermetic: subject.ValidatedInputs,
) -> None:
    artifact_root = tmp_path / "blank-root"
    result = _run(artifact_root)

    assert result["completed_steps"] == list(subject.STEP_ORDER)
    assert result["source_head"] == result["code_commit"] == _head()
    assert result["status"] == "complete_blocked"
    assert result["decision"] == "blocked_fail_closed_no_paper_no_live"
    assert result["required_blockers"] == list(subject.REQUIRED_BLOCKERS)
    assert result["required_blocker_count"] == len(subject.REQUIRED_BLOCKERS)
    assert result["required_blockers_sha256"] == subject.REQUIRED_BLOCKERS_SHA256
    assert result["required_blockers_missing"] == []
    assert result["required_blockers_preserved"] is True
    assert (
        "btc_okx_native:25_hour_demo_observation_window_incomplete"
        in result["required_blockers"]
    )
    assert (
        "owner:btc_observation "
        "btc_next_stage:natural_observation_window_30_60d_incomplete"
        not in result["required_blockers"]
    )
    assert all(value is False for value in result["safety"].values())

    for artifact_id, logical_path in subject.LATEST_PATHS.items():
        payload = json.loads(
            (artifact_root / Path(*logical_path.parts[1:])).read_text(encoding="utf-8")
        )
        assert payload["source_head"] == _head(), artifact_id
        assert payload["code_commit"] == _head(), artifact_id
        assert payload["required_blockers"] == list(subject.REQUIRED_BLOCKERS), artifact_id
        assert payload["required_blocker_count"] == len(
            subject.REQUIRED_BLOCKERS
        ), artifact_id
        assert payload["required_blockers_missing"] == [], artifact_id
        assert payload["required_blockers_preserved"] is True, artifact_id
        if artifact_id == "domain":
            assert all(isinstance(item, dict) for item in payload["blockers"])
            assert not any(
                item in payload["blockers"]
                for item in subject.REQUIRED_BLOCKERS
            )
        else:
            assert set(subject.REQUIRED_BLOCKERS).issubset(payload["blockers"]), artifact_id
        assert all(value is False for value in payload["safety"].values()), artifact_id
        assert payload["safety"] == subject.SAFETY, artifact_id

    domain_path = artifact_root / Path(*subject.LATEST_PATHS["domain"].parts[1:])
    domain = json.loads(domain_path.read_text(encoding="utf-8"))
    assert domain["blockers"]
    assert all(
        set(row) == {
            "code",
            "category",
            "owner",
            "next_executable_action",
        }
        for row in domain["blockers"]
    )

    engineering_path = artifact_root / Path(
        *subject.LATEST_PATHS["engineering"].parts[1:]
    )
    engineering = json.loads(engineering_path.read_text(encoding="utf-8"))
    assert engineering["public_ws_dependency"]["valid"] is True
    assert engineering["public_ws_dependency"]["import_safe"] is True
    assert (
        "btc_okx_websocket_client_dependency_missing"
        not in engineering["blockers"]
    )
    assert engineering["builder_chain_phase"] == "finalized_after_gate"
    assert engineering["builder_chain_declaration_sha256"] == subject.stable_payload_hash(
        subject._builder_chain_declaration(engineering["builder_chain"])
    )
    for row in engineering["builder_chain"]:
        target = artifact_root / Path(*Path(row["target_path"]).parts[1:])
        assert row["target_status"] == "built_staged"
        assert row["output_hash_verified"] is True
        assert row["immutable_output"] is True
        assert row["output_sha256"] == _digest(target)
    promotion_path = artifact_root / Path(
        *subject.LATEST_PATHS["promotion"].parts[1:]
    )
    promotion = json.loads(promotion_path.read_text(encoding="utf-8"))
    assert (
        promotion["input_hashes"]["engineering_evidence"]
        == engineering["pre_gate_engineering_evidence_sha256"]
    )

    ledger_path = artifact_root / Path(*subject.LATEST_PATHS["ledger"].parts[1:])
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger["pnl_derived_from_fills_positions_cash"] is False
    assert "btc_next_stage:ledger_positions_cash_pnl_receipts_missing" in ledger["blockers"]

    pointer_path = artifact_root / Path(*DEFAULT_POINTER_PATH.parts[1:])
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    assert "blockers" not in pointer
    assert pointer["code_commit"] == _head()
    manifest_path = artifact_root / Path(*Path(pointer["manifest_path"]).parts[1:])
    assert _digest(manifest_path) == pointer["manifest_sha256"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["step_order"] == list(subject.STEP_ORDER)
    assert manifest["artifact_count"] == len(subject.LATEST_PATHS)
    assert result["reload_verification"]["status"] == "valid"


@pytest.mark.parametrize("failed_step", subject.STEP_ORDER)
def test_every_step_failure_leaves_formal_pointer_unchanged(
    tmp_path: Path,
    hermetic: subject.ValidatedInputs,
    failed_step: str,
) -> None:
    artifact_root = tmp_path / f"failure-{subject.STEP_ORDER.index(failed_step)}"

    def fail(step: str) -> None:
        if step == failed_step:
            raise RuntimeError("injected")

    with pytest.raises((RuntimeError, subject.BTCNextStageOrchestratorError)):
        _run(artifact_root, run_id=f"failure-{subject.STEP_ORDER.index(failed_step)}", failure_injector=fail)

    pointer = artifact_root / Path(*DEFAULT_POINTER_PATH.parts[1:])
    assert not pointer.exists()


def test_nonblank_root_is_rejected_without_old_root_read(
    tmp_path: Path,
    hermetic: subject.ValidatedInputs,
) -> None:
    artifact_root = tmp_path / "old-root"
    artifact_root.mkdir()
    sentinel = artifact_root / "must-not-be-read.json"
    sentinel.write_text("not json and not evidence", encoding="utf-8")

    with pytest.raises(
        subject.BTCNextStageOrchestratorError,
        match="btc_runtime_artifact_bootstrap_root_not_empty",
    ):
        _run(artifact_root, run_id="old-root-rejected")
    assert sentinel.read_text(encoding="utf-8") == "not json and not evidence"


def test_writer_lock_fails_closed(
    tmp_path: Path,
    hermetic: subject.ValidatedInputs,
) -> None:
    artifact_root = tmp_path / "locked-root"
    with pytest.raises(subject.BTCNextStageOrchestratorError):
        def reenter(step: str) -> None:
            if step == "validate_head_and_source":
                return

        # Bootstrap through a failure after the root is created, then use the
        # resulting writer only after provisioning a separate clean root.
        del reenter
        _run(artifact_root, run_id="lock-prime")
        writer = BTCRuntimeArtifactWriter.from_environment(
            source_repo_root=REPO_ROOT,
            environment={ENVIRONMENT_VARIABLE: str(artifact_root)},
        )
        with writer.exclusive():
            subject._run_with_writer(
                repo_root=REPO_ROOT,
                expected_head=_head(),
                run_id="lock-collision",
                generated_at_utc=datetime.now(timezone.utc),
                inputs=hermetic,
                writer=writer,
            )


def test_head_drift_blocks_before_latest_or_pointer(
    tmp_path: Path,
    hermetic: subject.ValidatedInputs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = subject.capture_gate_build_state
    calls = 0

    def drift(*args, **kwargs):
        nonlocal calls
        calls += 1
        state = original(*args, **kwargs)
        if calls == 2:
            return replace(state, watched_input_hash="f" * 64, input_snapshot_hash="f" * 64)
        return state

    monkeypatch.setattr(subject, "capture_gate_build_state", drift)
    artifact_root = tmp_path / "drift-root"
    with pytest.raises(
        subject.BTCNextStageOrchestratorError,
        match="btc_next_stage_orchestrator_head_or_source_drift",
    ):
        _run(artifact_root, run_id="drift")
    assert not (artifact_root / Path(*DEFAULT_POINTER_PATH.parts[1:])).exists()
    assert all(
        not (artifact_root / Path(*path.parts[1:])).exists()
        for path in subject.LATEST_PATHS.values()
    )


def test_path_escape_and_invalid_run_id_fail_closed(tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(
        subject.BTCNextStageOrchestratorError,
        match="btc_next_stage_orchestrator_input_path_escape",
    ):
        subject._load_repo_json(
            REPO_ROOT,
            outside,
            required_prefix=".agent/handoffs/",
        )
    with pytest.raises(
        subject.BTCNextStageOrchestratorError,
        match="btc_next_stage_orchestrator_run_id_invalid",
    ):
        subject._validate_head_and_run(
            REPO_ROOT,
            expected_head=_head(),
            run_id="../escape",
        )


def test_schemas_and_cli_contract_are_exact() -> None:
    for name in (
        "btc_next_stage_engineering_evidence.schema.json",
        "btc_next_stage_current_head_orchestrator.schema.json",
    ):
        jsonschema.Draft202012Validator.check_schema(
            json.loads((REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"))
        )
    parser = cli.build_parser()
    option_strings = {
        option
        for action in parser._actions
        for option in action.option_strings
        if option.startswith("--") and option != "--help"
    }
    assert option_strings == {
        "--repo-root",
        "--expected-head",
        "--run-id",
        "--data-manifest",
        "--data-integrated-handoff",
        "--engineering-integrated-handoff",
        "--real-l2-attestation-manifest",
        "--real-l2-attestation-shared-root",
    }


def test_declared_builder_chain_never_claims_future_outputs(
    tmp_path: Path,
) -> None:
    domain_path = tmp_path / "domain.json"
    domain_path.write_text("{}\n", encoding="utf-8")
    rows = subject._declared_builder_chain(
        repo_root=REPO_ROOT,
        staged={"domain": domain_path},
        expected_head=_head(),
    )
    assert rows[0]["target_status"] == "built_staged"
    assert rows[0]["output_sha256"] == _digest(domain_path)
    for row in rows[1:]:
        assert row["target_status"] == "declared_not_built"
        assert row["output_sha256"] == ""
        assert row["output_hash_verified"] is False
        assert row["immutable_output"] is False
        assert row["builder_code_sha256"] == subject._git_blob_sha256(
            REPO_ROOT,
            _head(),
            row["builder_code_path"],
        )


def test_domain_blockers_remain_structured_objects(
    tmp_path: Path,
    hermetic: subject.ValidatedInputs,
) -> None:
    artifact_root = tmp_path / "domain-contract-root"
    _run(artifact_root, run_id="domain-contract")
    domain_path = artifact_root / Path(*subject.LATEST_PATHS["domain"].parts[1:])
    payload = json.loads(domain_path.read_text(encoding="utf-8"))
    assert payload["required_blockers"] == list(subject.REQUIRED_BLOCKERS)
    assert payload["required_blockers_missing"] == []
    assert payload["required_blockers_preserved"] is True
    assert payload["blocker_count"] == len(payload["blockers"])
    assert payload["blockers"]
    assert all(isinstance(row, dict) for row in payload["blockers"])
    assert all(
        set(row) == {
            "code",
            "category",
            "owner",
            "next_executable_action",
        }
        for row in payload["blockers"]
    )


def test_safety_schemas_reject_every_missing_or_true_flag(
    tmp_path: Path,
    hermetic: subject.ValidatedInputs,
) -> None:
    artifact_root = tmp_path / "negative-safety-root"
    _run(artifact_root, run_id="negative-safety")
    cases = (
        (
            "orchestrator",
            "btc_next_stage_current_head_orchestrator.schema.json",
        ),
        (
            "engineering",
            "btc_next_stage_engineering_evidence.schema.json",
        ),
    )
    for artifact_id, schema_name in cases:
        payload = json.loads(
            (
                artifact_root
                / Path(*subject.LATEST_PATHS[artifact_id].parts[1:])
            ).read_text(encoding="utf-8")
        )
        schema = json.loads(
            (REPO_ROOT / "schemas" / schema_name).read_text(encoding="utf-8")
        )
        assert payload["safety"] == subject.SAFETY
        for key in subject.SAFETY:
            missing = copy.deepcopy(payload)
            del missing["safety"][key]
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(missing, schema)
            unsafe = copy.deepcopy(payload)
            unsafe["safety"][key] = True
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(unsafe, schema)


def test_legacy_short_commit_must_prefix_full_head() -> None:
    subject._validate_legacy_head({"code_commit": _head()[:12]}, _head())
    with pytest.raises(
        subject.BTCNextStageOrchestratorError,
        match="btc_next_stage_orchestrator_legacy_code_commit_mismatch",
    ):
        subject._validate_legacy_head({"code_commit": "0" * 12}, _head())
