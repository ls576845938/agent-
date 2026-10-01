"""The paused natural-history receipt is explicit, sealed and never recomputed by GET."""

from __future__ import annotations

import copy
from dataclasses import replace
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess

import pytest
from fastapi.testclient import TestClient

from backend.app.services.donchian_stage_views import (
    MARKET_POLICY_TRIAL_PATH, MARKET_STATE_PATH, SELECTOR, read_stage_snapshot,
    validate_market_policy_trial_blocked_evidence, validate_market_policy_trial_evidence,
    validate_market_state_evidence, validate_stage_snapshot,
)


ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / ".agent/offline_evidence/donchian-stage-20260921.json"
MARKET_STATE = ROOT / MARKET_STATE_PATH
STATE_METRIC_FIELDS = sorted([
    "direction_score", "direction_label", "normalized_trend_strength",
    "path_efficiency_by_horizon.24", "path_efficiency_by_horizon.72",
    "path_efficiency_by_horizon.168", "multi_scale_agreement", "bar_volatility",
    "annualized_volatility", "volatility_relative_position", "volatility_expansion_ratio",
    "volatility_regime", "shock_score", "direction_persistence", "switching_frequency",
])


def policy_trial_report():
    baseline_net = Decimal("-0.243294323038495647991")
    policy_net = Decimal("0.015")
    arms = {
        "original_donchian": {
            "arm_id": "original_donchian", "run_id": "donchian-market-entry-baseline-20260927",
            "source_commit": "f2455bfbcafd15404bb4ff98dd6bb925728d0339", "run_identity_hash": "1" * 64,
            "source_artifact_sha256": "7" * 64, "ledger_receipt_sha256": "8" * 64,
            "writer_finished_at_utc": "2026-09-27T06:00:00+00:00",
            "ledger_reconciled_at_utc": "2026-09-27T06:01:00+00:00",
            "processed_events": 2960, "new_entries_proposed": 30,
            "new_entries_rejected": 0, "new_entries_executed": 30, "roundtrips": 28,
            "exposure_contract_hours": "200", "holding_hours": "180",
            "price_pnl_usdt": "0.0346310615", "fee_cashflow_usdt": "-0.26552203961525",
            "funding_cashflow_usdt": "-0.012403344923245647991", "net_usdt": str(baseline_net),
            "drawdown_status": "computed_from_ledger", "max_drawdown_usdt": "0.6",
            "exit_count": 28, "protective_exit_count": 26, "ledger_reconciled": True,
            "duplicate_order_count": 0, "duplicate_fill_count": 0,
            "final_position_contracts": "0", "blocker_count": 0,
        },
        "original_donchian_plus_frozen_entry_policy": {
            "arm_id": "original_donchian_plus_frozen_entry_policy",
            "run_id": "donchian-market-entry-conditioned-20260927",
            "source_commit": "f2455bfbcafd15404bb4ff98dd6bb925728d0339",
            "run_identity_hash": "2" * 64, "source_artifact_sha256": "9" * 64,
            "ledger_receipt_sha256": "a" * 64,
            "writer_finished_at_utc": "2026-09-27T08:00:00+00:00",
            "ledger_reconciled_at_utc": "2026-09-27T08:01:00+00:00",
            "processed_events": 2960,
            "new_entries_proposed": 30, "new_entries_rejected": 18,
            "new_entries_executed": 12, "roundtrips": 11,
            "exposure_contract_hours": "80", "holding_hours": "70",
            "price_pnl_usdt": "0.120", "fee_cashflow_usdt": "-0.100",
            "funding_cashflow_usdt": "-0.005", "net_usdt": str(policy_net),
            "drawdown_status": "computed_from_ledger", "max_drawdown_usdt": "0.3",
            "exit_count": 11, "protective_exit_count": 9, "ledger_reconciled": True,
            "duplicate_order_count": 0, "duplicate_fill_count": 0,
            "final_position_contracts": "0", "blocker_count": 0,
        },
    }
    effects = []
    for index in range(18):
        cutoff = f"2025-11-{(index % 18) + 1:02d}T01:00:00+00:00"
        content_hash = f"{index + 10:064x}"
        input_hash = f"{index + 100:064x}"
        effects.append({
            "event_id": f"event-{index:02d}", "phase": "market_entry_policy",
            "market_entry_policy": {
                "usage": "research_replay_entry_only", "attachment_hash": "3" * 64,
                "policy_id": "market_state_entry_admission",
                "policy_version": "entry_path_efficiency_72h_v1",
                "policy_hash": "1a5cc01f906a4cf244fa0e8a18b9cd3f30130ccfa1b3fed7e125af5c490fbe2b",
                "state_version": "market_state_descriptive_v2", "state_definition_hash": "c3313cf3de4bf56e8edc918f73ead7e9f5e6ab2b9a43d45a0b64b8eb10ee4624",
                "state_source_binding_hash": "79de6c8c2ece98c17c813fa0003480c975e5cc933c69d511142872ea4fe4b54a",
                "state_content_hash": content_hash,
                "state_input_hash": input_hash, "state_status": "observed",
                "state_reasons": [], "state_cutoff_utc": cutoff,
                "original_target_contracts": "0.01", "effective_target_contracts": "0",
                "applied": True, "reason": "path_efficiency_below_threshold",
                "existing_position_contracts": "0", "state_binding_status": "verified",
            },
            "selected_state": {
                "projection_source": "exact_state_hash_join", "projection_status": "complete",
                "missing_fields": [],
                "asset": "BTC-USDT-SWAP", "decision_time": cutoff, "cutoff_time": cutoff,
                "status": "observed", "reasons": [], "direction_score": 0.42,
                "direction_label": "up", "normalized_trend_strength": 0.37,
                "path_efficiency_by_horizon": {"24": 0.16, "72": 0.18, "168": 0.31},
                "multi_scale_agreement": 0.66, "bar_volatility": 0.011,
                "annualized_volatility": 0.52, "volatility_relative_position": 0.74,
                "volatility_expansion_ratio": 1.08, "volatility_regime": "stable",
                "shock_score": 0.35, "direction_persistence": 0.61,
                "switching_frequency": 0.12,
                "definition_version": "market_state_descriptive_v2",
                "definition_hash": "c3313cf3de4bf56e8edc918f73ead7e9f5e6ab2b9a43d45a0b64b8eb10ee4624",
                "source_binding_hash": "79de6c8c2ece98c17c813fa0003480c975e5cc933c69d511142872ea4fe4b54a",
                "input_hash": input_hash, "content_hash": content_hash,
            },
            "evidence_links": {
                "decision_outcome": "rejected_new_entry", "signal_id": f"signal-{index:02d}",
                "target_position_id": f"target-{index:02d}", "risk_check_id": None,
                "order_intent_id": None, "client_order_id": None, "exchange_order_id": None,
                "fill_ids": [], "ledger_event_id": None, "ledger_event_hash": None,
                "action": "no_order",
            },
        })
    payload = {
        "schema_version": "market_policy_trial_report_v1",
        "trial_id": "donchian-stage-market-policy-trial-20260927-v1",
        "status": "completed_exploratory_research_only",
        "truth_kind": "offline_policy_ab_replay",
        "usage": "policy_effect_estimation_only_not_promotion",
        "protocol": {
            "protocol_id": "donchian-stage-market-state-v2-20260927",
            "commit": "97d8ad21dda3317afae0bfa7f1bf68ff0ce1ed02",
            "sha256": "7eca70e55aa40d1f2db6e4c72b79a326bf73bd54d583a50347d7f34364e8d85e",
        },
        "source": {
            "stage_selector": SELECTOR,
            "stage_source_head": "897d5e99ebe4c898f71ac66cf33fb2d2420855d5",
            "stage_snapshot_sha256": "48aaba75b02a2d257abf5196d9c4490c52f4f14356c17a64a41703fb3d6add14",
            "diagnostic_artifact_sha256": "2a4345a7d9a867cd1888addad00659583ea744911aa0b5b8486ad8c282c9c00b",
            "diagnostic_evidence_hash": "11f279d63b0b43cee0c3229dca90f80a2049de090de27c701b75f20b0fdd2b2c",
            "data_version": "donchian-long-input-20260921-v2",
            "manifest_sha256": "349bd130a769796a71877f48ab7aa597338303ece8b124d4b9e23a3759e3993d",
            "aggregate_sha256": "62bed3a6efa945d8fa4f52917667dc44a276add7ed280bb45085ef52950d10af",
        },
        "consumer_binding": {
            "source_commit": "f2455bfbcafd15404bb4ff98dd6bb925728d0339",
            "attachment_hash": "3" * 64,
            "base_strategy_binding_hash": "6" * 64,
            "policy_hash": "1a5cc01f906a4cf244fa0e8a18b9cd3f30130ccfa1b3fed7e125af5c490fbe2b",
            "state_definition_hash": "c3313cf3de4bf56e8edc918f73ead7e9f5e6ab2b9a43d45a0b64b8eb10ee4624",
            "state_source_binding_hash": "79de6c8c2ece98c17c813fa0003480c975e5cc933c69d511142872ea4fe4b54a",
        },
        "window": {
            "analysis_start_utc": "2025-09-01T00:00:00+00:00",
            "analysis_end_exclusive_utc": "2026-01-02T08:00:00+00:00",
            "expected_events": 2960, "warmup_hours": 4800, "bar_size": "1h",
        },
        "arms": arms,
        "comparison": {
            "new_entries_rejected_delta": 18, "roundtrips_delta": -17,
            "exposure_contract_hours_delta": "-120", "holding_hours_delta": "-110",
            "net_usdt_delta": str(policy_net - baseline_net),
            "max_drawdown_usdt_delta": "-0.3",
            "effect_interpretation": "exploratory_only",
            "improvement_claim_supported": False, "promotion_supported": False,
        },
        "invariants": {
            "same_base_strategy": True, "same_data": True, "same_cost": True,
            "same_time_contract": True, "same_simulated_account": True,
            "no_training": True, "no_parameter_search": True,
            "entry_policy_only_changed_new_entry": True,
            "existing_position_exit_and_protection_not_overridden": True,
        },
        "decision_effects": effects,
        "limitations": ["exploratory_28_roundtrip_source_sample", "not_promotion_evidence"],
        **{flag: False for flag in (
            "demo_control_enabled", "execution_permission", "live", "order", "paper",
            "private", "promotion", "real_order", "runtime_observed", "transfer", "withdraw",
            "network_accessed")},
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return {**payload, "report_hash": hashlib.sha256(encoded).hexdigest()}


def blocked_policy_trial_report():
    return json.loads((ROOT / MARKET_POLICY_TRIAL_PATH).read_text(encoding="utf-8"))


def snapshot():
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_exact_committed_snapshot_is_paused_and_historical(tmp_path):
    target = committed_test_root(tmp_path / "sealed")
    view = read_stage_snapshot(target.parents[2], SELECTOR)
    assert view["status"] == "stage_baseline_reconciled_research_only"
    assert view["progress"]["processed_hours"] == 2960
    assert view["progress"]["planned_hours"] == 8760
    assert view["progress"]["paused"] is True
    assert view["source_head"] != view["publication_head"]
    assert view["counts"]["primary_decisions"] == 30
    assert view["counts"]["protective_exits"] == 26
    assert len(view["decision_links"]) == 30
    assert len(view["roundtrips"]) == 28
    assert view["read_only"] is True
    assert all(flag is False for flag in view["permissions"].values())
    assert "input_fingerprints" not in view
    market = view["market_state_evidence"]
    assert market["status"] == "completed_exploratory_research_only"
    assert market["description"]["observed_bars"] == 2960
    assert market["stratification"]["sample_units"] == {
        "bars": 2960, "roundtrips": 28, "contiguous_state_segments": 170}
    assert market["policy_trial"]["status"] == "not_started"
    assert market["policy_trial"]["effect_verified"] is False
    assert market["runtime_status"]["entry_policy_enabled"] is False


@pytest.mark.parametrize("selector", ["latest", "../other", SELECTOR.upper(), "donchian-v3-closeout-20260920"])
def test_no_selector_fallback(selector):
    assert read_stage_snapshot(ROOT, selector)["status"] == "not_bound"


@pytest.mark.parametrize("section,key,value", [
    ("counts", "fills", 55),
    ("counts", "primary_decisions", 31),
    ("economics", "cash_usdt", "5000"),
    ("progress", "paused", False),
    ("identity", "source_head", "f" * 40),
    ("identity", "cost_policy_hash", "f" * 64),
    ("identity", "spec_git", "latest:spec.json"),
    ("identity", "planned_evaluation_end_utc", "2026-01-02T08:00:00+00:00"),
    ("execution_assumptions", "taker_fee_bps", "0"),
    ("permissions", "order", True),
])
def test_tamper_or_reseal_cannot_change_frozen_facts(section, key, value):
    data = copy.deepcopy(snapshot())
    data[section][key] = value
    with pytest.raises(ValueError):
        validate_stage_snapshot(data, "f" * 40)


def test_missing_links_and_unverified_annual_claim_fail_closed():
    data = copy.deepcopy(snapshot())
    data["decision_links"].pop()
    with pytest.raises(ValueError):
        validate_stage_snapshot(data, "f" * 40)


def committed_test_root(tmp_path, *, include_market_state=True, trial=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True,
                       capture_output=True)
    git("init")
    git("config", "user.name", "Readonly Test")
    git("config", "user.email", "readonly@example.invalid")
    target = tmp_path / ".agent/offline_evidence/donchian-stage-20260921.json"
    target.parent.mkdir(parents=True)
    target.write_text(SNAPSHOT.read_text(encoding="utf-8"), encoding="utf-8")
    if include_market_state:
        market = tmp_path / MARKET_STATE_PATH
        market.parent.mkdir(parents=True, exist_ok=True)
        market.write_bytes(MARKET_STATE.read_bytes())
    if trial is not None:
        trial_path = tmp_path / MARKET_POLICY_TRIAL_PATH
        trial_path.parent.mkdir(parents=True, exist_ok=True)
        trial_path.write_text(json.dumps(trial, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    git("add", ".agent")
    git("commit", "-m", "sealed stage")
    return target


def test_committed_blob_only_and_missing_commit_fail_closed(tmp_path):
    target = tmp_path / ".agent/offline_evidence/donchian-stage-20260921.json"
    target.parent.mkdir(parents=True)
    target.write_text(SNAPSHOT.read_text(encoding="utf-8"), encoding="utf-8")
    assert read_stage_snapshot(tmp_path, SELECTOR)["status"] == "blocked"
    target = committed_test_root(tmp_path / "sealed")
    target.write_text("uncommitted corruption", encoding="utf-8")
    assert read_stage_snapshot(target.parents[2], SELECTOR)["status"] == "stage_baseline_reconciled_research_only"
    assert target.read_text(encoding="utf-8") == "uncommitted corruption"


def test_market_state_tamper_or_missing_fails_closed_without_invalidating_stage(tmp_path):
    evidence = json.loads(MARKET_STATE.read_text(encoding="utf-8"))
    tampered = copy.deepcopy(evidence)
    tampered["policy_trial"]["effect_verified"] = True
    with pytest.raises(ValueError):
        validate_market_state_evidence(tampered, "f" * 40)
    target = committed_test_root(tmp_path / "stage-only", include_market_state=False)
    view = read_stage_snapshot(target.parents[2], SELECTOR)
    assert view["status"] == "stage_baseline_reconciled_research_only"
    assert view["market_state_evidence"] == {
        "status": "blocked", "read_only": True,
        "reason": "market_state_diagnostic_missing_or_invalid",
        **{flag: False for flag in (
            "demo_control_enabled", "execution_permission", "live", "order", "paper",
            "private", "promotion", "real_order", "runtime_observed", "transfer", "withdraw")},
    }


def test_market_policy_trial_is_missing_until_a_separate_sealed_report_exists(tmp_path):
    target = committed_test_root(tmp_path / "missing-trial")
    trial = read_stage_snapshot(target.parents[2], SELECTOR)["market_state_evidence"]["policy_trial_evidence"]
    assert trial == {
        "schema_version": "market_policy_trial_read_model_v1",
        "trial_id": "donchian-stage-market-policy-trial-20260927-v1",
        "status": "not_started", "effect_verified": False, "read_only": True,
        "reason": "sealed_policy_trial_report_not_found_or_invalid",
        **{flag: False for flag in (
            "demo_control_enabled", "execution_permission", "live", "order", "paper",
            "private", "promotion", "real_order", "runtime_observed", "transfer", "withdraw",
            "network_accessed")},
    }


def test_market_policy_trial_projects_a_reconciled_fail_closed_partial_trial(tmp_path):
    report = blocked_policy_trial_report()
    validated = validate_market_policy_trial_blocked_evidence(report, "f" * 40)
    assert validated["status"] == "blocked_fail_closed"
    assert validated["effect_verified"] is False
    assert validated["rejected_entry_phase_count"] == 48
    assert validated["arms"]["original_donchian"]["processed_events"] == 2960
    conditioned = validated["arms"]["original_donchian_plus_frozen_entry_policy"]
    assert conditioned["processed_events"] == 1956
    assert conditioned["terminal_position"] == {
        "position_contracts": "-0.01", "average_price": "82667.566415",
        "status": "nonflat_blocked_preserved"}
    assert conditioned["blockers"] == [
        "ProtectionTriggerAmbiguous:historical_protection_double_touch_ambiguous"]
    target = committed_test_root(tmp_path / "blocked-trial", trial=report)
    projected = read_stage_snapshot(
        target.parents[2], SELECTOR)["market_state_evidence"]["policy_trial_evidence"]
    assert projected["status"] == "blocked_fail_closed"
    assert projected["effect_verified"] is False


@pytest.mark.parametrize("mutate", [
    lambda report: report["arms"]["original_donchian_plus_frozen_entry_policy"].__setitem__(
        "processed_events", 2960),
    lambda report: report["arms"]["original_donchian_plus_frozen_entry_policy"][
        "terminal_position"].__setitem__("position_contracts", "0"),
    lambda report: report["arms"]["original_donchian_plus_frozen_entry_policy"].__setitem__(
        "blockers", ["different"]),
    lambda report: report["consumer_binding"].__setitem__("state_source_binding_hash", "0" * 64),
    lambda report: report.__setitem__("rejected_entry_phase_count", 47),
    lambda report: report["safety"].__setitem__("real_order_submitted", True),
])
def test_market_policy_trial_blocked_receipt_rejects_tamper_or_safety_upgrade(mutate):
    report = blocked_policy_trial_report()
    mutate(report)
    unsigned = dict(report)
    unsigned.pop("projection_hash")
    report["projection_hash"] = hashlib.sha256(json.dumps(unsigned, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    with pytest.raises(ValueError):
        validate_market_policy_trial_blocked_evidence(report, "f" * 40)


def test_market_policy_trial_validates_real_arm_economics_and_decision_links(tmp_path):
    report = policy_trial_report()
    validated = validate_market_policy_trial_evidence(report, "f" * 40)
    assert validated["effect_verified"] is True
    assert validated["arms"]["original_donchian"]["roundtrips"] == 28
    assert validated["arms"]["original_donchian_plus_frozen_entry_policy"]["new_entries_rejected"] == 18
    assert len(validated["decision_effects"]) == 18
    assert validated["decision_effects"][0]["selected_state"]["path_efficiency_by_horizon"] == {
        "24": 0.16, "72": 0.18, "168": 0.31}
    target = committed_test_root(tmp_path / "with-trial", trial=report)
    view = read_stage_snapshot(target.parents[2], SELECTOR)
    assert view["market_state_evidence"]["policy_trial_evidence"]["status"] == "completed_exploratory_research_only"


def test_market_policy_trial_preserves_unknown_state_as_missing_not_zero():
    report = policy_trial_report()
    effect = report["decision_effects"][0]
    effect["market_entry_policy"].update({
        "state_status": "unknown", "state_reasons": ["insufficient_visible_history"],
        "reason": "state_unknown",
    })
    effect["selected_state"].update({
        "projection_source": "consumer_phase", "projection_status": "partial",
        "missing_fields": STATE_METRIC_FIELDS,
        "status": "unknown", "reasons": ["insufficient_visible_history"],
        "direction_score": None, "direction_label": None,
        "normalized_trend_strength": None,
        "path_efficiency_by_horizon": {"24": None, "72": None, "168": None},
        "multi_scale_agreement": None, "bar_volatility": None,
        "annualized_volatility": None, "volatility_relative_position": None,
        "volatility_expansion_ratio": None, "volatility_regime": None,
        "shock_score": None, "direction_persistence": None, "switching_frequency": None,
    })
    unsigned = dict(report)
    unsigned.pop("report_hash")
    report["report_hash"] = hashlib.sha256(json.dumps(unsigned, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    validated = validate_market_policy_trial_evidence(report, "f" * 40)
    state = validated["decision_effects"][0]["selected_state"]
    assert state["status"] == "unknown"
    assert state["path_efficiency_by_horizon"]["72"] is None


def test_market_policy_trial_accepts_honest_consumer_phase_projection_without_metrics():
    report = policy_trial_report()
    state = report["decision_effects"][0]["selected_state"]
    state.update({
        "projection_source": "consumer_phase", "projection_status": "partial",
        "missing_fields": STATE_METRIC_FIELDS,
        "direction_score": None, "direction_label": None,
        "normalized_trend_strength": None,
        "path_efficiency_by_horizon": {"24": None, "72": None, "168": None},
        "multi_scale_agreement": None, "bar_volatility": None,
        "annualized_volatility": None, "volatility_relative_position": None,
        "volatility_expansion_ratio": None, "volatility_regime": None,
        "shock_score": None, "direction_persistence": None, "switching_frequency": None,
    })
    unsigned = dict(report)
    unsigned.pop("report_hash")
    report["report_hash"] = hashlib.sha256(json.dumps(unsigned, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    validated = validate_market_policy_trial_evidence(report, "f" * 40)
    projected = validated["decision_effects"][0]["selected_state"]
    assert projected["projection_status"] == "partial"
    assert projected["missing_fields"] == STATE_METRIC_FIELDS


@pytest.mark.parametrize("mutate", [
    lambda report: report["source"].__setitem__("diagnostic_artifact_sha256", "0" * 64),
    lambda report: report["arms"]["original_donchian_plus_frozen_entry_policy"].__setitem__("source_commit", "b" * 40),
    lambda report: report["comparison"].__setitem__("net_usdt_delta", "99"),
    lambda report: report["invariants"].__setitem__("same_data", False),
    lambda report: report["decision_effects"][0]["evidence_links"].__setitem__("order_intent_id", "unexpected-order"),
    lambda report: report["decision_effects"][0]["selected_state"].__setitem__("content_hash", "f" * 64),
    lambda report: report["decision_effects"][0]["selected_state"]["path_efficiency_by_horizon"].__setitem__("72", 0.21),
    lambda report: report["decision_effects"][0]["selected_state"].__setitem__("missing_fields", ["shock_score"]),
    lambda report: report["decision_effects"][0]["market_entry_policy"].__setitem__("state_binding_status", "mismatch_non_entry_passthrough"),
    lambda report: report["decision_effects"][0]["selected_state"].__setitem__("cutoff_time", "2025-11-01T02:00:00+00:00"),
    lambda report: report.__setitem__("order", True),
])
def test_market_policy_trial_tamper_or_unsafe_claim_is_rejected(mutate):
    report = policy_trial_report()
    mutate(report)
    unsigned = dict(report)
    unsigned.pop("report_hash")
    report["report_hash"] = hashlib.sha256(json.dumps(unsigned, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    with pytest.raises(ValueError):
        validate_market_policy_trial_evidence(report, "f" * 40)


def test_readonly_registry_dispatch_is_exact_and_never_upgrades_permissions(tmp_path, monkeypatch):
    from backend.app.api import app_factory

    target = committed_test_root(tmp_path / "registry")
    monkeypatch.setattr(app_factory, "settings", replace(app_factory.settings,
        repo_root=target.parents[2], backend_evidence_profile="research_readonly",
        btc_demo_control_enabled=False, btc_runtime_artifact_root="",
        btc_private_readonly_observation_root=""))
    client = TestClient(app_factory.create_app())
    base = "/api/research/btc/strategy-registry"
    response = client.get(base, params={"offline_run": SELECTOR})
    assert response.status_code == 200
    body = response.json()
    assert body["offline_evidence"]["counts"]["fills"] == 56
    assert body["offline_evidence"]["progress"]["paused"] is True
    assert body["broker_or_order_allowed"] is False
    assert "input_fingerprints" not in body["offline_evidence"]
    for query in ("offline_run=latest", f"offline_run={SELECTOR}&offline_run={SELECTOR}",
                  f"offline_run={SELECTOR}&qlibRun=m1-okx-qlib"):
        rejected = client.get(base + "?" + query)
        assert rejected.status_code == 200
        assert rejected.json()["offline_evidence"]["status"] == "not_bound"


def test_reader_pins_resolved_commit_when_head_moves_between_git_calls(tmp_path, monkeypatch):
    from backend.app.services import donchian_stage_views as views

    resolved_head = "f" * 40
    calls = []
    def changing_head_git(command, *, cwd, timeout):
        calls.append(command)
        if command[1:] == ["rev-parse", "HEAD"]:
            return (resolved_head + "\n").encode("ascii")
        if command[1:] == ["show", f"{resolved_head}:{views.SNAPSHOT_PATH}"]:
            return SNAPSHOT.read_bytes()
        assert command[1:] == ["show", f"{resolved_head}:{views.MARKET_STATE_PATH}"]
        return MARKET_STATE.read_bytes()
    monkeypatch.setattr(views.subprocess, "check_output", changing_head_git)
    result = views.read_stage_snapshot(tmp_path, SELECTOR)
    assert result["publication_head"] == resolved_head
    assert result["status"] == "stage_baseline_reconciled_research_only"
    assert len(calls) == 3
    data = copy.deepcopy(snapshot())
    data["not_verified"].remove("annual_performance")
    with pytest.raises(ValueError):
        validate_stage_snapshot(data, "f" * 40)
