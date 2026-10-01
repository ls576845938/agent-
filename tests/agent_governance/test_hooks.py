from __future__ import annotations

import json
import hashlib
import re
import subprocess
import sys
from pathlib import Path

from tests.agent_governance.agent_hook_loader import load_hook_module


REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = load_hook_module(REPO_ROOT / ".codex" / "hooks" / "pre_tool_guard.py")


def _assert_available_team_context(context: str) -> None:
    assert "Quant team context packet" in context
    # A historical handoff may legitimately record that discovery was
    # unavailable at publication time.  The live packet must not itself be
    # unavailable after main-coverage recovery.
    assert "\n- team_context_unavailable:" not in context
    assert "- invalid_handoffs: unavailable" not in context
    assert re.search(r"(?:^|\n)- invalid_handoffs: \d+(?:\n|$)", context)


def test_pre_tool_guard_blocks_destructive_and_private_network_commands() -> None:
    assert GUARD.blocked_reason("git reset --hard HEAD~1")
    assert GUARD.blocked_reason("Remove-Item -Recurse .\\data")
    assert GUARD.blocked_reason("curl https://www.okx.com/api/v5/trade/order")
    assert GUARD.blocked_reason("Get-Content .env")


def test_pre_tool_guard_allows_safe_local_review() -> None:
    assert GUARD.blocked_reason('rg -n "/api/v5/trade" tests') is None
    assert (
        GUARD.blocked_reason("git status --short", sparse_checkout=False)
        == "full_repo_git_status_forbidden_in_non_sparse_worktree"
    )
    assert GUARD.blocked_reason("git status --short", sparse_checkout=True) is None
    assert GUARD.blocked_reason("git status --short -- AGENTS.md", sparse_checkout=False) is None
    assert (
        GUARD.blocked_reason("git diff", sparse_checkout=False)
        == "full_repo_git_diff_forbidden_in_non_sparse_worktree"
    )
    assert GUARD.blocked_reason("git diff -- AGENTS.md", sparse_checkout=False) is None
    assert GUARD.blocked_reason("Get-Content .env.example") is None


def test_pre_tool_guard_enforces_disk_watermarks_and_runtime_db_boundary() -> None:
    assert GUARD.blocked_reason("git worktree add ../full main", free_gb=49.9) == "disk_free_below_50gb"
    assert GUARD.blocked_reason("git worktree add ../full main", free_gb=60) == "direct_full_worktree_forbidden_use_governed_override"
    assert GUARD.blocked_reason("git worktree add --no-checkout ../sparse main", free_gb=49.9) is None
    assert GUARD.blocked_reason("py -3 scripts/build_btc_gate_report.py", free_gb=19.9) == "disk_free_below_20gb"
    assert GUARD.blocked_reason("git add -f data/market_data.sqlite", free_gb=100) == "mutable_runtime_database_must_not_enter_git"


