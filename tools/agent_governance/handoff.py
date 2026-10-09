from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

MODULE_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(MODULE_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_REPO_ROOT))

from tools.agent_governance.git_metadata import GitMetadataError, read_ref_heads


SCHEMA_VERSION = "agent_handoff_envelope_v1"
HANDOFF_ROOT = Path(".agent/handoffs")
HANDOFF_ROOT_POSIX = HANDOFF_ROOT.as_posix()
EVENT_TYPES = {"published", "acknowledged", "integrated", "rejected", "superseded"}
ROLES = {
    "a_share_developer",
    "architect",
    "btc_developer",
    "data_steward",
    "integrator",
    "researcher",
    "super_developer",
}
WRITER_ROLES = {"a_share_developer", "btc_developer", "data_steward", "integrator", "super_developer"}
DOMAINS = {"btc", "cn_equity", "data", "governance", "research", "shared", "us_equity"}
DELIVERABLE_TYPES = {"artifact", "code", "data_manifest", "document", "report", "schema", "test_evidence"}
READINESS_CLASSES = {
    "quality_checked",
    "research_ready",
    "backtest_ready",
    "promotion_evidence_ready",
}
GATE_IMPACTS = {"none", "evidence_only", "requires_gate_rebuild", "blocks_gate"}
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")

# Handoff discovery runs from client hooks, so each Git child and the whole
# lightweight scan must be bounded independently.  ``subprocess.run`` kills
# the child on timeout; callers surface the timeout instead of manufacturing
# an empty discovery result.
# A short-ref ``cat-file`` lookup on the registered Windows checkout can spend
# most of this budget in ref DWIM.  Discovery therefore captures immutable
# commit ids first and queries ``<commit>:<path>`` without increasing either
# limit.  Callers still pass the remaining deadline to ``_run_git``.
GIT_COMMAND_TIMEOUT_SECONDS = 4.0
HANDOFF_DISCOVERY_TIMEOUT_SECONDS = 10.0

# Discovery is used on every hook invocation.  These caps are deliberately
# independent of the number of agent refs and are enforced before materializing
# any handoff payload.  They make malformed or unexpectedly large Git trees
# fail closed instead of turning a hook into an unbounded reader.
MAX_DISCOVERY_REFS = 512
MAX_DISCOVERY_TREE_OBJECTS = 4096
MAX_DISCOVERY_BLOB_OBJECTS = 4096
MAX_DISCOVERY_TREE_DEPTH = 4
MAX_DISCOVERY_SINGLE_BLOB_BYTES = 1024 * 1024
MAX_DISCOVERY_MATERIALIZED_BYTES = 32 * 1024 * 1024
CANONICAL_TREE_MODE = "40000"
CANONICAL_BLOB_MODES = {"100644", "100755"}


