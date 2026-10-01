from __future__ import annotations

import json
import hashlib
import subprocess
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tools.agent_governance import private_readonly_permission as permission


REPO_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 8, 30, 2, 0, tzinfo=timezone.utc)
SESSION = "01a0506b-5a5b-7ed1-acb1-0b6ec8c83ea5"
TURN = "01a0506c-0000-7000-8000-000000000001"
REAL_VERIFY_EXTERNAL_SIGNATURE = permission.verify_external_signature
TEST_IDENTITY = (
    "a" * 40,
    "b" * 40,
    hashlib.sha256((REPO_ROOT / permission.RUNNER_PATH).read_bytes()).hexdigest(),
)


@pytest.fixture(autouse=True)
def _stub_operator_signature_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    """Behaviour tests use a test-only verifier; production has no private signer."""
    monkeypatch.setattr(
        permission,
        "_current_identity",
        lambda _repo_root: TEST_IDENTITY,
    )
    monkeypatch.setattr(
        permission,
        "verify_external_signature",
        lambda payload, signature, *, repo_root: permission.SignatureVerification(
            True, "private_readonly_signature_verified"
        ),
    )


def _issue(root: Path, *, session_id: str = SESSION, ttl_seconds: int = 300):
    payload = permission.build_unsigned_receipt(
        repo_root=REPO_ROOT,
        target_session_id=session_id,
        ttl_seconds=ttl_seconds,
        now=NOW,
    )
    pending = root / "pending" / permission._session_key(session_id)
    path = pending / f"{payload['receipt_id']}.json"
    signature_path = path.with_suffix(".sig")
    permission._atomic_json(path, payload, exclusive=True)
    permission._atomic_bytes(signature_path, b"test-only-external-signature", exclusive=True)
    return permission.ReceiptReference(
        receipt_id=str(payload["receipt_id"]),
        path=path,
        source_head=str(payload["source_head"]),
        runner_git_blob=str(payload["runner_git_blob"]),
        runner_sha256=str(payload["runner_sha256"]),
        expires_at=str(payload["expires_at"]),
        signature_path=signature_path,
    )


def _activate(root: Path, *, session_id: str = SESSION, turn_id: str = TURN):
    armed = permission.resolve_capability(
        root=root,
        repo_root=REPO_ROOT,
        session_id=session_id,
        turn_id="",
        event_name="UserPromptSubmit",
        now=NOW + timedelta(seconds=1),
        consume=True,
    )
    if not armed.armed:
        return armed
    return permission._bind_armed_capability(
        root=root,
        repo_root=REPO_ROOT,
        session_id=session_id,
        turn_id=turn_id,
        cwd=REPO_ROOT,
        command=_runner_command(armed.receipt_id, armed.source_head),
        now=NOW + timedelta(seconds=1),
    )


def _runner_command(receipt_id: str, source_head: str) -> str:
    del receipt_id, source_head
    return "py -3 scripts/run_btc_demo_private_readonly_observation.py"


def _cross_process_runner_claim(root_text: str) -> tuple[bool, str]:
    root = Path(root_text)
    permission.verify_external_signature = (
        lambda payload, signature, *, repo_root: permission.SignatureVerification(
            True, "private_readonly_signature_verified"
        )
    )
    permission._current_identity = lambda _repo_root: TEST_IDENTITY
    permission._require_main_checkout = lambda _repo_root: None
    result = permission.authorize_runner_process(
        root=root,
        repo_root=REPO_ROOT,
        cwd=REPO_ROOT,
        environ={"CODEX_SESSION_ID": SESSION},
        now=NOW + timedelta(seconds=1),
    )
    return result.allowed, result.reason


def test_runner_process_docstring_matches_signed_session_identity_contract() -> None:
    docstring = " ".join(
        (permission.authorize_runner_process.__doc__ or "").split()
    )

    assert "signed receipt target_session_id to match CODEX_SESSION_ID" in docstring
    assert "CODEX_THREAD_ID and THREAD_ID are not authorization identities" in docstring
    assert "two matching process identity variables" not in docstring


def test_runner_process_self_authorization_closes_unhooked_command_channel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _issue(tmp_path)
    monkeypatch.setattr(permission, "_require_main_checkout", lambda _root: None)
    permission.resolve_capability(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id="",
        event_name="UserPromptSubmit",
        now=NOW + timedelta(milliseconds=500),
        consume=True,
    )
    environment = {
        "CODEX_SESSION_ID": SESSION,
        "CODEX_THREAD_ID": "01a0506b-5a5b-7ed1-acb1-reviewer0001",
    }

    first = permission.authorize_runner_process(
        root=tmp_path,
        repo_root=REPO_ROOT,
        cwd=REPO_ROOT,
        environ=environment,
        now=NOW + timedelta(seconds=1),
    )
    replay = permission.authorize_runner_process(
        root=tmp_path,
        repo_root=REPO_ROOT,
        cwd=REPO_ROOT,
        environ=environment,
        now=NOW + timedelta(seconds=2),
    )

    assert first.allowed is True
    assert first.receipt_id == receipt.receipt_id
    assert first.source_head == receipt.source_head
    assert first.runtime_root.is_absolute()
    assert first.runtime_root.parent == REPO_ROOT.parent
    assert first.run_id
    assert len(first.authorization_ticket_hash) == 64
    assert replay.allowed is False
    assert replay.reason == "private_readonly_runner_start_replay"


