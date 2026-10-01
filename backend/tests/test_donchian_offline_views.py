"""Frozen Donchian offline receipt is read from a commit, never a live run."""
import copy
from dataclasses import replace
import json
from pathlib import Path
import subprocess

import pytest
from fastapi.testclient import TestClient

from backend.app.services.donchian_offline_views import (
    SELECTOR,
    digest,
    read_donchian_summary,
    seal_summary,
    validate_donchian_summary,
)


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / ".agent/offline_evidence/donchian-v3-closeout-20260920.json"
FIXTURE = ROOT / "tests/fixtures/strategy_v1/offline_contract.json"
FIXTURE_BYTES = subprocess.check_output(
    ["git", "show", "HEAD:tests/fixtures/strategy_v1/offline_contract.json"], cwd=ROOT)


def expected_identity():
    from quant_crypto.application.btc_strategy_registry import btc_strategy_registry
    return btc_strategy_registry.get("long_short_donchian_top5_okx_native").identity()


def payload():
    return json.loads(REPORT.read_text(encoding="utf-8"))


def reseal_stage(receipt, index=0):
    stage = receipt["summary"]["stages"][index]
    if stage["ledger"] is not None:
        stage["ledger"]["projection_sha256"] = digest(stage["ledger"]["projection"])
    stage["stage_sha256"] = digest({key: value for key, value in stage.items()
                                      if key != "stage_sha256"})
    return seal_summary(receipt["summary"])


def test_sealed_fixture_has_exact_five_phase_chain_and_false_permissions():
    result = validate_donchian_summary(payload(), expected_identity(), "f" * 40,
                                       FIXTURE_BYTES)
    assert result["historical_source"] is True
    assert [row["phase"] for row in result["stages"]] == [
        "primary", "hold", "reversal_close", "reversal_open", "exit"]
    assert result["counts"] == {"decisions": 5, "orders": 4, "fills": 4, "ledger_events": 4}
    assert all(value is False for value in result["permissions"].values())
    assert result["stages"][1]["order"] is None
    assert result["stages"][1]["fills"] == []
    assert result["stages"][1]["ledger"] is None


@pytest.mark.parametrize("field", ["client_order_id", "exchange_order_id", "ledger_event_hash", "fill_ids"])
def test_resealed_wrong_links_still_fail(field):
    bad = copy.deepcopy(payload())
    links = bad["summary"]["stages"][0]["evidence"]["links"]
    links[field] = ["wrong"] if field == "fill_ids" else "wrong"
    stage = bad["summary"]["stages"][0]
    stage["stage_sha256"] = digest({key: value for key, value in stage.items()
                                    if key != "stage_sha256"})
    bad = seal_summary(bad["summary"])
    with pytest.raises(ValueError):
        validate_donchian_summary(bad, expected_identity(), "f" * 40,
                                  FIXTURE_BYTES)


def test_permission_and_fixture_tamper_fail_even_when_resealed():
    bad = copy.deepcopy(payload())
    bad["summary"]["permissions"]["order"] = True
    with pytest.raises(ValueError):
        validate_donchian_summary(seal_summary(bad["summary"]), expected_identity(),
                                  "f" * 40, FIXTURE_BYTES)
    with pytest.raises(ValueError):
        validate_donchian_summary(payload(), expected_identity(), "f" * 40, b"wrong")


def test_resealed_source_swap_does_not_rebind_fixed_run():
    bad = copy.deepcopy(payload())
    bad["summary"]["source_head"] = "f" * 40
    with pytest.raises(ValueError, match="donchian_source_head_invalid"):
        validate_donchian_summary(seal_summary(bad["summary"]), expected_identity(),
                                  "f" * 40, FIXTURE_BYTES)


@pytest.mark.parametrize("field", ["plan", "order", "target", "fill_and_projection"])
def test_resealed_quantity_swaps_cannot_pass_fixed_contract(field):
    bad = copy.deepcopy(payload())
    row = bad["summary"]["stages"][0]
    if field == "plan":
        row["order_plan"]["contracts"] = "0.02"
    elif field == "order":
        row["order"]["sz"] = "0.02"
    elif field == "target":
        row["target_position"]["target_quantity"] = 0.02
    else:
        row["fills"][0]["size"] = "0.02"
        row["ledger"]["projection"]["fill_ledger"][0]["size"] = "0.02"
    with pytest.raises(ValueError):
        validate_donchian_summary(reseal_stage(bad), expected_identity(),
                                  "f" * 40, FIXTURE_BYTES)


def test_resealed_hold_position_cannot_change_without_an_economic_event():
    bad = copy.deepcopy(payload())
    bad["summary"]["stages"][1]["after"]["position_contracts"] = "0.02"
    with pytest.raises(ValueError):
        validate_donchian_summary(reseal_stage(bad, 1), expected_identity(),
                                  "f" * 40, FIXTURE_BYTES)


