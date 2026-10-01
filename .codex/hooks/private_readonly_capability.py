from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.agent_governance.private_readonly_permission import (
    CapabilityResult,
    PermissionErrorCode,
    default_capability_root,
    resolve_capability,
)


def evaluate_hook_capability(
    hook_input: dict[str, Any],
    *,
    repo_root: Path,
    root: Path | None = None,
    consume: bool = True,
) -> CapabilityResult:
    event_name = str(hook_input.get("hook_event_name", ""))
    session_id = str(hook_input.get("session_id", ""))
    turn_id = str(hook_input.get("turn_id", ""))
    try:
        capability_root = root if root is not None else default_capability_root()
    except PermissionErrorCode as exc:
        return CapabilityResult(False, str(exc))
    return resolve_capability(
        root=capability_root,
        repo_root=repo_root,
        session_id=session_id,
        turn_id=turn_id,
        event_name=event_name,
        consume=consume,
    )


def render_capability_context(result: CapabilityResult) -> list[str]:
    boundary = [
        "- private_readonly_hook_boundary: guardrail_only_not_os_or_platform_sandbox",
        "- private_readonly_runner_self_authorization: mandatory_all_channels_non_runner_blocked",
    ]
    if result.armed:
        return [
            f"- private_readonly_purpose: {result.purpose}",
            f"- private_readonly_runner_path: {result.runner_path}",
            "- private_readonly_capability: armed_zero_argument_runner_required",
            f"- private_readonly_source_head: {result.source_head}",
            f"- private_readonly_runner_git_blob: {result.runner_git_blob}",
            f"- private_readonly_runner_sha256: {result.runner_sha256}",
            f"- private_readonly_expires_at: {result.expires_at}",
            "- private=false until an exact-runner launch reservation and one-time process start claim both validate",
            "- promotion=false, paper=false, live=false, order=false, real_order=false, transfer=false, withdraw=false",
            *boundary,
        ]
    if not result.granted:
        return [
            "- private_readonly_capability: inactive",
            f"- private_readonly_capability_reason: {result.reason}",
            *boundary,
        ]
    return [
        f"- private_readonly_purpose: {result.purpose}",
        f"- private_readonly_runner_path: {result.runner_path}",
        "- private_readonly_capability: active_one_turn_one_launch",
        f"- private_readonly_source_head: {result.source_head}",
        f"- private_readonly_runner_git_blob: {result.runner_git_blob}",
        f"- private_readonly_runner_sha256: {result.runner_sha256}",
        f"- private_readonly_expires_at: {result.expires_at}",
        "- private=true applies only to the exact signed-purpose readonly runner",
        "- promotion=false, paper=false, live=false, order=false, real_order=false, transfer=false, withdraw=false",
        *boundary,
    ]