@pytest.mark.parametrize(
    "environment,reason",
    [
        ({}, "private_readonly_process_session_id_missing"),
        (
            {"CODEX_SESSION_ID": "bad"},
            "private_readonly_process_identity_invalid",
        ),
    ],
)
def test_runner_process_rejects_missing_or_mismatched_identity_before_receipt_use(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    environment: dict[str, str],
    reason: str,
) -> None:
    monkeypatch.setattr(
        permission,
        "_require_main_checkout",
        lambda _root: pytest.fail("main checkout must not be inspected first"),
    )

    result = permission.authorize_runner_process(
        root=tmp_path,
        repo_root=REPO_ROOT,
        cwd=REPO_ROOT,
        environ=environment,
        now=NOW,
    )

    assert result.allowed is False
    assert result.reason == reason


def test_hook_reservation_and_runner_process_start_are_distinct_one_time_claims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _issue(tmp_path)
    armed = permission.resolve_capability(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id="",
        event_name="UserPromptSubmit",
        now=NOW + timedelta(milliseconds=500),
        consume=True,
    )
    command = _runner_command(receipt.receipt_id, receipt.source_head)
    hook = permission.authorize_runner_command(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id=TURN,
        cwd=REPO_ROOT,
        command=command,
        now=NOW + timedelta(seconds=1),
    )
    monkeypatch.setattr(permission, "_require_main_checkout", lambda _root: None)

    process = permission.authorize_runner_process(
        root=tmp_path,
        repo_root=REPO_ROOT,
        cwd=REPO_ROOT,
        environ={"CODEX_SESSION_ID": SESSION, "CODEX_THREAD_ID": SESSION},
        now=NOW + timedelta(seconds=2),
    )

    assert armed.reason == "private_readonly_capability_armed"
    assert hook.allowed is True
    assert process.allowed is True
    launch = json.loads(
        (tmp_path / "launches" / f"{receipt.receipt_id}.json").read_text(
            encoding="utf-8"
        )
    )
    start = json.loads(
        (tmp_path / "runner_starts" / f"{receipt.receipt_id}.json").read_text(
            encoding="utf-8"
        )
    )
    assert launch["claim_channel"] == "pretool_hook"
    assert launch["turn_hash"] == permission._session_key(TURN)
    assert start["launch_claim_sha256"] == launch["claim_sha256"]


def test_runner_process_rejects_incomplete_hook_binding_before_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _issue(tmp_path)
    armed = permission.resolve_capability(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id="",
        event_name="UserPromptSubmit",
        now=NOW + timedelta(milliseconds=500),
        consume=True,
    )
    binding = permission._claim_binding_for_exact_runner(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id=TURN,
        cwd=REPO_ROOT,
        command=_runner_command(receipt.receipt_id, receipt.source_head),
        capability=armed,
        now=NOW + timedelta(seconds=1),
    )
    monkeypatch.setattr(permission, "_require_main_checkout", lambda _root: None)

    result = permission.authorize_runner_process(
        root=tmp_path,
        repo_root=REPO_ROOT,
        cwd=REPO_ROOT,
        environ={"CODEX_SESSION_ID": SESSION},
        now=NOW + timedelta(seconds=2),
    )

    assert binding.reason == "private_readonly_binding_claimed"
    assert result.allowed is False
    assert result.reason == "private_readonly_binding_claim_arm_unavailable"
    assert not (tmp_path / "launches" / f"{receipt.receipt_id}.json").exists()
    assert not (tmp_path / "runner_starts" / f"{receipt.receipt_id}.json").exists()


def test_concurrent_runner_processes_have_exactly_one_start_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _issue(tmp_path)
    permission.resolve_capability(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id="",
        event_name="UserPromptSubmit",
        now=NOW + timedelta(milliseconds=500),
        consume=True,
    )
    monkeypatch.setattr(permission, "_require_main_checkout", lambda _root: None)
    environment = {"CODEX_SESSION_ID": SESSION, "CODEX_THREAD_ID": SESSION}

    def claim(_index: int):
        return permission.authorize_runner_process(
            root=tmp_path,
            repo_root=REPO_ROOT,
            cwd=REPO_ROOT,
            environ=environment,
            now=NOW + timedelta(seconds=1),
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(claim, range(32)))

    assert sum(result.allowed for result in results) == 1
    assert len(list((tmp_path / "runner_starts").glob("*.json"))) == 1
    assert {result.reason for result in results if not result.allowed} == {
        "private_readonly_runner_start_replay"
    }


