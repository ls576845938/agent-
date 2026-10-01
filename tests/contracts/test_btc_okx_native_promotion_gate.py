from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from quant_crypto.research.btc_okx_native_promotion_gate import (
    ACTIVE_FAMILY_SCOPE_BLOCKER,
    ACTIVE_CRITERIA_LINEAGE_BLOCKER,
    DEPTH_FILL_MAPPING_BLOCKER,
    FROZEN_PREREG_BLOB_SHA256,
    INFORMATION_COVERAGE_BLOCKER,
    OBSERVATION_WINDOW_BLOCKER,
    OPEN_INTEREST_FAMILY_BLOCKER,
    UNCHANGED_EXTERNAL_BLOCKERS,
    evaluate_active_criteria_contract,
    evaluate_btc_okx_native_promotion_blockers,
    load_frozen_active_criteria_prereg,
)
from tests.contracts.test_btc_10s_microstructure_data_contract_report import (
    _prereg,
    _ready_metrics,
)


NOW = datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc)
HEAD = "a" * 40
HASH = "b" * 64


@pytest.mark.parametrize(
    "case",
    ("missing_ref", "ref_missing_file", "changed_content"),
)
def test_frozen_prereg_loader_never_falls_back_across_repo_or_ref(
    tmp_path: Path,
    case: str,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "contract-test"],
        check=True,
    )
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    if case == "changed_content":
        prereg_path = (
            repo
            / "docs"
            / "research"
            / "BTC_10S_MICROSTRUCTURE_DATA_CONTRACT_01_PREREG.json"
        )
        prereg_path.parent.mkdir(parents=True)
        prereg_path.write_text('{"thresholds":"lowered"}\n', encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "fixture"],
        check=True,
    )

    current_head = "refs/heads/does-not-exist" if case == "missing_ref" else "HEAD"
    payload, blob_sha = load_frozen_active_criteria_prereg(
        repo,
        current_head=current_head,
    )

    assert payload == {}
    assert blob_sha == ""


def test_missing_fixture_stale_and_wrong_head_evidence_keep_depth_blocker() -> None:
    cases = [
        ({}, {}),
        (_l2(evidence_class="fixture_or_diagnostic_only", promotion_evidence_ready=False), _mapping()),
        (_l2(generated_at_utc=(NOW - timedelta(days=2)).isoformat()), _mapping()),
        (_l2(source_head="c" * 40), _mapping()),
    ]

    for l2_report, mapping_report in cases:
        result = evaluate_btc_okx_native_promotion_blockers(
            l2_batch_report=l2_report,
            fill_mapping_report=mapping_report,
            current_head=HEAD,
            now_utc=NOW,
        )
        assert DEPTH_FILL_MAPPING_BLOCKER in result["promotion_blockers"]
        assert result["depth_fill_mapping_blocker_retired"] is False
        assert list(UNCHANGED_EXTERNAL_BLOCKERS) == result["unchanged_external_blockers"]


def test_incomplete_or_cross_report_mismatch_keeps_depth_blocker() -> None:
    mapping = _mapping(run_id="different-run")
    mapping["depth_integrity"]["valid_for_mapping"] = False

    result = evaluate_btc_okx_native_promotion_blockers(
        l2_batch_report=_l2(),
        fill_mapping_report=mapping,
        current_head=HEAD,
        now_utc=NOW,
    )

    assert DEPTH_FILL_MAPPING_BLOCKER in result["promotion_blockers"]
    assert "cross_report:run_id_mismatch" in result["validation_errors"]
    assert "fill_mapping:depth_integrity_incomplete" in result["validation_errors"]


def test_valid_current_head_evidence_retires_only_depth_blocker() -> None:
    result = evaluate_btc_okx_native_promotion_blockers(
        l2_batch_report=_l2(),
        fill_mapping_report=_mapping(),
        current_head=HEAD,
        now_utc=NOW,
    )

    assert result["depth_fill_mapping_blocker_retired"] is True
    assert DEPTH_FILL_MAPPING_BLOCKER not in result["promotion_blockers"]
    assert result["promotion_blockers"] == list(UNCHANGED_EXTERNAL_BLOCKERS)
    assert result["quality_checked"] is True
    assert result["promotion_evidence_ready"] is False
    assert result["paper_allowed"] is False
    assert result["live_allowed"] is False


