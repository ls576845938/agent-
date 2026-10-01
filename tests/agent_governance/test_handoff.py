from __future__ import annotations

import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import tools.agent_governance.handoff as handoff_module

from tools.agent_governance.handoff import (
    handoff_template,
    scan_handoffs,
    validate_handoff,
    validate_handoff_against_git,
    write_handoff,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((REPO_ROOT / "schemas" / "agent_handoff_envelope.schema.json").read_text(encoding="utf-8"))


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _raw_tree(*entries: tuple[str, str, str]) -> bytes:
    return b"".join(
        mode.encode("ascii") + b" " + name.encode("utf-8") + b"\0" + bytes.fromhex(object_id)
        for mode, name, object_id in entries
    )


def _repo(tmp_path: Path) -> tuple[Path, str, str, bytes]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "Tests")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-b", "agent/data_steward/dataset")
    manifest = b'{"schema_version":"fixture_manifest_v1"}\n'
    path = repo / ".agent" / "data_manifests" / "fixture" / "v1.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(manifest)
    _git(repo, "add", path.relative_to(repo).as_posix())
    _git(repo, "commit", "-m", "publish manifest")
    deliverable = _git(repo, "rev-parse", "HEAD")
    return repo, base, deliverable, manifest


def _published_payload(base: str, deliverable: str, content: bytes, *, event_id: str = "data-ready-001") -> dict[str, object]:
    return handoff_template(
        event_id=event_id,
        ticket_id="data-ticket-001",
        event_type="published",
        producer_role="data_steward",
        consumer_roles=["super_developer", "researcher"],
        domain="data",
        producer_branch="agent/data_steward/dataset",
        base_commit=base,
        deliverable_commit=deliverable,
        deliverables=[
            {
                "type": "document",
                "path": ".agent/data_manifests/fixture/v1.json",
                "sha256": hashlib.sha256(content).hexdigest(),
                "schema_version": "fixture_manifest_v1",
                "readiness_class": "research_ready",
            }
        ],
        tests=[{"command": "pytest data contract", "result": "passed", "evidence_path": ""}],
        blockers=[],
        gate_impact="evidence_only",
        promotion_eligible=False,
        created_at="2026-07-12T00:00:00Z",
    )


def test_committed_handoff_is_cross_branch_visible_but_uncommitted_event_is_not(tmp_path: Path) -> None:
    repo, base, deliverable, content = _repo(tmp_path)
    payload = _published_payload(base, deliverable, content)
    Draft202012Validator(SCHEMA).validate(payload)
    assert validate_handoff(payload) == []
    assert validate_handoff_against_git(payload, repo_root=repo) == []

    event_path = write_handoff(payload, repo_root=repo)
    assert scan_handoffs(repo)["events"] == []
    _git(repo, "add", event_path.relative_to(repo).as_posix())
    _git(repo, "commit", "-m", "publish handoff")
    _git(repo, "branch", "agent/super_developer/copied-handoff")

    _git(repo, "checkout", "main")
    scan = scan_handoffs(repo)
    assert not scan["invalid"]
    assert [item["event"]["event_id"] for item in scan["events"]] == ["data-ready-001"]
    assert scan["events"][0]["observed_refs"] == [
        "agent/data_steward/dataset",
        "agent/super_developer/copied-handoff",
    ]
    discovery = scan_handoffs(repo, verify_git=False)
    assert not discovery["invalid"]
    assert discovery["events"][0]["observed_refs"] == scan["events"][0]["observed_refs"]
    assert not (repo / event_path.relative_to(repo)).exists()


def test_handoff_rejects_hash_role_and_promotion_misrepresentation(tmp_path: Path) -> None:
    repo, base, deliverable, content = _repo(tmp_path)
    payload = _published_payload(base, deliverable, content)
    payload["deliverables"][0]["sha256"] = "0" * 64  # type: ignore[index]
    assert any("hash_mismatch" in error for error in validate_handoff_against_git(payload, repo_root=repo))

    payload = _published_payload(base, deliverable, content)
    payload["producer_role"] = "architect"
    assert "handoff_read_only_role_cannot_publish" in validate_handoff(payload)

    payload = _published_payload(base, deliverable, content)
    payload["promotion_eligible"] = True
    assert "handoff_promotion_eligible_without_clean_evidence" in validate_handoff(payload)


def test_handoff_accepts_a_share_writer_and_cn_equity_domain(tmp_path: Path) -> None:
    _, base, deliverable, content = _repo(tmp_path)
    payload = _published_payload(base, deliverable, content)
    payload["producer_role"] = "a_share_developer"
    payload["producer_branch"] = "agent/a_share_developer/a-share-development-v1"
    payload["consumer_roles"] = ["data_steward", "architect"]
    payload["domain"] = "cn_equity"

    Draft202012Validator(SCHEMA).validate(payload)
    assert validate_handoff(payload) == []


