from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
HOOK_DIR = Path(__file__).resolve().parent
if str(HOOK_DIR) not in sys.path:
    sys.path.insert(0, str(HOOK_DIR))

from tools.agent_governance.disk_guard import MIN_FREE_GB, evaluate_disk_guard
from tools.agent_governance.private_readonly_permission import (
    PermissionErrorCode,
    PURPOSE_RUNNERS,
    authorize_runner_command,
    default_capability_root,
    resolve_capability,
    utc_now,
)


DESTRUCTIVE_PATTERNS = (
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+-[^\r\n]*f",
    r"\bgit\s+checkout\s+--\s",
    r"\bremove-item\b[^\r\n]*-recurse\b",
    r"\brm\s+-rf\b",
)

SECRET_READ_PATTERN = re.compile(
    r"(?i)\b(get-content|type|cat|more)\b[^\r\n]*(?:^|\s|[\\/])\.env(?:\s|$|[\"'])"
)

NETWORK_CLIENT_PATTERN = re.compile(
    r"(?i)\b(curl|wget|invoke-webrequest|invoke-restmethod)\b|requests\.(get|post|put|delete)|httpx\.(get|post|put|delete)"
)

PRIVATE_ENDPOINT_PATTERN = re.compile(
    r"(?i)(/api/v\d+/(trade|account|asset|withdraw)|/private(?:/|\b)|/order(?:s)?(?:/|\b)|withdraw)"
)

FULL_WORKTREE_PATTERN = re.compile(r"(?i)\bgit\s+(?:-[^\s]+\s+)*worktree\s+add\b")
LOW_DISK_WRITE_PATTERN = re.compile(
    r"(?i)(--execute-network|fetch_[^\s]*\.py|run_[^\s]*(?:refresh|collector)[^\s]*\.py|"
    r"build_[^\s]*report\.py|market_data\.sqlite|(?:^|[\\/])artifacts[\\/])"
)
PROTECTED_DATABASE_ADD_PATTERN = re.compile(
    r"(?i)\bgit\s+add\b[^\r\n]*data[\\/]market_data\.sqlite(?:-wal|-shm)?\b"
)
UNSCOPED_STATUS_PATTERN = re.compile(r"(?im)(?:^|[;&|(\r\n]\s*)git\s+status\b")
UNSCOPED_WORKTREE_DIFF_PATTERN = re.compile(r"(?im)(?:^|[;&|(\r\n]\s*)git\s+diff\b")
PRIVATE_READONLY_OPERATOR_ACTION_PATTERN = re.compile(
    r"(?i)\b(?:build_unsigned_receipt|install_signed_receipt)\b|"
    r"(?:private_readonly_permission\.py|tools\.agent_governance\.private_readonly_permission)\s+(?:prepare|install)\b"
)
PRIVATE_READONLY_SIGN_PATTERN = re.compile(r"(?i)\bssh-keygen(?:\.exe)?\b[^\r\n]*\s-Y\s+sign\b")
PRIVATE_READONLY_FORGE_PATTERN = re.compile(
    r"(?i)private-readonly-permission-v1|btc_private_readonly_permission_receipt_v[12]"
)
PYTHON_DYNAMIC_PATTERN = re.compile(r"(?i)\b(?:py(?:\.exe)?|python(?:\.exe)?)\b[^\r\n]*\s-(?:c|m)\b")
PYTHON_EXECUTION_PATTERN = re.compile(r"(?i)^\s*(?:py(?:\.exe)?|python(?:\.exe)?)\b")