def test_active_criteria_uses_preregistered_ess_and_regime_coverage_not_days() -> None:
    result = _evaluate_active(_active_criteria("trade_imbalance_continuation"))

    assert result["active_family_scope_valid"] is True
    assert result["information_coverage_evidence_valid"] is True
    assert result["open_interest_required"] is False
    assert result["promotion_blockers"] == []
    serialized = str(result).lower()
    assert "natural_day" not in serialized
    assert "30_day" not in serialized


def test_open_interest_is_scoped_only_to_declared_dependent_family() -> None:
    non_oi = _evaluate_active(_active_criteria("micro_breakout"))
    liquidation = _evaluate_active(
        _active_criteria("liquidation_cascade_recovery")
    )

    assert OPEN_INTEREST_FAMILY_BLOCKER not in non_oi["promotion_blockers"]
    assert OPEN_INTEREST_FAMILY_BLOCKER in liquidation["promotion_blockers"]


def test_unknown_family_or_unfrozen_thresholds_fail_closed() -> None:
    unknown = _evaluate_active(_active_criteria("unregistered_family"))
    unfrozen = _active_criteria("trade_imbalance_continuation")
    unfrozen["prereg_semantic_sha256"] = "0" * 64
    invalid = _evaluate_active(unfrozen)

    assert ACTIVE_FAMILY_SCOPE_BLOCKER in unknown["promotion_blockers"]
    assert INFORMATION_COVERAGE_BLOCKER in invalid["promotion_blockers"]