def test_discovery_reports_divergent_event_content_across_agent_refs(tmp_path: Path) -> None:
    repo, base, deliverable, content = _repo(tmp_path)
    payload = _published_payload(base, deliverable, content)
    event_path = write_handoff(payload, repo_root=repo)
    _git(repo, "add", event_path.relative_to(repo).as_posix())
    _git(repo, "commit", "-m", "publish handoff")

    _git(repo, "checkout", "-b", "agent/super_developer/divergent-handoff")
    payload["blockers"] = ["divergent_copy_must_not_be_hidden"]
    event_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _git(repo, "add", event_path.relative_to(repo).as_posix())
    _git(repo, "commit", "-m", "diverge handoff")
    _git(repo, "checkout", "main")

    scan = scan_handoffs(repo, verify_git=False)
    assert len(scan["events"]) == 1
    assert any("handoff_event_id_conflict" in item["errors"] for item in scan["invalid"])


def test_discovery_materializes_shared_blob_once_across_refs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo, base, deliverable, content = _repo(tmp_path)
    payload = _published_payload(base, deliverable, content, event_id="shared-blob-001")
    event_path = write_handoff(payload, repo_root=repo)
    _git(repo, "add", event_path.relative_to(repo).as_posix())
    _git(repo, "commit", "-m", "publish shared handoff")
    _git(repo, "branch", "agent/super_developer/shared-copy")
    _git(repo, "checkout", "main")

    calls: list[tuple[str, ...]] = []
    original = handoff_module._git_batch_objects

    def spy(repo_root: Path, object_ids: list[str], *, deadline: float) -> dict[str, bytes | None]:
        calls.append(tuple(object_ids))
        return original(repo_root, object_ids, deadline=deadline)

    monkeypatch.setattr(handoff_module, "_git_batch_objects", spy)

    scan = scan_handoffs(repo, verify_git=False)

    assert not scan["invalid"]
    assert [item["event"]["event_id"] for item in scan["events"]] == ["shared-blob-001"]
    assert scan["events"][0]["observed_refs"] == [
        "agent/data_steward/dataset",
        "agent/super_developer/shared-copy",
    ]
    assert len(calls) == 1
    assert len(calls[0]) == 1


def test_tree_discovery_reuses_root_object_without_second_git_batch(monkeypatch) -> None:
    root_id = "a" * 40
    blob_id = "b" * 40
    root_raw = b"100644 event.json\0" + bytes.fromhex(blob_id)
    root_specs = [
        f"agent/data_steward/one:{handoff_module.HANDOFF_ROOT.as_posix()}",
        f"agent/super_developer/two:{handoff_module.HANDOFF_ROOT.as_posix()}",
    ]
    parse_calls: list[bytes] = []
    original_parse = handoff_module._parse_git_tree

    def root_rows(repo_root, specs, **kwargs):
        assert specs == root_specs
        return {spec: (root_id, "tree", root_raw) for spec in specs}

    def no_root_reread(repo_root, object_ids, *, deadline):
        pytest.fail(f"root tree was read twice: {object_ids}")

    def capture_parse(raw: bytes):
        parse_calls.append(raw)
        return original_parse(raw)

    monkeypatch.setattr(handoff_module, "_git_batch_records", root_rows)
    monkeypatch.setattr(handoff_module, "_git_batch_tree_objects", no_root_reread)
    monkeypatch.setattr(handoff_module, "_parse_git_tree", capture_parse)

    entries = handoff_module._git_tree_handoff_entries(
        Path("unused"),
        ["agent/data_steward/one", "agent/super_developer/two"],
        deadline=handoff_module.time.monotonic() + 1.0,
    )

    assert entries == [
        ("agent/data_steward/one", ".agent/handoffs/event.json", blob_id),
        ("agent/super_developer/two", ".agent/handoffs/event.json", blob_id),
    ]
    assert parse_calls == [root_raw]