def test_cross_process_runner_start_claim_has_exactly_one_winner(
    tmp_path: Path,
) -> None:
    _issue(tmp_path)
    permission.resolve_capability(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id="",
        event_name="UserPromptSubmit",
        now=NOW + timedelta(milliseconds=500),
        consume=True,
    )

    with ProcessPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(_cross_process_runner_claim, [str(tmp_path)] * 16)
        )

    assert sum(allowed for allowed, _reason in results) == 1
    assert len(list((tmp_path / "runner_starts").glob("*.json"))) == 1
    assert {reason for allowed, reason in results if not allowed} == {
        "private_readonly_runner_start_replay"
    }


def test_runner_process_revalidates_revocation_and_current_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _issue(tmp_path)
    permission.resolve_capability(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id="",
        event_name="UserPromptSubmit",
        now=NOW + timedelta(seconds=1),
        consume=True,
    )
    monkeypatch.setattr(permission, "_require_main_checkout", lambda _root: None)
    environment = {"CODEX_SESSION_ID": SESSION}

    permission.revoke_receipt(
        root=tmp_path,
        receipt_id=receipt.receipt_id,
        now=NOW + timedelta(seconds=2),
    )
    revoked = permission.authorize_runner_process(
        root=tmp_path,
        repo_root=REPO_ROOT,
        cwd=REPO_ROOT,
        environ=environment,
        now=NOW + timedelta(seconds=3),
    )
    assert revoked.reason == "private_readonly_receipt_revoked"

    other_root = tmp_path / "other"
    _issue(other_root)
    permission.resolve_capability(
        root=other_root,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id="",
        event_name="UserPromptSubmit",
        now=NOW + timedelta(seconds=1),
        consume=True,
    )
    monkeypatch.setattr(
        permission,
        "_current_identity",
        lambda _repo_root: ("f" * 40, TEST_IDENTITY[1], TEST_IDENTITY[2]),
    )
    wrong_head = permission.authorize_runner_process(
        root=other_root,
        repo_root=REPO_ROOT,
        cwd=REPO_ROOT,
        environ=environment,
        now=NOW + timedelta(seconds=3),
    )
    assert wrong_head.reason == "private_readonly_source_head_mismatch"


def test_runner_process_rejects_wrong_cwd_multiple_receipts_and_tampered_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(permission, "_require_main_checkout", lambda _root: None)
    wrong_cwd = permission.authorize_runner_process(
        root=tmp_path,
        repo_root=REPO_ROOT,
        cwd=tmp_path,
        environ={"CODEX_SESSION_ID": SESSION},
        now=NOW,
    )
    assert wrong_cwd.reason == "private_readonly_registered_main_cwd_required"

    _issue(tmp_path)
    _issue(tmp_path)
    ambiguous = permission.resolve_capability(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id="",
        event_name="UserPromptSubmit",
        now=NOW + timedelta(seconds=1),
        consume=True,
    )
    blocked = permission.authorize_runner_process(
        root=tmp_path,
        repo_root=REPO_ROOT,
        cwd=REPO_ROOT,
        environ={"CODEX_SESSION_ID": SESSION},
        now=NOW + timedelta(seconds=2),
    )
    assert ambiguous.reason == "private_readonly_receipt_ambiguous"
    assert blocked.allowed is False

    clean_root = tmp_path / "tampered"
    receipt = _issue(clean_root)
    permission.resolve_capability(
        root=clean_root,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id="",
        event_name="UserPromptSubmit",
        now=NOW + timedelta(seconds=1),
        consume=True,
    )
    capability = permission._capability_for_runner_process(
        root=clean_root,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        now=NOW + timedelta(seconds=2),
    )
    launch = permission._build_runner_launch_claim(
        capability=capability,
        session_id=SESSION,
        claim_channel="runner_self",
        turn_hash="",
        now=NOW + timedelta(seconds=2),
    )
    launch["source_head"] = "f" * 40
    permission._atomic_json(
        clean_root / "launches" / f"{receipt.receipt_id}.json",
        launch,
        exclusive=True,
    )
    tampered = permission.authorize_runner_process(
        root=clean_root,
        repo_root=REPO_ROOT,
        cwd=REPO_ROOT,
        environ={"CODEX_SESSION_ID": SESSION},
        now=NOW + timedelta(seconds=3),
    )
    assert tampered.reason == "private_readonly_runner_launch_digest_invalid"


def test_receipt_issued_in_future_is_not_valid() -> None:
    payload = permission.build_unsigned_receipt(
        repo_root=REPO_ROOT,
        target_session_id=SESSION,
        ttl_seconds=300,
        now=NOW + timedelta(seconds=10),
    )
    result = permission._validate_receipt(
        payload,
        signature=b"test-only-external-signature",
        root=Path("unused-test-root"),
        repo_root=REPO_ROOT,
        session_id=SESSION,
        now=NOW,
    )

    assert result.reason == "private_readonly_receipt_not_yet_valid"


