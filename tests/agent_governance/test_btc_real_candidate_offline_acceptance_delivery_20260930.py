"""Failure-first tests for the one-time real-candidate offline acceptance contract."""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def module():
    return importlib.import_module(
        "tools.agent_governance.btc_real_candidate_offline_acceptance_delivery_20260930"
    )


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root).decode().strip()


def write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def commit(root: Path, message: str) -> str:
    subprocess.run(["git", "add", "--all"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=root, check=True)
    return git(root, "rev-parse", "HEAD")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def evidence_ref(
    logical_path: str,
    schema_version: str,
    digest: str = "c" * 64,
) -> dict:
    return {
        "logical_path": logical_path,
        "revision": "immutable-revision-1",
        "sha256": digest,
        "schema_version": schema_version,
        "seal_sha256": "d" * 64,
    }


def artifact_ref(name: str) -> dict:
    schemas = {
        "fit_budget.json": "alpha_factory_fit_budget_v1",
        "run_seal.json": "qlib_run_seal_v1",
    }
    return evidence_ref("factory/" + name, schemas.get(name, name + "_schema_v1"))


def synthetic_source(tmp_path: Path) -> tuple[Path, dict, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=repo, check=True)
    write(repo, "base.txt", "base\n")
    baseline = commit(repo, "baseline")
    feature_paths = [
        "quant_shared/alpha_factory/contracts.py",
        "quant_shared/alpha_factory/engine.py",
        "integrations/qlib_adapter/factory_trainer.py",
        "integrations/qlib_adapter/run_qlib_workflow.py",
        "integrations/qlib_adapter/research_pipeline.py",
        "integrations/qlib_adapter/factory_delivery.py",
        "integrations/qlib_adapter/factory_package.py",
        "quant_shared/strategy_delivery/package_evidence.py",
        "quant_crypto/application/qlib_offline_replay.py",
        "quant_crypto/application/btc_registered_candidate.py",
    ]
    source_paths = [
        "backend/app/api/app_factory.py",
        "backend/app/services/candidate_delivery_bootstrap.py",
        "backend/app/services/alpha_factory.py",
        *feature_paths,
        "backend/app/services/candidate_offline_inputs.py",
    ]
    test_paths = [f"tests/contracts/test_source_{index:02d}.py" for index in range(10)]
    for index, path in enumerate(source_paths + test_paths):
        write(repo, path, f"# frozen {index}\n")
    source = commit(repo, "source")
    inventory = {}
    for path in source_paths + test_paths:
        mode, kind, blob, tree_path = git(repo, "ls-tree", source, "--", path).split(maxsplit=3)
        assert kind == "blob" and tree_path == path
        raw = subprocess.check_output(["git", "show", source + ":" + path], cwd=repo)
        inventory[path] = {
            "blob": blob,
            "sha256": sha(raw),
            "mode": mode,
            "classification": "test" if path.startswith("tests/") else "source",
        }

    def fingerprint(paths: list[str]) -> str:
        payload = [[path, inventory[path]["sha256"]] for path in sorted(paths)]
        return sha(json.dumps(payload, separators=(",", ":")).encode())

    contract = {
        "source_sealed": True,
        "source_base_commit": baseline,
        "source_commit": source,
        "source_inventory": inventory,
        "source_file_count": 14,
        "test_file_count": 10,
        "runtime_feature_primitives": [
            "momentum_20d", "momentum_60d", "momentum_120d", "volatility_20d",
            "volatility_60d", "liquidity_20d", "reversal_1d", "volume_20d",
        ],
        "required_dependency_version_keys": ["numpy", "pandas", "lightgbm", "qlib"],
        "required_dependency_versions": {
            "numpy": "2.4.6", "pandas": "3.0.4", "lightgbm": "4.7.0", "qlib": "0.9.7"
        },
        "required_python_version": "3.11.15",
        "source_fingerprints": {
            "feature_runtime": {
                "primitive_names": [
                    "momentum_20d", "momentum_60d", "momentum_120d", "volatility_20d",
                    "volatility_60d", "liquidity_20d", "reversal_1d", "volume_20d",
                ],
                "inputs": feature_paths,
                "sha256": sha(json.dumps({
                    "primitive_names": [
                        "momentum_20d", "momentum_60d", "momentum_120d", "volatility_20d",
                        "volatility_60d", "liquidity_20d", "reversal_1d", "volume_20d",
                    ],
                    "files": [[path, inventory[path]["sha256"]] for path in sorted(feature_paths)],
                }, sort_keys=True, separators=(",", ":")).encode()),
            },
            "dependency_runtime": {
                "versions": {
                    "numpy": "2.4.6", "pandas": "3.0.4", "lightgbm": "4.7.0", "qlib": "0.9.7"
                },
                "sha256": sha(json.dumps(
                    {"numpy": "2.4.6", "pandas": "3.0.4", "lightgbm": "4.7.0", "qlib": "0.9.7"},
                    sort_keys=True, separators=(",", ":")
                ).encode()),
            },
            "combined": {
                "inputs": source_paths + test_paths,
                "sha256": fingerprint(source_paths + test_paths),
            },
        },
    }
    write(repo, "docs/read-only.txt", "production metadata\n")
    production = commit(repo, "production source S")
    mode, kind, blob, tree_path = git(repo, "ls-tree", production, "--", "docs/read-only.txt").split(maxsplit=3)
    assert kind == "blob" and tree_path == "docs/read-only.txt"
    preparation_inventory = {
        "docs/read-only.txt": {
            "blob": blob,
            "sha256": sha(subprocess.check_output(
                ["git", "show", production + ":docs/read-only.txt"], cwd=repo
            )),
            "mode": mode,
        }
    }
    contract.update(
        {
            "reviewed_source_commit": source,
            "allowed_source_paths": source_paths,
            "allowed_test_paths": test_paths,
            "max_source_file_count": 14,
            "max_test_file_count": 10,
            "required_feature_implementation_paths": feature_paths,
            "reviewed_feature_inventory": {
                path: {key: value for key, value in inventory[path].items() if key != "classification"}
                for path in feature_paths
            },
            "allowed_production_preparation_paths": ["docs/read-only.txt"],
            "allowed_production_preparation_prefixes": [".agent/handoffs/GOV/", ".agent/handoffs/BUSINESS/"],
        }
    )
    contract.pop("source_commit")
    contract.pop("source_file_count")
    contract.pop("test_file_count")
    return repo, contract, production, preparation_inventory


@pytest.fixture()
def source_fixture(tmp_path: Path):
    return synthetic_source(tmp_path)


def sealed_contract() -> dict:
    value = module().contract(ROOT)
    value.update(
        {
            "source_sealed": True,
            "source_base_commit": "a" * 40,
            "reviewed_source_commit": "b" * 40,
            "allowed_source_paths": [f"quant_crypto/source_{i:02d}.py" for i in range(14)],
            "allowed_test_paths": [f"tests/contracts/test_source_{i:02d}.py" for i in range(10)],
            "max_source_file_count": 14,
            "max_test_file_count": 10,
            "source_inventory": {
                **{
                    f"quant_crypto/source_{i:02d}.py": {
                        "blob": f"{i + 1:040x}", "sha256": f"{i + 1:064x}",
                        "mode": "100644", "classification": "source",
                    }
                    for i in range(14)
                },
                **{
                    f"tests/contracts/test_source_{i:02d}.py": {
                        "blob": f"{i + 20:040x}", "sha256": f"{i + 20:064x}",
                        "mode": "100644", "classification": "test",
                    }
                    for i in range(10)
                },
            },
            "required_feature_implementation_paths": [f"quant_crypto/source_{i:02d}.py" for i in range(10)],
            "reviewed_feature_inventory": {
                f"quant_crypto/source_{i:02d}.py": {
                    "blob": f"{i + 1:040x}", "sha256": f"{i + 1:064x}", "mode": "100644",
                }
                for i in range(10)
            },
            "source_fingerprints": {
                "feature_runtime": {
                    "primitive_names": value["runtime_feature_primitives"],
                    "inputs": [f"quant_crypto/source_{i:02d}.py" for i in range(10)],
                    "sha256": "1" * 64,
                },
                "dependency_runtime": {
                    "versions": value["required_dependency_versions"],
                    "sha256": "2" * 64,
                },
                "combined": {
                    "inputs": [
                        *[f"quant_crypto/source_{i:02d}.py" for i in range(14)],
                        *[f"tests/contracts/test_source_{i:02d}.py" for i in range(10)],
                    ],
                    "sha256": "3" * 64,
                },
            },
            "source_handoff": {
                "path": ".agent/handoffs/SOURCE/published.json",
                "commit": "c" * 40,
                "sha256": "4" * 64,
                "schema_version": "agent_handoff_envelope_v1",
                "event_id": "published-source",
                "ticket_id": "SOURCE",
                "deliverable_commit": "b" * 40,
                "readiness_classes": ["quality_checked"],
                "blockers": ["deployment_acceptance_pending"],
            },
            "allowed_production_preparation_paths": ["docs/production.md"],
            "allowed_production_preparation_prefixes": [".agent/handoffs/GOV/", ".agent/handoffs/BUSINESS/"],
        }
    )
    return value


def source_receipt(value: dict) -> dict:
    return {
        "schema_version": value["receipt_schema_version"],
        "ticket_id": value["ticket_id"],
        "phase": "source_review",
        "governance_commit": "d" * 40,
        "reviewed_source_commit": value["reviewed_source_commit"],
        "production_source_commit": "c" * 40,
        "production_preparation_inventory": {},
        "reviewed_commit": "e" * 40,
        "source_change_risk": value["source_change_risk"],
        "readiness_ceiling": value["readiness_ceiling"],
        "source_review": {
            "commit": "e" * 40,
            "path": value["review_report_paths"]["source_review"],
            "sha256": "5" * 64,
        },
        "checks": {name: "passed" for name in value["required_source_checks"]},
        "safety_flags": {name: False for name in value["required_false_flags"]},
    }


def deployment_receipt(value: dict, outcome: str = "passed") -> dict:
    fit_count = 4 if outcome == "blocked_screening" else 5
    screening_passed = outcome != "blocked_screening"
    item = source_receipt(value)
    item.update(
        {
            "phase": "deployment_acceptance",
            "consumer_commit": None if outcome in value["pre_run_blocked_outcomes"] else "f" * 40,
            "execution_commit": None if outcome in value["pre_run_blocked_outcomes"] else "f" * 40,
            "integration_review": None if outcome in value["pre_run_blocked_outcomes"] else {
                "commit": "f" * 40,
                "path": value["review_report_paths"]["integration_review"],
                "sha256": "6" * 64,
            },
            "acceptance": None if outcome in value["pre_run_blocked_outcomes"] else {
                "commit": "f" * 40,
                "path": value["review_report_paths"]["deployment_acceptance"],
                "sha256": "7" * 64,
            },
            "blocked_report": (
                {
                    "commit": "d" * 40,
                    "path": value["review_report_paths"]["blocked_deployment"],
                    "sha256": "a" * 64,
                }
                if outcome in value["pre_run_blocked_outcomes"] else None
            ),
            "campaign_evidence": {
                "commit": "d" * 40 if outcome in value["pre_run_blocked_outcomes"] else "f" * 40,
                "path": value["campaign_evidence_path"],
                "sha256": "b" * 64,
                "schema_version": value["campaign_evidence_schema_version"],
            },
            "campaign": {
                "campaign_id": value["fixed_campaign"]["campaign_id"],
                "attempts": [
                    {"fit_index": i, "stage": "screening_fold" if i < 5 else "final_audit",
                     "outcome": "passed", "evidence_sha256": "c" * 64,
                     "evidence_ref": artifact_ref("fit_budget.json")}
                    for i in range(1, fit_count + 1)
                ],
                "actual_fit_count": fit_count,
                "screening_passed": screening_passed,
                "calibration_passed": outcome == "passed",
            },
            "bindings": {
                name: {
                    "version": name + "-v1",
                    "sha256": "8" * 64,
                    "evidence_ref": evidence_ref("identity/candidate_offline_job_identity.json", "candidate_offline_job_identity_v1", "8" * 64),
                    **({"source_commit": item["production_source_commit"]} if name == "candidate" else {}),
                }
                for name in ("candidate", "catalog", "account", "input")
            },
            "missing_bindings": [],
            "run_evidence": {
                "business_outcome": outcome,
                "business_passed": outcome == "passed",
                "official_run_count": 1 if outcome == "passed" else 0,
                "run_id": "real-candidate-run-1" if outcome == "passed" else None,
                "decision_hours": 48 if outcome == "passed" else 0,
                "settlement_events": 6 if outcome == "passed" else 0,
                "requested_pause_after_event": 24,
                "actual_checkpoint_after_event": 24 if outcome == "passed" else None,
                "checkpoint_selection_rule": "first_safe_boundary_at_or_after_requested_event",
                "checkpoint_selected_by_pnl": False,
                "checkpoint": (
                    evidence_ref("state/state.json", "alpha_factory_state_v1", "9" * 64)
                    if outcome == "passed" else None
                ),
                "same_task_resumed": outcome == "passed",
                "run_seal": artifact_ref("run_seal.json") if outcome == "passed" else None,
                "ledger_evidence": evidence_ref("runtime/ledger_reconciliation.json", "account_ledger_replay_v1") if outcome == "passed" else None,
                "minute_sampling_only": True,
                "tick_path_verified": False,
                "exact_exchange_settlement_verified": False,
                "blockers": [] if outcome == "passed" else [outcome],
                "not_run": [] if outcome == "passed" else ["official_offline_run"],
            },
            "temporary_runtime": copy.deepcopy(
                value["pre_run_blocked_runtime_required"]
                if outcome in value["pre_run_blocked_outcomes"]
                else value["temporary_runtime_required"]
            ),
            "final_runtime": copy.deepcopy(value["final_runtime_required"]),
        }
    )
    if outcome in value["pre_run_blocked_outcomes"]:
        item["temporary_runtime"]["auth_mode"] = "key"
    item["final_runtime"]["auth_mode"] = "key"
    item["checks"].update(
        {
            name: (
                "passed"
                if outcome == "passed" or name in value["required_source_checks"]
                else "not_run"
            )
            for name in value["required_deployment_checks"]
        }
    )
    return item


def test_real_contract_is_sealed_to_the_reviewed_source_and_handoff():
    m = module()
    value = m.contract(ROOT)
    assert value["source_sealed"] is True
    assert value["source_base_commit"] == "ee42a967663d7bc306b4ac8b0d3c7d178f5b79cd"
    assert value["reviewed_source_commit"] == "4f730f54b34e3d2c2af7cc62e796058bc2fc3048"
    assert "production_source_commit" not in value
    assert value["max_source_file_count"] == len(value["allowed_source_paths"]) == 14
    assert value["max_test_file_count"] == len(value["allowed_test_paths"]) == 10
    assert {
        "backend/app/api/app_factory.py",
        "backend/app/services/candidate_delivery_bootstrap.py",
    }.issubset(value["allowed_source_paths"])
    assert "tests/api/test_qlib_pipeline.py" in value["allowed_test_paths"]
    assert len(value["source_inventory"]) == 23
    assert sum(item["classification"] == "source" for item in value["source_inventory"].values()) == 14
    assert sum(item["classification"] == "test" for item in value["source_inventory"].values()) == 9
    assert value["source_handoff"]["event_id"] == (
        "published-btc-real-candidate-clean-source-refreeze-20261001-4f730f54"
    )
    result = subprocess.run(
        ["py", "-3", "-B", "-X", "utf8", str(Path(m.__file__).relative_to(ROOT)),
         "--repo-root", str(ROOT), "validate-source"],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "blockers": [], "source_sealed": True, "status": "valid"
    }


def test_exact_source_inventory_hashes_fingerprints_and_s_to_f_fidelity(source_fixture):
    repo, value, deployment, preparation_inventory = source_fixture
    m = module()
    m._verify_frozen_source(repo, value)
    m._verify_production_source(repo, value, deployment, preparation_inventory)
    m._verify_source_fidelity(repo, value, deployment)


@pytest.mark.parametrize(
    "mutation,expected",
    [
        (lambda v: v["source_inventory"].pop(next(iter(v["source_inventory"]))), "source_touch_set_mismatch"),
        (lambda v: next(iter(v["source_inventory"].values())).__setitem__("blob", "f" * 40), "source_blob_or_mode_mismatch"),
        (lambda v: next(iter(v["source_inventory"].values())).__setitem__("sha256", "f" * 64), "source_sha256_mismatch"),
        (lambda v: v["source_fingerprints"]["feature_runtime"].__setitem__("sha256", "f" * 64), "source_fingerprint_mismatch:feature_runtime"),
    ],
)
def test_source_drift_fails_closed(source_fixture, mutation, expected):
    repo, original, _, _ = source_fixture
    value = copy.deepcopy(original)
    mutation(value)
    with pytest.raises((ValueError, subprocess.SubprocessError), match=expected):
        module()._verify_frozen_source(repo, value)


def test_source_review_does_not_require_fit_candidate_or_run(monkeypatch):
    m = module()
    value = sealed_contract()
    monkeypatch.setattr(m, "_load_contract", lambda *args, **kwargs: value)
    monkeypatch.setattr(m, "_verify_receipt_evidence", lambda *args, **kwargs: None)
    assert m.blockers(source_receipt(value), repo_root=ROOT) == []


def test_deployment_pass_requires_exact_bounded_campaign_and_run(monkeypatch):
    m = module()
    value = sealed_contract()
    monkeypatch.setattr(m, "_load_contract", lambda *args, **kwargs: value)
    monkeypatch.setattr(m, "_verify_receipt_evidence", lambda *args, **kwargs: None)
    item = deployment_receipt(value)
    assert m.blockers(item, repo_root=ROOT) == []
    item = deployment_receipt(value)
    item["campaign"]["attempts"].append(
        {"fit_index": 6, "stage": "final_audit", "outcome": "passed",
         "evidence_sha256": "c" * 64,
         "evidence_ref": artifact_ref("fit_budget.json")}
    )
    item["campaign"]["actual_fit_count"] = 6
    assert "fit_budget_exceeded" in m.blockers(item, repo_root=ROOT)
    item = deployment_receipt(value)
    item["run_evidence"]["official_run_count"] = 2
    assert "official_run_count_mismatch" in m.blockers(item, repo_root=ROOT)
    item = deployment_receipt(value)
    item["campaign"]["attempts"][2]["outcome"] = "failed"
    assert "passed_campaign_incomplete" in m.blockers(item, repo_root=ROOT)


@pytest.mark.parametrize("outcome", ["blocked_screening", "blocked_calibration"])
def test_natural_candidate_failure_is_a_deliverable_blocked_report_not_a_pass(monkeypatch, outcome):
    m = module()
    value = sealed_contract()
    monkeypatch.setattr(m, "_load_contract", lambda *args, **kwargs: value)
    monkeypatch.setattr(m, "_verify_receipt_evidence", lambda *args, **kwargs: None)
    item = deployment_receipt(value, outcome)
    item["bindings"]["candidate"] = None
    item["missing_bindings"] = ["candidate"]
    problems = m.blockers(item, repo_root=ROOT)
    assert problems == ["business_acceptance_not_passed:" + outcome]


def test_failed_or_crashed_fit_still_consumes_budget(monkeypatch):
    m = module()
    value = sealed_contract()
    monkeypatch.setattr(m, "_load_contract", lambda *args, **kwargs: value)
    monkeypatch.setattr(m, "_verify_receipt_evidence", lambda *args, **kwargs: None)
    item = deployment_receipt(value, "blocked_screening")
    item["campaign"]["attempts"][0]["outcome"] = "crashed"
    item["campaign"]["attempts"][1]["outcome"] = "failed"
    item["bindings"]["candidate"] = None
    item["missing_bindings"] = ["candidate"]
    assert m.blockers(item, repo_root=ROOT) == [
        "business_acceptance_not_passed:blocked_screening"
    ]


def test_temporary_offline_worker_does_not_enable_trading_and_final_is_readonly(monkeypatch):
    m = module()
    value = sealed_contract()
    monkeypatch.setattr(m, "_load_contract", lambda *args, **kwargs: value)
    monkeypatch.setattr(m, "_verify_receipt_evidence", lambda *args, **kwargs: None)
    item = deployment_receipt(value)
    assert item["temporary_runtime"]["offline_worker_enabled"] is True
    assert item["safety_flags"]["execution_permission"] is False
    assert item["final_runtime"]["profile"] == "research_readonly"
    item["safety_flags"].pop("order")
    assert "safety_flags_missing_or_unknown" in m.blockers(item, repo_root=ROOT)
    item = deployment_receipt(value)
    item["final_runtime"]["offline_worker_enabled"] = True
    assert "final_runtime_mismatch" in m.blockers(item, repo_root=ROOT)


def test_actual_source_inventory_may_be_a_strict_subset_of_ticket_allowlist(tmp_path):
    m = module()
    repo = tmp_path / "subset-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=repo, check=True)
    write(repo, "base.txt", "base\n")
    base = commit(repo, "base")
    source_allowlist = [f"quant_crypto/allowed_{i:02d}.py" for i in range(14)]
    test_allowlist = [f"tests/contracts/test_allowed_{i:02d}.py" for i in range(10)]
    changed = [source_allowlist[0], source_allowlist[4], test_allowlist[2]]
    for index, path in enumerate(changed):
        write(repo, path, f"# reviewed {index}\n")
    reviewed = commit(repo, "reviewed source R")
    inventory = {}
    for path in changed:
        mode, kind, blob, tree_path = git(repo, "ls-tree", reviewed, "--", path).split(maxsplit=3)
        assert kind == "blob" and tree_path == path
        raw = subprocess.check_output(["git", "show", reviewed + ":" + path], cwd=repo)
        inventory[path] = {
            "blob": blob,
            "sha256": sha(raw),
            "mode": mode,
            "classification": "test" if path.startswith("tests/") else "source",
        }
    write(repo, "docs/production-metadata.md", "production preparation\n")
    production = commit(repo, "production source S")
    value = {
        "source_sealed": True,
        "source_base_commit": base,
        "reviewed_source_commit": reviewed,
        "allowed_source_paths": source_allowlist,
        "allowed_test_paths": test_allowlist,
        "max_source_file_count": 14,
        "max_test_file_count": 10,
        "source_inventory": inventory,
        "required_feature_implementation_paths": changed,
        "reviewed_feature_inventory": {
            path: {key: item for key, item in inventory[path].items() if key != "classification"}
            for path in changed
        },
    }
    m._verify_reviewed_source(repo, value)


def test_actual_safe_checkpoint_need_not_equal_requested_event_24(monkeypatch):
    m = module()
    value = sealed_contract()
    monkeypatch.setattr(m, "_load_contract", lambda *args, **kwargs: value)
    monkeypatch.setattr(m, "_verify_receipt_evidence", lambda *args, **kwargs: None)
    item = deployment_receipt(value)
    item["run_evidence"]["requested_pause_after_event"] = 24
    item["run_evidence"]["actual_checkpoint_after_event"] = 31
    item["run_evidence"]["checkpoint_selection_rule"] = "first_safe_boundary_at_or_after_requested_event"
    item["run_evidence"]["checkpoint_selected_by_pnl"] = False
    assert m.blockers(item, repo_root=ROOT) == []


def test_blocked_deployment_explicit_not_run_checks_do_not_become_pass(monkeypatch):
    m = module()
    value = sealed_contract()
    monkeypatch.setattr(m, "_load_contract", lambda *args, **kwargs: value)
    monkeypatch.setattr(m, "_verify_receipt_evidence", lambda *args, **kwargs: None)
    item = deployment_receipt(value, "blocked_screening")
    item["bindings"]["candidate"] = None
    item["missing_bindings"] = ["candidate"]
    for name in value["required_deployment_checks"]:
        item["checks"][name] = "not_run"
    for name in value["required_source_checks"]:
        item["checks"][name] = "passed"
    assert m.blockers(item, repo_root=ROOT) == [
        "business_acceptance_not_passed:blocked_screening"
    ]


def test_readonly_restore_does_not_force_key_auth_mode(monkeypatch):
    m = module()
    value = sealed_contract()
    monkeypatch.setattr(m, "_load_contract", lambda *args, **kwargs: value)
    monkeypatch.setattr(m, "_verify_receipt_evidence", lambda *args, **kwargs: None)
    item = deployment_receipt(value)
    item["final_runtime"]["auth_mode"] = "local_no_password"
    item["final_runtime"]["auth_mode_changed_for_restore"] = False
    item["final_runtime"]["password_step_added"] = False
    assert m.blockers(item, repo_root=ROOT) == []


def test_source_handoff_must_use_fixed_business_ticket_identity():
    m = module()
    value = sealed_contract()
    value["source_handoff"]["path"] = ".agent/handoffs/UNRELATED/published.json"
    with pytest.raises(ValueError, match="source_handoff_reference_invalid"):
        m._verify_source_handoff(ROOT, value)


def test_dependency_fingerprint_requires_all_four_exact_versions(source_fixture):
    repo, original, _, _ = source_fixture
    value = copy.deepcopy(original)
    value["source_fingerprints"]["dependency_runtime"]["versions"]["qlib"] = ""
    with pytest.raises(ValueError, match="dependency_versions_invalid"):
        module()._verify_frozen_source(repo, value)


def test_campaign_evidence_manifest_cross_checks_receipt_and_external_artifacts(tmp_path):
    m = module()
    value = sealed_contract()
    value["campaign_evidence_path"] = "evidence.json"
    receipt_value = deployment_receipt(value)
    repo = tmp_path / "campaign-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=repo, check=True)
    payload = {
        "schema_version": value["campaign_evidence_schema_version"],
        "ticket_id": value["ticket_id"],
        "reviewed_source_commit": value["reviewed_source_commit"],
        "production_source_commit": receipt_value["production_source_commit"],
        "consumer_commit": receipt_value["consumer_commit"],
        "execution_commit": receipt_value["execution_commit"],
        "business_outcome": "passed",
        "campaign": receipt_value["campaign"],
        "bindings": receipt_value["bindings"],
        "run_evidence": receipt_value["run_evidence"],
        "temporary_runtime": receipt_value["temporary_runtime"],
        "final_runtime": receipt_value["final_runtime"],
        "safety_flags": receipt_value["safety_flags"],
        "checks": receipt_value["checks"],
        "source_fingerprints": value["source_fingerprints"],
        "external_artifacts": {
            name: artifact_ref(name)
            for name in value["approved_external_artifact_names"]
        },
        "missing_external_artifacts": [],
    }
    write(repo, value["campaign_evidence_path"], json.dumps(payload, sort_keys=True) + "\n")
    evidence_commit = commit(repo, "campaign evidence")
    raw = subprocess.check_output(
        ["git", "show", evidence_commit + ":" + value["campaign_evidence_path"]], cwd=repo
    )
    reference = {
        "commit": evidence_commit,
        "path": value["campaign_evidence_path"],
        "sha256": sha(raw),
        "schema_version": value["campaign_evidence_schema_version"],
    }
    assert m._campaign_evidence(repo, reference, receipt_value, value) == evidence_commit
    forged = copy.deepcopy(receipt_value)
    forged["campaign"]["actual_fit_count"] = 4
    with pytest.raises(ValueError, match="campaign_evidence_mismatch:campaign"):
        m._campaign_evidence(repo, reference, forged, value)


def test_structured_review_report_decision_and_commits_are_not_self_reported_booleans(tmp_path):
    m = module()
    value = sealed_contract()
    value["review_report_paths"]["source_review"] = "source-review.json"
    repo = tmp_path / "review-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=repo, check=True)
    path = value["review_report_paths"]["source_review"]
    payload = {
        "schema_version": "btc_real_candidate_offline_review_v1",
        "ticket_id": value["ticket_id"],
        "phase": "source_review",
        "decision": "approved",
        "reviewed_source_commit": value["reviewed_source_commit"],
        "production_source_commit": "c" * 40,
        "consumer_commit": None,
        "execution_commit": None,
        "blockers": ["deployment_acceptance_pending"],
        "not_run": ["real_fit"],
        "production_preparation_inventory_sha256": sha(b"{}"),
        "dependency_runtime": {
            "interpreter_identity": "canonical_repo_venv_py311",
            "python_version": value["required_python_version"],
            "versions": value["required_dependency_versions"],
        },
    }
    write(repo, path, json.dumps(payload, sort_keys=True) + "\n")
    report_commit = commit(repo, "source review")
    raw = subprocess.check_output(["git", "show", report_commit + ":" + path], cwd=repo)
    reference = {"commit": report_commit, "path": path, "sha256": sha(raw)}
    assert m._review_report(
        repo, reference, path, phase="source_review", decision="approved",
        reviewed_source_commit=value["reviewed_source_commit"],
        production_source_commit="c" * 40,
        production_preparation_inventory={},
        consumer_commit=None, execution_commit=None,
    ) == report_commit
    with pytest.raises(ValueError, match="review_report_mismatch:source_review:production_source_commit"):
        m._review_report(
            repo, reference, path, phase="source_review", decision="approved",
            reviewed_source_commit=value["reviewed_source_commit"],
            production_source_commit="f" * 40,
            production_preparation_inventory={},
            consumer_commit=None, execution_commit=None,
        )


def test_contract_seals_r_without_self_referential_s():
    value = sealed_contract()
    assert value["source_sealed"] is True
    assert "production_source_commit" not in value
    assert "production_preparation_inventory" not in value
    module()._validate_contract_shape(value)


def test_feature_fingerprint_inputs_are_fixed_implementation_inventory(source_fixture):
    repo, original, _, _ = source_fixture
    value = copy.deepcopy(original)
    value["source_fingerprints"]["feature_runtime"]["inputs"] = [next(iter(value["source_inventory"]))]
    with pytest.raises(ValueError, match="source_fingerprint_inputs_invalid:feature_runtime"):
        module()._verify_frozen_source(repo, value)


def test_production_preparation_inventory_is_receipt_owned_and_exact(source_fixture):
    repo, value, production, inventory = source_fixture
    module()._verify_production_source(repo, value, production, inventory)
    forged = copy.deepcopy(inventory)
    forged["docs/read-only.txt"]["sha256"] = "f" * 64
    with pytest.raises(ValueError, match="production_preparation_sha256_mismatch"):
        module()._verify_production_source(repo, value, production, forged)


def test_campaign_objects_require_immutable_evidence_references(monkeypatch):
    m = module()
    value = sealed_contract()
    monkeypatch.setattr(m, "_load_contract", lambda *args, **kwargs: value)
    monkeypatch.setattr(m, "_verify_receipt_evidence", lambda *args, **kwargs: None)
    item = deployment_receipt(value)
    item["bindings"]["catalog"].pop("evidence_ref")
    assert "binding_invalid:catalog" in m.blockers(item, repo_root=ROOT)
    item = deployment_receipt(value)
    item["run_evidence"]["checkpoint"].pop("revision")
    assert "checkpoint_resume_pair_invalid" in m.blockers(item, repo_root=ROOT)


def test_real_git_full_receipts_support_post_s_q_and_post_f_a_without_self_reference(
    tmp_path, monkeypatch
):
    """Exercise both receipt phases through blockers(), not only the DAG helper."""

    from tools.agent_governance.handoff import handoff_template

    m = module()
    repo, source_value, original_production, _ = synthetic_source(tmp_path)
    subprocess.run(["git", "config", "core.longpaths", "true"], cwd=repo, check=True)
    reviewed = source_value["reviewed_source_commit"]
    baseline = git(repo, "rev-list", "--max-parents=0", "HEAD")
    source_path = next(iter(source_value["source_inventory"]))
    source_raw = subprocess.check_output(["git", "show", reviewed + ":" + source_path], cwd=repo)
    source_handoff_path = (
        ".agent/handoffs/BTC-REAL-CANDIDATE-OFFLINE-ACCEPTANCE-20260930/"
        "published-source-fixture.json"
    )

    subprocess.run(["git", "switch", "-c", "source-handoff", reviewed], cwd=repo, check=True)
    payload = handoff_template(
        event_id="published-source-fixture",
        ticket_id="BTC-REAL-CANDIDATE-OFFLINE-ACCEPTANCE-20260930",
        event_type="published",
        producer_role="btc_developer",
        consumer_roles=["architect", "integrator"],
        domain="btc",
        producer_branch="agent/btc_developer/fixture",
        base_commit=baseline,
        deliverable_commit=reviewed,
        deliverables=[{
            "type": "code", "path": source_path, "sha256": sha(source_raw),
            "schema_version": "btc_real_candidate_source_fixture_v1",
            "readiness_class": "quality_checked",
        }],
        tests=[{"command": "fixture source test", "result": "passed", "evidence_path": ""}],
        blockers=["deployment_acceptance_pending"],
        gate_impact="none",
        promotion_eligible=False,
        created_at="2026-09-30T00:00:00Z",
    )
    write(repo, source_handoff_path, json.dumps(payload, sort_keys=True) + "\n")
    source_handoff_commit = commit(repo, "published source handoff")
    source_handoff_raw = subprocess.check_output(
        ["git", "show", source_handoff_commit + ":" + source_handoff_path], cwd=repo
    )

    subprocess.run(["git", "switch", "main"], cwd=repo, check=True)
    subprocess.run(
        ["git", "merge", "--no-ff", "source-handoff", "-m", "production source S"],
        cwd=repo, check=True,
    )
    production = git(repo, "rev-parse", "HEAD")

    def inventory_between(before: str, after: str) -> dict:
        result = {}
        for path in git(repo, "diff", "--name-only", before, after, "--").splitlines():
            mode, kind, blob, tree_path = git(repo, "ls-tree", after, "--", path).split(maxsplit=3)
            assert kind == "blob" and tree_path == path
            raw = subprocess.check_output(["git", "show", after + ":" + path], cwd=repo)
            result[path] = {"blob": blob, "sha256": sha(raw), "mode": mode}
        return result

    preparation_inventory = inventory_between(reviewed, production)
    value = sealed_contract()
    for key in (
        "source_base_commit", "reviewed_source_commit", "allowed_source_paths",
        "allowed_test_paths", "max_source_file_count", "max_test_file_count",
        "source_inventory", "required_feature_implementation_paths",
        "reviewed_feature_inventory", "source_fingerprints",
    ):
        value[key] = copy.deepcopy(source_value[key])
    value["governance_base_commit"] = baseline
    value["allowed_production_preparation_paths"] = ["docs/read-only.txt"]
    value["allowed_production_preparation_prefixes"] = m.contract(ROOT)[
        "allowed_production_preparation_prefixes"
    ]
    value["source_handoff"] = {
        "path": source_handoff_path,
        "commit": source_handoff_commit,
        "sha256": sha(source_handoff_raw),
        "schema_version": "agent_handoff_envelope_v1",
        "event_id": payload["event_id"],
        "ticket_id": payload["ticket_id"],
        "deliverable_commit": reviewed,
        "readiness_classes": ["quality_checked"],
        "blockers": payload["blockers"],
    }
    value["rollback_ref"] = "refs/heads/codex/fixture-rollback"
    subprocess.run(["git", "branch", "codex/fixture-rollback", baseline], cwd=repo, check=True)
    assert [
        path for path in preparation_inventory
        if not m._production_preparation_allowed(path, value)
    ] == []

    inventory_sha = sha(json.dumps(
        preparation_inventory, sort_keys=True, separators=(",", ":")
    ).encode())

    def review_payload(*, phase: str, decision: str, consumer: str | None) -> dict:
        return {
            "schema_version": "btc_real_candidate_offline_review_v1",
            "ticket_id": value["ticket_id"],
            "phase": phase,
            "decision": decision,
            "reviewed_source_commit": reviewed,
            "production_source_commit": production,
            "consumer_commit": consumer,
            "execution_commit": consumer,
            "blockers": [] if phase != "source_review" else ["deployment_acceptance_pending"],
            "not_run": [] if phase != "source_review" else ["real_fit", "offline_run"],
            "production_preparation_inventory_sha256": inventory_sha,
            "dependency_runtime": {
                "interpreter_identity": "canonical_repo_venv_py311",
                "python_version": value["required_python_version"],
                "versions": value["required_dependency_versions"],
            },
        }

    def reference(at: str, path: str) -> dict:
        raw = subprocess.check_output(["git", "show", at + ":" + path], cwd=repo)
        return {"commit": at, "path": path, "sha256": sha(raw)}

    source_review_path = value["review_report_paths"]["source_review"]
    subprocess.run(["git", "switch", "-c", "source-review", production], cwd=repo, check=True)
    write(repo, source_review_path, json.dumps(
        review_payload(phase="source_review", decision="approved", consumer=None), sort_keys=True
    ) + "\n")
    source_review = commit(repo, "post-S source review Q")
    source_review_reference = reference(source_review, source_review_path)

    monkeypatch.setattr(m, "_load_contract", lambda *args, **kwargs: value)
    source_item = source_receipt(value)
    source_item.update({
        "governance_commit": baseline,
        "production_source_commit": production,
        "production_preparation_inventory": preparation_inventory,
        "reviewed_commit": source_review,
        "source_review": source_review_reference,
    })
    assert m.blockers(source_item, repo_root=repo) == []

    subprocess.run(["git", "switch", "main"], cwd=repo, check=True)
    (repo / source_review_path).parent.mkdir(parents=True, exist_ok=True)
    (repo / source_review_path).write_bytes(subprocess.check_output(
        ["git", "show", source_review + ":" + source_review_path], cwd=repo
    ))
    consumer = commit(repo, "frozen execution F")
    assert subprocess.run(
        ["git", "merge-base", "--is-ancestor", source_review, consumer], cwd=repo
    ).returncode == 1

    item = deployment_receipt(value)
    item.update({
        "governance_commit": baseline,
        "production_source_commit": production,
        "production_preparation_inventory": preparation_inventory,
        "reviewed_commit": source_review,
        "source_review": source_review_reference,
        "consumer_commit": consumer,
        "execution_commit": consumer,
    })
    item["bindings"]["candidate"]["source_commit"] = production

    campaign_payload = {
        "schema_version": value["campaign_evidence_schema_version"],
        "ticket_id": value["ticket_id"],
        "reviewed_source_commit": reviewed,
        "production_source_commit": production,
        "consumer_commit": consumer,
        "execution_commit": consumer,
        "business_outcome": "passed",
        "campaign": item["campaign"],
        "bindings": item["bindings"],
        "run_evidence": item["run_evidence"],
        "temporary_runtime": item["temporary_runtime"],
        "final_runtime": item["final_runtime"],
        "safety_flags": item["safety_flags"],
        "checks": item["checks"],
        "source_fingerprints": value["source_fingerprints"],
        "external_artifacts": {
            name: artifact_ref(name) for name in value["approved_external_artifact_names"]
        },
        "missing_external_artifacts": [],
    }
    subprocess.run(["git", "switch", "-c", "acceptance", consumer], cwd=repo, check=True)
    write(repo, value["campaign_evidence_path"], json.dumps(campaign_payload, sort_keys=True) + "\n")
    write(repo, value["review_report_paths"]["integration_review"], json.dumps(
        review_payload(phase="integration_review", decision="approved", consumer=consumer), sort_keys=True
    ) + "\n")
    write(repo, value["review_report_paths"]["deployment_acceptance"], json.dumps(
        review_payload(phase="deployment_acceptance", decision="approved", consumer=consumer), sort_keys=True
    ) + "\n")
    acceptance = commit(repo, "post-F acceptance A")
    item["campaign_evidence"] = {
        **reference(acceptance, value["campaign_evidence_path"]),
        "schema_version": value["campaign_evidence_schema_version"],
    }
    item["integration_review"] = reference(
        acceptance, value["review_report_paths"]["integration_review"]
    )
    item["acceptance"] = reference(
        acceptance, value["review_report_paths"]["deployment_acceptance"]
    )
    assert m.blockers(item, repo_root=repo) == []

    subprocess.run(["git", "switch", "-c", "bad-consumer", consumer], cwd=repo, check=True)
    write(repo, "quant_crypto/unreviewed_after_s.py", "late source\n")
    bad_consumer = commit(repo, "forbidden post-S source")
    with pytest.raises(ValueError, match="evidence_delta_not_allowed:quant_crypto/unreviewed_after_s.py"):
        m._only_evidence_delta(repo, production, bad_consumer, value)


def test_pre_run_campaign_branch_rejects_non_evidence_delta(tmp_path):
    m = module()
    repo = tmp_path / "blocked-campaign"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=repo, check=True)
    write(repo, "base.txt", "Q\n")
    source_review = commit(repo, "source review Q")
    write(repo, "quant_crypto/late.py", "not evidence\n")
    campaign = commit(repo, "invalid pre-run campaign")
    with pytest.raises(ValueError, match="evidence_delta_not_allowed:quant_crypto/late.py"):
        m._only_evidence_delta(repo, source_review, campaign, m.contract(ROOT))


def test_all_blocked_run_outcomes_still_obey_upper_bounds(monkeypatch):
    m = module()
    value = sealed_contract()
    monkeypatch.setattr(m, "_load_contract", lambda *args, **kwargs: value)
    monkeypatch.setattr(m, "_verify_receipt_evidence", lambda *args, **kwargs: None)
    item = deployment_receipt(value, "blocked_execution")
    item["run_evidence"]["official_run_count"] = 2
    item["run_evidence"]["decision_hours"] = 49
    item["run_evidence"]["settlement_events"] = 7
    problems = m.blockers(item, repo_root=ROOT)
    assert "official_run_count_out_of_bounds" in problems
    assert "decision_hours_out_of_bounds" in problems
    assert "settlement_events_out_of_bounds" in problems


@pytest.mark.parametrize(
    "path",
    [
        "quant_crypto/application/qlib_offline_replay.py",
        "backend/app/core/security/auth.py",
        "docs/agent_playbooks/delivery_risk_policy.json",
        "start-backend.cmd",
        ".codex/hooks.json",
        "../docs/escape.md",
        ".agent/handoffs/OTHER/event.json",
    ],
)
def test_only_ticket_governance_delta_is_allowed(path):
    assert not module().allowed_delta(path, module().contract(ROOT))
