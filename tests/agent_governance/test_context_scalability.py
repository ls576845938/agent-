from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

import tools.agent_governance.handoff as handoff_module
from tools.agent_governance.handoff import HandoffError, _parse_git_tree, handoff_template, scan_handoffs, write_handoff
from tools.agent_governance.team_context import render_team_context


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def test_discovery_400_refs_uses_fixed_git_batches_and_one_blob_materialization(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "Tests")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-b", "agent/data_steward/feature")
    manifest = b'{"schema_version":"fixture_manifest_v1"}\n'
    manifest_path = repo / ".agent" / "data_manifests" / "fixture.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_bytes(manifest)
    _git(repo, "add", manifest_path.relative_to(repo).as_posix())
    _git(repo, "commit", "-m", "manifest")
    deliverable = _git(repo, "rev-parse", "HEAD")
    payload = handoff_template(
        event_id="scale-shared-001",
        ticket_id="scale-ticket-001",
        event_type="published",
        producer_role="data_steward",
        consumer_roles=["super_developer"],
        domain="data",
        producer_branch="agent/data_steward/feature",
        base_commit=base,
        deliverable_commit=deliverable,
        deliverables=[
            {
                "type": "document",
                "path": ".agent/data_manifests/fixture.json",
                "sha256": hashlib.sha256(manifest).hexdigest(),
                "schema_version": "fixture_manifest_v1",
                "readiness_class": "research_ready",
            }
        ],
        tests=[{"command": "pytest", "result": "passed", "evidence_path": ""}],
        gate_impact="evidence_only",
        created_at="2026-07-12T00:00:00Z",
    )
    event_path = write_handoff(payload, repo_root=repo)
    _git(repo, "add", event_path.relative_to(repo).as_posix())
    _git(repo, "commit", "-m", "handoff")
    shared_head = _git(repo, "rev-parse", "HEAD")
    before_hash = hashlib.sha256(
        subprocess.run(
            ["git", "show", f"{shared_head}:{event_path.relative_to(repo).as_posix()}"],
            cwd=repo,
            check=True,
            capture_output=True,
        ).stdout
    ).hexdigest()
    _git(repo, "checkout", "main")
    for index in range(400):
        _git(repo, "branch", f"agent/data_steward/copy-{index:03d}", shared_head)

    calls: list[tuple[str, ...]] = []
    original_run_git = handoff_module._run_git
    original_batch_objects = handoff_module._git_batch_objects
    blob_batches: list[tuple[str, ...]] = []

    def spy_run_git(repo_root: Path, *args: str, **kwargs):
        calls.append(args)
        return original_run_git(repo_root, *args, **kwargs)

    def spy_batch_objects(repo_root: Path, object_ids: list[str], *, deadline: float):
        blob_batches.append(tuple(object_ids))
        return original_batch_objects(repo_root, object_ids, deadline=deadline)

    monkeypatch.setattr(handoff_module, "_run_git", spy_run_git)
    monkeypatch.setattr(handoff_module, "_git_batch_objects", spy_batch_objects)
    scan = scan_handoffs(repo, verify_git=False)

    assert not scan["invalid"]
    assert len(scan["refs"]) == 401
    assert scan["events"][0]["observed_refs"] == sorted(scan["refs"])
    assert len(blob_batches) == 1
    assert len(blob_batches[0]) == 1
    assert len(calls) == 4
    assert calls[0][:2] == ("for-each-ref", "--merged=refs/heads/main")
    assert all(args[:2] == ("cat-file", "--batch") for args in calls[1:])
    assert hashlib.sha256(
        subprocess.run(
            ["git", "show", f"{shared_head}:{event_path.relative_to(repo).as_posix()}"],
            cwd=repo,
            check=True,
            capture_output=True,
        ).stdout
    ).hexdigest() == before_hash


def test_active_team_projection_omits_terminal_and_branch_history() -> None:
    packet = {
        "schema_version": "agent_team_context_v1",
        "projection": "active",
        "current_branch": "main",
        "current_head": "a" * 40,
        "consumer_role": "super_developer",
        "change_risk": "governance_control",
        "handoff_verification_mode": "discovery_only",
        "branches": [{"branch": "agent/old", "head": "b" * 40, "ahead_main": -1, "behind_main": -1}],
        "ready_upstreams": [],
        "available_deliveries": [],
        "blocked_dependencies": [],
        "integration_candidates": [],
        "terminal_handoffs": [{"event_id": "old", "ticket_id": "old", "producer_role": "data_steward", "state": "superseded", "readiness_classes": [], "blockers": []}],
        "invalid_handoffs": [{"path": "bad.json"}],
        "domain_read_models": [],
    }
    rendered = render_team_context(packet, active_only=True)
    assert "branch_heads:" not in rendered
    assert "terminal:" not in rendered
    assert "invalid_handoffs: 1" in rendered


def _tree_entry(mode: str, name: str, object_id: str = "0" * 40) -> bytes:
    return f"{mode} {name}\0".encode("ascii") + bytes.fromhex(object_id)


def test_git_tree_parser_accepts_canonical_tree_and_blob_modes() -> None:
    parsed = _parse_git_tree(
        _tree_entry("40000", "ticket") + _tree_entry("100644", "event.json")
    )
    assert [item[0] for item in parsed] == ["40000", "100644"]


@pytest.mark.parametrize("mode", ["99999", "120000", "160000"])
def test_git_tree_parser_rejects_noncanonical_modes(mode: str) -> None:
    with pytest.raises(HandoffError, match="handoff_git_tree_mode_invalid"):
        _parse_git_tree(_tree_entry(mode, "event.json"))