def test_tree_discovery_groups_alias_root_users_without_reparsing(monkeypatch) -> None:
    root_id = "a" * 40
    blob_id = "b" * 40
    root_raw = _raw_tree(("100644", "event.json", blob_id))
    refs = [f"agent/super_developer/alias-{index:04d}" for index in range(256)]
    root_specs = [f"{ref}:{handoff_module.HANDOFF_ROOT.as_posix()}" for ref in refs]
    observed_specs: list[str] = []
    parse_calls: list[bytes] = []
    original_parse = handoff_module._parse_git_tree

    def resolve_roots(repo_root, specs, **kwargs):
        observed_specs.extend(specs)
        return {spec: (root_id, "tree", root_raw) for spec in specs}

    def no_child_fetch(repo_root, object_ids, *, deadline):
        pytest.fail(f"leaf-only root must not fetch child trees: {object_ids}")

    def capture_parse(raw: bytes):
        parse_calls.append(raw)
        return original_parse(raw)

    monkeypatch.setattr(handoff_module, "_git_batch_records", resolve_roots)
    monkeypatch.setattr(handoff_module, "_git_batch_tree_objects", no_child_fetch)
    monkeypatch.setattr(handoff_module, "_parse_git_tree", capture_parse)

    entries = handoff_module._git_tree_handoff_entries(
        Path("unused"), refs, deadline=handoff_module.time.monotonic() + 1.0
    )

    assert observed_specs == root_specs
    assert parse_calls == [root_raw]
    assert entries == [
        (ref, ".agent/handoffs/event.json", blob_id)
        for ref in refs
    ]


def test_tree_discovery_materialized_byte_cap_counts_cached_root_only_when_read(monkeypatch) -> None:
    root_id = "a" * 40
    blob_id = "b" * 40
    root_raw = _raw_tree(("100644", "event.json", blob_id))
    refs = ["agent/data_steward/one", "agent/super_developer/two"]

    monkeypatch.setattr(
        handoff_module,
        "_git_batch_records",
        lambda repo_root, specs, **kwargs: {spec: (root_id, "tree", root_raw) for spec in specs},
    )
    monkeypatch.setattr(
        handoff_module,
        "_git_batch_tree_objects",
        lambda *args, **kwargs: pytest.fail("cached root must not be materialized again"),
    )

    actual_root_batch_bytes = len(root_raw) * len(refs)
    monkeypatch.setattr(handoff_module, "MAX_DISCOVERY_MATERIALIZED_BYTES", actual_root_batch_bytes)
    assert len(
        handoff_module._git_tree_handoff_entries(
            Path("unused"), refs, deadline=handoff_module.time.monotonic() + 1.0
        )
    ) == 2

    monkeypatch.setattr(handoff_module, "MAX_DISCOVERY_MATERIALIZED_BYTES", actual_root_batch_bytes - 1)
    with pytest.raises(handoff_module.HandoffError, match="handoff_discovery_materialized_bytes_exceeded"):
        handoff_module._git_tree_handoff_entries(
            Path("unused"), refs, deadline=handoff_module.time.monotonic() + 1.0
        )


def test_tree_discovery_counts_unique_tree_objects_across_depths(monkeypatch) -> None:
    root_id = "a" * 40
    child_id = "b" * 40
    parent_id = "c" * 40
    blob_id = "d" * 40
    root_raw = _raw_tree(
        ("40000", "direct", child_id),
        ("40000", "nested", parent_id),
    )
    child_raw = _raw_tree(("100644", "event.json", blob_id))
    parent_raw = _raw_tree(("40000", "repeated", child_id))
    batches: list[tuple[str, ...]] = []

    monkeypatch.setattr(
        handoff_module,
        "_git_batch_records",
        lambda repo_root, specs, **kwargs: {spec: (root_id, "tree", root_raw) for spec in specs},
    )

    def fetch(repo_root, object_ids, *, deadline):
        batches.append(tuple(object_ids))
        available = {child_id: child_raw, parent_id: parent_raw}
        return {object_id: available[object_id] for object_id in object_ids}

    monkeypatch.setattr(handoff_module, "_git_batch_tree_objects", fetch)
    monkeypatch.setattr(handoff_module, "MAX_DISCOVERY_TREE_OBJECTS", 3)

    entries = handoff_module._git_tree_handoff_entries(
        Path("unused"), ["agent/data_steward/one"], deadline=handoff_module.time.monotonic() + 1.0
    )

    assert entries == [
        ("agent/data_steward/one", ".agent/handoffs/direct/event.json", blob_id),
        ("agent/data_steward/one", ".agent/handoffs/nested/repeated/event.json", blob_id),
    ]
    assert batches == [(child_id, parent_id)]