def test_default_deny_for_missing_or_wrong_session(tmp_path: Path) -> None:
    missing = permission.resolve_capability(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id="",
        turn_id=TURN,
        event_name="UserPromptSubmit",
        now=NOW,
        consume=True,
    )
    assert missing.granted is False
    assert missing.reason == "private_readonly_session_id_missing"

    _issue(tmp_path)
    wrong = permission.resolve_capability(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id="01a0506b-5a5b-7ed1-acb1-ffffffffffff",
        turn_id=TURN,
        event_name="UserPromptSubmit",
        now=NOW + timedelta(seconds=1),
        consume=True,
    )
    assert wrong.granted is False
    assert wrong.reason == "private_readonly_receipt_missing"


def test_prompt_keywords_never_authorize_without_receipt(tmp_path: Path) -> None:
    result = permission.resolve_capability(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id=TURN,
        event_name="UserPromptSubmit",
        now=NOW,
        consume=True,
    )
    assert result.granted is False


def test_user_prompt_without_turn_id_arms_but_does_not_bind_receipt(
    tmp_path: Path,
) -> None:
    _issue(tmp_path)
    result = permission.resolve_capability(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id="",
        event_name="UserPromptSubmit",
        now=NOW + timedelta(seconds=1),
        consume=True,
    )

    assert result.granted is False
    assert result.armed is True
    assert result.reason == "private_readonly_capability_armed"
    assert not permission._lease_path(tmp_path, SESSION).exists()


def test_next_user_prompt_interrupts_unbound_arm_without_rearming(
    tmp_path: Path,
) -> None:
    receipt = _issue(tmp_path)
    first = permission.resolve_capability(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id="",
        event_name="UserPromptSubmit",
        now=NOW + timedelta(seconds=1),
        consume=True,
    )
    second = permission.resolve_capability(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id="",
        event_name="UserPromptSubmit",
        now=NOW + timedelta(seconds=2),
        consume=True,
    )
    launch = permission.authorize_runner_command(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id=TURN,
        cwd=REPO_ROOT,
        command=_runner_command(receipt.receipt_id, receipt.source_head),
        now=NOW + timedelta(seconds=3),
    )

    assert first.armed is True
    assert second.granted is False
    assert second.armed is False
    assert second.reason == "private_readonly_armed_attempt_interrupted"
    assert launch.allowed is False
    assert launch.reason == "private_readonly_armed_attempt_missing"
    assert not permission._lease_path(tmp_path, SESSION).exists()


def test_armed_pretool_denies_non_runner_and_invalid_turn_without_binding(
    tmp_path: Path,
) -> None:
    from tests.agent_governance.agent_hook_loader import load_hook_module

    guard = load_hook_module(REPO_ROOT / ".codex" / "hooks" / "pre_tool_guard.py")
    _issue(tmp_path)
    result = permission.resolve_capability(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id="",
        event_name="UserPromptSubmit",
        now=NOW + timedelta(seconds=1),
        consume=True,
    )

    assert result.armed is True
    assert guard.blocked_reason(
        "rg -n safe AGENTS.md",
        session_id=SESSION,
        turn_id=TURN,
        capability_root=tmp_path,
        cwd=REPO_ROOT,
        tool_name="exec_command",
        now=NOW + timedelta(seconds=2),
    ) == "private_readonly_armed_non_runner_tool_denied"
    assert guard.blocked_reason(
        "rg -n safe AGENTS.md",
        session_id=SESSION,
        turn_id="",
        capability_root=tmp_path,
        cwd=REPO_ROOT,
        tool_name="exec_command",
        now=NOW + timedelta(seconds=2),
    ) == "private_readonly_turn_id_invalid"
    assert not permission._lease_path(tmp_path, SESSION).exists()


def test_invalid_runner_shape_does_not_bind_armed_receipt(tmp_path: Path) -> None:
    receipt = _issue(tmp_path)
    permission.resolve_capability(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id="",
        event_name="UserPromptSubmit",
        now=NOW + timedelta(seconds=1),
        consume=True,
    )
    invalid = permission.authorize_runner_command(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id=TURN,
        cwd=REPO_ROOT,
        command=_runner_command(receipt.receipt_id, receipt.source_head) + " --once",
        now=NOW + timedelta(seconds=2),
    )

    assert invalid.allowed is False
    assert invalid.reason == "private_readonly_runner_argument_invalid"
    assert not permission._lease_path(tmp_path, SESSION).exists()


def test_concurrent_exact_runner_claim_binds_only_one_turn(tmp_path: Path) -> None:
    receipt = _issue(tmp_path)
    permission.resolve_capability(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id="",
        event_name="UserPromptSubmit",
        now=NOW + timedelta(seconds=1),
        consume=True,
    )
    command = _runner_command(receipt.receipt_id, receipt.source_head)
    turns = (
        "01a0506c-0000-7000-8000-000000000011",
        "01a0506c-0000-7000-8000-000000000012",
    )

    def claim(turn_id: str):
        return permission.authorize_runner_command(
            root=tmp_path,
            repo_root=REPO_ROOT,
            session_id=SESSION,
            turn_id=turn_id,
            cwd=REPO_ROOT,
            command=command,
            now=NOW + timedelta(seconds=2),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, turns))

    assert sum(result.allowed for result in results) == 1
    assert {result.reason for result in results} <= {
        "private_readonly_runner_launch_authorized",
        "private_readonly_capability_bound_to_other_turn",
    }