def blocked_reason(
    command: str,
    *,
    free_gb: float | None = None,
    sparse_checkout: bool | None = None,
    session_id: str = "",
    turn_id: str = "",
    capability_root: Path | None = None,
    cwd: Path | None = None,
    tool_name: str = "Bash",
    now: datetime | None = None,
) -> str | None:
    normalized_command = command.replace("\\", "/").lower()
    runner_invocation = any(path.lower() in normalized_command for path in PURPOSE_RUNNERS.values())
    root = capability_root
    if root is None:
        try:
            root = default_capability_root()
        except PermissionErrorCode:
            root = None
    effective_cwd = (cwd or REPO_ROOT).resolve()
    active_capability = None
    if root is not None and session_id:
        active_capability = resolve_capability(
            root=root,
            repo_root=REPO_ROOT,
            session_id=session_id,
            turn_id=turn_id,
            event_name="PreToolUse",
            now=now or utc_now(),
            consume=False,
        )
    if active_capability is not None and active_capability.armed:
        if not turn_id or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._:-]{15,127}",
            turn_id,
        ):
            return "private_readonly_turn_id_invalid"
        if tool_name.lower() not in {"bash", "exec_command"} or not runner_invocation:
            return "private_readonly_armed_non_runner_tool_denied"
        authorization = authorize_runner_command(
            root=root,
            repo_root=REPO_ROOT,
            session_id=session_id,
            turn_id=turn_id,
            cwd=effective_cwd,
            command=command,
            now=now or utc_now(),
        )
        return None if authorization.allowed else authorization.reason
    if active_capability is not None and active_capability.granted:
        # Capability mode is an allowlist, not a network-client denylist.  The
        # only action this hook may release is one exact zero-argument launch
        # reservation through a canonical shell tool. The spawned runner still
        # must create its independent one-time process start claim.
        if tool_name.lower() not in {"bash", "exec_command"} or not runner_invocation:
            return "private_readonly_active_session_non_runner_tool_denied"
        authorization = authorize_runner_command(
            root=root,
            repo_root=REPO_ROOT,
            session_id=session_id,
            turn_id=turn_id,
            cwd=effective_cwd,
            command=command,
            now=now or utc_now(),
        )
        return None if authorization.allowed else authorization.reason
    if runner_invocation:
        if root is None:
            return "private_readonly_capability_root_unavailable"
        authorization = authorize_runner_command(
            root=root,
            repo_root=REPO_ROOT,
            session_id=session_id,
            turn_id=turn_id,
            cwd=effective_cwd,
            command=command,
            now=now or utc_now(),
        )
        return None if authorization.allowed else authorization.reason
    if PRIVATE_READONLY_OPERATOR_ACTION_PATTERN.search(command):
        return "private_readonly_operator_action_requires_external_terminal"
    if PRIVATE_READONLY_SIGN_PATTERN.search(command):
        return "private_readonly_signing_requires_external_operator"
    if PRIVATE_READONLY_FORGE_PATTERN.search(command):
        return "private_readonly_receipt_store_is_operator_owned"
    for pattern in DESTRUCTIVE_PATTERNS:
        if re.search(pattern, command, flags=re.IGNORECASE):
            return "destructive_command_requires_explicit_user_authorization"
    if SECRET_READ_PATTERN.search(command) and ".env.example" not in command.lower():
        return "secret_file_read_blocked"
    if NETWORK_CLIENT_PATTERN.search(command) and PRIVATE_ENDPOINT_PATTERN.search(command):
        return "private_order_or_withdraw_endpoint_blocked"
    if PROTECTED_DATABASE_ADD_PATTERN.search(command):
        return "mutable_runtime_database_must_not_enter_git"
    explicit_pathspec = bool(re.search(r"\s--\s+\S", command))
    if sparse_checkout is not True and UNSCOPED_STATUS_PATTERN.search(command) and not explicit_pathspec:
        return "full_repo_git_status_forbidden_in_non_sparse_worktree"
    staged_diff = bool(re.search(r"(?i)\bgit\s+diff\b[^\r\n]*(?:--cached|--staged)", command))
    if (
        sparse_checkout is not True
        and UNSCOPED_WORKTREE_DIFF_PATTERN.search(command)
        and not explicit_pathspec
        and not staged_diff
    ):
        return "full_repo_git_diff_forbidden_in_non_sparse_worktree"
    if FULL_WORKTREE_PATTERN.search(command) and "--no-checkout" not in command.lower():
        result = _disk_result("full-worktree", free_gb)
        if not result["allowed"]:
            return str(result["blocker"])
        return "direct_full_worktree_forbidden_use_governed_override"
    if LOW_DISK_WRITE_PATTERN.search(command):
        result = _disk_result("data-collection", free_gb)
        if not result["allowed"]:
            return str(result["blocker"])
    return None


def _disk_result(operation: str, free_gb: float | None) -> dict[str, object]:
    free_bytes = None if free_gb is None else int(free_gb * 1024**3)
    try:
        return evaluate_disk_guard(operation=operation, path=REPO_ROOT, free_bytes=free_bytes)
    except OSError as exc:
        return {
            "allowed": False,
            "blocker": f"disk_probe_failed:{type(exc).__name__}:{exc}",
            "minimum_free_gb": MIN_FREE_GB[operation],
        }


def _is_sparse_checkout(cwd: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "config", "--bool", "--get", "core.sparseCheckout"],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except OSError:
        return False
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def main() -> int:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    hook_input = json.load(sys.stdin)
    tool_input = hook_input.get("tool_input") or {}
    command = str(tool_input.get("command", ""))
    cwd = Path(str(hook_input.get("cwd") or REPO_ROOT)).resolve()
    reason = blocked_reason(
        command,
        sparse_checkout=_is_sparse_checkout(cwd),
        session_id=str(hook_input.get("session_id", "")),
        turn_id=str(hook_input.get("turn_id", "")),
        cwd=cwd,
        tool_name=str(hook_input.get("tool_name", "Bash")),
    )
    if reason:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
        print(json.dumps(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