def test_tree_discovery_depth_cap_still_fails_with_cached_objects(monkeypatch) -> None:
    tree_ids = [f"{value:040x}" for value in range(1, 6)]
    tree_raw = {
        tree_ids[index]: _raw_tree(("40000", f"level-{index + 1}", tree_ids[index + 1]))
        for index in range(4)
    }
    tree_raw[tree_ids[-1]] = _raw_tree(("100644", "event.json", "f" * 40))
    monkeypatch.setattr(
        handoff_module,
        "_git_batch_records",
        lambda repo_root, specs, **kwargs: {
            spec: (tree_ids[0], "tree", tree_raw[tree_ids[0]]) for spec in specs
        },
    )
    monkeypatch.setattr(
        handoff_module,
        "_git_batch_tree_objects",
        lambda repo_root, object_ids, *, deadline: {
            object_id: tree_raw[object_id] for object_id in object_ids
        },
    )

    with pytest.raises(handoff_module.HandoffError, match="handoff_discovery_tree_depth_exceeded"):
        handoff_module._git_tree_handoff_entries(
            Path("unused"), ["agent/data_steward/one"], deadline=handoff_module.time.monotonic() + 1.0
        )


def test_tree_discovery_cached_root_preserves_missing_wrong_type_and_malformed_failures(monkeypatch) -> None:
    spec = f"agent/data_steward/one:{handoff_module.HANDOFF_ROOT.as_posix()}"

    monkeypatch.setattr(
        handoff_module,
        "_git_batch_records",
        lambda repo_root, specs, **kwargs: {spec: ("", "missing", None)},
    )
    assert handoff_module._git_tree_handoff_entries(
        Path("unused"), ["agent/data_steward/one"], deadline=handoff_module.time.monotonic() + 1.0
    ) == []

    monkeypatch.setattr(
        handoff_module,
        "_git_batch_records",
        lambda repo_root, specs, **kwargs: {spec: ("a" * 40, "blob", b"{}")},
    )
    with pytest.raises(handoff_module.HandoffError, match="handoff_git_tree_root_invalid"):
        handoff_module._git_tree_handoff_entries(
            Path("unused"), ["agent/data_steward/one"], deadline=handoff_module.time.monotonic() + 1.0
        )

    monkeypatch.setattr(
        handoff_module,
        "_git_batch_records",
        lambda repo_root, specs, **kwargs: {spec: ("a" * 40, "tree", b"40000 malformed")},
    )
    with pytest.raises(handoff_module.HandoffError, match="handoff_git_tree_entry_invalid"):
        handoff_module._git_tree_handoff_entries(
            Path("unused"), ["agent/data_steward/one"], deadline=handoff_module.time.monotonic() + 1.0
        )


def test_tree_discovery_missing_child_object_still_fails_closed(monkeypatch) -> None:
    child_id = "b" * 40
    root_raw = _raw_tree(("40000", "child", child_id))
    monkeypatch.setattr(
        handoff_module,
        "_git_batch_records",
        lambda repo_root, specs, **kwargs: {spec: ("a" * 40, "tree", root_raw) for spec in specs},
    )
    monkeypatch.setattr(
        handoff_module,
        "_git_batch_tree_objects",
        lambda repo_root, object_ids, *, deadline: {child_id: None},
    )

    with pytest.raises(handoff_module.HandoffError, match="handoff_git_tree_object_missing"):
        handoff_module._git_tree_handoff_entries(
            Path("unused"), ["agent/data_steward/one"], deadline=handoff_module.time.monotonic() + 1.0
        )


def test_tree_discovery_cached_root_still_checks_global_deadline(monkeypatch) -> None:
    monkeypatch.setattr(
        handoff_module,
        "_git_batch_records",
        lambda repo_root, specs, **kwargs: {
            spec: ("a" * 40, "tree", b"") for spec in specs
        },
    )
    monkeypatch.setattr(handoff_module.time, "monotonic", lambda: 101.0)

    with pytest.raises(handoff_module.HandoffError, match="handoff_discovery_timeout"):
        handoff_module._git_tree_handoff_entries(
            Path("unused"), ["agent/data_steward/one"], deadline=100.0
        )


def test_unique_append_only_events_do_not_overwrite_each_other(tmp_path: Path) -> None:
    repo, base, deliverable, content = _repo(tmp_path)
    payloads = [_published_payload(base, deliverable, content, event_id=f"data-ready-{index:03d}") for index in range(8)]
    with ThreadPoolExecutor(max_workers=4) as executor:
        paths = list(executor.map(lambda payload: write_handoff(payload, repo_root=repo), payloads))
    assert len({path.name for path in paths}) == 8
    assert all(path.is_file() for path in paths)


def test_full_scan_reports_empty_or_malformed_committed_event(tmp_path: Path) -> None:
    repo, _, _, _ = _repo(tmp_path)
    path = repo / ".agent" / "handoffs" / "broken-ticket" / "broken-event.json"
    path.parent.mkdir(parents=True)
    path.write_text("", encoding="utf-8")
    _git(repo, "add", path.relative_to(repo).as_posix())
    _git(repo, "commit", "-m", "broken handoff")

    scan = scan_handoffs(repo, verify_git=True)
    assert not scan["events"]
    assert scan["invalid"][0]["path"].endswith("broken-event.json")
    assert "handoff_unreadable" in scan["invalid"][0]["errors"][0]