@pytest.mark.parametrize("field", ["plan_before", "plan_after", "order_filled", "fill_fee", "funding"])
def test_resealed_position_or_economic_totals_cannot_drift(field):
    bad = copy.deepcopy(payload())
    row = bad["summary"]["stages"][0]
    if field == "plan_before":
        row["order_plan"]["position_before_contracts"] = "0.02"
    elif field == "plan_after":
        row["order_plan"]["position_after_contracts"] = "0.02"
    elif field == "order_filled":
        row["order"]["accFillSz"] = "0.02"
    elif field == "fill_fee":
        row["fills"][0]["fee"] = "-0.006"
        row["ledger"]["projection"]["fill_ledger"][0]["fee"] = "-0.006"
    else:
        row["ledger"]["projection"]["funding_ledger"]["cashflow"] = "1"
    with pytest.raises(ValueError):
        validate_donchian_summary(reseal_stage(bad), expected_identity(),
                                  "f" * 40, FIXTURE_BYTES)


@pytest.mark.parametrize("field", ["event_hash", "raw_payload_sha256"])
def test_resealed_ledger_hash_reference_cannot_rebind_fixed_receipt(field, tmp_path):
    bad = copy.deepcopy(payload())
    row = bad["summary"]["stages"][0]
    row["ledger"][field] = "f" * 64
    if field == "event_hash":
        row["evidence"]["links"]["ledger_event_hash"] = "f" * 64
    tampered = reseal_stage(bad)
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True,
                       capture_output=True)
    git("init")
    git("config", "user.name", "Readonly Test")
    git("config", "user.email", "readonly@example.invalid")
    receipt = tmp_path / ".agent/offline_evidence/donchian-v3-closeout-20260920.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps(tampered), encoding="utf-8")
    fixture = tmp_path / "tests/fixtures/strategy_v1/offline_contract.json"
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes(FIXTURE_BYTES)
    git("add", ".agent", "tests")
    git("commit", "-m", "tampered receipt")
    result = read_donchian_summary(tmp_path, SELECTOR, expected_identity())
    assert result["status"] == "blocked"
    assert result["reason"] == "donchian_summary_missing_or_invalid"


def test_selector_is_fixed_and_missing_commit_does_not_read_dirty_file(tmp_path):
    assert read_donchian_summary(tmp_path, "latest", expected_identity())["status"] == "not_bound"
    assert read_donchian_summary(tmp_path, "../other", expected_identity())["status"] == "not_bound"
    target = tmp_path / ".agent/offline_evidence/donchian-v3-closeout-20260920.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(payload()), encoding="utf-8")
    assert read_donchian_summary(tmp_path, SELECTOR, expected_identity())["status"] == "blocked"


def test_reader_uses_committed_object_even_if_worktree_is_corrupt(tmp_path):
    def git(*args):
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True,
                              capture_output=True)
    git("init")
    git("config", "user.name", "Readonly Test")
    git("config", "user.email", "readonly@example.invalid")
    target = tmp_path / ".agent/offline_evidence/donchian-v3-closeout-20260920.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(payload()), encoding="utf-8")
    fixture = tmp_path / "tests/fixtures/strategy_v1/offline_contract.json"
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes(FIXTURE_BYTES)
    git("add", ".agent", "tests")
    git("commit", "-m", "sealed fixture")
    target.write_text("uncommitted corruption", encoding="utf-8")
    result = read_donchian_summary(tmp_path, SELECTOR, expected_identity())
    assert result["status"] == "sealed_offline_summary"
    assert target.read_text() == "uncommitted corruption"


def test_existing_readonly_registry_get_requires_one_exact_selector(tmp_path, monkeypatch):
    from backend.app.api import app_factory

    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True,
                       capture_output=True)
    git("init")
    git("config", "user.name", "Readonly Test")
    git("config", "user.email", "readonly@example.invalid")
    receipt = tmp_path / ".agent/offline_evidence/donchian-v3-closeout-20260920.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps(payload()), encoding="utf-8")
    fixture = tmp_path / "tests/fixtures/strategy_v1/offline_contract.json"
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes(FIXTURE_BYTES)
    git("add", ".agent", "tests")
    git("commit", "-m", "readonly receipt")
    monkeypatch.setattr(app_factory, "settings", replace(app_factory.settings,
        repo_root=tmp_path, backend_evidence_profile="research_readonly",
        btc_demo_control_enabled=False, btc_runtime_artifact_root="",
        btc_private_readonly_observation_root=""))
    client = TestClient(app_factory.create_app())
    base = "/api/research/btc/strategy-registry"
    assert "offline_evidence" not in client.get(base).json()
    response = client.get(base, params={"offline_run": SELECTOR})
    assert response.status_code == 200, response.text
    assert response.json()["offline_evidence"]["counts"]["fills"] == 4
    assert response.json()["broker_or_order_allowed"] is False
    for query in ("offline_run=latest", f"offline_run={SELECTOR}&offline_run={SELECTOR}",
                  f"offline_run={SELECTOR}&qlibRun=m1-okx-qlib"):
        rejected = client.get(base + "?" + query)
        assert rejected.status_code == 200
        assert rejected.json()["offline_evidence"]["status"] == "not_bound"