def test_session_claim_concurrency_is_stable_for_100_trials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = permission._current_identity(REPO_ROOT)
    monkeypatch.setattr(permission, "_current_identity", lambda repo_root: identity)
    expected_reasons = {
        "private_readonly_runner_launch_authorized",
        "private_readonly_capability_bound_to_other_turn",
    }

    for iteration in range(100):
        root = tmp_path / f"trial-{iteration:03d}"
        receipt = _issue(root)
        armed = permission.resolve_capability(
            root=root,
            repo_root=REPO_ROOT,
            session_id=SESSION,
            turn_id="",
            event_name="UserPromptSubmit",
            now=NOW + timedelta(seconds=1),
            consume=True,
        )
        assert armed.reason == "private_readonly_capability_armed"
        command = _runner_command(receipt.receipt_id, receipt.source_head)
        turns = (
            f"01a0506c-0000-7000-8000-{iteration:012d}",
            f"01a0506d-0000-7000-8000-{iteration:012d}",
        )

        def claim(turn_id: str):
            return permission.authorize_runner_command(
                root=root,
                repo_root=REPO_ROOT,
                session_id=SESSION,
                turn_id=turn_id,
                cwd=REPO_ROOT,
                command=command,
                now=NOW + timedelta(seconds=2),
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, turns))

        assert sum(result.allowed for result in results) == 1, iteration
        assert {result.reason for result in results} == expected_reasons, iteration


def test_session_scoped_binding_claim_stabilizes_loser_and_same_turn_recovery(
    tmp_path: Path,
) -> None:
    from tests.agent_governance.agent_hook_loader import load_hook_module

    guard = load_hook_module(REPO_ROOT / ".codex" / "hooks" / "pre_tool_guard.py")
    receipt = _issue(tmp_path)
    armed = permission.resolve_capability(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id="",
        event_name="UserPromptSubmit",
        now=NOW + timedelta(seconds=1),
        consume=True,
    )
    command = _runner_command(receipt.receipt_id, receipt.source_head)

    invalid = permission._claim_binding_for_exact_runner(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id=TURN,
        cwd=REPO_ROOT,
        command=command + " --once",
        capability=armed,
        now=NOW + timedelta(seconds=2),
    )
    assert invalid.reason == "private_readonly_runner_argument_invalid"
    assert not permission._binding_claim_path(tmp_path, SESSION).exists()

    winner = permission._claim_binding_for_exact_runner(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id=TURN,
        cwd=REPO_ROOT,
        command=command,
        capability=armed,
        now=NOW + timedelta(seconds=2),
    )
    interrupted = permission.resolve_capability(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id="",
        event_name="UserPromptSubmit",
        now=NOW + timedelta(seconds=3),
        consume=True,
    )
    non_runner = guard.blocked_reason(
        "rg -n safe AGENTS.md",
        session_id=SESSION,
        turn_id="01a0506c-0000-7000-8000-000000000099",
        capability_root=tmp_path,
        cwd=REPO_ROOT,
        tool_name="exec_command",
        now=NOW + timedelta(seconds=3),
    )
    loser = permission._claim_binding_for_exact_runner(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id="01a0506c-0000-7000-8000-000000000099",
        cwd=REPO_ROOT,
        command=command,
        capability=armed,
        now=NOW + timedelta(seconds=2),
    )
    recovered = permission._bind_armed_capability(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id=TURN,
        cwd=REPO_ROOT,
        command=command,
        now=NOW + timedelta(seconds=3),
    )

    assert winner.reason == "private_readonly_binding_claimed"
    assert interrupted.reason == "private_readonly_binding_in_progress"
    assert non_runner == "private_readonly_armed_non_runner_tool_denied"
    assert loser.reason == "private_readonly_capability_bound_to_other_turn"
    assert recovered.granted is True
    assert recovered.reason == "private_readonly_capability_active"


def test_receipt_binds_identity_and_permanent_false_flags(tmp_path: Path) -> None:
    receipt = _issue(tmp_path)
    payload = json.loads(receipt.path.read_text(encoding="utf-8"))
    assert payload["target_session_id"] == SESSION
    assert payload["source_head"]
    assert payload["runner_git_blob"]
    assert len(payload["runner_sha256"]) == 64
    assert payload["issuer_channel"] == "human_local_terminal_outside_codex"
    assert payload["credential_storage"] == "windows_keyring_only"
    assert payload["permissions"] == {
        "live": False,
        "order": False,
        "paper": False,
        "private": True,
        "promotion": False,
        "real_order": False,
        "transfer": False,
        "withdraw": False,
    }
    serialized = json.dumps(payload, sort_keys=True).lower()
    for forbidden in ("api_key", "passphrase", "authorization_header"):
        assert forbidden not in serialized