def test_discovery_reports_malformed_committed_event_without_empty_success(tmp_path: Path) -> None:
    repo, _, _, _ = _repo(tmp_path)
    path = repo / ".agent" / "handoffs" / "broken-ticket" / "broken-event.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not-json", encoding="utf-8")
    _git(repo, "add", path.relative_to(repo).as_posix())
    _git(repo, "commit", "-m", "broken discovery handoff")

    scan = scan_handoffs(repo, verify_git=False)

    assert scan["events"] == []
    assert scan["invalid"]
    assert scan["invalid"][0]["path"].endswith("broken-event.json")
    assert "handoff_unreadable" in scan["invalid"][0]["errors"][0]


def test_discovery_timeout_is_visible_and_not_converted_to_empty_scan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo, _, _, _ = _repo(tmp_path)

    def fail(*args, **kwargs):
        raise handoff_module.HandoffError("handoff_discovery_timeout")

    monkeypatch.setattr(handoff_module, "_git_tree_handoff_index", fail)

    with pytest.raises(handoff_module.HandoffError, match="handoff_discovery_timeout"):
        scan_handoffs(repo, verify_git=False)


def test_full_git_scan_preserves_invalid_source_per_distinct_projection(
    tmp_path: Path, monkeypatch
) -> None:
    refs = [
        {"branch": "agent/super_developer/source-a", "head": "a" * 40},
        {"branch": "agent/super_developer/source-b", "head": "b" * 40},
    ]
    main_root = "1" * 40
    root_a = "2" * 40
    root_b = "3" * 40
    shared_bad = "4" * 40
    payload_a = {"event_id": "shared-event", "source": "a"}
    payload_b = {"event_id": "shared-event", "source": "b"}
    raw_a = json.dumps(payload_a, sort_keys=True).encode("utf-8")
    raw_b = json.dumps(payload_b, sort_keys=True).encode("utf-8")
    parsed = {
        main_root: [],
        root_a: [
            ("100644", "bad.json", shared_bad),
            ("100644", "z-a.json", "5" * 40),
        ],
        root_b: [
            ("100644", "a-b.json", "6" * 40),
            ("100644", "bad.json", shared_bad),
        ],
    }
    monkeypatch.setattr(handoff_module, "list_agent_ref_heads", lambda _: refs)
    monkeypatch.setattr(handoff_module, "_main_ref_head", lambda _: "f" * 40)
    monkeypatch.setattr(handoff_module, "_merged_agent_refs", lambda *args, **kwargs: set())
    monkeypatch.setattr(
        handoff_module,
        "_git_tree_handoff_index",
        lambda *args, **kwargs: (
            {
                "main": main_root,
                refs[0]["branch"]: root_a,
                refs[1]["branch"]: root_b,
            },
            parsed,
        ),
    )
    monkeypatch.setattr(
        handoff_module,
        "_git_batch_bytes",
        lambda repo_root, specs: {
            spec: (
                raw_a
                if spec.endswith("z-a.json")
                else raw_b
                if spec.endswith("a-b.json")
                else b"{"
            )
            for spec in specs
        },
    )
    monkeypatch.setattr(handoff_module, "validate_handoff_against_git", lambda *args, **kwargs: [])

    scan = scan_handoffs(tmp_path, verify_git=True)

    assert scan == {
        "events": [
            {
                "event": payload_a,
                "path": ".agent/handoffs/z-a.json",
                "content_sha256": hashlib.sha256(raw_a).hexdigest(),
                "observed_refs": [refs[0]["branch"]],
            }
        ],
        "invalid": [
            {
                "ref": refs[0]["branch"],
                "path": ".agent/handoffs/bad.json",
                "errors": [
                    "handoff_unreadable:JSONDecodeError:Expecting property name enclosed in double quotes: "
                    "line 1 column 2 (char 1)"
                ],
            },
            {
                "ref": refs[1]["branch"],
                "path": ".agent/handoffs/a-b.json",
                "event_id": "shared-event",
                "errors": ["handoff_event_id_conflict"],
            },
            {
                "ref": refs[1]["branch"],
                "path": ".agent/handoffs/bad.json",
                "errors": [
                    "handoff_unreadable:JSONDecodeError:Expecting property name enclosed in double quotes: "
                    "line 1 column 2 (char 1)"
                ],
            },
        ],
        "refs": [refs[0]["branch"], refs[1]["branch"]],
        "ref_heads": refs,
        "main_coverage": {
            "source_ref": "main",
            "covered_refs": [],
            "uncovered_refs": [refs[0]["branch"], refs[1]["branch"]],
            "main_projection_entries": 0,
        },
        "verification_mode": "full_git",
    }


