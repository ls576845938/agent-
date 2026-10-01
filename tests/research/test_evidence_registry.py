from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _write_candidate(root: Path, candidate_id: str = "cand_1") -> Path:
    path = root / "research" / "candidates" / candidate_id / "candidate.json"
    _write_json(
        path,
        {
            "candidate_id": candidate_id,
            "data_version": "dv_1",
            "experiment_id": "exp_1",
        },
    )
    return path


def _write_manifest_with_review(root: Path, manifest_id: str, candidate_id: str) -> None:
    _write_json(
        root / "research" / "manifests" / manifest_id / "manifest.json",
        {
            "strategy_candidate_id": manifest_id,
            "source_candidate_id": candidate_id,
            "source_experiment_id": f"exp_{candidate_id}",
            "promotion_status": "PAPER_REVIEW_CANDIDATE",
            "paper_review_id": "prev_001",
            "paper_review_evidence_pack_path": str(
                root / "research" / "evidence_packs" / "psim_001" / "evidence_pack.json"
            ),
            "paper_review_candidate_path": str(
                root / "research" / "evidence_packs" / "psim_001" / "evidence_pack.json#sections.paper_review_candidate"
            ),
            "paper_review_candidate_status": "READY_FOR_REVIEW",
            "paper_review_blocking_reasons": [],
        },
    )


def _write_pending_review(root: Path) -> None:
    _write_json(
        root / "research" / "paper_reviews" / "prev_001" / "review.json",
        {
            "paper_review_id": "prev_001",
            "strategy_manifest_id": "sm_1",
            "portfolio_sim_id": "psim_001",
            "evidence_pack_path": str(
                root / "research" / "evidence_packs" / "psim_001" / "evidence_pack.json"
            ),
            "source_candidate_ids": ["cand_1", "cand_2"],
            "evidence_gate_status": "READY_FOR_REVIEW",
            "evidence_gate_blocking_reasons": [],
            "proposed_symbols": ["SPY", "QQQ"],
            "proposed_capital": 101000.0,
            "proposed_risk_envelope": {"max_drawdown_pct": 0.1},
            "status": "PENDING_HUMAN_REVIEW",
            "created_at": "2026-05-10T00:00:00+00:00",
        },
    )


def test_rebuilt_saved_registry_has_usable_subject_index(tmp_path: Path) -> None:
    from quant_us.research.evidence_registry import (
        find_registry_subject_evidence,
        inspect_saved_evidence_registry,
        rebuild_evidence_registry,
    )

    _write_candidate(tmp_path)

    registry = rebuild_evidence_registry(tmp_path)
    saved = inspect_saved_evidence_registry(tmp_path)
    lookup = find_registry_subject_evidence(tmp_path, candidate_id="cand_1")

    assert registry["subject_index_schema_version"] == "subject_evidence_index_v1"
    assert saved["registry_status"] == "present"
    assert saved["registry_integrity_status"] == "PASS/STABLE"
    assert "cand_1" in saved["subject_index"]["candidate_id"]
    assert lookup["matched"] is True
    assert lookup["reason"] == "ok"


def test_saved_registry_count_mismatch_is_diagnostic_when_artifacts_are_unchanged(
    tmp_path: Path,
) -> None:
    from quant_us.research.evidence_registry import (
        inspect_saved_evidence_registry,
        rebuild_evidence_registry,
    )

    _write_candidate(tmp_path)
    rebuild_evidence_registry(tmp_path)
    registry_path = tmp_path / "research" / "evidence_registry.json"
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload["counts"]["candidate_count"] = 999
    registry_path.write_text(json.dumps(payload), encoding="utf-8")

    saved = inspect_saved_evidence_registry(tmp_path)

    assert saved["registry_status"] == "present"
    assert saved["registry_integrity_status"] == "PASS/STABLE"
    assert "stale_snapshot:count_mismatch:candidate_count" in saved["registry_notes"]