def test_receipt_rejects_wrong_head_and_runner_hash(tmp_path: Path) -> None:
    receipt = _issue(tmp_path)
    payload = json.loads(receipt.path.read_text(encoding="utf-8"))
    payload["source_head"] = "0" * 40
    receipt.path.write_text(json.dumps(payload), encoding="utf-8")
    assert _activate(tmp_path).reason == "private_readonly_receipt_digest_invalid"

    head_session = "01a0506b-5a5b-7ed1-acb1-cccccccccccc"
    receipt = _issue(tmp_path, session_id=head_session)
    payload = json.loads(receipt.path.read_text(encoding="utf-8"))
    payload["source_head"] = "0" * 40
    payload["receipt_sha256"] = permission.receipt_digest(payload)
    receipt.path.write_text(json.dumps(payload), encoding="utf-8")
    wrong_head = permission.resolve_capability(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=head_session,
        turn_id=TURN,
        event_name="UserPromptSubmit",
        now=NOW + timedelta(seconds=1),
        consume=True,
    )
    assert wrong_head.reason == "private_readonly_source_head_mismatch"

    other = "01a0506b-5a5b-7ed1-acb1-eeeeeeeeeeee"
    receipt = _issue(tmp_path, session_id=other)
    payload = json.loads(receipt.path.read_text(encoding="utf-8"))
    payload["runner_sha256"] = "f" * 64
    payload["receipt_sha256"] = permission.receipt_digest(payload)
    receipt.path.write_text(json.dumps(payload), encoding="utf-8")
    result = permission.resolve_capability(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=other,
        turn_id=TURN,
        event_name="UserPromptSubmit",
        now=NOW + timedelta(seconds=1),
        consume=True,
    )
    assert result.reason == "private_readonly_runner_sha256_mismatch"


def test_expired_and_revoked_receipts_fail_closed(tmp_path: Path) -> None:
    _issue(tmp_path, ttl_seconds=60)
    expired = permission.resolve_capability(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id=TURN,
        event_name="UserPromptSubmit",
        now=NOW + timedelta(seconds=61),
        consume=True,
    )
    assert expired.reason == "private_readonly_receipt_expired"

    other = "01a0506b-5a5b-7ed1-acb1-dddddddddddd"
    receipt = _issue(tmp_path, session_id=other)
    permission.revoke_receipt(root=tmp_path, receipt_id=receipt.receipt_id, now=NOW)
    revoked = permission.resolve_capability(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=other,
        turn_id=TURN,
        event_name="UserPromptSubmit",
        now=NOW + timedelta(seconds=1),
        consume=True,
    )
    assert revoked.reason == "private_readonly_receipt_revoked"


def test_receipt_consumes_once_and_binds_one_turn(tmp_path: Path) -> None:
    _issue(tmp_path)
    assert _activate(tmp_path).granted is True
    replay = permission.resolve_capability(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id="01a0506c-0000-7000-8000-000000000002",
        event_name="UserPromptSubmit",
        now=NOW + timedelta(seconds=2),
        consume=True,
    )
    assert replay.granted is False
    assert replay.reason == "private_readonly_active_lease_exists"


def test_subagent_event_cannot_consume_parent_receipt(tmp_path: Path) -> None:
    _issue(tmp_path)
    result = permission.resolve_capability(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id=TURN,
        event_name="SubagentStart",
        now=NOW + timedelta(seconds=1),
        consume=True,
    )
    assert result.granted is False
    assert result.reason == "private_readonly_root_user_prompt_required"
    _activate(tmp_path)
    active_parent = permission.resolve_capability(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id=TURN,
        event_name="SubagentStart",
        now=NOW + timedelta(seconds=2),
        consume=True,
    )
    assert active_parent.granted is False
    assert active_parent.reason == "private_readonly_root_user_prompt_required"


def test_exact_runner_claim_is_one_time(tmp_path: Path) -> None:
    receipt = _issue(tmp_path)
    active = _activate(tmp_path)
    command = _runner_command(receipt.receipt_id, active.source_head)
    first = permission.authorize_runner_command(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id=TURN,
        cwd=REPO_ROOT,
        command=command,
        now=NOW + timedelta(seconds=2),
    )
    assert first.allowed is True
    second = permission.authorize_runner_command(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id=TURN,
        cwd=REPO_ROOT,
        command=command,
        now=NOW + timedelta(seconds=3),
    )
    assert second.allowed is False
    assert second.reason == "private_readonly_runner_launch_replay"


@pytest.mark.parametrize(
    "mutator,reason",
    [
        (lambda cmd: cmd + "; " + "cu" + "rl https://example.com", "private_readonly_shell_metachar_blocked"),
        (lambda cmd: cmd + " --once", "private_readonly_runner_argument_invalid"),
        (lambda cmd: cmd.replace(permission.RUNNER_PATH, "other.py"), "private_readonly_runner_entry_invalid"),
        (lambda cmd: cmd + " --once --once", "private_readonly_runner_argument_invalid"),
    ],
)
def test_runner_rejects_injection_and_extra_shape(
    tmp_path: Path, mutator, reason: str
) -> None:
    receipt = _issue(tmp_path)
    active = _activate(tmp_path)
    result = permission.authorize_runner_command(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id=TURN,
        cwd=REPO_ROOT,
        command=mutator(_runner_command(receipt.receipt_id, active.source_head)),
        now=NOW + timedelta(seconds=2),
    )
    assert result.allowed is False
    assert result.reason == reason