def test_git_child_timeout_is_bounded_and_visible(tmp_path: Path, monkeypatch) -> None:
    repo, _, _, _ = _repo(tmp_path)
    observed_timeouts: list[float] = []

    def timeout_run(*args, **kwargs):
        observed_timeouts.append(kwargs["timeout"])
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(handoff_module.subprocess, "run", timeout_run)

    with pytest.raises(handoff_module.HandoffError, match="handoff_git_timeout"):
        scan_handoffs(repo, verify_git=False)
    assert observed_timeouts
    assert all(0 < value <= handoff_module.GIT_COMMAND_TIMEOUT_SECONDS for value in observed_timeouts)


def test_git_timeout_default_and_explicit_values_are_positive_and_bounded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    observed_timeouts: list[float] = []

    def successful_run(*args, **kwargs):
        observed_timeouts.append(kwargs["timeout"])
        return subprocess.CompletedProcess(args[0], 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(handoff_module.subprocess, "run", successful_run)

    assert 0 < handoff_module.GIT_COMMAND_TIMEOUT_SECONDS < handoff_module.HANDOFF_DISCOVERY_TIMEOUT_SECONDS
    handoff_module._run_git(tmp_path, "status")
    handoff_module._run_git(tmp_path, "status", timeout=3.0)
    handoff_module._run_git(tmp_path, "status", timeout=30.0)

    assert observed_timeouts == [handoff_module.GIT_COMMAND_TIMEOUT_SECONDS, 3.0, handoff_module.GIT_COMMAND_TIMEOUT_SECONDS]


def test_git_timeout_accepts_simulated_three_second_child_without_sleep(
    tmp_path: Path,
    monkeypatch,
) -> None:
    observed_timeouts: list[float] = []

    def simulated_run(*args, **kwargs):
        observed_timeouts.append(kwargs["timeout"])
        return subprocess.CompletedProcess(args[0], 0, stdout=b"ok", stderr=b"")

    monkeypatch.setattr(handoff_module.subprocess, "run", simulated_run)

    result = handoff_module._run_git(tmp_path, "cat-file", "-t", "object", timeout=3.0)
    assert result.stdout == b"ok"
    assert observed_timeouts == [3.0]


def test_discovery_remaining_timeout_never_exceeds_deadline_or_command_budget(monkeypatch) -> None:
    now = 100.0
    monkeypatch.setattr(handoff_module.time, "monotonic", lambda: now)

    assert handoff_module._remaining_timeout(
        now + handoff_module.HANDOFF_DISCOVERY_TIMEOUT_SECONDS,
        "discovery",
    ) == handoff_module.GIT_COMMAND_TIMEOUT_SECONDS
    assert handoff_module._remaining_timeout(now + 2.5, "discovery") == 2.5

    with pytest.raises(handoff_module.HandoffError, match="handoff_discovery_timeout"):
        handoff_module._remaining_timeout(now, "discovery")


def test_non_finite_git_timeout_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(handoff_module.HandoffError, match="handoff_git_timeout"):
        handoff_module._run_git(tmp_path, "status", timeout=float("inf"))


def test_discovery_deduplicates_alias_refs_before_ref_cap(tmp_path: Path, monkeypatch) -> None:
    repo, _, _, _ = _repo(tmp_path)
    head = "a" * 40
    ref_heads = [
        {"branch": f"agent/super_developer/alias-{index:04d}", "head": head}
        for index in range(handoff_module.MAX_DISCOVERY_REFS + 7)
    ]
    observed_scan_refs: list[list[str]] = []

    monkeypatch.setattr(handoff_module, "list_agent_ref_heads", lambda _: ref_heads)
    def capture_index(
        repo_root: Path,
        refs: list[str],
        *,
        deadline: float,
        enforce_ref_cap: bool,
    ):
        observed_scan_refs.append(refs)
        root_id = "1" * 40
        return (
            {ref: root_id for ref in refs if ref != "main"},
            {root_id: [("100644", "event.json", "a" * 40)]},
        )

    monkeypatch.setattr(handoff_module, "_git_tree_handoff_index", capture_index)

    scan = scan_handoffs(repo, verify_git=False)

    assert observed_scan_refs == [[item["branch"] for item in ref_heads] + ["main"]]
    assert scan["refs"] == [item["branch"] for item in ref_heads]
    assert len(scan["ref_heads"]) == handoff_module.MAX_DISCOVERY_REFS + 7


def test_discovery_keeps_ref_cap_for_distinct_commit_roots(tmp_path: Path, monkeypatch) -> None:
    repo, _, _, _ = _repo(tmp_path)
    ref_heads = [
        {
            "branch": f"agent/super_developer/distinct-{index:04d}",
            "head": f"{index:040x}",
        }
        for index in range(handoff_module.MAX_DISCOVERY_REFS + 1)
    ]
    monkeypatch.setattr(handoff_module, "list_agent_ref_heads", lambda _: ref_heads)
    monkeypatch.setattr(
        handoff_module,
        "_git_tree_handoff_index",
        lambda _, refs, *, deadline, enforce_ref_cap: (
            {
                ref: f"{index + 1:040x}"
                for index, ref in enumerate(refs)
                if ref != "main"
            },
            {
                f"{index + 1:040x}": [("100644", "event.json", f"{index + 1000:040x}")]
                for index, ref in enumerate(refs)
                if ref != "main"
            },
        ),
    )

    with pytest.raises(handoff_module.HandoffError, match="handoff_discovery_ref_cap_exceeded"):
        scan_handoffs(repo, verify_git=False)


def test_discovery_deduplicates_distinct_commit_heads_with_same_handoff_tree(tmp_path: Path, monkeypatch) -> None:
    repo, _, _, _ = _repo(tmp_path)
    ref_heads = [
        {
            "branch": f"agent/super_developer/no-handoff-{index:04d}",
            "head": f"{index:040x}",
        }
        for index in range(handoff_module.MAX_DISCOVERY_REFS + 1)
    ]
    observed_scan_refs: list[list[str]] = []
    monkeypatch.setattr(handoff_module, "list_agent_ref_heads", lambda _: ref_heads)

    def capture_index(
        repo_root: Path,
        refs: list[str],
        *,
        deadline: float,
        enforce_ref_cap: bool,
    ):
        observed_scan_refs.append(refs)
        roots = {
            ref: f"{index + 1:040x}"
            for index, ref in enumerate(refs)
            if ref != "main"
        }
        return roots, {
            root_id: [("100644", "event.json", "a" * 40)]
            for root_id in roots.values()
        }

    monkeypatch.setattr(handoff_module, "_git_tree_handoff_index", capture_index)

    scan = scan_handoffs(repo, verify_git=False)

    assert observed_scan_refs == [[item["branch"] for item in ref_heads] + ["main"]]
    assert len(scan["ref_heads"]) == handoff_module.MAX_DISCOVERY_REFS + 1


def test_full_scan_deduplicates_alias_refs_before_ref_cap(tmp_path: Path, monkeypatch) -> None:
    repo, _, _, _ = _repo(tmp_path)
    head = "b" * 40
    ref_heads = [
        {"branch": f"agent/super_developer/full-alias-{index:04d}", "head": head}
        for index in range(handoff_module.MAX_DISCOVERY_REFS + 5)
    ]
    observed_scan_refs: list[list[str]] = []

    monkeypatch.setattr(handoff_module, "list_agent_ref_heads", lambda _: ref_heads)
    monkeypatch.setattr(
        handoff_module,
        "_git_tree_handoff_index",
        lambda _, refs, *, deadline, enforce_ref_cap: (
            {ref: "1" * 40 for ref in refs if ref != "main"},
            {"1" * 40: [("100644", "event.json", "b" * 40)]},
        ),
    )

    def capture_blobs(repo_root: Path, specs: list[str]) -> dict[str, bytes | None]:
        observed_scan_refs.append([spec.split(":", 1)[0] for spec in specs])
        return {spec: b"{}" for spec in specs}

    monkeypatch.setattr(handoff_module, "_git_batch_bytes", capture_blobs)

    scan = scan_handoffs(repo, verify_git=True)

    assert observed_scan_refs == [[ref_heads[0]["branch"]]]
    assert len(scan["ref_heads"]) == handoff_module.MAX_DISCOVERY_REFS + 5


def test_main_projection_covers_over_cap_merged_refs_and_preserves_observed_refs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo, base, deliverable, content = _repo(tmp_path)
    payload = _published_payload(base, deliverable, content, event_id="main-covered-001")
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    ref_heads = [
        {
            "branch": f"agent/integrator/covered-{index:04d}",
            "head": f"{index + 1:040x}",
        }
        for index in range(handoff_module.MAX_DISCOVERY_REFS + 1)
    ]
    main_root = "f" * 40
    main_child = "e" * 40
    main_entries = [
        ("100644", f"event-{index:04d}.json", f"{index + 1:040x}")
        for index in range(len(ref_heads))
    ]
    monkeypatch.setattr(handoff_module, "list_agent_ref_heads", lambda _: ref_heads)
    monkeypatch.setattr(handoff_module, "_merged_agent_refs", lambda *args, **kwargs: {item["branch"] for item in ref_heads})

    def tree_index(repo_root: Path, refs: list[str], *, deadline: float, enforce_ref_cap: bool):
        roots = {"main": main_root}
        parsed = {
            main_root: [("40000", "covered", main_child)],
            main_child: main_entries,
        }
        for index, item in enumerate(ref_heads):
            ref = item["branch"]
            root_id = f"{index + 10000:040x}"
            child_id = f"{index + 20000:040x}"
            roots[ref] = root_id
            parsed[root_id] = [("40000", "covered", child_id)]
            parsed[child_id] = [("100644", f"event-{index:04d}.json", f"{index + 1:040x}")]
        return ({ref: root_id for ref, root_id in roots.items() if ref in refs}, parsed)

    monkeypatch.setattr(handoff_module, "_git_tree_handoff_index", tree_index)
    monkeypatch.setattr(
        handoff_module,
        "_git_batch_objects",
        lambda repo_root, object_ids, *, deadline: {object_id: raw for object_id in object_ids},
    )

    scan = scan_handoffs(repo, verify_git=False)

    assert not scan["invalid"]
    assert [item["event"]["event_id"] for item in scan["events"]] == ["main-covered-001"]
    assert scan["main_coverage"]["source_ref"] == "main"
    assert len(scan["main_coverage"]["covered_refs"]) == handoff_module.MAX_DISCOVERY_REFS + 1
    observed = scan["events"][0]["observed_refs"]
    assert observed[0] == "agent/integrator/covered-0000" or observed[0] == "main"
    assert set(observed) == {"main", *(item["branch"] for item in ref_heads)}


def test_merged_projection_mismatch_is_not_dropped_and_still_hits_cap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo, _, _, _ = _repo(tmp_path)
    ref_heads = [
        {
            "branch": f"agent/integrator/uncovered-{index:04d}",
            "head": f"{index + 1:040x}",
        }
        for index in range(handoff_module.MAX_DISCOVERY_REFS + 1)
    ]
    monkeypatch.setattr(handoff_module, "list_agent_ref_heads", lambda _: ref_heads)
    monkeypatch.setattr(handoff_module, "_merged_agent_refs", lambda *args, **kwargs: {item["branch"] for item in ref_heads})
    monkeypatch.setattr(
        handoff_module,
        "_git_tree_handoff_index",
        lambda _, refs, *, deadline, enforce_ref_cap: (
            {
                item["branch"]: f"{index + 10000:040x}"
                for index, item in enumerate(ref_heads)
                if item["branch"] in refs
            },
            {
                f"{index + 10000:040x}": [
                    ("100644", f"event-{index:04d}.json", f"{index + 1:040x}")
                ]
                for index, item in enumerate(ref_heads)
                if item["branch"] in refs
            },
        ),
    )

    with pytest.raises(handoff_module.HandoffError, match="handoff_discovery_ref_cap_exceeded"):
        scan_handoffs(repo, verify_git=False)


def test_main_ref_missing_fails_closed_before_discovery(tmp_path: Path, monkeypatch) -> None:
    repo, _, _, _ = _repo(tmp_path)
    monkeypatch.setattr(handoff_module, "list_agent_ref_heads", lambda _: [])
    monkeypatch.setattr(handoff_module, "read_ref_heads", lambda *_args, **_kwargs: {})

    with pytest.raises(handoff_module.HandoffError, match="handoff_discovery_main_missing"):
        scan_handoffs(repo, verify_git=False)


def test_main_coverage_is_used_by_full_git_validation(tmp_path: Path, monkeypatch) -> None:
    repo, base, deliverable, content = _repo(tmp_path)
    payload = _published_payload(base, deliverable, content, event_id="main-full-git-001")
    event_path = write_handoff(payload, repo_root=repo)
    _git(repo, "add", event_path.relative_to(repo).as_posix())
    _git(repo, "commit", "-m", "publish main handoff")
    _git(repo, "checkout", "main")
    _git(repo, "merge", "--ff-only", "agent/data_steward/dataset")

    captured: list[str] = []
    original = handoff_module._git_batch_bytes

    def capture(repo_root: Path, specs: list[str]) -> dict[str, bytes | None]:
        captured.extend(specs)
        return original(repo_root, specs)

    monkeypatch.setattr(handoff_module, "_git_batch_bytes", capture)
    scan = scan_handoffs(repo, verify_git=True)

    assert not scan["invalid"]
    assert scan["events"][0]["event"]["event_id"] == "main-full-git-001"
    assert any(spec.startswith("main:.agent/handoffs/") for spec in captured)
    assert "main" in scan["events"][0]["observed_refs"]
