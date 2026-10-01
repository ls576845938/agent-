from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

from tools.agent_governance.handoff import handoff_template, write_handoff
from tools.agent_governance.team_context import (
    DOMAIN_READ_MODELS,
    _domain_next_action,
    _derive_demo_fastpath_state,
    _first_blocker_detail,
    build_team_context,
    render_team_context,
)
from quant_crypto.adapters.btc_runtime_artifact_store import (
    ENVIRONMENT_VARIABLE,
    OWNER_MARKER_NAME,
    build_btc_runtime_artifact_owner_marker,
    repository_identity_for_source,
)
from quant_crypto.adapters.btc_domain_read_model_repository import (
    BTCPublishedDomainReadModelRepository,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _repo_with_handoff(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "Tests")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-b", "agent/btc_developer/feature")
    deliverable_path = repo / "docs" / "btc-contract.md"
    deliverable_path.parent.mkdir()
    deliverable_path.write_text("contract\n", encoding="utf-8")
    _git(repo, "add", deliverable_path.relative_to(repo).as_posix())
    _git(repo, "commit", "-m", "btc contract")
    deliverable = _git(repo, "rev-parse", "HEAD")
    content = subprocess.run(
        ["git", "show", f"{deliverable}:docs/btc-contract.md"],
        cwd=repo,
        check=True,
        capture_output=True,
    ).stdout
    payload = handoff_template(
        event_id="btc-contract-ready",
        ticket_id="btc-contract-ticket",
        event_type="published",
        producer_role="btc_developer",
        consumer_roles=["a_share_developer", "super_developer", "architect"],
        domain="btc",
        producer_branch="agent/btc_developer/feature",
        base_commit=base,
        deliverable_commit=deliverable,
        deliverables=[
            {
                "type": "document",
                "path": "docs/btc-contract.md",
                "sha256": hashlib.sha256(content).hexdigest(),
                "schema_version": "btc_contract_v1",
                "readiness_class": "quality_checked",
            }
        ],
        tests=[{"command": "pytest contract", "result": "passed", "evidence_path": ""}],
        created_at="2026-07-12T00:00:00Z",
    )
    handoff_path = write_handoff(payload, repo_root=repo)
    _git(repo, "add", handoff_path.relative_to(repo).as_posix())
    _git(repo, "commit", "-m", "handoff")
    _git(repo, "checkout", "main")
    return repo


def test_team_context_discovers_other_branch_without_mutating_current_worktree(tmp_path: Path) -> None:
    repo = _repo_with_handoff(tmp_path)
    before = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    started = time.perf_counter()
    packet = build_team_context(
        repo_root=repo,
        consumer_role="super_developer",
        shared_data_root=tmp_path / "shared",
    )
    elapsed = time.perf_counter() - started
    after = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")

    assert before == after == ""
    assert elapsed < 2.0
    assert [item["event_id"] for item in packet["ready_upstreams"]] == ["btc-contract-ready"]
    assert packet["guardrails"]["read_only"] is True
    assert packet["guardrails"]["merge_or_commit_performed"] is False
    rendered = render_team_context(packet, max_chars=1200)
    assert "btc-contract-ready" in rendered
    assert len(rendered) <= 1200


def test_team_context_filters_unrelated_consumers(tmp_path: Path) -> None:
    repo = _repo_with_handoff(tmp_path)
    packet = build_team_context(
        repo_root=repo,
        consumer_role="data_steward",
        shared_data_root=tmp_path / "shared",
    )
    assert packet["ready_upstreams"] == []
    assert packet["blocked_dependencies"] == []


def test_team_context_prefers_btc_domain_read_model_and_fails_closed_when_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    assert DOMAIN_READ_MODELS["btc"][0] == Path(
        "artifacts/btc_domain_read_model/latest/btc_domain_read_model.json"
    )

    monkeypatch.delenv(ENVIRONMENT_VARIABLE, raising=False)
    repo = _repo_with_handoff(tmp_path)
    packet = build_team_context(
        repo_root=repo,
        consumer_role="architect",
        shared_data_root=tmp_path / "shared",
    )
    btc = next(
        row for row in packet["domain_read_models"] if row["domain"] == "btc"
    )

    assert btc["path"] == (
        "artifacts/btc_domain_read_model/latest/btc_domain_read_model.json"
    )
    assert btc["status"] == "unavailable"
    assert btc["freshness"] == "missing"
    assert btc["first_blocker"] == "runtime_artifact_root_unavailable"


def test_team_context_uses_external_btc_root_without_writes_or_local_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _repo_with_handoff(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    decoy = repo / DOMAIN_READ_MODELS["btc"][0]
    decoy.parent.mkdir(parents=True, exist_ok=True)
    decoy.write_text(
        json.dumps(
            {
                "status": "repo_local_decoy_must_not_be_read",
                "code_commit": head,
            }
        ),
        encoding="utf-8",
    )
    for domain in ("us_equity", "cn_equity"):
        path = repo / DOMAIN_READ_MODELS[domain][0]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "status": f"{domain}_unchanged",
                    "code_commit": head,
                    "gate": {"first_blocker": f"{domain}_blocker"},
                }
            ),
            encoding="utf-8",
        )

    artifact_root = tmp_path / "external-btc-runtime"
    artifact_root.mkdir()
    marker = build_btc_runtime_artifact_owner_marker(
        repository_identity_for_source(repo)
    )
    (artifact_root / OWNER_MARKER_NAME).write_text(
        json.dumps(marker, sort_keys=True),
        encoding="utf-8",
    )
    logical = DOMAIN_READ_MODELS["btc"][0]
    external = artifact_root.joinpath(*logical.parts[1:])
    external.parent.mkdir(parents=True, exist_ok=True)
    external.write_text(
        json.dumps(
            {
                "status": "external_btc_read_model",
                "freshness": "current_head",
                "code_commit": head,
                "source_head": head,
                "blockers": [
                    {
                        "code": "btc_external_blocker",
                        "category": "engineering",
                        "owner": "btc",
                        "next_executable_action": (
                            "resolve_engineering_blocker:"
                            "btc_external_blocker"
                        ),
                    }
                ],
                "gate": {
                    "owner": "btc",
                    "first_blocker": "btc_external_blocker",
                },
            }
        ),
        encoding="utf-8",
    )
    before = _file_inventory(artifact_root)
    monkeypatch.setenv(ENVIRONMENT_VARIABLE, str(artifact_root))
    monkeypatch.setattr(
        BTCPublishedDomainReadModelRepository,
        "read_published",
        lambda self, *, source_head: self.artifact_reader.read_json(logical),
    )

    packet = build_team_context(
        repo_root=repo,
        consumer_role="architect",
        shared_data_root=tmp_path / "shared",
    )

    by_domain = {
        row["domain"]: row for row in packet["domain_read_models"]
    }
    assert by_domain["btc"]["status"] == "external_btc_read_model"
    assert by_domain["btc"]["path"] == logical.as_posix()
    assert by_domain["btc"]["first_blocker"] == "btc_external_blocker"
    assert by_domain["btc"]["first_blocker_detail"] == {
        "code": "btc_external_blocker",
        "category": "engineering",
        "owner": "btc",
        "next_executable_action": (
            "resolve_engineering_blocker:btc_external_blocker"
        ),
    }
    assert by_domain["us_equity"]["status"] == "us_equity_unchanged"
    assert by_domain["cn_equity"]["status"] == "cn_equity_unchanged"
    assert str(artifact_root) not in json.dumps(packet)
    assert _file_inventory(artifact_root) == before