def test_context_hook_emits_role_specific_additional_context() -> None:
    hook = REPO_ROOT / ".codex" / "hooks" / "inject_agent_context.py"
    payload = {
        "hook_event_name": "UserPromptSubmit",
        "cwd": str(REPO_ROOT),
        "prompt": "作为 BTC 程序员检查永续 OMS 和 gate",
    }
    result = subprocess.run(
        [sys.executable, str(hook)],
        cwd=REPO_ROOT,
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    output = json.loads(result.stdout)
    context = output["hookSpecificOutput"]["additionalContext"]

    assert output["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "role: btc_developer" in context
    assert "BTC-OMS-001" in context
    assert "ARCH-READONLY-001" not in context
    assert "Quant team context packet" in context
    assert "uncommitted files in other worktrees are not deliverables" in context
    assert len(context) <= 4000
    _assert_available_team_context(context)
    assert "branch_heads:" not in context
    assert "terminal:" not in context


def test_private_readonly_user_prompt_hook_can_arm_without_turn_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    permission = __import__(
        "tools.agent_governance.private_readonly_permission",
        fromlist=["private_readonly_permission"],
    )
    capability_hook = load_hook_module(
        REPO_ROOT / ".codex" / "hooks" / "private_readonly_capability.py"
    )
    monkeypatch.setattr(
        permission,
        "verify_external_signature",
        lambda payload, signature, *, repo_root: permission.SignatureVerification(
            True, "private_readonly_signature_verified"
        ),
    )
    monkeypatch.setattr(
        permission,
        "_current_identity",
        lambda _repo_root: (
            "a" * 40,
            "b" * 40,
            hashlib.sha256((REPO_ROOT / permission.RUNNER_PATH).read_bytes()).hexdigest(),
        ),
    )
    payload = permission.build_unsigned_receipt(
        repo_root=REPO_ROOT,
        target_session_id="01a0506b-5a5b-7ed1-acb1-0b6ec8c83ea5",
        ttl_seconds=300,
    )
    pending = (
        tmp_path
        / "pending"
        / permission._session_key(str(payload["target_session_id"]))
    )
    receipt = pending / f"{payload['receipt_id']}.json"
    permission._atomic_json(receipt, payload, exclusive=True)
    permission._atomic_bytes(
        receipt.with_suffix(".sig"), b"test-only-signature", exclusive=True
    )

    result = capability_hook.evaluate_hook_capability(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": payload["target_session_id"],
        },
        repo_root=REPO_ROOT,
        root=tmp_path,
        consume=True,
    )

    assert result.granted is False
    assert result.armed is True
    assert result.reason == "private_readonly_capability_armed"


def test_builtin_explorer_hook_falls_back_to_shared_rules() -> None:
    hook = REPO_ROOT / ".codex" / "hooks" / "inject_agent_context.py"
    payload = {
        "hook_event_name": "SubagentStart",
        "cwd": str(REPO_ROOT),
        "agent_type": "explorer",
    }
    result = subprocess.run(
        [sys.executable, str(hook)],
        cwd=REPO_ROOT,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    output = json.loads(result.stdout)

    assert "agent_context_injection_failed" not in result.stdout
    assert "GOV-ROOT-001" in output["hookSpecificOutput"]["additionalContext"]
    assert "promotion, paper, live, private, or order" in output["hookSpecificOutput"]["additionalContext"]
    assert "dirty_paths: not_rechecked" in output["hookSpecificOutput"]["additionalContext"]
    assert len(output["hookSpecificOutput"]["additionalContext"]) <= 4000
    _assert_available_team_context(output["hookSpecificOutput"]["additionalContext"])


def test_context_hook_recognizes_a_share_developer() -> None:
    hook = REPO_ROOT / ".codex" / "hooks" / "inject_agent_context.py"
    payload = {
        "hook_event_name": "UserPromptSubmit",
        "cwd": str(REPO_ROOT),
        "prompt": "作为 A股程序员开发沪深回测与执行模拟",
    }
    result = subprocess.run(
        [sys.executable, str(hook)],
        cwd=REPO_ROOT,
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]

    assert "role: a_share_developer" in context
    assert "CN-BOUNDARY-001" in context
    assert "CN-DATA-PIT-001" in context
    assert "CN-MARKET-001" in context


def test_context_hook_classifies_demo_transport_before_negative_live_text() -> None:
    hook = REPO_ROOT / ".codex" / "hooks" / "inject_agent_context.py"
    payload = {
        "hook_event_name": "UserPromptSubmit",
        "cwd": str(REPO_ROOT),
        "agent_type": "btc_developer",
        "prompt": (
            "修复 Demo public tail stale seed parser；"
            "仍禁止实盘、转账和提现"
        ),
    }
    result = subprocess.run(
        [sys.executable, str(hook)],
        cwd=REPO_ROOT,
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    context = json.loads(result.stdout)[
        "hookSpecificOutput"
    ]["additionalContext"]

    assert "change_risk: demo_transport_hotfix" in context
    assert "promotion_artifact_rebuild_required: False" in context
    assert "QSYS-ARTIFACT-001" not in context
    assert "legacy promotion blockers and domain read models omitted" in context
