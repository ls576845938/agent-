"""Frozen Qlib inference must reproduce sealed research without training or execution."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import socket

import numpy as np
import pandas as pd
import pytest

from integrations.qlib_adapter.frozen_inference import (
    FrozenInferenceError,
    _load_feature_frame,
    run_frozen_inference,
)
from tools.agent_governance.shared_data import (
    default_shared_data_root,
    load_manifest_from_git,
    resolve_manifest_payload,
)


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "tests/fixtures/strategy_v2/contract.json"


def _forbidden(*args, **kwargs):
    raise AssertionError("V2 forbids network, credentials, training and transport")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)


@pytest.fixture(scope="module")
def contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def archive_root(contract):
    manifest = load_manifest_from_git(ROOT, contract["archive_manifest_git_spec"])
    return resolve_manifest_payload(
        manifest,
        shared_root=default_shared_data_root(ROOT),
        verify_files=True,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_failure_first_entry_exists_and_contract_is_fail_closed(contract):
    assert contract["usage"] == "research_only"
    assert contract["output_kind"] == "frozen_inference"
    assert contract["comparison"] == {
        "prediction_atol": 1e-10,
        "prediction_rtol": 1e-8,
        "feature_atol": 0.0,
        "feature_rtol": 0.0,
        "tolerance_policy": "frozen_no_auto_widen",
    }
    assert all(value is False for value in contract["permissions"].values())


def test_symbolic_archive_manifest_git_ref_rejects(contract):
    changed = copy.deepcopy(contract)
    _, path = changed["archive_manifest_git_spec"].split(":", maxsplit=1)
    changed["archive_manifest_git_spec"] = f"HEAD:{path}"
    with pytest.raises(FrozenInferenceError, match="archive_manifest_git_spec_invalid"):
        run_frozen_inference(changed, repo_root=ROOT)


def test_calibration_clip_drift_rejects_even_when_predictions_do_not_hit_clip(contract):
    changed = copy.deepcopy(contract)
    changed["calibration"]["clip_fraction"] = 0.5
    with pytest.raises(FrozenInferenceError, match="calibration_clip_fraction_mismatch"):
        run_frozen_inference(changed, repo_root=ROOT)


@pytest.mark.parametrize("value", [True, None, "0.05", 0.0, -0.1, float("nan"), float("inf")])
def test_invalid_calibration_clip_rejects(contract, value):
    changed = copy.deepcopy(contract)
    changed["calibration"]["clip_fraction"] = value
    with pytest.raises(FrozenInferenceError, match="calibration_clip_fraction_invalid"):
        run_frozen_inference(changed, repo_root=ROOT)


def test_symbolic_calibration_evidence_git_ref_rejects(contract):
    changed = copy.deepcopy(contract)
    _, path = changed["calibration_evidence"]["git_spec"].split(":", maxsplit=1)
    changed["calibration_evidence"]["git_spec"] = f"main:{path}"
    with pytest.raises(FrozenInferenceError, match="calibration_evidence_git_spec_invalid"):
        run_frozen_inference(changed, repo_root=ROOT)


@pytest.mark.parametrize(
    ("path", "value", "reason"),
    [
        (("candidate_id",), "other", "candidate_id_mismatch"),
        (("source_code_version",), "0" * 40, "source_code_version_mismatch"),
        (("domain",), "equity", "domain_mismatch"),
        (("venue_instrument",), "BTCUSDT", "venue_instrument_mismatch"),
        (("source_instrument",), "BTC-USDT-SWAP", "source_instrument_mismatch"),
        (("bar_size",), "1d", "bar_size_mismatch"),
        (("time_semantics", "decision_time"), "event_time_plus_2h", "time_semantics_mismatch"),
    ],
)
def test_wrong_identity_version_domain_instrument_or_time_rejects(contract, path, value, reason):
    changed = copy.deepcopy(contract)
    target = changed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(FrozenInferenceError, match=reason):
        run_frozen_inference(changed, repo_root=ROOT)


@pytest.mark.parametrize("mutation", ["swap", "missing"])
def test_wrong_or_missing_ordered_feature_rejects(contract, mutation):
    changed = copy.deepcopy(contract)
    if mutation == "swap":
        changed["features_in_order"][0], changed["features_in_order"][1] = (
            changed["features_in_order"][1], changed["features_in_order"][0]
        )
    else:
        changed["feature_expressions"].pop()
        changed["features_in_order"].pop()
    with pytest.raises(FrozenInferenceError, match="feature_(names|count)_mismatch"):
        run_frozen_inference(changed, repo_root=ROOT)


def test_corrupted_sealed_package_rejects(contract, archive_root, tmp_path, monkeypatch):
    import integrations.qlib_adapter.frozen_inference as module

    copied_archive = tmp_path / "archive"
    copied_run = copied_archive / "qlib_runs" / contract["run_id"]
    shutil.copytree(archive_root / "qlib_runs" / contract["run_id"], copied_run)
    (copied_run / "model.txt").write_text("corrupt", encoding="utf-8")
    monkeypatch.setattr(module, "resolve_manifest_payload", lambda *args, **kwargs: copied_archive)
    with pytest.raises(FrozenInferenceError, match="sealed_evidence_blocked"):
        run_frozen_inference(contract, repo_root=ROOT)


def test_full_sealed_feature_raw_and_calibrated_prediction_parity(contract, archive_root):
    run_root = archive_root / "qlib_runs" / contract["run_id"]
    before = {name: _sha256(run_root / name) for name in contract["artifact_sha256"]}
    result = run_frozen_inference(contract, repo_root=ROOT)
    after = {name: _sha256(run_root / name) for name in contract["artifact_sha256"]}

    assert before == after == contract["artifact_sha256"]
    assert len(result.rows) == contract["decision_count"] == 1392
    assert result.output_kind == "frozen_inference"
    assert result.usage == "research_only"
    assert result.reference_parity == {
        "features": "passed_same_sealed_provider_config_and_order",
        "raw_score": "passed",
        "calibrated_prediction": "passed",
    }
    np.testing.assert_allclose(
        result.rows["raw_score"], result.rows["reference_raw_score"],
        atol=1e-10, rtol=1e-8,
    )
    np.testing.assert_allclose(
        result.rows["calibrated_prediction"], result.rows["reference_calibrated_prediction"],
        atol=1e-10, rtol=1e-8,
    )
    assert result.rows[contract["features_in_order"]].dtypes.eq(np.dtype("float32")).all()
    assert result.rows["event_time"].dt.tz is not None
    assert (result.rows["available_time"] == result.rows["event_time"] + pd.Timedelta(hours=1)).all()
    assert (result.rows["decision_time"] == result.rows["available_time"]).all()
    assert result.policy_bindings["position"]["volatility_target_applied"] is False
    assert set(result.policy_digests) == {"position", "exit", "cost"}
    assert all(len(value) == 64 for value in result.policy_digests.values())
    assert all(value is False for value in result.permissions.values())


def test_batch_and_one_by_one_predictions_match_for_every_row(contract):
    batch = run_frozen_inference(contract, repo_root=ROOT, prediction_mode="batch")
    sequential = run_frozen_inference(contract, repo_root=ROOT, prediction_mode="one_by_one")
    pd.testing.assert_frame_equal(
        batch.rows[["event_time", *contract["features_in_order"]]],
        sequential.rows[["event_time", *contract["features_in_order"]]],
    )
    np.testing.assert_allclose(batch.rows["raw_score"], sequential.rows["raw_score"], atol=1e-10, rtol=1e-8)
    np.testing.assert_allclose(
        batch.rows["calibrated_prediction"], sequential.rows["calibrated_prediction"], atol=1e-10, rtol=1e-8
    )


def test_visible_prefix_matches_full_history_and_future_is_not_visible(contract):
    full = run_frozen_inference(contract, repo_root=ROOT)
    decision_cutoff = pd.Timestamp("2026-07-01T01:00:00Z")
    prefix = run_frozen_inference(contract, repo_root=ROOT, visible_through=decision_cutoff)
    expected = full.rows.loc[full.rows["decision_time"] <= decision_cutoff].reset_index(drop=True)
    pd.testing.assert_frame_equal(prefix.rows, expected)
    assert prefix.rows.iloc[-1]["event_time"] == pd.Timestamp("2026-07-01T00:00:00Z")


def test_prediction_mutation_is_detected_by_sealed_reference(contract, monkeypatch):
    import integrations.qlib_adapter.frozen_inference as module

    original = module._predict

    def changed_prediction(model, values, *, mode):
        return original(model, values, mode=mode) + 1e-4

    monkeypatch.setattr(module, "_predict", changed_prediction)
    with pytest.raises(FrozenInferenceError, match="raw_score_parity_failed"):
        run_frozen_inference(contract, repo_root=ROOT)


def test_physical_future_perturbation_cannot_change_past_features_or_scores(contract, archive_root, tmp_path):
    original = archive_root / "qlib_runs" / contract["run_id"] / "qlib_provider"
    changed = tmp_path / "changed-provider"
    shutil.copytree(original, changed)
    cutoff = pd.Timestamp("2026-07-01 00:00:00")
    calendar = pd.DatetimeIndex(
        pd.to_datetime((changed / "calendars/60min.txt").read_text(encoding="utf-8").splitlines())
    )
    future_start = int(np.searchsorted(calendar.to_numpy(), cutoff.to_datetime64(), side="right"))
    for path in (changed / "features/btc-usdt-swap").glob("*.60min.bin"):
        values = np.fromfile(path, dtype="<f4")
        values[future_start + 1 :] = values[future_start + 1 :] * np.float32(9.0) + np.float32(12345.0)
        values.tofile(path)

    feature_spec = [contract["feature_expressions"], contract["features_in_order"]]
    baseline = _load_feature_frame(
        original, feature_spec=feature_spec, instrument=contract["qlib_instrument"],
        start_time=contract["handler_range"][0], end_time=cutoff,
    )
    perturbed = _load_feature_frame(
        changed, feature_spec=feature_spec, instrument=contract["qlib_instrument"],
        start_time=contract["handler_range"][0], end_time=cutoff,
    )
    pd.testing.assert_frame_equal(baseline, perturbed)


def test_nonfinite_feature_rejects_after_fillna(contract, archive_root, tmp_path):
    provider = tmp_path / "bad-provider"
    shutil.copytree(archive_root / "qlib_runs" / contract["run_id"] / "qlib_provider", provider)
    close_path = provider / "features/btc-usdt-swap/close.60min.bin"
    values = np.fromfile(close_path, dtype="<f4")
    values[-100] = np.float32(np.inf)
    values.tofile(close_path)
    with pytest.raises(FrozenInferenceError, match="nonfinite_feature"):
        _load_feature_frame(
            provider,
            feature_spec=[contract["feature_expressions"], contract["features_in_order"]],
            instrument=contract["qlib_instrument"],
            start_time=contract["handler_range"][0],
            end_time=contract["handler_range"][1],
        )


def test_v2_never_returns_execution_objects(contract):
    result = run_frozen_inference(contract, repo_root=ROOT, visible_through="2026-06-01T03:00:00Z")
    forbidden = {"target_position", "order_intent", "risk_decision", "fill", "ledger"}
    assert forbidden.isdisjoint(result.rows.columns)
    assert result.execution_binding_status == "not_bound_research_only"
    assert result.permissions["execution_permission"] is False
