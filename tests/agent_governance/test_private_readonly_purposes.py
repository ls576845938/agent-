"""Offline purpose isolation; fake signatures never grant a real capability."""
from datetime import datetime, timezone, timedelta
import hashlib
import subprocess
from pathlib import Path

import pytest

from tools.agent_governance import private_readonly_permission as p

NOW = datetime(2026, 9, 14, tzinfo=timezone.utc)
SESSION = "01a0506b-5a5b-7ed1-acb1-0b6ec8c83ea5"
TURN = "01a0506c-0000-7000-8000-000000000001"
PURPOSE = "okx_demo_account_facts_once"
ENTRY = "scripts/run_btc_account_facts_readonly.py"


@pytest.fixture
def harness(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    root = tmp_path / "receipts"
    monkeypatch.setattr(p, "_current_identity", lambda *a, **k: ("a" * 40, "b" * 40, "c" * 64))
    monkeypatch.setattr(p, "_require_main_checkout", lambda *a, **k: None)
    monkeypatch.setattr(p, "verify_external_signature", lambda *a, **k: p.SignatureVerification(True, "test_only"))
    return repo, root


def issue(harness, purpose=PURPOSE):
    repo, root = harness
    payload = p.build_unsigned_receipt(repo_root=repo, target_session_id=SESSION,
                                       ttl_seconds=300, now=NOW, purpose=purpose)
    path = root / "pending" / p._session_key(SESSION) / (payload["receipt_id"] + ".json")
    p._atomic_json(path, payload, exclusive=True)
    p._atomic_bytes(path.with_suffix(".sig"), b"test-only", exclusive=True)
    return payload


def arm(harness):
    repo, root = harness
    return p.resolve_capability(root=root, repo_root=repo, session_id=SESSION,
                                turn_id="", event_name="UserPromptSubmit", now=NOW, consume=True)


def command(harness, entry, suffix=""):
    repo, root = harness
    return p.authorize_runner_command(root=root, repo_root=repo, cwd=repo,
                                      session_id=SESSION, turn_id=TURN,
                                      command=f"py -3 {entry}{suffix}", now=NOW)


def process(harness, entry):
    repo, root = harness
    return p.authorize_runner_process(root=root, repo_root=repo, cwd=repo,
                                      environ={"CODEX_SESSION_ID": SESSION},
                                      runner_path=entry, now=NOW)


@pytest.mark.parametrize("hooked", [True, False])
def test_new_purpose_one_shot_cannot_start_observer(harness, hooked):
    payload = issue(harness)
    assert payload["purpose"] == PURPOSE
    assert payload["runner_path"] == ENTRY
    assert arm(harness).armed
    assert not command(harness, p.RUNNER_PATH).allowed
    assert not process(harness, p.RUNNER_PATH).allowed
    if hooked:
        assert command(harness, ENTRY).allowed
    result = process(harness, ENTRY)
    assert result.allowed
    assert result.purpose == PURPOSE
    assert result.runner_path == ENTRY
    assert "account-facts" in result.run_id
    assert process(harness, ENTRY).reason == "private_readonly_runner_start_replay"
    assert all(v is False for k, v in payload["permissions"].items() if k != "private")


def test_legacy_receipt_remains_observer_only(harness):
    payload = issue(harness, "btc_demo_observation")
    assert payload["schema_version"] == p.SCHEMA_VERSION
    assert "purpose" not in payload
    assert arm(harness).armed
    assert not command(harness, ENTRY).allowed
    assert not process(harness, ENTRY).allowed
    assert command(harness, p.RUNNER_PATH).allowed
    assert process(harness, p.RUNNER_PATH).allowed


@pytest.mark.parametrize("suffix", [" --once", "; echo bad", " ", " --allow-orders"])
def test_new_entry_still_requires_exact_zero_argument_command(harness, suffix):
    issue(harness)
    arm(harness)
    assert not command(harness, ENTRY, suffix).allowed
    assert command(harness, ENTRY).allowed


@pytest.mark.parametrize("field,value", [("purpose", "live"), ("runner_path", p.RUNNER_PATH),
                                        ("runner_path", "scripts/arbitrary.py"),
                                        ("schema_version", p.SCHEMA_VERSION)])
def test_recomputed_digest_cannot_change_purpose_mapping(harness, field, value):
    repo, root = harness
    payload = issue(harness)
    payload[field] = value
    payload["receipt_sha256"] = p.receipt_digest(payload)
    result = p._validate_receipt(payload, signature=b"test-only", root=root,
                                 repo_root=repo, session_id=SESSION, now=NOW)
    assert not result.granted


def test_unknown_purpose_never_builds_receipt(harness):
    with pytest.raises(p.PermissionErrorCode):
        issue(harness, "anything")


@pytest.mark.parametrize("mutation", ["session", "head", "blob", "sha", "expiry", "permissions", "signature"])
def test_new_purpose_preserves_all_receipt_guards(harness, monkeypatch, mutation):
    repo, root = harness
    payload = issue(harness)
    now = NOW
    if mutation == "session":
        payload["target_session_id"] = TURN
    elif mutation in {"head", "blob", "sha"}:
        field = {"head": "source_head", "blob": "runner_git_blob", "sha": "runner_sha256"}[mutation]
        payload[field] = "d" * len(payload[field])
    elif mutation == "expiry":
        now += timedelta(seconds=301)
    elif mutation == "permissions":
        payload["permissions"]["order"] = True
    else:
        monkeypatch.setattr(p, "verify_external_signature", lambda *a, **k: p.SignatureVerification(False, "bad_signature"))
    payload["receipt_sha256"] = p.receipt_digest(payload)
    assert not p._validate_receipt(payload, signature=b"fake", root=root, repo_root=repo,
                                    session_id=SESSION, now=now).granted


@pytest.mark.parametrize("claim_kind", ["binding", "launch"])
def test_new_scope_cannot_be_stripped_from_claim_even_with_rehashed_digest(harness, claim_kind):
    repo, root = harness
    payload = issue(harness)
    arm(harness)
    assert command(harness, ENTRY).allowed
    path = (p._binding_claim_path(root, SESSION) if claim_kind == "binding"
            else p._runner_launch_path(root, payload["receipt_id"]))
    claim = p._read_json(path)
    claim.pop("purpose")
    claim.pop("runner_path")
    claim.pop("claim_sha256")
    claim["claim_sha256"] = hashlib.sha256(p._canonical_bytes(claim)).hexdigest()
    p._atomic_json(path, claim)
    if claim_kind == "launch":
        assert not process(harness, ENTRY).allowed
    else:
        capability = p._active_capability_for_runner_session(root=root, repo_root=repo, session_id=SESSION, now=NOW)
        assert p._binding_claim_result(root=root, session_id=SESSION, turn_id=TURN,
                                        capability=capability).reason.endswith("capability_mismatch")


def test_new_entry_hook_allows_only_scoped_exact_launch_and_blocks_v2_forgery(harness, monkeypatch):
    from tests.agent_governance.agent_hook_loader import load_hook_module
    hook = load_hook_module(Path(__file__).resolve().parents[2] / ".codex/hooks/pre_tool_guard.py")
    repo, root = harness
    monkeypatch.setattr(hook, "REPO_ROOT", repo)
    assert hook.blocked_reason("btc_private_readonly_permission_receipt_v2", free_gb=100,
                               capability_root=root) == "private_readonly_receipt_store_is_operator_owned"
    issue(harness)
    arm(harness)
    kwargs = dict(free_gb=100, sparse_checkout=True, session_id=SESSION, turn_id=TURN,
                  capability_root=root, cwd=repo, tool_name="exec_command", now=NOW)
    assert hook.blocked_reason(p.CANONICAL_RUNNER_COMMAND, **kwargs) is not None
    assert hook.blocked_reason(f"py -3 {ENTRY}", **kwargs) is None
    assert hook.blocked_reason(f"py -3 {ENTRY}", **kwargs) == "private_readonly_runner_launch_replay"


def test_account_entry_absent_from_committed_repo_fails_closed(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    def git(*args):
        return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    git("init", "-b", "main")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-m", "fixture")
    with pytest.raises(p.PermissionErrorCode):
        p.build_unsigned_receipt(repo_root=repo, target_session_id=SESSION,
                                  ttl_seconds=300, purpose=PURPOSE, now=NOW)


def test_new_entry_identity_uses_actual_selected_committed_script(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    def git(*args):
        return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    git("init", "-b", "main")
    script = repo / ENTRY
    script.parent.mkdir()
    script.write_text("# inert governance fixture\n", encoding="utf-8")
    git("add", "--", ENTRY)
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "fixture")
    payload = p.build_unsigned_receipt(repo_root=repo, target_session_id=SESSION,
                                       ttl_seconds=300, purpose=PURPOSE, now=NOW)
    assert payload["runner_git_blob"] == git("rev-parse", f"main:{ENTRY}").stdout.decode().strip()
    assert payload["runner_sha256"] == hashlib.sha256(script.read_bytes()).hexdigest()
    script.write_text("# changed fixture\n", encoding="utf-8")
    with pytest.raises(p.PermissionErrorCode, match="worktree_mismatch"):
        p.build_unsigned_receipt(repo_root=repo, target_session_id=SESSION,
                                  ttl_seconds=300, purpose=PURPOSE, now=NOW)