def test_recomputed_hash_cannot_replace_frozen_prereg_or_pointer_identity() -> None:
    tampered = _active_criteria("trade_imbalance_continuation")
    tampered["preregistration"]["information_thresholds"][
        "autocorrelation_adjusted_ess_by_horizon"
    ]["10s"] = 1
    tampered["prereg_semantic_sha256"] = hashlib.sha256(
        json.dumps(
            tampered["preregistration"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    result = _evaluate_active(tampered)

    assert INFORMATION_COVERAGE_BLOCKER in result["promotion_blockers"]

    wrong_lineage = _active_criteria("trade_imbalance_continuation")
    wrong_lineage["data_version"] = "another-version"
    result = _evaluate_active(wrong_lineage)
    assert ACTIVE_CRITERIA_LINEAGE_BLOCKER in result["promotion_blockers"]


def test_authorized_25h_demo_window_retires_only_observation_blocker() -> None:
    result = evaluate_btc_okx_native_promotion_blockers(
        l2_batch_report={},
        fill_mapping_report={},
        observation_window_report=_observation(),
        current_head=HEAD,
        now_utc=NOW,
    )

    assert result["observation_window_blocker_retired"] is True
    assert OBSERVATION_WINDOW_BLOCKER not in result["promotion_blockers"]
    assert DEPTH_FILL_MAPPING_BLOCKER in result["promotion_blockers"]
    assert {
        "btc_okx_native:natural_strategy_runtime_non_flat_fill_sample_missing",
        "btc_okx_native:funding_cashflow_not_observed_in_demo_runtime",
        "btc_okx_native:private_ws_runtime_reconciliation_observation_incomplete",
        "btc_okx_native:manual_promotion_approval_missing",
    }.issubset(result["promotion_blockers"])
    assert result["promotion_evidence_ready"] is False
    assert result["paper_allowed"] is False
    assert result["live_allowed"] is False


def test_fixture_or_cross_version_unsafe_window_never_retires_blocker() -> None:
    fixture = _observation(evidence_class="fixture_or_diagnostic_only")
    unsafe = _observation()
    unsafe["version_policy"]["cross_runtime_version_accumulation_allowed"] = True

    for report in (fixture, unsafe):
        result = evaluate_btc_okx_native_promotion_blockers(
            l2_batch_report=_l2(),
            fill_mapping_report=_mapping(),
            observation_window_report=report,
            current_head=HEAD,
            now_utc=NOW,
        )
        assert result["observation_window_blocker_retired"] is False
        assert OBSERVATION_WINDOW_BLOCKER in result["promotion_blockers"]


def _common(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "generated_at_utc": NOW.isoformat(),
        "source_head": HEAD,
        "data_version": "btc-okx-l2-immutable-v1",
        "run_id": "btc-l2-depth-fill-run-1",
        "params_hash": HASH,
        "output_hash": HASH,
        "input_hashes": {"immutable://btc/l2/v1": HASH},
        "evidence_class": "promotion_evidence",
        "promotion_evidence_ready": True,
    }
    payload.update(overrides)
    return payload


def _l2(**overrides: object) -> dict[str, object]:
    payload = _common(
        schema_version="btc_okx_l2_depth_observation_batch_v2",
        depth_gate_progress_after={"gate_ready": True},
    )
    payload.update(overrides)
    return payload


def _mapping(**overrides: object) -> dict[str, object]:
    payload = _common(
        schema_version="btc_depth_slippage_fill_mapping_report_v2",
        strategy_fill_mapping_verified=True,
        depth_integrity={"valid_for_mapping": True},
    )
    payload.update(overrides)
    return payload


def _observation(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "btc_demo_observation_accumulator_v3",
        "source_head": HEAD,
        "generated_at_utc": NOW.isoformat(),
        "authority": "authorized_okx_demo_accumulator",
        "evidence_class": "authorized_okx_demo_observation_window",
        "required_observation_hours": 25,
        "observation_hours": 25,
        "window_25h_complete": True,
        "strategy_version": "btc-trend@1",
        "data_version": "btc-data-v1",
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
    }
    payload.update(overrides)
    return payload


def _active_criteria(family: str) -> dict[str, object]:
    prereg = _prereg()
    semantic = hashlib.sha256(
        json.dumps(
            prereg,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": "btc_promotion_gate_active_criteria_v1",
        "source_head": HEAD,
        "generated_at_utc": NOW.isoformat(),
        "active_strategy_family": family,
        "active_horizon": "10s",
        "run_id": "btc-l2-depth-fill-run-1",
        "data_version": "btc-okx-l2-immutable-v1",
        "immutable_manifest_sha256": HASH,
        "immutable_evidence_sha256": HASH,
        "data_steward_attestation": {
            "kind": "data_steward_attestation",
            "uri": "immutable://btc/okx/attestation/v1",
            "path": "artifacts/btc/attestation/v1.json",
            "sha256": HASH,
            "producer_role": "data_steward",
        },
        "prereg_semantic_sha256": semantic,
        "prereg_blob_sha256": FROZEN_PREREG_BLOB_SHA256,
        "preregistration": prereg,
        "measured_metrics": _ready_metrics(),
    }


def _evaluate_active(report: dict[str, object]) -> dict[str, object]:
    return evaluate_active_criteria_contract(
        report=report,
        current_head=HEAD,
        expected_preregistration=_prereg(),
        expected_prereg_blob_sha256=FROZEN_PREREG_BLOB_SHA256,
        pointer_validation={
            "status": "valid_current_head",
            "run_id": "btc-l2-depth-fill-run-1",
            "data_version": "btc-okx-l2-immutable-v1",
            "manifest": {"actual_sha256": HASH},
            "evidence": {"actual_sha256": HASH},
            "input_lineage": [
                {
                    "kind": "data_steward_attestation",
                    "uri": "immutable://btc/okx/attestation/v1",
                    "path": "artifacts/btc/attestation/v1.json",
                    "sha256": HASH,
                    "producer_role": "data_steward",
                }
            ],
            "verified_data_steward_attestation": {
                "kind": "data_steward_attestation",
                "uri": "immutable://btc/okx/attestation/v1",
                "path": "artifacts/btc/attestation/v1.json",
                "sha256": HASH,
                "producer_role": "data_steward",
                "verified": True,
            },
        },
    )