def test_team_context_ignores_repo_local_btc_decoy_when_root_is_relative(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _repo_with_handoff(tmp_path)
    decoy = repo / DOMAIN_READ_MODELS["btc"][0]
    decoy.parent.mkdir(parents=True, exist_ok=True)
    decoy.write_text(
        '{"status":"repo_local_decoy_must_not_be_read"}',
        encoding="utf-8",
    )
    monkeypatch.setenv(ENVIRONMENT_VARIABLE, "relative/runtime-artifacts")

    packet = build_team_context(
        repo_root=repo,
        consumer_role="architect",
        shared_data_root=tmp_path / "shared",
    )
    btc = next(
        row for row in packet["domain_read_models"] if row["domain"] == "btc"
    )

    assert btc["status"] == "unavailable"
    assert btc["first_blocker"] == "runtime_artifact_root_unavailable"
    assert "repo_local_decoy_must_not_be_read" not in json.dumps(packet)


def test_team_context_preserves_structured_blocker_and_fills_missing_action(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _repo_with_handoff(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    artifact_root = tmp_path / "external-btc-runtime"
    artifact_root.mkdir()
    marker = build_btc_runtime_artifact_owner_marker(
        repository_identity_for_source(repo)
    )
    (artifact_root / OWNER_MARKER_NAME).write_text(
        json.dumps(marker, sort_keys=True),
        encoding="utf-8",
    )
    monkeypatch.setenv(ENVIRONMENT_VARIABLE, str(artifact_root))
    monkeypatch.setattr(
        BTCPublishedDomainReadModelRepository,
        "read_published",
        lambda self, *, source_head: {
            "status": "blocked",
            "freshness": "current_head",
            "source_head": head,
            "code_commit": head,
            "blockers": [
                {
                    "code": "btc_okx_websocket_client_dependency_missing",
                    "category": "engineering",
                    "owner": "btc_developer",
                }
            ],
        },
    )

    packet = build_team_context(
        repo_root=repo,
        consumer_role="architect",
        shared_data_root=tmp_path / "shared",
    )
    btc = next(
        row for row in packet["domain_read_models"] if row["domain"] == "btc"
    )

    assert btc["first_blocker"] == (
        "btc_okx_websocket_client_dependency_missing"
    )
    assert btc["owner"] == "btc_developer"
    assert btc["next_action"] == (
        "resolve_engineering_blocker:"
        "btc_okx_websocket_client_dependency_missing"
    )
    assert btc["first_blocker_detail"] == {
        "code": "btc_okx_websocket_client_dependency_missing",
        "category": "engineering",
        "owner": "btc_developer",
        "next_executable_action": (
            "resolve_engineering_blocker:"
            "btc_okx_websocket_client_dependency_missing"
        ),
    }
    assert "{" not in btc["first_blocker"]


def test_missing_blocker_category_classifies_runtime_and_wait_states_without_engineering_action() -> None:
    cases = {
        "w32time_unsynchronized_leap3_stratum0": "runtime_clock",
        "okx_public_time_round_trip_and_offset_threshold_unstable": (
            "runtime_clock"
        ),
        "okx_public_dns_resolution_failed": "runtime_network",
        "okx_public_tls_handshake_failed": "runtime_network",
        "okx_public_ws_connection_reset_10054": "runtime_network",
        "1d_coverage_incomplete_waiting_for_observation": "natural_time",
        "manual_promotion_approval_missing": "manual_approval",
    }

    for code, expected_category in cases.items():
        blocker = _first_blocker_detail({"code": code})

        assert blocker["category"] == expected_category
        assert "engineering" not in blocker["next_executable_action"]
        assert "ticket" not in blocker["next_executable_action"]


def test_missing_blocker_category_keeps_explicit_dependency_defect_engineering() -> None:
    blocker = _first_blocker_detail(
        {
            "code": "btc_okx_websocket_client_dependency_missing",
            "owner": "btc_developer",
        }
    )

    assert blocker == {
        "code": "btc_okx_websocket_client_dependency_missing",
        "category": "engineering",
        "owner": "btc_developer",
        "next_executable_action": (
            "resolve_engineering_blocker:"
            "btc_okx_websocket_client_dependency_missing"
        ),
    }


def test_unknown_blocker_requires_triage_and_never_invents_engineering_scope() -> None:
    blocker = _first_blocker_detail({"code": "opaque_vendor_condition_xyz"})

    assert blocker == {
        "code": "opaque_vendor_condition_xyz",
        "category": "unclassified",
        "owner": "unassigned",
        "next_executable_action": (
            "triage_blocker_category_and_await_user_scope"
        ),
    }
    assert _domain_next_action(
        gate={"next_action": "create_engineering_ticket_for_unknown_blocker"},
        payload={},
        blocker=blocker,
    ) == "triage_blocker_category_and_await_user_scope"


def test_runtime_blocker_rejects_report_supplied_engineering_expansion() -> None:
    blocker = _first_blocker_detail(
        {
            "code": "okx_public_tls_connection_reset_10054",
            "next_executable_action": (
                "resolve_engineering_blocker:tls_runtime"
            ),
        }
    )

    assert blocker["next_executable_action"] == (
        "restore_runtime_connectivity_then_continue_existing_retry_"
        "keep_code_frozen"
    )
    assert _domain_next_action(
        gate={"next_action": "resolve_engineering_blocker:tls_runtime"},
        payload={"next_action": "rebuild_gate_after_network_failure"},
        blocker=blocker,
    ) == (
        "restore_runtime_connectivity_then_continue_existing_retry_"
        "keep_code_frozen"
    )


def test_team_context_registers_us_and_cn_current_head_read_model_candidates() -> None:
    assert DOMAIN_READ_MODELS["us_equity"][0] == Path(
        "artifacts/us_equity_strategy_production_line/latest/"
        "us_equity_operator_read_model.json"
    )
    assert DOMAIN_READ_MODELS["cn_equity"][0] == Path(
        "artifacts/cn_equity_operator_read_model/latest/"
        "cn_equity_operator_read_model.json"
    )


def test_a_share_consumer_discovers_targeted_handoff(tmp_path: Path) -> None:
    repo = _repo_with_handoff(tmp_path)
    packet = build_team_context(
        repo_root=repo,
        consumer_role="a_share_developer",
        shared_data_root=tmp_path / "shared",
    )

    assert [item["event_id"] for item in packet["ready_upstreams"]] == ["btc-contract-ready"]
    assert packet["consumer_role"] == "a_share_developer"


def test_integrated_delivery_remains_visible_as_available(tmp_path: Path) -> None:
    repo = _repo_with_handoff(tmp_path)
    _git(repo, "checkout", "-b", "agent/integrator/feature")
    head = _git(repo, "rev-parse", "HEAD")
    payload = handoff_template(
        event_id="btc-contract-integrated",
        ticket_id="btc-contract-ticket",
        event_type="integrated",
        producer_role="integrator",
        consumer_roles=["architect", "btc_developer"],
        domain="btc",
        producer_branch="agent/integrator/feature",
        base_commit=head,
        deliverable_commit=head,
        deliverables=[],
        tests=[{"command": "pytest contract", "result": "passed", "evidence_path": ""}],
        transition_for="btc-contract-ready",
        created_at="2026-07-12T01:00:00Z",
    )
    path = write_handoff(payload, repo_root=repo)
    _git(repo, "add", path.relative_to(repo).as_posix())
    _git(repo, "commit", "-m", "integrate handoff")
    _git(repo, "checkout", "main")

    packet = build_team_context(
        repo_root=repo,
        consumer_role="architect",
        shared_data_root=tmp_path / "shared",
    )
    assert packet["ready_upstreams"] == []
    assert [item["event_id"] for item in packet["available_deliveries"]] == ["btc-contract-ready"]
    assert packet["available_deliveries"][0]["state"] == "integrated"


def test_demo_transport_context_uses_gate_none_fastpath_without_promotion_noise(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _repo_with_handoff(tmp_path)
    deliverable = _git(
        repo, "rev-parse", "agent/btc_developer/feature^"
    )
    _git(repo, "merge", "--ff-only", deliverable)
    monkeypatch.delenv(ENVIRONMENT_VARIABLE, raising=False)

    packet = build_team_context(
        repo_root=repo,
        consumer_role="super_developer",
        change_risk="demo_transport_hotfix",
        shared_data_root=tmp_path / "shared",
    )

    assert packet["change_risk"] == "demo_transport_hotfix"
    assert packet["ready_upstreams"] == []
    assert packet["blocked_dependencies"] == []
    assert packet["domain_read_models"] == []
    assert packet["available_deliveries"][0]["state"] == (
        "integrated_fastpath"
    )
    rendered = render_team_context(packet)
    assert "legacy promotion blockers" in rendered
    assert "domain_read_models:" not in rendered


def test_demo_fastpath_only_removes_delivery_and_promotion_rebuild_noise(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "Tests")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    head = _git(repo, "rev-parse", "HEAD")
    record = {
        "state": "published",
        "state_event_id": "demo-tail",
        "event": {
            "event_id": "demo-tail",
            "deliverable_commit": head,
            "gate_impact": "none",
            "promotion_eligible": False,
            "blockers": [
                "owner:integrator deliverable_commit_not_integrated_to_refs_heads_main",
                "owner:integrator promotion_artifact_rebuild_pending",
                "demo_safety_attestation_missing",
            ],
        },
    }

    _derive_demo_fastpath_state(
        record,
        repo_root=repo,
        current_head=head,
    )

    assert record["state"] == "integrated_fastpath"
    assert record["event"]["blockers"] == [
        "demo_safety_attestation_missing"
    ]


def test_team_context_cli_runs_as_a_direct_script() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "agent_governance" / "team_context.py"),
            "--repo-root",
            str(REPO_ROOT),
            "--role",
            "architect",
            "--format",
            "json",
            "--max-events",
            "1",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "agent_team_context_v1"
    assert payload["guardrails"]["read_only"] is True
    # The registered repository may contain committed malformed handoffs.
    # The direct CLI must expose that condition as unavailable (exit 2), not
    # silently turn it into an empty successful context.
    assert result.returncode in {0, 2}
    if result.returncode == 2:
        assert (
            payload.get("status") == "unavailable"
            or payload.get("invalid_handoffs")
        )


def _file_inventory(root: Path) -> tuple[tuple[str, str], ...]:
    return tuple(
        (
            path.relative_to(root).as_posix(),
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    )