def test_guard_denies_operator_actions_signing_and_non_runner_bypasses(tmp_path: Path) -> None:
    from tests.agent_governance.agent_hook_loader import load_hook_module

    guard = load_hook_module(REPO_ROOT / ".codex" / "hooks" / "pre_tool_guard.py")
    prepare_command = (
        "py -3 tools/agent_governance/private_readonly_permission.py prepare "
        f"--target-session-id {SESSION}"
    )
    assert guard.blocked_reason(
        prepare_command,
        session_id=SESSION,
        turn_id=TURN,
        capability_root=tmp_path,
        cwd=REPO_ROOT,
    ) == "private_readonly_operator_action_requires_external_terminal"
    direct_install = (
        "py -3 -c \"from tools.agent_governance.private_readonly_permission "
        "import install_signed_receipt\""
    )
    assert guard.blocked_reason(
        direct_install,
        session_id=SESSION,
        turn_id=TURN,
        capability_root=tmp_path,
        cwd=REPO_ROOT,
    ) == "private_readonly_operator_action_requires_external_terminal"
    sign_command = "ssh-keygen -Y sign -f operator-private-key receipt.json"
    assert guard.blocked_reason(
        sign_command,
        session_id=SESSION,
        turn_id=TURN,
        capability_root=tmp_path,
        cwd=REPO_ROOT,
    ) == "private_readonly_signing_requires_external_operator"
    forged_store = "Set-Content private-readonly-permission-v1/pending/fake.json {}"
    assert guard.blocked_reason(
        forged_store,
        session_id=SESSION,
        turn_id=TURN,
        capability_root=tmp_path,
        cwd=REPO_ROOT,
    ) == "private_readonly_receipt_store_is_operator_owned"

    _issue(tmp_path)
    _activate(tmp_path)
    commands = (
        "cu" + "rl https://example.com",
        "Invoke-" + "RestMethod https://example.com",
        "py -3 -c \"print('bypass')\"",
        "py -3 scripts/other_private_account_reader.py",
    )
    for command in commands:
        assert guard.blocked_reason(
            command,
            session_id=SESSION,
            turn_id=TURN,
            capability_root=tmp_path,
            cwd=REPO_ROOT,
            now=NOW + timedelta(seconds=2),
        )


def test_unsigned_receipt_builder_does_not_install_or_grant(tmp_path: Path) -> None:
    payload = permission.build_unsigned_receipt(
        repo_root=REPO_ROOT,
        target_session_id=SESSION,
        ttl_seconds=300,
        now=NOW,
    )
    assert payload["permissions"]["private"] is True
    assert list(tmp_path.rglob("*")) == []
    result = permission.resolve_capability(
        root=tmp_path,
        repo_root=REPO_ROOT,
        session_id=SESSION,
        turn_id=TURN,
        event_name="UserPromptSubmit",
        now=NOW,
        consume=True,
    )
    assert result.granted is False
    assert result.reason == "private_readonly_receipt_missing"


def test_hook_suffix_enables_only_scoped_private_capability() -> None:
    from tests.agent_governance.agent_hook_loader import load_hook_module

    hook = load_hook_module(
        REPO_ROOT / ".codex" / "hooks" / "inject_agent_context.py"
    )
    capability = permission.CapabilityResult(
        True,
        "private_readonly_capability_active",
        receipt_id="a" * 32,
        source_head="b" * 40,
        runner_git_blob="c" * 40,
        runner_sha256="d" * 64,
        expires_at="2026-08-30T02:05:00Z",
    )
    suffix = hook._safety_suffix(
        packet={"role": "btc_developer", "head": "b" * 40},
        team_packet={"invalid_handoffs": []},
        team_error=None,
        capability=capability,
    )
    assert "private=true" in suffix
    assert "private_readonly_capability: active_one_turn_one_launch" in suffix
    assert "guardrail_only_not_os_or_platform_sandbox" in suffix
    assert "runner_self_authorization: mandatory_all_channels_non_runner_blocked" in suffix
    for flag in (
        "promotion=false",
        "paper=false",
        "live=false",
        "order=false",
        "real_order=false",
        "transfer=false",
        "withdraw=false",
    ):
        assert flag in suffix
    assert capability.receipt_id not in suffix
    lowered = suffix.lower()
    for forbidden in ("api_key", "passphrase", "authorization_header"):
        assert forbidden not in lowered


def test_armed_hook_context_keeps_private_false_until_exact_pretool() -> None:
    from tests.agent_governance.agent_hook_loader import load_hook_module

    hook = load_hook_module(
        REPO_ROOT / ".codex" / "hooks" / "private_readonly_capability.py"
    )
    armed = permission.CapabilityResult(
        False,
        "private_readonly_capability_armed",
        receipt_id="a" * 32,
        source_head="b" * 40,
        runner_git_blob="c" * 40,
        runner_sha256="d" * 64,
        expires_at="2026-08-30T02:05:00Z",
        armed=True,
    )

    context = "\n".join(hook.render_capability_context(armed))

    assert "armed_zero_argument_runner_required" in context
    assert "runner_self_authorization" in context
    assert "private=false until" in context
    assert "order=false" in context
    assert "private=true" not in context


