from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.agent_governance.context_packet import (  # noqa: E402
    build_packet,
    canonical_role,
    infer_role,
    infer_scopes,
    load_catalog,
    render_markdown,
)
from tools.agent_governance.delivery_policy import (  # noqa: E402
    infer_change_risk,
)
from tools.agent_governance.team_context import (  # noqa: E402
    build_team_context,
    render_team_context,
)
from private_readonly_capability import (  # noqa: E402
    evaluate_hook_capability,
    render_capability_context,
)
from tools.agent_governance.private_readonly_permission import (  # noqa: E402
    CapabilityResult,
)


MAX_ADDITIONAL_CONTEXT_CHARS = 4000
SESSION_EVENTS = {"SessionStart", "SubagentStart"}


def _clip_section(value: str, max_chars: int, *, marker: str) -> str:
    if max_chars <= 0:
        return ""
    if len(value) <= max_chars:
        return value
    if max_chars <= len(marker) + 2:
        return value[:max_chars]
    head = max(1, (max_chars - len(marker) - 2) // 2)
    tail = max_chars - head - len(marker) - 2
    return f"{value[:head].rstrip()}\n{marker}\n{value[-tail:].lstrip()}" if tail else value[:head]


def _safety_suffix(
    *,
    packet: dict[str, object],
    team_packet: dict[str, object] | None,
    team_error: Exception | None,
    capability: CapabilityResult,
) -> str:
    invalid = (
        str(len(team_packet.get("invalid_handoffs", [])))
        if team_packet is not None
        else "unavailable"
    )
    private_flag = "true" if capability.granted else "false"
    lines = [
        "Quant hook safety suffix",
        f"- role: {packet.get('role', 'all')}",
        f"- change_risk: {packet.get('change_risk', 'unclassified')}",
        f"- current_head: {packet.get('head', 'unavailable')}",
        f"- invalid_handoffs: {invalid}",
        f"- permissions: promotion=false, paper_or_live=false, private={private_flag}, order=false, real_order=false, transfer=false, withdraw=false",
    ]
    lines.extend(render_capability_context(capability))
    if capability.granted:
        lines.append(
            "- all non-observer private actions and every order/live capability remain denied"
        )
    else:
        lines.append(
            "- promotion, paper, live, private, order, real_order, transfer, and withdraw permissions remain false"
        )
    if team_error is not None:
        lines.append(
            f"- team_context_unavailable: {type(team_error).__name__}:{team_error}"
        )
    return "\n".join(lines)


def _compose_context(
    governance_context: str,
    team_context: str,
    safety_suffix: str,
    *,
    limit: int = MAX_ADDITIONAL_CONTEXT_CHARS,
) -> str:
    separator = "\n\n"
    if len(governance_context) + len(separator) + len(team_context) + len(separator) + len(safety_suffix) <= limit:
        return separator.join((governance_context, team_context, safety_suffix))
    available = max(0, limit - len(safety_suffix) - 2)
    # Keep an active Team Context section even when governance rules are long;
    # safety metadata is appended last and is never discarded.
    team_budget = min(2000, max(800, available // 2))
    governance_budget = max(0, available - team_budget)
    team = _clip_section(team_context, team_budget, marker="- active_team_context_truncated: true")
    governance = _clip_section(
        governance_context,
        governance_budget,
        marker="- governance_context_truncated: true",
    )
    rendered = separator.join((governance, team, safety_suffix))
    if len(rendered) <= limit:
        return rendered
    # Defensive final bound for unusual non-ASCII/error strings.  The suffix
    # is short and contains all safety identity fields, so reserve it first.
    suffix_budget = min(len(safety_suffix), limit)
    body_budget = max(0, limit - suffix_budget - 2)
    body = _clip_section(
        separator.join((governance, team)),
        body_budget,
        marker="- context_sections_truncated: true",
    )
    return separator.join((body, safety_suffix))[-limit:]


def main() -> int:
    try:
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8")
        hook_input = json.load(sys.stdin)
        event = str(hook_input.get("hook_event_name", "SessionStart"))
        prompt = str(hook_input.get("prompt", ""))
        raw_role = str(hook_input.get("agent_type", ""))
        role = canonical_role(raw_role) if raw_role else infer_role(prompt)
        scopes = infer_scopes(prompt)
        change_risk = infer_change_risk(prompt)
        capability = evaluate_hook_capability(
            hook_input,
            repo_root=REPO_ROOT,
            consume=True,
        )
        if event == "SessionStart" and not scopes:
            scopes = {"shared"}
        is_session = event in SESSION_EVENTS
        max_rules = 14 if is_session else 8
        governance_budget = 1550 if is_session else 1700
        team_budget = 1950 if is_session else 1800
        packet = build_packet(
            catalog=load_catalog(),
            role=role,
            scopes=scopes,
            change_risk=change_risk,
            repo_root=REPO_ROOT,
            max_rules=max_rules,
            include_dirty=False,
        )
        governance_context = render_markdown(packet, max_chars=governance_budget)
        team_packet: dict[str, object] | None = None
        team_error: Exception | None = None
        try:
            team_packet = build_team_context(
                repo_root=REPO_ROOT,
                consumer_role=role,
                change_risk=change_risk,
                max_events=12,
                projection="active",
            )
            team_context = render_team_context(
                team_packet,
                active_only=True,
                max_chars=team_budget,
            )
        except Exception as exc:  # Governance rules still load when team discovery fails.
            team_error = exc
            team_context = (
                "Quant team context packet\n"
                f"- team_context_unavailable:{type(exc).__name__}:{exc}\n"
                "- cross-agent-dependent work must fail closed until discovery is restored\n"
                "- promotion, paper, live, private, and order permissions remain false"
            )
        safety_suffix = _safety_suffix(
            packet=packet,
            team_packet=team_packet,
            team_error=team_error,
            capability=capability,
        )
        output = {
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": _compose_context(
                    governance_context,
                    team_context,
                    safety_suffix,
                ),
            }
        }
    except Exception as exc:  # Hook failures must stay visible without weakening safety defaults.
        output = {"systemMessage": f"agent_context_injection_failed:{type(exc).__name__}:{exc}"}
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