def test_saved_registry_missing_subject_index_is_stale_until_rebuilt(
    tmp_path: Path,
) -> None:
    from quant_us.research.evidence_registry import (
        find_registry_subject_evidence,
        inspect_saved_evidence_registry,
        rebuild_evidence_registry,
    )

    _write_candidate(tmp_path)
    rebuild_evidence_registry(tmp_path)
    registry_path = tmp_path / "research" / "evidence_registry.json"
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload.pop("subject_index", None)
    payload.pop("subject_index_schema_version", None)
    registry_path.write_text(json.dumps(payload), encoding="utf-8")

    stale = inspect_saved_evidence_registry(tmp_path)
    lookup = find_registry_subject_evidence(tmp_path, candidate_id="cand_1")
    rebuilt = rebuild_evidence_registry(tmp_path)
    fresh = inspect_saved_evidence_registry(tmp_path)

    assert stale["registry_status"] == "stale"
    assert stale["registry_integrity_status"] == "STALE/CHANGED"
    assert "stale_snapshot:subject_index_schema_missing_or_mismatch" in stale["registry_notes"]
    assert lookup["matched"] is False
    assert lookup["reason"] == "registry_not_ready:stale:STALE/CHANGED"
    assert rebuilt["subject_index"]["candidate_id"]["cand_1"]
    assert fresh["registry_status"] == "present"