class HandoffError(ValueError):
    pass


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def validate_handoff(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {
        "schema_version",
        "event_id",
        "ticket_id",
        "event_type",
        "producer_role",
        "consumer_roles",
        "domain",
        "producer_branch",
        "base_commit",
        "deliverable_commit",
        "created_at",
        "expires_at",
        "depends_on",
        "supersedes",
        "transition_for",
        "deliverables",
        "tests",
        "blockers",
        "gate_impact",
        "promotion_eligible",
        "guardrails",
    }
    errors.extend(f"handoff_missing_field:{key}" for key in sorted(required - set(payload)))
    errors.extend(f"handoff_unknown_field:{key}" for key in sorted(set(payload) - required))
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append("handoff_schema_version_invalid")
    for key in ("event_id", "ticket_id"):
        if not ID_PATTERN.fullmatch(str(payload.get(key, ""))):
            errors.append(f"handoff_{key}_invalid")
    event_type = str(payload.get("event_type", ""))
    if event_type not in EVENT_TYPES:
        errors.append("handoff_event_type_invalid")
    role = str(payload.get("producer_role", ""))
    if role not in ROLES:
        errors.append("handoff_producer_role_invalid")
    if role in ROLES and role not in WRITER_ROLES:
        errors.append("handoff_read_only_role_cannot_publish")
    consumers = payload.get("consumer_roles")
    if not isinstance(consumers, list) or not consumers or any(item not in ROLES for item in consumers):
        errors.append("handoff_consumer_roles_invalid")
    elif len(consumers) != len(set(consumers)):
        errors.append("handoff_consumer_roles_duplicate")
    if payload.get("domain") not in DOMAINS:
        errors.append("handoff_domain_invalid")
    branch = str(payload.get("producer_branch", ""))
    if not branch.startswith(f"agent/{role}/"):
        errors.append("handoff_producer_branch_role_mismatch")
    for key in ("base_commit", "deliverable_commit"):
        if not COMMIT_PATTERN.fullmatch(str(payload.get(key, ""))):
            errors.append(f"handoff_{key}_invalid")
    if _parse_timestamp(str(payload.get("created_at", ""))) is None:
        errors.append("handoff_created_at_invalid")
    expires_at = str(payload.get("expires_at", ""))
    if expires_at and _parse_timestamp(expires_at) is None:
        errors.append("handoff_expires_at_invalid")
    elif expires_at:
        created = _parse_timestamp(str(payload.get("created_at", "")))
        expires = _parse_timestamp(expires_at)
        if created and expires and expires <= created:
            errors.append("handoff_expires_at_not_after_created_at")
    for key in ("depends_on", "supersedes"):
        values = payload.get(key)
        if not isinstance(values, list) or any(not ID_PATTERN.fullmatch(str(value)) for value in values):
            errors.append(f"handoff_{key}_invalid")
        elif len(values) != len(set(values)):
            errors.append(f"handoff_{key}_duplicate")
    transition_for = str(payload.get("transition_for", ""))
    if event_type in {"acknowledged", "integrated", "rejected"}:
        if not ID_PATTERN.fullmatch(transition_for):
            errors.append("handoff_transition_for_required")
    elif transition_for:
        errors.append("handoff_transition_for_unexpected")
    if event_type == "superseded" and not payload.get("supersedes"):
        errors.append("handoff_supersedes_required")

    deliverables = payload.get("deliverables")
    if not isinstance(deliverables, list):
        errors.append("handoff_deliverables_invalid")
        deliverables = []
    if event_type == "published" and not deliverables:
        errors.append("handoff_published_without_deliverables")
    for index, item in enumerate(deliverables):
        if not isinstance(item, Mapping):
            errors.append(f"handoff_deliverable_invalid:{index}")
            continue
        if item.get("type") not in DELIVERABLE_TYPES:
            errors.append(f"handoff_deliverable_type_invalid:{index}")
        if not _safe_repo_path(str(item.get("path", ""))):
            errors.append(f"handoff_deliverable_path_invalid:{index}")
        if not HASH_PATTERN.fullmatch(str(item.get("sha256", ""))):
            errors.append(f"handoff_deliverable_hash_invalid:{index}")
        if not str(item.get("schema_version", "")).strip():
            errors.append(f"handoff_deliverable_schema_version_missing:{index}")
        if item.get("readiness_class") not in READINESS_CLASSES:
            errors.append(f"handoff_deliverable_readiness_invalid:{index}")
        expected_keys = {"type", "path", "sha256", "schema_version", "readiness_class"}
        if set(item) != expected_keys:
            errors.append(f"handoff_deliverable_fields_invalid:{index}")

    tests = payload.get("tests")
    if not isinstance(tests, list):
        errors.append("handoff_tests_invalid")
    else:
        for index, item in enumerate(tests):
            if not isinstance(item, Mapping) or not str(item.get("command", "")).strip():
                errors.append(f"handoff_test_invalid:{index}")
            elif item.get("result") not in {"passed", "failed", "not_run"}:
                errors.append(f"handoff_test_result_invalid:{index}")
            elif set(item) != {"command", "result", "evidence_path"} or not isinstance(item.get("evidence_path"), str):
                errors.append(f"handoff_test_fields_invalid:{index}")
    if not isinstance(payload.get("blockers"), list) or any(not isinstance(item, str) for item in payload.get("blockers", [])):
        errors.append("handoff_blockers_invalid")
    if payload.get("gate_impact") not in GATE_IMPACTS:
        errors.append("handoff_gate_impact_invalid")
    if not isinstance(payload.get("promotion_eligible"), bool):
        errors.append("handoff_promotion_eligible_invalid")
    if payload.get("promotion_eligible") is True:
        readiness = {item.get("readiness_class") for item in deliverables if isinstance(item, Mapping)}
        if readiness != {"promotion_evidence_ready"} or payload.get("blockers"):
            errors.append("handoff_promotion_eligible_without_clean_evidence")

    guardrails = payload.get("guardrails")
    if not isinstance(guardrails, Mapping) or guardrails.get("handoff_only") is not True:
        errors.append("handoff_guardrails_invalid")
    else:
        expected_guardrails = {
            "handoff_only",
            "promotion_unlock_allowed",
            "paper_or_live_unlock_allowed",
            "private_endpoint_allowed",
            "order_endpoint_allowed",
            "real_order_submitted",
        }
        if set(guardrails) != expected_guardrails:
            errors.append("handoff_guardrail_fields_invalid")
        for key in (
            "promotion_unlock_allowed",
            "paper_or_live_unlock_allowed",
            "private_endpoint_allowed",
            "order_endpoint_allowed",
            "real_order_submitted",
        ):
            if guardrails.get(key) is not False:
                errors.append(f"handoff_safety_flag_invalid:{key}")
    return _dedupe(errors)


def validate_handoff_against_git(payload: Mapping[str, Any], *, repo_root: Path) -> list[str]:
    errors = validate_handoff(payload)
    if errors:
        return errors
    base = str(payload["base_commit"])
    deliverable_commit = str(payload["deliverable_commit"])
    producer_branch = str(payload["producer_branch"])
    if not _git_object_exists(repo_root, f"{base}^{{commit}}"):
        errors.append("handoff_base_commit_missing")
    if not _git_object_exists(repo_root, f"{deliverable_commit}^{{commit}}"):
        errors.append("handoff_deliverable_commit_missing")
        return errors
    if not _git_is_ancestor(repo_root, base, deliverable_commit):
        errors.append("handoff_base_not_ancestor_of_deliverable")
    if _git_ref_exists(repo_root, producer_branch) and not _git_is_ancestor(repo_root, deliverable_commit, producer_branch):
        errors.append("handoff_deliverable_not_on_producer_branch")
    for index, item in enumerate(payload["deliverables"]):
        path = str(item["path"])
        try:
            content = _git_bytes(repo_root, "show", f"{deliverable_commit}:{path}")
        except HandoffError:
            errors.append(f"handoff_deliverable_missing_at_commit:{index}:{path}")
            continue
        if sha256_bytes(content) != item["sha256"]:
            errors.append(f"handoff_deliverable_hash_mismatch:{index}:{path}")
    return _dedupe(errors)


def write_handoff(payload: Mapping[str, Any], *, repo_root: Path) -> Path:
    errors = validate_handoff_against_git(payload, repo_root=repo_root)
    if errors:
        raise HandoffError(";".join(errors))
    ticket = str(payload["ticket_id"])
    event_id = str(payload["event_id"])
    path = repo_root / HANDOFF_ROOT / ticket / f"{event_id}.json"
    if path.exists():
        raise HandoffError(f"handoff_event_already_exists:{event_id}")
    _write_json_atomic(path, payload)
    return path


def list_agent_refs(repo_root: Path) -> list[str]:
    return [item["branch"] for item in list_agent_ref_heads(repo_root)]


def list_agent_ref_heads(repo_root: Path) -> list[dict[str, str]]:
    try:
        refs = read_ref_heads(repo_root, prefix="refs/heads/agent/")
    except (OSError, GitMetadataError):
        output = _git_text(
            repo_root,
            "for-each-ref",
            "--format=%(refname:short)%09%(objectname)",
            "refs/heads/agent/",
        )
        refs = {}
        for line in output.splitlines():
            branch, separator, head = line.partition("\t")
            if separator:
                refs[f"refs/heads/{branch.strip()}"] = head.strip()
    return sorted(
        ({"branch": ref.removeprefix("refs/heads/"), "head": head} for ref, head in refs.items()),
        key=lambda item: item["branch"],
    )


def _deduplicate_scan_ref_heads(
    ref_heads: list[dict[str, str]],
) -> tuple[list[dict[str, str]], dict[str, list[str]]]:
    """Choose one canonical ref per commit root before bounded tree discovery.

    Agent branches are aliases for the same committed handoff tree surprisingly
    often.  Walking every alias spends the discovery budget on duplicate roots
    and can turn a healthy repository into a fail-closed empty context once the
    alias count crosses ``MAX_DISCOVERY_REFS``.  Keep the full ref list for
    reporting, but scan each unique commit root once and restore all aliases in
    ``observed_refs``.  The cap remains on unique roots, so a repository with
    more than the bounded number of distinct roots still fails closed.
    """

    by_head: dict[str, list[str]] = defaultdict(list)
    for item in ref_heads:
        branch = str(item.get("branch", ""))
        head = str(item.get("head", ""))
        by_head[head].append(branch)

    scan_ref_heads: list[dict[str, str]] = []
    aliases_by_scan_ref: dict[str, list[str]] = {}
    for head, branches in by_head.items():
        aliases = sorted(set(branches))
        if not aliases:
            continue
        canonical = aliases[0]
        scan_ref_heads.append({"branch": canonical, "head": head})
        aliases_by_scan_ref[canonical] = aliases

    scan_ref_heads.sort(key=lambda item: item["branch"])
    if len(scan_ref_heads) > MAX_DISCOVERY_REFS:
        raise HandoffError("handoff_discovery_ref_cap_exceeded")
    return scan_ref_heads, aliases_by_scan_ref


def _deduplicate_handoff_entries(
    ref_heads: list[dict[str, str]],
    entries: list[tuple[str, str, str]],
) -> tuple[list[dict[str, str]], dict[str, list[str]]]:
    """Select one ref per identical committed handoff-tree projection.

    A branch head is not a useful discovery identity: merged aliases often
    have different commit ids while carrying the same ``.agent/handoffs``
    tree.  The bounded index is therefore keyed by the exact path/blob
    projection discovered from that tree.  All aliases remain attached to
    the selected canonical ref so ``observed_refs`` preserves provenance.
    """

    entries_by_ref: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for ref, path, object_id in entries:
        entries_by_ref[ref].append((path, object_id))

    ref_by_name = {str(item.get("branch", "")): item for item in ref_heads}
    groups: dict[tuple[tuple[str, str], ...], list[str]] = defaultdict(list)
    for ref in sorted(ref_by_name):
        projection = tuple(sorted(entries_by_ref.get(ref, [])))
        if projection:
            groups[projection].append(ref)
    if len(groups) > MAX_DISCOVERY_REFS:
        raise HandoffError("handoff_discovery_ref_cap_exceeded")

    scan_ref_heads: list[dict[str, str]] = []
    aliases_by_scan_ref: dict[str, list[str]] = {}
    for aliases in groups.values():
        aliases = sorted(set(aliases))
        canonical = aliases[0]
        scan_ref_heads.append(ref_by_name[canonical])
        aliases_by_scan_ref[canonical] = aliases
    scan_ref_heads.sort(key=lambda item: item["branch"])
    return scan_ref_heads, aliases_by_scan_ref


def _main_ref_head(repo_root: Path) -> str:
    """Return the registered main head, failing closed when it is absent.

    Discovery is invoked from hooks, so reading the ref metadata avoids a
    per-ref Git process while still making the current main ref an explicit
    precondition for coverage.  The object is subsequently consumed by the
    bounded tree walk and final blob validation below.
    """

    try:
        heads = read_ref_heads(repo_root, prefix="refs/heads/")
    except (OSError, GitMetadataError):
        # The fallback is one bounded query, never one query per agent ref.
        output = _git_text(
            repo_root,
            "for-each-ref",
            "--format=%(refname:short)%09%(objectname)",
            "refs/heads/",
        )
        heads = {}
        for line in output.splitlines():
            branch, separator, head = line.partition("\t")
            if separator:
                heads[f"refs/heads/{branch.strip()}"] = head.strip()
    head = str(heads.get("refs/heads/main", ""))
    if not COMMIT_PATTERN.fullmatch(head):
        raise HandoffError("handoff_discovery_main_missing")
    return head


def _merged_agent_refs(
    repo_root: Path,
    ref_heads: list[dict[str, str]],
    *,
    main_head: str,
    deadline: float,
) -> set[str]:
    """Return agent refs merged into main using one bounded Git query.

    The query is deliberately independent of the handoff tree walk.  Its
    output is cross-checked against the already-read ref heads so a malformed
    or unexpected ref cannot be silently treated as covered.
    """

    known = {str(item.get("branch", "")): str(item.get("head", "")) for item in ref_heads}
    if not known:
        return set()
    output = _run_git(
        repo_root,
        "for-each-ref",
        f"--merged={main_head}",
        "--format=%(refname:strip=2)%09%(objectname)",
        "refs/heads/agent/",
        check=True,
        text=True,
        timeout=_remaining_timeout(deadline, "discovery"),
    ).stdout
    merged: set[str] = set()
    for line in output.splitlines():
        branch, separator, head = line.partition("\t")
        branch = branch.strip()
        head = head.strip()
        if not separator or branch not in known:
            raise HandoffError("handoff_discovery_merged_ref_invalid")
        if not COMMIT_PATTERN.fullmatch(head) or head != known[branch]:
            raise HandoffError("handoff_discovery_merged_ref_head_mismatch")
        merged.add(branch)
    return merged


def _assert_captured_ref_heads_unchanged(
    repo_root: Path,
    ref_heads: list[dict[str, str]],
    *,
    main_head: str,
    deadline: float,
) -> None:
    """Fail closed if branch metadata moved after the immutable snapshot."""

    _remaining_timeout(deadline, "discovery")
    expected = {
        str(item.get("branch", "")): str(item.get("head", ""))
        for item in ref_heads
    }
    current = {
        str(item.get("branch", "")): str(item.get("head", ""))
        for item in list_agent_ref_heads(repo_root)
    }
    current_main = _main_ref_head(repo_root)
    _remaining_timeout(deadline, "discovery")
    if current_main != main_head or current != expected:
        raise HandoffError("handoff_discovery_ref_heads_changed")


def scan_handoffs(repo_root: Path, *, verify_git: bool = True) -> dict[str, Any]:
    canonical: dict[str, dict[str, Any]] = {}
    invalid: list[dict[str, Any]] = []
    ref_heads = list_agent_ref_heads(repo_root)
    refs = [item["branch"] for item in ref_heads]
    deadline = time.monotonic() + HANDOFF_DISCOVERY_TIMEOUT_SECONDS
    # Main is an authoritative coverage source, not an agent alias.  Include
    # it in the same bounded tree walk so its projection and blobs are held to
    # the exact same parser/cap checks without starting a Git child per ref.
    main_head = _main_ref_head(repo_root)
    captured_heads = {
        str(item.get("branch", "")): str(item.get("head", ""))
        for item in ref_heads
    }
    if len(captured_heads) != len(ref_heads):
        raise HandoffError("handoff_discovery_ref_head_invalid")
    captured_heads["main"] = main_head
    merged_refs = _merged_agent_refs(
        repo_root,
        ref_heads,
        main_head=main_head,
        deadline=deadline,
    )
    root_by_ref, parsed_trees = _git_tree_handoff_index(
        repo_root,
        [*refs, "main"],
        captured_heads=captured_heads,
        deadline=deadline,
        enforce_ref_cap=False,
    )
    _assert_captured_ref_heads_unchanged(
        repo_root,
        ref_heads,
        main_head=main_head,
        deadline=deadline,
    )
    projection_cache: dict[str, tuple[tuple[str, str], ...]] = {}
    main_root = root_by_ref.get("main", "")
    main_projection = {
        (f"{HANDOFF_ROOT_POSIX}/{path}", object_id)
        for path, object_id in _handoff_tree_projection(main_root, parsed_trees, projection_cache)
    }
    main_observed_by_pair: dict[tuple[str, str], set[str]] = {
        pair: {"main"} for pair in main_projection
    }
    has_json_cache: dict[str, bool] = {}
    subset_cache: dict[tuple[str, str], bool] = {}
    covered_refs = {
        ref
        for ref in refs
        if ref in merged_refs
        and ref in root_by_ref
        and _handoff_tree_has_json(root_by_ref[ref], parsed_trees, has_json_cache)
        and _handoff_tree_projection_is_subset(
            root_by_ref[ref],
            main_root,
            parsed_trees,
            has_json_cache,
            subset_cache,
        )
    }
    covered_observed = _handoff_tree_grouped_observed(
        {ref: root_by_ref[ref] for ref in covered_refs},
        parsed_trees,
        deadline=deadline,
    )
    for pair, observed_refs in covered_observed.items():
        if pair not in main_projection:
            raise HandoffError("handoff_discovery_main_projection_conflict")
        main_observed_by_pair[pair].update(observed_refs)

    uncovered_ref_heads = [item for item in ref_heads if item["branch"] not in covered_refs]
    ref_by_name = {str(item.get("branch", "")): item for item in uncovered_ref_heads}
    projection_groups: dict[tuple[tuple[str, str], ...], list[str]] = defaultdict(list)
    for ref in sorted(ref_by_name):
        root_id = root_by_ref.get(ref, "")
        projection = tuple(
            (f"{HANDOFF_ROOT_POSIX}/{path}", object_id)
            for path, object_id in _handoff_tree_projection(root_id, parsed_trees, projection_cache)
        )
        if projection:
            projection_groups[projection].append(ref)
    if len(projection_groups) > MAX_DISCOVERY_REFS:
        raise HandoffError("handoff_discovery_ref_cap_exceeded")

    grouped: dict[tuple[str, str], set[str]] = {
        pair: set(observed_refs) for pair, observed_refs in main_observed_by_pair.items()
    }
    full_git_rows: list[tuple[str, str, str, list[str]]] = [
        ("main", path, object_id, sorted(observed_refs))
        for (path, object_id), observed_refs in main_observed_by_pair.items()
    ]
    for projection, group_refs in projection_groups.items():
        aliases = sorted(set(group_refs))
        canonical_ref = aliases[0]
        for path, object_id in projection:
            pair = (path, object_id)
            grouped.setdefault(pair, set()).update(aliases)
            # Full Git verification deliberately retains one source row per
            # distinct projection group.  Two different candidate trees may
            # share the same damaged blob; collapsing those rows would hide
            # one invalid source even though discovery-only may safely
            # materialize the immutable blob once.
            full_git_rows.append((canonical_ref, path, object_id, aliases))

    source_rows: list[tuple[str, str, str, list[str]]] = []
    for (path, object_id), observed_refs in grouped.items():
        ordered_refs = sorted(observed_refs)
        source_ref = "main" if "main" in observed_refs else ordered_refs[0]
        source_rows.append((source_ref, path, object_id, ordered_refs))
    source_rows.sort(key=lambda item: (0 if item[0] == "main" else 1, item[1], item[0]))

    if verify_git:
        # Preserve the original full-verification source order exactly: main
        # paths first, then candidate rows by canonical ref and path.  Event
        # conflict winners and invalid ordering are observable scan semantics.
        full_git_rows.sort(
            key=lambda item: (0, item[1], "")
            if item[0] == "main"
            else (1, item[0], item[1])
        )
        specs = [f"{ref}:{path}" for ref, path, _, _ in full_git_rows]
        blobs = _git_batch_bytes(repo_root, specs)
        sources = [
            (ref, path, observed_refs, blobs.get(f"{ref}:{path}"))
            for ref, path, _, observed_refs in full_git_rows
        ]
    else:
        # Discovery is deliberately metadata-first.  A single batch resolves
        # every ref's ``.agent/handoffs`` tree; bounded tree batches then walk
        # only that subtree and a final batch materializes each unique blob
        # once.  No Git child is started per ref.
        object_order: list[str] = []
        seen_objects: set[str] = set()
        for _, _, object_id, _ in source_rows:
            if object_id not in seen_objects:
                seen_objects.add(object_id)
                object_order.append(object_id)
        if len(object_order) > MAX_DISCOVERY_BLOB_OBJECTS:
            raise HandoffError("handoff_discovery_blob_cap_exceeded")
        blobs_by_object = _git_batch_objects(repo_root, object_order, deadline=deadline)
        if sum(len(raw or b"") for raw in blobs_by_object.values()) > MAX_DISCOVERY_MATERIALIZED_BYTES:
            raise HandoffError("handoff_discovery_materialized_bytes_exceeded")
        sources = [
            (ref, path, observed_refs, blobs_by_object.get(object_id))
            for ref, path, object_id, observed_refs in source_rows
        ]

    for ref, path, observed_refs, raw in sources:
        if path.endswith(".json"):
            try:
                spec = f"{ref}:{path}"
                if raw is None:
                    raise HandoffError(f"handoff_git_object_missing:{spec}")
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("not_object")
                event_id = str(payload.get("event_id", ""))
                digest = sha256_bytes(raw)
                if event_id in canonical:
                    if canonical[event_id]["content_sha256"] != digest:
                        invalid.append(
                            {
                                "ref": ref,
                                "path": path,
                                "event_id": event_id,
                                "errors": ["handoff_event_id_conflict"],
                            }
                        )
                    else:
                        canonical[event_id]["observed_refs"] = sorted(
                            set([*canonical[event_id]["observed_refs"], *observed_refs])
                        )
                    continue
                errors = (
                    validate_handoff_against_git(payload, repo_root=repo_root)
                    if verify_git
                    else validate_handoff(payload)
                )
            except (HandoffError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                invalid.append({"ref": ref, "path": path, "errors": [f"handoff_unreadable:{type(exc).__name__}:{exc}"]})
                continue
            if errors:
                invalid.append({"ref": ref, "path": path, "event_id": event_id, "errors": errors})
                continue
            canonical[event_id] = {
                "event": payload,
                "path": path,
                "content_sha256": digest,
                "observed_refs": sorted(observed_refs),
            }
    return {
        "events": list(canonical.values()),
        "invalid": invalid,
        "refs": refs,
        "ref_heads": ref_heads,
        "main_coverage": {
            "source_ref": "main",
            "covered_refs": sorted(covered_refs),
            "uncovered_refs": sorted(set(refs) - covered_refs),
            "main_projection_entries": len(main_projection),
        },
        "verification_mode": "full_git" if verify_git else "discovery_only",
    }


def handoff_template(
    *,
    event_id: str,
    ticket_id: str,
    event_type: str,
    producer_role: str,
    consumer_roles: list[str],
    domain: str,
    producer_branch: str,
    base_commit: str,
    deliverable_commit: str,
    deliverables: list[dict[str, Any]],
    tests: list[dict[str, Any]],
    blockers: list[str] | None = None,
    gate_impact: str = "none",
    promotion_eligible: bool = False,
    expires_at: str = "",
    depends_on: list[str] | None = None,
    supersedes: list[str] | None = None,
    transition_for: str = "",
    created_at: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "ticket_id": ticket_id,
        "event_type": event_type,
        "producer_role": producer_role,
        "consumer_roles": consumer_roles,
        "domain": domain,
        "producer_branch": producer_branch,
        "base_commit": base_commit,
        "deliverable_commit": deliverable_commit,
        "created_at": created_at or _utc_now(),
        "expires_at": expires_at,
        "depends_on": depends_on or [],
        "supersedes": supersedes or [],
        "transition_for": transition_for,
        "deliverables": deliverables,
        "tests": tests,
        "blockers": blockers or [],
        "gate_impact": gate_impact,
        "promotion_eligible": promotion_eligible,
        "guardrails": {
            "handoff_only": True,
            "promotion_unlock_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
        },
    }


def _safe_repo_path(value: str) -> bool:
    if not value or "\\" in value or value.startswith("/"):
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts and path.as_posix() == value


def _git_ref_exists(repo_root: Path, ref: str) -> bool:
    return _git_object_exists(repo_root, f"refs/heads/{ref}^{{commit}}")


def _git_tree_handoff_entries(
    repo_root: Path,
    refs: list[str],
    *,
    deadline: float,
    enforce_ref_cap: bool = True,
) -> list[tuple[str, str, str]]:
    """Return ``(ref, path, blob_oid)`` without materializing blob content.

    The old implementation invoked ``git ls-tree`` once for every ref.  This
    implementation resolves all ref/path expressions in one ``cat-file``
    batch, then walks the resulting handoff trees in a fixed number of
    depth-limited batches.  Shared tree objects are parsed once and their
    ref/path users are carried in memory, so the Git process count is bounded
    even when hundreds of refs point at the same commit.
    """

    root_by_ref, parsed_tree_cache = _git_tree_handoff_index(
        repo_root,
        refs,
        deadline=deadline,
        enforce_ref_cap=enforce_ref_cap,
    )
    if not root_by_ref:
        return []
    tree_users: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for ref, object_id in root_by_ref.items():
        tree_users[object_id][""].add(ref)

    entries: list[tuple[str, str, str]] = []
    for depth in range(MAX_DISCOVERY_TREE_DEPTH):
        if not tree_users:
            break
        # A cache hit must not bypass the discovery-wide deadline that the
        # corresponding Git batch would otherwise enforce.
        _remaining_timeout(deadline, "discovery")
        next_users: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        for object_id in sorted(tree_users):
            parsed = parsed_tree_cache[object_id]
            for prefix, prefix_refs in tree_users[object_id].items():
                for mode, name, child_id in parsed:
                    child_path = f"{prefix}/{name}" if prefix else name
                    if mode == CANONICAL_TREE_MODE:
                        next_users[child_id][child_path].update(prefix_refs)
                    elif mode in CANONICAL_BLOB_MODES and child_path.endswith(".json"):
                        path = f"{HANDOFF_ROOT_POSIX}/{child_path}"
                        entries.extend((ref, path, child_id) for ref in prefix_refs)
        tree_users = next_users
        if depth == MAX_DISCOVERY_TREE_DEPTH - 1 and tree_users:
            raise HandoffError("handoff_discovery_tree_depth_exceeded")
    return sorted(entries, key=lambda item: (item[1], item[0], item[2]))


def _git_tree_handoff_index(
    repo_root: Path,
    refs: list[str],
    *,
    captured_heads: Mapping[str, str] | None = None,
    deadline: float,
    enforce_ref_cap: bool = True,
) -> tuple[dict[str, str], dict[str, list[tuple[str, str, str]]]]:
    """Resolve ref roots and parse every reachable tree object exactly once."""

    if not refs:
        return {}, {}
    if enforce_ref_cap and len(refs) > MAX_DISCOVERY_REFS:
        raise HandoffError("handoff_discovery_ref_cap_exceeded")

    if captured_heads is None:
        root_specs = [f"{ref}:{HANDOFF_ROOT_POSIX}" for ref in refs]
    else:
        root_specs = []
        for ref in refs:
            head = str(captured_heads.get(ref, ""))
            if not COMMIT_PATTERN.fullmatch(head):
                raise HandoffError(f"handoff_discovery_ref_head_invalid:{ref}")
            root_specs.append(f"{head}:{HANDOFF_ROOT_POSIX}")
    root_rows = _git_batch_records(
        repo_root,
        root_specs,
        deadline=deadline,
        max_single_bytes=MAX_DISCOVERY_MATERIALIZED_BYTES,
        max_total_bytes=MAX_DISCOVERY_MATERIALIZED_BYTES,
    )
    root_by_ref: dict[str, str] = {}
    tree_raw_cache: dict[str, bytes] = {}
    for ref, spec in zip(refs, root_specs):
        object_id, object_type, raw = root_rows[spec]
        if object_type == "missing":
            continue
        if object_type != "tree" or raw is None:
            raise HandoffError(f"handoff_git_tree_root_invalid:{ref}")
        root_by_ref[ref] = object_id
        tree_raw_cache.setdefault(object_id, raw)

    materialized_bytes = sum(len(raw or b"") for _, _, raw in root_rows.values())
    if materialized_bytes > MAX_DISCOVERY_MATERIALIZED_BYTES:
        raise HandoffError("handoff_discovery_materialized_bytes_exceeded")
    seen_tree_object_ids = set(tree_raw_cache)
    if len(seen_tree_object_ids) > MAX_DISCOVERY_TREE_OBJECTS:
        raise HandoffError("handoff_discovery_tree_cap_exceeded")

    parsed_tree_cache: dict[str, list[tuple[str, str, str]]] = {}
    frontier = set(tree_raw_cache)
    for depth in range(MAX_DISCOVERY_TREE_DEPTH):
        if not frontier:
            break
        _remaining_timeout(deadline, "discovery")
        missing_object_ids = sorted(object_id for object_id in frontier if object_id not in tree_raw_cache)
        if missing_object_ids:
            fetched_trees = _git_batch_tree_objects(repo_root, missing_object_ids, deadline=deadline)
            for object_id in missing_object_ids:
                raw = fetched_trees.get(object_id)
                if raw is None:
                    raise HandoffError(f"handoff_git_tree_object_missing:{object_id}")
                tree_raw_cache[object_id] = raw
                materialized_bytes += len(raw)
                if materialized_bytes > MAX_DISCOVERY_MATERIALIZED_BYTES:
                    raise HandoffError("handoff_discovery_materialized_bytes_exceeded")
        next_frontier: set[str] = set()
        for object_id in sorted(frontier):
            parsed = parsed_tree_cache.get(object_id)
            if parsed is None:
                parsed = _parse_git_tree(tree_raw_cache[object_id])
                parsed_tree_cache[object_id] = parsed
            next_frontier.update(child_id for mode, _, child_id in parsed if mode == CANONICAL_TREE_MODE)
        seen_tree_object_ids.update(next_frontier)
        if len(seen_tree_object_ids) > MAX_DISCOVERY_TREE_OBJECTS:
            raise HandoffError("handoff_discovery_tree_cap_exceeded")
        if depth == MAX_DISCOVERY_TREE_DEPTH - 1 and next_frontier:
            raise HandoffError("handoff_discovery_tree_depth_exceeded")
        frontier = next_frontier
    return root_by_ref, parsed_tree_cache


def _handoff_tree_projection(
    root_id: str,
    parsed_trees: Mapping[str, list[tuple[str, str, str]]],
    cache: dict[str, tuple[tuple[str, str], ...]],
) -> tuple[tuple[str, str], ...]:
    """Return the JSON path/blob projection for one immutable tree root."""

    if not root_id:
        return ()
    cached = cache.get(root_id)
    if cached is not None:
        return cached
    projected: list[tuple[str, str]] = []
    for mode, name, child_id in parsed_trees[root_id]:
        if mode == CANONICAL_TREE_MODE:
            projected.extend(
                (f"{name}/{child_path}", object_id)
                for child_path, object_id in _handoff_tree_projection(child_id, parsed_trees, cache)
            )
        elif name.endswith(".json"):
            projected.append((name, child_id))
    value = tuple(sorted(projected))
    cache[root_id] = value
    return value


def _handoff_tree_has_json(
    root_id: str,
    parsed_trees: Mapping[str, list[tuple[str, str, str]]],
    cache: dict[str, bool],
) -> bool:
    if not root_id:
        return False
    cached = cache.get(root_id)
    if cached is not None:
        return cached
    result = any(
        _handoff_tree_has_json(child_id, parsed_trees, cache)
        if mode == CANONICAL_TREE_MODE
        else name.endswith(".json")
        for mode, name, child_id in parsed_trees[root_id]
    )
    cache[root_id] = result
    return result


def _handoff_tree_projection_is_subset(
    candidate_root: str,
    main_root: str,
    parsed_trees: Mapping[str, list[tuple[str, str, str]]],
    has_json_cache: dict[str, bool],
    cache: dict[tuple[str, str], bool],
) -> bool:
    """Compare JSON projections without expanding every ref into path tuples."""

    key = (candidate_root, main_root)
    cached = cache.get(key)
    if cached is not None:
        return cached
    if candidate_root == main_root:
        cache[key] = True
        return True
    if not candidate_root:
        cache[key] = True
        return True
    if not main_root:
        result = not _handoff_tree_has_json(candidate_root, parsed_trees, has_json_cache)
        cache[key] = result
        return result

    main_by_name = {name: (mode, child_id) for mode, name, child_id in parsed_trees[main_root]}
    result = True
    for mode, name, child_id in parsed_trees[candidate_root]:
        if mode == CANONICAL_TREE_MODE:
            if not _handoff_tree_has_json(child_id, parsed_trees, has_json_cache):
                continue
            main_entry = main_by_name.get(name)
            if main_entry is None or main_entry[0] != CANONICAL_TREE_MODE:
                result = False
                break
            if not _handoff_tree_projection_is_subset(
                child_id,
                main_entry[1],
                parsed_trees,
                has_json_cache,
                cache,
            ):
                result = False
                break
        elif name.endswith(".json"):
            main_entry = main_by_name.get(name)
            if main_entry is None or main_entry[0] == CANONICAL_TREE_MODE or main_entry[1] != child_id:
                result = False
                break
    cache[key] = result
    return result


def _handoff_tree_grouped_observed(
    root_by_ref: Mapping[str, str],
    parsed_trees: Mapping[str, list[tuple[str, str, str]]],
    *,
    deadline: float,
) -> dict[tuple[str, str], set[str]]:
    """Project many refs while sharing prefix work for identical tree users."""

    tree_users: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for ref, root_id in root_by_ref.items():
        tree_users[root_id][""].add(ref)
    observed: dict[tuple[str, str], set[str]] = defaultdict(set)
    for depth in range(MAX_DISCOVERY_TREE_DEPTH):
        if not tree_users:
            break
        _remaining_timeout(deadline, "discovery")
        next_users: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        for object_id in sorted(tree_users):
            for prefix, prefix_refs in tree_users[object_id].items():
                for mode, name, child_id in parsed_trees[object_id]:
                    child_path = f"{prefix}/{name}" if prefix else name
                    if mode == CANONICAL_TREE_MODE:
                        next_users[child_id][child_path].update(prefix_refs)
                    elif child_path.endswith(".json"):
                        observed[(f"{HANDOFF_ROOT_POSIX}/{child_path}", child_id)].update(prefix_refs)
        tree_users = next_users
        if depth == MAX_DISCOVERY_TREE_DEPTH - 1 and tree_users:
            raise HandoffError("handoff_discovery_tree_depth_exceeded")
    return observed


def _git_batch_objects(
    repo_root: Path,
    object_ids: list[str],
    *,
    deadline: float,
) -> dict[str, bytes | None]:
    """Read each unique Git blob object once after metadata grouping."""

    if not object_ids:
        return {}
    if len(object_ids) > MAX_DISCOVERY_BLOB_OBJECTS:
        raise HandoffError("handoff_discovery_blob_cap_exceeded")
    records = _git_batch_records(
        repo_root,
        object_ids,
        deadline=deadline,
        expected_type="blob",
        max_single_bytes=MAX_DISCOVERY_SINGLE_BLOB_BYTES,
        max_total_bytes=MAX_DISCOVERY_MATERIALIZED_BYTES,
    )
    return {object_id: (row[2] if row[1] != "missing" else None) for object_id, row in records.items()}


def _git_batch_tree_objects(
    repo_root: Path,
    object_ids: list[str],
    *,
    deadline: float,
) -> dict[str, bytes | None]:
    records = _git_batch_records(
        repo_root,
        object_ids,
        deadline=deadline,
        expected_type="tree",
        max_single_bytes=MAX_DISCOVERY_MATERIALIZED_BYTES,
        max_total_bytes=MAX_DISCOVERY_MATERIALIZED_BYTES,
    )
    return {object_id: (row[2] if row[1] != "missing" else None) for object_id, row in records.items()}


def _git_batch_records(
    repo_root: Path,
    specs: list[str],
    *,
    deadline: float,
    expected_type: str | None = None,
    max_single_bytes: int | None = None,
    max_total_bytes: int | None = None,
) -> dict[str, tuple[str, str, bytes | None]]:
    """Read Git objects/specs in one bounded ``cat-file --batch`` child.

    Rows contain ``(resolved_object_id, object_type, content)``.  Missing
    specs are represented as ``("", "missing", None)`` and are handled by
    callers as absent ref trees or missing blobs.  Size limits are checked
    from the batch header before slicing content.
    """

    if not specs:
        return {}
    timeout = _remaining_timeout(deadline, "discovery")
    result = _run_git(
        repo_root,
        "cat-file",
        "--batch",
        input=("\n".join(specs) + "\n").encode("utf-8"),
        check=True,
        timeout=timeout,
    )
    output = result.stdout
    cursor = 0
    total_bytes = 0
    rows: dict[str, tuple[str, str, bytes | None]] = {}
    for spec in specs:
        newline = output.find(b"\n", cursor)
        if newline < 0:
            raise HandoffError("handoff_git_batch_header_missing")
        header = output[cursor:newline].decode("ascii", errors="replace")
        cursor = newline + 1
        parts = header.split(" ")
        if len(parts) == 2 and parts[1] == "missing":
            rows[spec] = ("", "missing", None)
            continue
        if len(parts) != 3:
            raise HandoffError(f"handoff_git_batch_object_invalid:{spec}:{header}")
        object_id, object_type, size_text = parts
        if not COMMIT_PATTERN.fullmatch(object_id):
            raise HandoffError(f"handoff_git_batch_object_invalid:{spec}:{header}")
        if expected_type and object_type != expected_type:
            raise HandoffError(f"handoff_git_batch_object_type_invalid:{spec}:{object_type}")
        try:
            size = int(size_text)
        except ValueError as exc:
            raise HandoffError(f"handoff_git_batch_size_invalid:{spec}") from exc
        if size < 0:
            raise HandoffError(f"handoff_git_batch_size_invalid:{spec}")
        if max_single_bytes is not None and size > max_single_bytes:
            raise HandoffError(f"handoff_discovery_single_blob_bytes_exceeded:{spec}")
        total_bytes += size
        if max_total_bytes is not None and total_bytes > max_total_bytes:
            raise HandoffError("handoff_discovery_materialized_bytes_exceeded")
        content = output[cursor : cursor + size]
        cursor += size
        if len(content) != size or output[cursor : cursor + 1] != b"\n":
            raise HandoffError(f"handoff_git_batch_delimiter_invalid:{spec}")
        cursor += 1
        rows[spec] = (object_id, object_type, content)
    return rows


def _parse_git_tree(raw: bytes) -> list[tuple[str, str, str]]:
    """Parse raw Git tree bytes into ``(mode, name, object_id)`` entries."""

    entries: list[tuple[str, str, str]] = []
    cursor = 0
    while cursor < len(raw):
        space = raw.find(b" ", cursor)
        nul = raw.find(b"\0", space + 1)
        if space <= cursor or nul < 0 or nul + 21 > len(raw):
            raise HandoffError("handoff_git_tree_entry_invalid")
        mode_raw = raw[cursor:space]
        if mode_raw == b"40000":
            mode = CANONICAL_TREE_MODE
        elif mode_raw == b"100644":
            mode = "100644"
        elif mode_raw == b"100755":
            mode = "100755"
        else:
            mode = mode_raw.decode("ascii", errors="replace")
            raise HandoffError(f"handoff_git_tree_mode_invalid:{mode}")
        try:
            name = raw[space + 1 : nul].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HandoffError("handoff_git_tree_entry_not_utf8") from exc
        if "/" in name or name in {"", ".", ".."}:
            raise HandoffError("handoff_git_tree_entry_path_invalid")
        object_id_raw = raw[nul + 1 : nul + 21]
        if len(object_id_raw) != 20:
            raise HandoffError("handoff_git_tree_object_id_invalid")
        # ``bytes.hex`` is canonical lowercase hexadecimal by construction;
        # avoid compiling and running a redundant regex for every tree entry.
        object_id = object_id_raw.hex()
        entries.append((mode, name, object_id))
        cursor = nul + 21
    return entries


def _git_tree_handoff_paths(repo_root: Path, refs: list[str]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for ref in refs:
        output = _git_text(
            repo_root,
            "ls-tree",
            "-r",
            "--name-only",
            ref,
            "--",
            HANDOFF_ROOT.as_posix(),
        )
        rows.extend((ref, path) for path in output.splitlines() if path.endswith(".json"))
    return sorted(rows)


def _git_object_exists(repo_root: Path, value: str) -> bool:
    result = _run_git(repo_root, "cat-file", "-e", value, check=False)
    return result.returncode == 0


def _git_is_ancestor(repo_root: Path, ancestor: str, descendant: str) -> bool:
    result = _run_git(
        repo_root,
        "merge-base",
        "--is-ancestor",
        ancestor,
        descendant,
        check=False,
    )
    return result.returncode == 0


def _git_text(repo_root: Path, *args: str) -> str:
    return _run_git(repo_root, *args, check=True, text=True).stdout.strip()


def _git_bytes(repo_root: Path, *args: str, timeout: float | None = None) -> bytes:
    return _run_git(repo_root, *args, check=True, timeout=timeout).stdout


def _git_batch_bytes(repo_root: Path, specs: list[str]) -> dict[str, bytes | None]:
    if not specs:
        return {}
    result = _run_git(
        repo_root,
        "cat-file",
        "--batch",
        input=("\n".join(specs) + "\n").encode("utf-8"),
        check=True,
    )

    output = result.stdout
    cursor = 0
    rows: dict[str, bytes | None] = {}
    for spec in specs:
        newline = output.find(b"\n", cursor)
        if newline < 0:
            raise HandoffError("handoff_git_batch_header_missing")
        header = output[cursor:newline].decode("utf-8", errors="replace")
        cursor = newline + 1
        if header.endswith(" missing"):
            rows[spec] = None
            continue
        parts = header.rsplit(" ", 2)
        if len(parts) != 3 or parts[1] != "blob":
            raise HandoffError(f"handoff_git_batch_object_invalid:{spec}:{header}")
        try:
            size = int(parts[2])
        except ValueError as exc:
            raise HandoffError(f"handoff_git_batch_size_invalid:{spec}") from exc
        content = output[cursor : cursor + size]
        cursor += size
        if output[cursor : cursor + 1] != b"\n":
            raise HandoffError(f"handoff_git_batch_delimiter_invalid:{spec}")
        cursor += 1
        rows[spec] = content
    return rows


def _run_git(
    repo_root: Path,
    *args: str,
    input: bytes | None = None,
    check: bool = False,
    text: bool = False,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    requested_timeout = GIT_COMMAND_TIMEOUT_SECONDS if timeout is None else timeout
    try:
        command_timeout = float(requested_timeout)
    except (TypeError, ValueError):
        command_timeout = 0.0
    if not math.isfinite(command_timeout) or command_timeout <= 0:
        raise HandoffError(f"handoff_git_timeout:{args[0] if args else 'unknown'}")
    # Explicit callers cannot bypass the per-child bound.  Discovery supplies
    # a smaller remaining deadline when one is closer to expiry.
    command_timeout = min(command_timeout, GIT_COMMAND_TIMEOUT_SECONDS)
    kwargs: dict[str, Any] = {
        "cwd": repo_root,
        "input": input,
        "check": check,
        "capture_output": True,
        "timeout": command_timeout,
    }
    if text:
        kwargs.update({"text": True, "encoding": "utf-8"})
    try:
        return subprocess.run(["git", *args], **kwargs)
    except subprocess.TimeoutExpired as exc:
        raise HandoffError(f"handoff_git_timeout:{args[0] if args else 'unknown'}") from exc
    except (OSError, subprocess.CalledProcessError) as exc:
        raise HandoffError(f"handoff_git_command_failed:{args[0] if args else 'unknown'}") from exc


def _remaining_timeout(deadline: float, operation: str) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise HandoffError(f"handoff_{operation}_timeout")
    return min(GIT_COMMAND_TIMEOUT_SECONDS, remaining)


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate, emit, or scan append-only cross-agent handoffs.")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--input", type=Path, required=True)
    emit = subparsers.add_parser("emit")
    emit.add_argument("--input", type=Path, required=True)
    subparsers.add_parser("scan")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    try:
        if args.command == "scan":
            output = scan_handoffs(repo_root)
            exit_code = 2 if output["invalid"] else 0
        else:
            payload = json.loads(args.input.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise HandoffError("handoff_input_not_object")
            errors = validate_handoff_against_git(payload, repo_root=repo_root)
            if errors:
                raise HandoffError(";".join(errors))
            if args.command == "emit":
                path = write_handoff(payload, repo_root=repo_root)
                output = {"status": "emitted", "path": path.relative_to(repo_root).as_posix(), "event_id": payload["event_id"]}
            else:
                output = {"status": "valid", "event_id": payload["event_id"]}
            exit_code = 0
    except (OSError, json.JSONDecodeError, HandoffError) as exc:
        output = {"status": "blocked", "blockers": str(exc).split(";")}
        exit_code = 2
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