def test_pretool_matcher_covers_all_supported_local_tools() -> None:
    hooks = json.loads(
        (REPO_ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8")
    )
    entries = hooks["hooks"]["PreToolUse"]
    assert len(entries) == 1
    assert entries[0]["matcher"] in {".*", "^.*$"}


def test_active_capability_uses_default_deny_for_every_non_runner_tool(
    tmp_path: Path,
) -> None:
    from tests.agent_governance.agent_hook_loader import load_hook_module

    guard = load_hook_module(REPO_ROOT / ".codex" / "hooks" / "pre_tool_guard.py")
    _issue(tmp_path)
    _activate(tmp_path)
    bypasses = (
        ("Bash", "node other-client.js"),
        ("Bash", "certutil -urlcache https://example.com out.bin"),
        ("Bash", "Start-BitsTransfer -Source https://example.com -Destination out.bin"),
        ("Bash", "[System.Net.WebClient]::new().DownloadString('https://example.com')"),
        ("Read", ""),
        ("mcp__local__tool", ""),
        ("computer-use", ""),
    )
    for tool_name, command in bypasses:
        assert guard.blocked_reason(
            command,
            session_id=SESSION,
            turn_id=TURN,
            capability_root=tmp_path,
            cwd=REPO_ROOT,
            tool_name=tool_name,
            now=NOW + timedelta(seconds=2),
        ) == "private_readonly_active_session_non_runner_tool_denied"


def test_guard_releases_only_exact_runner_on_canonical_shell_once(
    tmp_path: Path,
) -> None:
    from tests.agent_governance.agent_hook_loader import load_hook_module

    guard = load_hook_module(REPO_ROOT / ".codex" / "hooks" / "pre_tool_guard.py")
    receipt = _issue(tmp_path)
    active = _activate(tmp_path)
    command = _runner_command(receipt.receipt_id, active.source_head)
    assert guard.blocked_reason(
        command,
        session_id=SESSION,
        turn_id=TURN,
        capability_root=tmp_path,
        cwd=REPO_ROOT,
        tool_name="exec_command",
        now=NOW + timedelta(seconds=2),
    ) is None
    assert guard.blocked_reason(
        command,
        session_id=SESSION,
        turn_id=TURN,
        capability_root=tmp_path,
        cwd=REPO_ROOT,
        tool_name="exec_command",
        now=NOW + timedelta(seconds=3),
    ) == "private_readonly_runner_launch_replay"


def test_repository_has_no_receipt_signer_and_requires_external_signature() -> None:
    assert not hasattr(permission, "issue_receipt")
    assert not hasattr(permission, "sign_receipt")
    assert hasattr(permission, "verify_external_signature")


def test_repository_enrolls_exact_operator_public_key_only() -> None:
    allowed_signers = (
        REPO_ROOT / permission.ALLOWED_SIGNERS_PATH
    ).read_text(encoding="utf-8")
    assert allowed_signers.splitlines() == [
        "btc-private-readonly-operator "
        "ssh-ed25519 "
        "AAAAC3NzaC1lZDI1NTE5AAAAIDfyEav2dkOWMf5etsgtyruv2FGMlnrg3AUyMM75efGN "
        "btc-private-readonly-operator"
    ]
    assert "PRIVATE KEY" not in allowed_signers


@pytest.mark.parametrize(
    "allowed_signers,verify_returncode,reason",
    [
        (
            b"different-principal ssh-ed25519 AAAATEST\n",
            0,
            "private_readonly_operator_signer_not_enrolled",
        ),
        (
            b"btc-private-readonly-operator ssh-ed25519 AAAATEST\n",
            1,
            "private_readonly_signature_verification_failed",
        ),
        (
            b"btc-private-readonly-operator ssh-ed25519 AAASWAPPED\n",
            1,
            "private_readonly_signature_verification_failed",
        ),
    ],
)
def test_fake_signature_wrong_signer_and_swapped_key_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    allowed_signers: bytes,
    verify_returncode: int,
    reason: str,
) -> None:
    payload = permission.build_unsigned_receipt(
        repo_root=REPO_ROOT,
        target_session_id=SESSION,
        ttl_seconds=300,
        now=NOW,
    )

    def fake_run(args, **kwargs):
        if args[:2] == ["git", "show"]:
            return subprocess.CompletedProcess(args, 0, stdout=allowed_signers, stderr=b"")
        assert args[:3] == ["ssh-keygen", "-Y", "verify"]
        return subprocess.CompletedProcess(args, verify_returncode, stdout=b"", stderr=b"")

    monkeypatch.setattr(permission.subprocess, "run", fake_run)
    result = REAL_VERIFY_EXTERNAL_SIGNATURE(
        payload,
        b"forged-signature",
        repo_root=REPO_ROOT,
    )
    assert result.verified is False
    assert result.reason == reason