def test_report_registry_stale_output_includes_rebuild_command(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from quant_us.cli import cmd_report_evidence_registry
    from quant_us.research.evidence_registry import rebuild_evidence_registry

    _write_candidate(tmp_path)
    rebuild_evidence_registry(tmp_path)
    registry_path = tmp_path / "research" / "evidence_registry.json"
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload.pop("subject_index", None)
    payload.pop("subject_index_schema_version", None)
    registry_path.write_text(json.dumps(payload), encoding="utf-8")

    cmd_report_evidence_registry(argparse.Namespace(data_root=str(tmp_path)))

    output = capsys.readouterr().out
    assert "registry_state: STALE (stale)" in output
    assert (
        f"rebuild_command: quant-us research evidence-registry-rebuild --data-root {tmp_path}"
        in output
    )


def test_registry_captures_pending_review_candidate_ids_and_manifest_review_links(
    tmp_path: Path,
) -> None:
    from quant_us.research.evidence_registry import (
        inspect_saved_evidence_registry,
        rebuild_evidence_registry,
    )

    _write_candidate(tmp_path, "cand_1")
    _write_candidate(tmp_path, "cand_2")
    _write_manifest_with_review(tmp_path, "sm_1", "cand_1")
    _write_pending_review(tmp_path)

    rebuild_evidence_registry(tmp_path)
    saved = inspect_saved_evidence_registry(tmp_path)

    manifest_row = saved["evidence"]["strategy_manifests"][0]
    review_row = saved["evidence"]["paper_reviews"][0]

    assert manifest_row["details"]["paper_review_id"] == "prev_001"
    assert manifest_row["details"]["paper_review_candidate_status"] == "READY_FOR_REVIEW"
    assert review_row["details"]["candidate_id"] == "cand_1"
    assert review_row["details"]["source_candidate_ids"] == ["cand_1", "cand_2"]
    assert review_row["details"]["evidence_gate_status"] == "READY_FOR_REVIEW"


def test_saved_registry_uses_validation_index_without_rescanning_payloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import quant_us.research.evidence_registry as registry_module

    _write_candidate(tmp_path)
    rebuilt = registry_module.rebuild_evidence_registry(tmp_path)

    assert rebuilt["validation_index"]["schema_version"] == (
        "evidence_registry_validation_index_v1"
    )

    def unexpected_full_scan(_root: Path) -> dict[str, object]:
        raise AssertionError("saved registry inspection must not rebuild the evidence payload")

    def unexpected_hash(_path: Path) -> str:
        raise AssertionError("unchanged indexed evidence must not be rehashed")

    monkeypatch.setattr(registry_module, "_scan_all_evidence", unexpected_full_scan)
    monkeypatch.setattr(registry_module, "_file_sha256", unexpected_hash)

    saved = registry_module.inspect_saved_evidence_registry(tmp_path)

    assert saved["registry_status"] == "present"
    assert saved["registry_integrity_status"] == "PASS/STABLE"


def test_saved_registry_detects_new_large_manifest_before_reading_or_hashing_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import quant_us.research.evidence_registry as registry_module

    _write_candidate(tmp_path)
    registry_module.rebuild_evidence_registry(tmp_path)
    new_manifest = tmp_path / "manifests" / "run_new_large.json"
    new_manifest.parent.mkdir(parents=True, exist_ok=True)
    new_manifest.write_text("x" * (4 * 1024 * 1024), encoding="utf-8")

    def unexpected_hash(path: Path) -> str:
        if path == new_manifest:
            raise AssertionError("new candidate must not be hashed before stale is known")
        return "unused"

    monkeypatch.setattr(registry_module, "_file_sha256", unexpected_hash)

    saved = registry_module.inspect_saved_evidence_registry(tmp_path)

    assert saved["registry_status"] == "stale"
    assert "stale_snapshot:discovery_path_set_changed" in saved["registry_notes"]


def test_saved_registry_rejects_validation_index_path_outside_data_root(
    tmp_path: Path,
) -> None:
    from quant_us.research.evidence_registry import (
        inspect_saved_evidence_registry,
        rebuild_evidence_registry,
    )

    _write_candidate(tmp_path)
    rebuild_evidence_registry(tmp_path)
    registry_path = tmp_path / "research" / "evidence_registry.json"
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload["validation_index"]["discovery_paths"].append(str(tmp_path.parent / "outside.json"))
    registry_path.write_text(json.dumps(payload), encoding="utf-8")

    saved = inspect_saved_evidence_registry(tmp_path)

    assert saved["registry_status"] == "conflict"
    assert saved["registry_integrity_status"] == "CONFLICT"
    assert any("validation_index_path_outside_data_root" in note for note in saved["registry_notes"])


def test_saved_registry_summary_keeps_integrity_but_omits_full_payload(
    tmp_path: Path,
) -> None:
    from quant_us.research.evidence_registry import (
        inspect_saved_evidence_registry_summary,
        rebuild_evidence_registry,
    )

    candidate_path = _write_candidate(tmp_path)
    rebuilt = rebuild_evidence_registry(tmp_path)

    summary = inspect_saved_evidence_registry_summary(tmp_path)

    assert summary["schema_version"] == "evidence_registry_summary_v1"
    assert summary["source"]["schema_version"] == rebuilt["schema_version"]
    assert summary["source"]["validation_index_schema_version"] == (
        "evidence_registry_validation_index_v1"
    )
    assert summary["source"]["validation_index_sha256"] == (
        rebuilt["validation_index"]["index_sha256"]
    )
    assert summary["response_view"] == "summary"
    assert summary["registry_status"] == "present"
    assert summary["registry_integrity_status"] == "PASS/STABLE"
    assert summary["counts"] == rebuilt["counts"]
    assert "evidence" not in summary
    assert "chains" not in summary
    assert "subject_index" not in summary
    assert "validation_index" not in summary

    candidate_path.write_text(
        json.dumps(
            {
                "candidate_id": "cand_1",
                "data_version": "tampered",
                "experiment_id": "exp_1",
            }
        ),
        encoding="utf-8",
    )
    tampered = inspect_saved_evidence_registry_summary(tmp_path)
    assert tampered["registry_status"] == "changed"
    assert tampered["registry_integrity_status"] == "STALE/CHANGED"
    assert any("content_changed" in note for note in tampered["registry_notes"])


def test_saved_registry_summary_detects_path_addition_and_deletion(
    tmp_path: Path,
) -> None:
    from quant_us.research.evidence_registry import (
        inspect_saved_evidence_registry_summary,
        rebuild_evidence_registry,
    )

    candidate_path = _write_candidate(tmp_path)
    rebuild_evidence_registry(tmp_path)

    candidate_path.unlink()
    deleted = inspect_saved_evidence_registry_summary(tmp_path)
    assert deleted["registry_status"] == "stale"
    assert "stale_snapshot:discovery_path_set_changed" in deleted["registry_notes"]

    _write_candidate(tmp_path)
    rebuild_evidence_registry(tmp_path)
    added = tmp_path / "research" / "candidates" / "cand_2" / "candidate.json"
    _write_json(added, {"candidate_id": "cand_2"})
    changed = inspect_saved_evidence_registry_summary(tmp_path)
    assert changed["registry_status"] == "stale"
    assert "stale_snapshot:discovery_path_set_changed" in changed["registry_notes"]


def test_saved_registry_reuses_parent_resolution_within_one_inspection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import quant_us.research.evidence_registry as registry_module

    report_dir = tmp_path / "runtime"
    for index in range(32):
        _write_json(
            report_dir / f"daily_report_2026-09-{index + 1:02d}.json",
            {"report_date": f"2026-09-{index + 1:02d}", "session_id": f"s-{index}"},
        )
    registry_module.rebuild_evidence_registry(tmp_path)

    original_resolve = Path.resolve
    resolve_calls: list[Path] = []

    def counting_resolve(path: Path, *args: object, **kwargs: object) -> Path:
        resolve_calls.append(path)
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", counting_resolve)

    saved = registry_module.inspect_saved_evidence_registry(tmp_path)

    assert saved["registry_status"] == "present"
    assert saved["registry_integrity_status"] == "PASS/STABLE"
    assert len(resolve_calls) <= 4


def test_index_path_batch_validation_checks_each_parent_boundary_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import quant_us.research.evidence_registry as registry_module

    root = tmp_path / "data"
    paths: set[str] = set()
    for parent_index in range(3):
        for file_index in range(12):
            path = root / f"parent-{parent_index}" / f"evidence-{file_index}.json"
            _write_json(path, {"ok": True})
            paths.add(str(path))
    resolved_root = root.resolve()
    original_relative_to = Path.relative_to
    relative_to_calls: list[Path] = []

    def counting_relative_to(path: Path, *args: object, **kwargs: object) -> Path:
        relative_to_calls.append(path)
        return original_relative_to(path, *args, **kwargs)

    monkeypatch.setattr(Path, "relative_to", counting_relative_to)

    invalid_path, stats = registry_module._validated_index_path_stats(
        paths,
        resolved_root=resolved_root,
    )

    assert invalid_path is None
    assert len(stats) == len(paths)
    assert len(relative_to_calls) == 3


def test_index_path_batch_reuses_directory_entry_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import quant_us.research.evidence_registry as registry_module

    root = tmp_path / "data"
    paths: set[str] = set()
    for index in range(32):
        path = root / "evidence" / f"evidence-{index}.json"
        _write_json(path, {"index": index})
        paths.add(str(path))
    resolved_root = root.resolve()

    def unexpected_lstat(_path: Path, *args: object, **kwargs: object):
        raise AssertionError("ordinary indexed files must reuse scandir metadata")

    monkeypatch.setattr(Path, "lstat", unexpected_lstat)
    invalid_path, stats = registry_module._validated_index_path_stats(
        paths,
        resolved_root=resolved_root,
    )

    assert invalid_path is None
    assert set(stats) == paths
    assert all(value is not None for value in stats.values())


def test_discovery_reuses_directory_entry_file_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import quant_us.research.evidence_registry as registry_module

    expected = tmp_path / "manifests" / "dataset.json"
    _write_json(expected, {"status": "ok"})

    def unexpected_is_file(_path: Path, *args: object, **kwargs: object):
        raise AssertionError("fixed discovery must reuse scandir file metadata")

    monkeypatch.setattr(Path, "is_file", unexpected_is_file)
    discovered = registry_module._discover_evidence_candidate_paths(tmp_path)

    assert str(expected) in discovered


def test_index_path_batch_does_not_merge_case_alias_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import quant_us.research.evidence_registry as registry_module

    root = tmp_path / "data"
    canonical = root / "evidence" / "Evidence.json"
    _write_json(canonical, {"ok": True})
    aliased = canonical.with_name("evidence.json")
    lstat_paths: list[Path] = []
    original_lstat = Path.lstat

    def counting_lstat(path: Path, *args: object, **kwargs: object):
        lstat_paths.append(path)
        return original_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", counting_lstat)
    invalid_path, stats = registry_module._validated_index_path_stats(
        {str(aliased)},
        resolved_root=root.resolve(),
    )

    assert invalid_path is None
    assert lstat_paths == [aliased]
    assert stats[str(aliased)] is not None


def test_index_path_batch_cancellation_counts_unrelated_directory_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import quant_us.research.evidence_registry as registry_module

    root = tmp_path / "data"
    parent = root / "evidence"
    for index in range(256):
        _write_json(parent / f"unrelated-{index:03d}.txt", {"index": index})
    target = parent / "zz-target.json"
    _write_json(target, {"target": True})
    resolved_root = root.resolve()
    original_scandir = registry_module.os.scandir
    enumerated = 0

    class CountingScandir:
        def __init__(self, path: Path) -> None:
            self._inner = original_scandir(path)

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            self._inner.close()

        def __iter__(self):
            return self

        def __next__(self):
            nonlocal enumerated
            entry = next(self._inner)
            enumerated += 1
            return entry

    monkeypatch.setattr(registry_module.os, "scandir", CountingScandir)

    with pytest.raises(registry_module.EvidenceRegistryInspectionCancelled):
        registry_module._validated_index_path_stats(
            {str(target)},
            resolved_root=resolved_root,
            should_cancel=lambda: enumerated >= 64,
        )

    assert enumerated <= 65


def test_index_path_batch_preserves_normalized_duplicate_raw_keys(
    tmp_path: Path,
) -> None:
    import quant_us.research.evidence_registry as registry_module

    root = tmp_path / "data"
    evidence = root / "evidence" / "record.json"
    _write_json(evidence, {"ok": True})
    raw_paths = {
        str(evidence),
        str(evidence.parent) + "\\.\\" + evidence.name,
    }

    invalid_path, stats = registry_module._validated_index_path_stats(
        raw_paths,
        resolved_root=root.resolve(),
    )

    assert invalid_path is None
    assert set(stats) == raw_paths
    assert all(value is not None for value in stats.values())


def test_saved_registry_summary_builds_conflict_report_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import quant_us.research.evidence_registry as registry_module

    _write_candidate(tmp_path)
    registry_module.rebuild_evidence_registry(tmp_path)
    original_conflict_report = registry_module._registry_conflict_report
    conflict_report_calls = 0

    def counting_conflict_report(
        registry: dict[str, object],
        **kwargs: object,
    ) -> dict[str, object]:
        nonlocal conflict_report_calls
        conflict_report_calls += 1
        return original_conflict_report(registry, **kwargs)

    monkeypatch.setattr(
        registry_module,
        "_registry_conflict_report",
        counting_conflict_report,
    )

    summary = registry_module.inspect_saved_evidence_registry_summary(tmp_path)

    assert summary["registry_integrity_status"] == "PASS/STABLE"
    assert conflict_report_calls == 1


def test_saved_registry_summary_cancellation_is_fail_closed(
    tmp_path: Path,
) -> None:
    import quant_us.research.evidence_registry as registry_module

    _write_candidate(tmp_path)
    registry_module.rebuild_evidence_registry(tmp_path)
    checks = 0

    def cancel_during_validation() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 3

    with pytest.raises(registry_module.EvidenceRegistryInspectionCancelled):
        registry_module.inspect_saved_evidence_registry_summary(
            tmp_path,
            should_cancel=cancel_during_validation,
        )


def test_index_path_batch_cancellation_stops_before_full_scan(
    tmp_path: Path,
) -> None:
    import quant_us.research.evidence_registry as registry_module

    root = tmp_path / "data"
    paths: set[str] = set()
    for index in range(128):
        path = root / "evidence" / f"evidence-{index}.json"
        _write_json(path, {"index": index})
        paths.add(str(path))
    resolved_root = root.resolve()
    cancellation_checks = 0

    def cancel_before_metadata_scan() -> bool:
        nonlocal cancellation_checks
        cancellation_checks += 1
        return cancellation_checks >= 4

    with pytest.raises(registry_module.EvidenceRegistryInspectionCancelled):
        registry_module._validated_index_path_stats(
            paths,
            resolved_root=resolved_root,
            should_cancel=cancel_before_metadata_scan,
        )

    assert cancellation_checks == 4


def test_index_path_batch_validation_matches_full_resolve_boundary(
    tmp_path: Path,
) -> None:
    import quant_us.research.evidence_registry as registry_module

    root = tmp_path / "data"
    root.mkdir()
    ordinary = root / "nested" / "ordinary.json"
    _write_json(ordinary, {"ok": True})
    cases = (
        root,
        root / "..",
        ordinary,
        root / "nested" / "missing.json",
        root / "nested" / ".." / "nested" / "ordinary.json",
        tmp_path / "outside.json",
        root / ".." / "outside.json",
    )
    resolved_root = root.resolve()

    for path in cases:
        try:
            path.resolve(strict=False).relative_to(resolved_root)
            legacy_within_root = True
        except (OSError, ValueError):
            legacy_within_root = False
        invalid_path, _stats = registry_module._validated_index_path_stats(
            {str(path)},
            resolved_root=resolved_root,
        )
        assert (invalid_path is None) is legacy_within_root


def test_index_path_batch_rejects_external_parent_when_leaf_resolves_inside(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import quant_us.research.evidence_registry as registry_module

    root = tmp_path / "data"
    inside = root / "inside.json"
    outside_parent = tmp_path / "outside"
    outside_link = outside_parent / "link.json"
    _write_json(inside, {"inside": True})
    outside_parent.mkdir()
    resolved_root = root.resolve()
    original_resolve = Path.resolve
    original_lstat = Path.lstat
    inside_stat = inside.stat()

    def mocked_resolve(path: Path, *args: object, **kwargs: object) -> Path:
        if path == outside_parent:
            return outside_parent
        if path == outside_link:
            return inside
        return original_resolve(path, *args, **kwargs)

    def mocked_lstat(path: Path, *args: object, **kwargs: object):
        if path == outside_link:
            return inside_stat
        return original_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", mocked_resolve)
    monkeypatch.setattr(Path, "lstat", mocked_lstat)
    monkeypatch.setattr(registry_module, "_stat_is_reparse_point", lambda _stat: True)

    invalid_path, stats = registry_module._validated_index_path_stats(
        {str(outside_link)},
        resolved_root=resolved_root,
    )

    assert invalid_path == str(outside_link)
    assert stats == {}


def test_index_path_batch_external_parent_cache_hit_is_history_independent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import quant_us.research.evidence_registry as registry_module

    root = tmp_path / "data"
    inside = root / "middle" / "inside.json"
    external_leaf = tmp_path / "zz-external-link.json"
    _write_json(inside, {"inside": True})
    resolved_root = root.resolve()
    original_resolve = Path.resolve
    original_lstat = Path.lstat
    inside_stat = inside.stat()

    def mocked_resolve(path: Path, *args: object, **kwargs: object) -> Path:
        if path == external_leaf:
            return inside
        return original_resolve(path, *args, **kwargs)

    def mocked_lstat(path: Path, *args: object, **kwargs: object):
        if path == external_leaf:
            return inside_stat
        return original_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", mocked_resolve)
    monkeypatch.setattr(Path, "lstat", mocked_lstat)
    monkeypatch.setattr(registry_module, "_stat_is_reparse_point", lambda _stat: True)

    invalid_path, stats = registry_module._validated_index_path_stats(
        {str(root), str(inside), str(external_leaf)},
        resolved_root=resolved_root,
    )

    assert invalid_path == str(external_leaf)
    assert stats == {}


def test_index_path_batch_validation_rejects_parent_and_file_reparse_escape(
    tmp_path: Path,
) -> None:
    import quant_us.research.evidence_registry as registry_module

    root = tmp_path / "data"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    outside_file = outside / "evidence.json"
    _write_json(outside_file, {"outside": True})

    linked_parent = root / "linked-parent"
    linked_file = root / "linked-file.json"
    try:
        linked_parent.symlink_to(outside, target_is_directory=True)
        linked_file.symlink_to(outside_file)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    resolved_root = root.resolve()
    for escaped_path in (linked_parent / outside_file.name, linked_file):
        invalid_path, _stats = registry_module._validated_index_path_stats(
            {str(escaped_path)},
            resolved_root=resolved_root,
        )
        assert invalid_path == str(escaped_path)


def test_index_path_batch_validation_fully_resolves_reparse_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import quant_us.research.evidence_registry as registry_module

    root = tmp_path / "data"
    evidence = root / "evidence.json"
    _write_json(evidence, {"ok": True})
    resolved_root = root.resolve()
    original_resolve = Path.resolve
    resolve_calls: list[Path] = []

    def counting_resolve(path: Path, *args: object, **kwargs: object) -> Path:
        resolve_calls.append(path)
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", counting_resolve)
    monkeypatch.setattr(registry_module, "_stat_is_reparse_point", lambda _stat: True)

    invalid_path, stats = registry_module._validated_index_path_stats(
        {str(evidence)},
        resolved_root=resolved_root,
    )

    assert invalid_path is None
    assert stats[str(evidence)] is not None
    assert evidence in resolve_calls
