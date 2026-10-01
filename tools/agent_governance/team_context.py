from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

MODULE_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(MODULE_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_REPO_ROOT))

from tools.agent_governance.handoff import HandoffError, ROLES, scan_handoffs
from tools.agent_governance.git_metadata import GitMetadataError, current_branch_head
from tools.agent_governance.shared_data import SharedDataError, default_shared_data_root, resolve_manifest_payload
from tools.agent_governance.delivery_policy import CHANGE_RISKS, canonical_change_risk
from quant_crypto.adapters.btc_runtime_artifact_store import (
    BTCRuntimeArtifactReader,
    BTCRuntimeArtifactStoreError,
)
from quant_crypto.adapters.btc_domain_read_model_repository import (
    BTCPublishedDomainReadModelRepository,
)
from quant_crypto.application.btc_domain_read_model import (
    BTCPublishedDomainReadModelUnavailable,
)


SCHEMA_VERSION = "agent_team_context_v1"
BLOCKER_CATEGORIES = {
    "runtime_clock",
    "runtime_network",
    "natural_time",
    "manual_approval",
    "data_steward",
    "integrator",
    "engineering",
    "unclassified",
}
DOMAIN_READ_MODELS = {
    "cn_equity": (
        Path("artifacts/cn_equity_operator_read_model/latest/cn_equity_operator_read_model.json"),
    ),
    "us_equity": (
        Path("artifacts/us_equity_strategy_production_line/latest/us_equity_operator_read_model.json"),
    ),
    "btc": (
        Path("artifacts/btc_domain_read_model/latest/btc_domain_read_model.json"),
        Path("artifacts/btc_operator_root_cause_view/latest/btc_operator_root_cause_view_report.json"),
        Path("artifacts/btc_perpetual_gate_objective_status/latest/btc_perpetual_gate_objective_status_report.json"),
    ),
}
def build_team_context(
    *,
    repo_root: Path,
    consumer_role: str = "all",
    change_risk: str = "unclassified",
    max_events: int = 20,
    projection: str = "full",
    shared_data_root: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    risk = canonical_change_risk(change_risk)
    if consumer_role != "all" and consumer_role not in ROLES:
        raise ValueError(f"team_context_role_invalid:{consumer_role}")
    if projection not in {"full", "active"}:
        raise ValueError(f"team_context_projection_invalid:{projection}")
    timestamp = now or datetime.now(timezone.utc)
    scan = scan_handoffs(root, verify_git=False)
    records = _resolve_states(scan["events"], timestamp)
    records = [record for record in records if _visible_to(record, consumer_role)]
    try:
        current_branch, current_head = current_branch_head(root)
    except (OSError, GitMetadataError):
        current_branch = _git_text(root, "branch", "--show-current", default="unknown")
        current_head = _git_text(root, "rev-parse", "HEAD", default="unknown")
    if risk == "demo_transport_hotfix":
        records = [
            record
            for record in records
            if record["event"].get("domain") == "btc"
            and record["event"].get("gate_impact") == "none"
        ]
        for record in records:
            _derive_demo_fastpath_state(
                record,
                repo_root=root,
                current_head=current_head,
            )
    records.sort(key=lambda item: item["event"]["created_at"], reverse=True)
    records = records[:max_events]
    shared_root = (shared_data_root or default_shared_data_root(root)).resolve()
    try:
        btc_artifact_reader = BTCRuntimeArtifactReader.from_environment(
            source_repo_root=root,
        )
    except BTCRuntimeArtifactStoreError:
        btc_artifact_reader = None

    ready: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    integration: list[dict[str, Any]] = []
    available: list[dict[str, Any]] = []
    terminal: list[dict[str, Any]] = []
    for record in records:
        summary = _summarize_record(record)
        manifest_errors = _shared_manifest_errors(record, root, shared_root)
        summary["blockers"] = _dedupe([*summary["blockers"], *manifest_errors])
        if summary["state"] in {"integrated", "integrated_fastpath"}:
            if summary["expired"] or summary["blockers"]:
                blocked.append(summary)
            else:
                available.append(summary)
            continue
        if summary["state"] in {"rejected", "superseded"}:
            terminal.append(summary)
            continue
        if summary["expired"] or summary["blockers"]:
            blocked.append(summary)
        else:
            ready.append(summary)
        if summary["state"] == "acknowledged" and not summary["expired"] and not summary["blockers"]:
            integration.append(summary)

    branches = [
        {"branch": item["branch"], "head": item["head"], "behind_main": -1, "ahead_main": -1}
        for item in scan["ref_heads"]
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": timestamp.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "repo_root": str(root),
        "current_branch": current_branch,
        "current_head": current_head,
        "consumer_role": consumer_role,
        "change_risk": risk,
        "handoff_verification_mode": scan["verification_mode"],
        "projection": projection,
        "shared_data_root": str(shared_root),
        "branches": branches,
        "ready_upstreams": ready,
        "available_deliveries": available,
        "blocked_dependencies": blocked,
        "integration_candidates": integration,
        "terminal_handoffs": terminal,
        "invalid_handoffs": scan["invalid"],
        "domain_read_models": (
            []
            if risk == "demo_transport_hotfix"
            else _load_domain_read_models(
                root,
                current_head=current_head,
                btc_artifact_reader=btc_artifact_reader,
            )
        ),
        "guardrails": {
            "read_only": True,
            "derived_state_only": True,
            "uncommitted_worktree_files_consumable": False,
            "full_handoff_validation_required_before_consumption": True,
            "promotion_unlock_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "merge_or_commit_performed": False,
        },
    }


def render_team_context(
    packet: Mapping[str, Any],
    *,
    max_chars: int = 7000,
    active_only: bool = False,
) -> str:
    active_only = active_only or packet.get("projection") == "active"
    lines = [
        "Quant team context packet",
        f"- schema: {packet.get('schema_version', 'unknown')}",
        f"- current_branch: {packet.get('current_branch', 'unknown')}",
        f"- current_head: {str(packet.get('current_head', 'unknown'))[:12]}",
        f"- consumer_role: {packet.get('consumer_role', 'all')}",
        f"- change_risk: {packet.get('change_risk', 'unclassified')}",
        f"- handoff_verification_mode: {packet.get('handoff_verification_mode', 'unknown')}",
        f"- agent_branches: {len(packet.get('branches', []))}",
        f"- ready_upstreams: {len(packet.get('ready_upstreams', []))}",
        f"- available_deliveries: {len(packet.get('available_deliveries', []))}",
        f"- blocked_dependencies: {len(packet.get('blocked_dependencies', []))}",
        f"- integration_candidates: {len(packet.get('integration_candidates', []))}",
        f"- invalid_handoffs: {len(packet.get('invalid_handoffs', []))}",
    ]
    branches = packet.get("branches", [])
    if branches and not active_only:
        lines.append("- branch_heads:")
        for item in branches[:12]:
            divergence = (
                "divergence=not_computed"
                if item["ahead_main"] < 0 or item["behind_main"] < 0
                else f"ahead_main={item['ahead_main']}, behind_main={item['behind_main']}"
            )
            lines.append(
                f"  - {item['branch']} @ {item['head'][:12]} "
                f"({divergence})"
            )
    for label, key in (
        ("ready", "ready_upstreams"),
        ("available", "available_deliveries"),
        ("blocked", "blocked_dependencies"),
        ("integration", "integration_candidates"),
    ):
        items = packet.get(key, [])
        if not items:
            continue
        lines.append(f"- {label}:")
        for item in items[:10]:
            blocker = f" blockers={','.join(item['blockers'][:2])}" if item["blockers"] else ""
            lines.append(
                f"  - {item['event_id']} ticket={item['ticket_id']} producer={item['producer_role']} "
                f"state={item['state']} readiness={','.join(item['readiness_classes']) or 'none'}{blocker}"
            )
    if not active_only:
        terminal = packet.get("terminal_handoffs", [])
        if terminal:
            lines.append("- terminal:")
            for item in terminal[:10]:
                blocker = f" blockers={','.join(item['blockers'][:2])}" if item["blockers"] else ""
                lines.append(
                    f"  - {item['event_id']} ticket={item['ticket_id']} producer={item['producer_role']} "
                    f"state={item['state']} readiness={','.join(item['readiness_classes']) or 'none'}{blocker}"
                )
    domain_models = packet.get("domain_read_models", [])
    if domain_models:
        lines.append("- domain_read_models:")
        for item in domain_models:
            lines.append(
                f"  - {item['domain']}: status={item['status']} freshness={item['freshness']} "
                f"owner={item['owner']} blocker={item['first_blocker'] or 'none'} "
                f"action={item['next_action'] or 'none'}"
            )
    guardrail_lines = [
        "- uncommitted files in other worktrees are not deliverables",
        "- run handoff.py validate before consuming or integrating a discovered delivery",
        "- handoffs and manifests never unlock promotion, paper, live, private, or order actions",
    ]
    if packet.get("change_risk") == "demo_transport_hotfix":
        guardrail_lines.append(
            "- delivery_view: btc gate_impact=none only; legacy promotion blockers and domain read models omitted"
        )
    rendered = "\n".join([*lines, *guardrail_lines])
    if len(rendered) <= max_chars:
        return rendered
    suffix = "\n".join(
        ["- team_context_truncated: true", *guardrail_lines]
    )
    body_budget = max(0, max_chars - len(suffix) - 1)
    body = "\n".join(lines)[:body_budget].rstrip()
    return f"{body}\n{suffix}" if body else suffix[:max_chars]


def _resolve_states(entries: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    by_id = {entry["event"]["event_id"]: entry for entry in entries}
    published: dict[str, dict[str, Any]] = {}
    for entry in entries:
        event = entry["event"]
        if event["event_type"] == "published":
            published[event["event_id"]] = {
                **entry,
                "state": "published",
                "state_event_id": event["event_id"],
                "state_errors": [],
                "expired": _expired(event.get("expires_at", ""), now),
            }

    transitions = sorted(
        (entry for entry in entries if entry["event"]["event_type"] != "published"),
        key=lambda item: item["event"]["created_at"],
    )
    for entry in transitions:
        event = entry["event"]
        targets = list(event.get("supersedes", [])) if event["event_type"] == "superseded" else [event.get("transition_for", "")]
        for target_id in targets:
            target = published.get(target_id)
            if not target:
                entry.setdefault("transition_errors", []).append(f"handoff_transition_target_missing:{target_id}")
                continue
            authorization_error = _transition_authorization_error(target["event"], event)
            if authorization_error:
                target["state_errors"].append(authorization_error)
                continue
            target["state"] = event["event_type"]
            target["state_event_id"] = event["event_id"]
    for entry in entries:
        for error in entry.get("transition_errors", []):
            event_id = entry["event"].get("transition_for")
            if event_id in published:
                published[event_id]["state_errors"].append(error)
    return list(published.values())


_FASTPATH_DELIVERY_NOISE = (
    "deliverable_commit_not_integrated",
    "not_integrated_to_refs_heads_main",
    "promotion_artifact",
    "artifact_rebuild",
    "readmodel_refresh",
    "read_model_refresh",
)


def _derive_demo_fastpath_state(
    record: dict[str, Any],
    *,
    repo_root: Path,
    current_head: str,
) -> None:
    event = record["event"]
    if (
        record.get("state") not in {"published", "acknowledged"}
        or event.get("gate_impact") != "none"
        or event.get("promotion_eligible") is not False
        or not _is_ancestor(
            repo_root,
            str(event.get("deliverable_commit") or ""),
            current_head,
        )
    ):
        return
    event["blockers"] = [
        blocker
        for blocker in event.get("blockers", [])
        if not any(
            marker in str(blocker).casefold()
            for marker in _FASTPATH_DELIVERY_NOISE
        )
    ]
    record["state"] = "integrated_fastpath"
    record["state_event_id"] = event["event_id"]


def _is_ancestor(repo_root: Path, ancestor: str, descendant: str) -> bool:
    if not ancestor or not descendant:
        return False
    try:
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def _transition_authorization_error(published: Mapping[str, Any], transition: Mapping[str, Any]) -> str:
    event_type = transition["event_type"]
    role = transition["producer_role"]
    if event_type in {"acknowledged", "rejected"} and role not in published["consumer_roles"]:
        return f"handoff_transition_consumer_unauthorized:{transition['event_id']}"
    if event_type == "integrated" and role != "integrator":
        return f"handoff_integration_role_unauthorized:{transition['event_id']}"
    if event_type == "superseded" and role != published["producer_role"]:
        return f"handoff_supersede_role_unauthorized:{transition['event_id']}"
    return ""


def _shared_manifest_errors(record: Mapping[str, Any], repo_root: Path, shared_root: Path) -> list[str]:
    errors: list[str] = []
    event = record["event"]
    for item in event["deliverables"]:
        if item["type"] != "data_manifest":
            continue
        try:
            raw = subprocess.run(
                ["git", "show", f"{event['deliverable_commit']}:{item['path']}"],
                cwd=repo_root,
                check=True,
                capture_output=True,
            ).stdout
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise SharedDataError("shared_data_manifest_not_object")
            resolve_manifest_payload(payload, shared_root=shared_root, verify_files=False)
        except (OSError, subprocess.CalledProcessError, UnicodeDecodeError, json.JSONDecodeError, SharedDataError) as exc:
            errors.append(f"handoff_shared_data_unavailable:{item['path']}:{exc}")
    return errors


def _summarize_record(record: Mapping[str, Any]) -> dict[str, Any]:
    event = record["event"]
    return {
        "event_id": event["event_id"],
        "ticket_id": event["ticket_id"],
        "producer_role": event["producer_role"],
        "consumer_roles": event["consumer_roles"],
        "domain": event["domain"],
        "producer_branch": event["producer_branch"],
        "deliverable_commit": event["deliverable_commit"],
        "state": record["state"],
        "state_event_id": record["state_event_id"],
        "expired": record["expired"],
        "readiness_classes": sorted({item["readiness_class"] for item in event["deliverables"]}),
        "blockers": _dedupe([*event["blockers"], *record.get("state_errors", [])]),
        "gate_impact": event["gate_impact"],
        "promotion_eligible": event["promotion_eligible"],
        "path": record["path"],
        "observed_refs": record["observed_refs"],
    }


def _visible_to(record: Mapping[str, Any], consumer_role: str) -> bool:
    if consumer_role == "all":
        return True
    event = record["event"]
    return consumer_role == event["producer_role"] or consumer_role in event["consumer_roles"]


def _expired(value: str, now: datetime) -> bool:
    if not value:
        return False
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed < now


def _load_domain_read_models(
    repo_root: Path,
    *,
    current_head: str,
    btc_artifact_reader: BTCRuntimeArtifactReader | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for domain, candidates in DOMAIN_READ_MODELS.items():
        if domain == "btc":
            if btc_artifact_reader is None:
                rows.append(_unavailable_btc_domain_row(candidates[0]))
                continue
            try:
                payload = dict(
                    BTCPublishedDomainReadModelRepository(
                        repo_root=repo_root,
                        artifact_reader=btc_artifact_reader,
                    ).read_published(source_head=current_head)
                )
            except (
                BTCRuntimeArtifactStoreError,
                BTCPublishedDomainReadModelUnavailable,
            ):
                rows.append(
                    _unavailable_btc_domain_row(
                        candidates[0],
                        code="published_domain_read_model_unavailable",
                        action=(
                            "validate_external_owner_pointer_manifest_snapshot_"
                            "and_direct_current_head_contract"
                        ),
                    )
                )
                continue
            gate = (
                payload.get("gate", {})
                if isinstance(payload.get("gate"), Mapping)
                else {}
            )
            blocker = _first_blocker_detail(payload.get("blockers"))
            next_action = _domain_next_action(
                gate=gate,
                payload=payload,
                blocker=blocker,
            )
            rows.append(
                {
                    "domain": domain,
                    "path": candidates[0].as_posix(),
                    "status": str(payload.get("status") or "blocked"),
                    "freshness": str(payload.get("freshness") or "blocked"),
                    "owner": blocker["owner"],
                    "next_action": next_action,
                    "first_blocker": blocker["code"],
                    "first_blocker_detail": {
                        **blocker,
                        "next_executable_action": next_action,
                    },
                }
            )
            continue
        else:
            logical_path = None
            path = next(
                (
                    repo_root / item
                    for item in candidates
                    if (repo_root / item).is_file()
                ),
                None,
            )
        if path is None:
            rows.append(
                {
                    "domain": domain,
                    "path": candidates[0].as_posix(),
                    "status": "unavailable",
                    "freshness": "missing",
                    "owner": "",
                    "next_action": "Build the domain operator read model on the consuming branch.",
                    "first_blocker": "domain_read_model_missing",
                }
            )
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        commit = str(payload.get("code_commit") or payload.get("commit") or "") if isinstance(payload, Mapping) else ""
        freshness = "current_head" if commit and (current_head.startswith(commit) or commit.startswith(current_head)) else "stale_or_unknown"
        gate = payload.get("gate", {}) if isinstance(payload, Mapping) and isinstance(payload.get("gate"), Mapping) else {}
        blockers = payload.get("blockers", []) if isinstance(payload, Mapping) else []
        blocker = _first_blocker_detail(
            gate.get("first_blocker")
            or (blockers[0] if isinstance(blockers, list) and blockers else "")
        )
        next_action = _domain_next_action(
            gate=gate,
            payload=payload if isinstance(payload, Mapping) else {},
            blocker=blocker,
        )
        rows.append(
            {
                "domain": domain,
                "path": (
                    logical_path.as_posix()
                    if domain == "btc" and logical_path is not None
                    else path.relative_to(repo_root).as_posix()
                ),
                "status": str(payload.get("status") or payload.get("decision") or "unknown"),
                "freshness": freshness,
                "owner": str(
                    gate.get("owner")
                    or payload.get("owner")
                    or blocker["owner"]
                ),
                "next_action": next_action,
                "first_blocker": blocker["code"],
                "first_blocker_detail": {
                    **blocker,
                    "next_executable_action": next_action,
                },
            }
        )
    return rows


def _unavailable_btc_domain_row(
    logical_path: Path,
    *,
    code: str = "runtime_artifact_root_unavailable",
    action: str = (
        "restore_runtime_environment_then_continue_existing_retry_keep_code_frozen"
    ),
) -> dict[str, Any]:
    category = _blocker_category(code, "btc_operations")
    blocker = {
        "code": code,
        "category": category,
        "owner": "btc_operations",
        "next_executable_action": action,
    }
    return {
        "domain": "btc",
        "path": logical_path.as_posix(),
        "status": "unavailable",
        "freshness": "missing",
        "owner": blocker["owner"],
        "next_action": action,
        "first_blocker": code,
        "first_blocker_detail": blocker,
    }


def _first_blocker_detail(value: Any) -> dict[str, str]:
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, Mapping):
        code = str(value.get("code") or value.get("first_blocker") or "").strip()
        owner = str(value.get("owner") or "").strip()
        supplied_category = str(value.get("category") or "").strip()
        category = (
            supplied_category
            if supplied_category in BLOCKER_CATEGORIES
            else (
                "unclassified"
                if supplied_category
                else _blocker_category(code, owner)
            )
        )
        action = str(value.get("next_executable_action") or "").strip()
    else:
        raw = str(value or "").strip()
        owner = ""
        code = raw
        if raw.lower().startswith("owner:"):
            owner_token, _, remainder = raw.partition(" ")
            owner = owner_token.partition(":")[2].strip()
            code = remainder.strip() or raw
        category = _blocker_category(code, owner)
        action = ""
    if not code:
        return {
            "code": "",
            "category": "",
            "owner": owner,
            "next_executable_action": "",
        }
    owner = owner or _blocker_owner(category)
    safe_action = (
        action
        if action and _action_allowed_for_category(action, category)
        else _fallback_blocker_action(code, category)
    )
    return {
        "code": code,
        "category": category,
        "owner": owner,
        "next_executable_action": safe_action,
    }


def _domain_next_action(
    *,
    gate: Mapping[str, Any],
    payload: Mapping[str, Any],
    blocker: Mapping[str, str],
) -> str:
    category = str(blocker.get("category") or "unclassified")
    top_level = payload.get("next_executable_action")
    nested_action = (
        str(top_level.get("action") or "")
        if isinstance(top_level, Mapping)
        else ""
    )
    for candidate in (
        gate.get("next_action"),
        payload.get("next_action"),
        nested_action,
        blocker.get("next_executable_action"),
    ):
        text = str(candidate or "").strip()
        if text and _action_allowed_for_category(text, category):
            return text
    return _fallback_blocker_action(
        str(blocker.get("code") or "domain_read_model_blocked"),
        category,
    )


def _blocker_category(code: str, owner: str) -> str:
    lowered = f"{code} {owner}".lower()
    if any(
        token in lowered
        for token in (
            "dependency_missing",
            "missing_dependency",
            "import_error",
            "importerror",
            "module_not_found",
            "modulenotfound",
            "code_defect",
            "implementation_missing",
            "entrypoint_missing",
        )
    ):
        return "engineering"
    if any(
        token in lowered
        for token in (
            "w32time",
            "clock",
            "ntp",
            "time_round_trip",
            "time round trip",
            "offset",
            "rtt",
            "latency",
            "stratum",
            "leap3",
            "unsynchronized",
        )
    ):
        return "runtime_clock"
    if any(
        token in lowered
        for token in (
            "dns",
            "tls",
            "ssl",
            "network",
            "proxy",
            "connection_reset",
            "connection reset",
            "10054",
            "public_ws",
            "public websocket",
            "websocket_runtime",
            "runtime_artifact_root",
            "domain_read_model_unavailable",
        )
    ):
        return "runtime_network"
    if any(token in lowered for token in ("manual", "approval", "reviewer")):
        return "manual_approval"
    if any(
        token in lowered
        for token in (
            "natural",
            "observation",
            "coverage",
            "waiting_for",
            "wait_for",
        )
    ):
        return "natural_time"
    if "data_steward" in lowered or any(
        token in lowered for token in ("manifest", "data_", "snapshot")
    ):
        return "data_steward"
    if "integrator" in lowered or "wiring" in lowered:
        return "integrator"
    if "developer" in lowered or any(
        token in lowered
        for token in (
            "engineering",
            "schema_defect",
            "contract_defect",
            "deterministic_failure",
            "reproducible_failure",
        )
    ):
        return "engineering"
    return "unclassified"


def _blocker_owner(category: str) -> str:
    return {
        "runtime_clock": "runtime_operations",
        "runtime_network": "runtime_operations",
        "data_steward": "data_steward",
        "integrator": "integrator",
        "manual_approval": "architect/manual_reviewer",
        "natural_time": "btc_observation",
        "engineering": "btc_developer",
        "unclassified": "unassigned",
    }.get(category, "unassigned")


def _fallback_blocker_action(code: str, category: str) -> str:
    if category == "runtime_clock":
        return (
            "restore_clock_synchronization_then_continue_existing_retry_"
            "keep_code_frozen"
        )
    if category == "runtime_network":
        return (
            "restore_runtime_connectivity_then_continue_existing_retry_"
            "keep_code_frozen"
        )
    if category == "data_steward":
        return "wait_for_validated_immutable_data_handoff_then_rebuild_read_model"
    if category == "integrator":
        return "integrator_wire_committed_contract_then_rebuild_read_model"
    if category == "manual_approval":
        return "manual_reviewer_review_current_head_packet"
    if category == "natural_time":
        return "continue_observe_only_without_signal_or_threshold_changes"
    if category == "engineering":
        return f"resolve_engineering_blocker:{code}"
    return "triage_blocker_category_and_await_user_scope"


def _action_allowed_for_category(action: str, category: str) -> bool:
    if category == "engineering":
        return True
    if category == "unclassified":
        return False
    lowered = action.lower()
    engineering_markers = (
        "resolve_engineering_blocker",
        "create_engineering_ticket",
        "producer_ticket",
        "integration_ticket",
        "rebuild_gate",
        "rebuild_handoff",
    )
    return not any(marker in lowered for marker in engineering_markers)


def _git_text(repo_root: Path, *args: str, default: str = "") -> str:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return default


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a bounded read-only view of cross-agent state.")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--role", default="all")
    parser.add_argument(
        "--change-risk",
        default="unclassified",
        choices=CHANGE_RISKS,
    )
    parser.add_argument("--shared-data-root", type=Path)
    parser.add_argument("--max-events", type=int, default=20)
    parser.add_argument("--max-chars", type=int, default=7000)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        packet = build_team_context(
            repo_root=args.repo_root,
            consumer_role=args.role,
            change_risk=args.change_risk,
            max_events=max(1, args.max_events),
            shared_data_root=args.shared_data_root,
        )
    except (HandoffError, ValueError) as exc:
        packet = {
            "schema_version": SCHEMA_VERSION,
            "status": "unavailable",
            "blockers": [f"team_context_unavailable:{type(exc).__name__}:{exc}"],
            "guardrails": {"read_only": True, "promotion_unlock_allowed": False, "paper_or_live_unlock_allowed": False},
        }
        exit_code = 2
    else:
        exit_code = 2 if packet["invalid_handoffs"] else 0
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.format == "markdown":
        print(render_team_context(packet, max_chars=args.max_chars))
    else:
        print(json.dumps(packet, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
