from __future__ import annotations

import ast
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess

import jsonschema
import pytest

from scripts import build_cn_equity_current_head_gate_report as gate


REPO_ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 7, 24, 16, 30, tzinfo=timezone.utc)


def _head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _operator(head: str) -> dict:
    return gate.build_current_head_read_model(
        repo_root=REPO_ROOT,
        current_head=head,
        generated_at=NOW,
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build(tmp_path: Path, **overrides) -> dict:
    head = _head()
    values = {
        "repo_root": REPO_ROOT,
        "output_root": tmp_path,
        "current_head": head,
        "generated_at": NOW,
        "operator_payload": _operator(head),
    }
    values.update(overrides)
    return gate.build_cn_equity_current_head_gate(**values)


def test_builders_are_serial_and_successful_wrapper_stays_blocked(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    report = _build(tmp_path, stage_hook=calls.append)

    assert calls == list(gate.STAGE_ORDER)
    assert report["builder_order"] == list(gate.STAGE_ORDER)
    assert report["wrapper_status"] == "success"
    assert report["status"] == "blocked"
    assert report["decision"] == "blocked_fail_closed"
    assert report["root_blocker_count"] > 0
    assert len(
        {item["code"] for item in report["root_blockers"]}
    ) == report["root_blocker_count"]
    assert all(value is False for value in report["safety_flags"].values())
    assert report["readiness"] == {
        "quality_checked": True,
        "research_ready": False,
        "backtest_ready": False,
        "promotion_evidence_ready": False,
        "paper_ready": False,
        "live_ready": False,
    }
    paper = _read_json(tmp_path / gate.STAGE_ARTIFACTS["paper_readiness"])
    assert paper["status"] == "blocked"
    assert paper["decision"] == "blocked_fail_closed"


def test_stage_schema_head_hash_freshness_and_dependencies(
    tmp_path: Path,
) -> None:
    report = _build(tmp_path)
    stage_schema = _read_json(REPO_ROOT / gate.STAGE_SCHEMA)
    previous_path: Path | None = None

    for ordinal, stage_id in enumerate(gate.STAGE_ORDER, start=1):
        path = tmp_path / gate.STAGE_ARTIFACTS[stage_id]
        payload = _read_json(path)
        jsonschema.Draft202012Validator(
            stage_schema,
            format_checker=jsonschema.FormatChecker(),
        ).validate(payload)
        record = report["stage_reports"][stage_id]
        assert payload["stage_ordinal"] == ordinal
        assert payload["source_head"] == _head()
        assert payload["freshness"] == "current_head"
        assert record["sha256"] == _sha256(path)
        assert payload["input_set_sha256"] == gate._hash_mapping(
            payload["input_hashes"]
        )
        assert all(
            value is False for value in payload["safety_flags"].values()
        )
        if previous_path is None:
            assert payload["dependencies"] == []
        else:
            assert len(payload["dependencies"]) == 1
            dependency = payload["dependencies"][0]
            assert dependency["path"] == previous_path.as_posix()
            assert dependency["sha256"] == _sha256(tmp_path / previous_path)
        previous_path = gate.STAGE_ARTIFACTS[stage_id]

    assert sum(
        record["root_blocker_count"]
        for record in report["stage_reports"].values()
    ) == report["root_blocker_count"]
    gate.validate_gate_bundle(
        report,
        repo_root=REPO_ROOT,
        output_root=tmp_path,
        expected_head=_head(),
        evaluated_at=NOW,
        operator_payload=_operator(_head()),
    )


def test_root_blockers_dedupe_and_filter_report_self_references() -> None:
    payload = _operator(_head())
    first = dict(payload["blockers"][0])
    payload["blockers"].extend(
        [
            first,
            {
                **first,
                "code": "classification:readiness=quality_checked",
            },
            {
                **first,
                "code": "domain_read_model_missing",
            },
            {
                **first,
                "code": "cn_equity_current_head_gate_report_blocked",
            },
        ]
    )

    roots = gate.extract_root_blockers(payload)
    codes = [item["code"] for item in roots]

    assert len(codes) == len(set(codes))
    assert "classification:readiness=quality_checked" not in codes
    assert "domain_read_model_missing" not in codes
    assert "cn_equity_current_head_gate_report_blocked" not in codes


def test_unsafe_operator_flag_fails_before_artifact_publication(
    tmp_path: Path,
) -> None:
    head = _head()
    operator = deepcopy(_operator(head))
    operator["safety"]["paper_allowed"] = True

    with pytest.raises(
        gate.CNCurrentHeadGateError,
        match="operator_contract_invalid|unsafe_flag",
    ):
        _build(tmp_path, operator_payload=operator)

    assert not (tmp_path / gate.FINAL_ARTIFACT).exists()
    assert not any(
        (tmp_path / path).exists()
        for path in gate.STAGE_ARTIFACTS.values()
    )


def test_current_head_mismatch_fails_closed_without_artifact(
    tmp_path: Path,
) -> None:
    head = _head()
    with pytest.raises(
        gate.CNCurrentHeadGateError,
        match="operator_contract_invalid",
    ):
        gate.build_cn_equity_current_head_gate(
            repo_root=REPO_ROOT,
            output_root=tmp_path,
            current_head="f" * 40,
            generated_at=NOW,
            operator_payload=_operator(head),
        )
    assert not (tmp_path / gate.FINAL_ARTIFACT).exists()


def test_builder_failure_before_publish_preserves_existing_latest(
    tmp_path: Path,
) -> None:
    final_path = tmp_path / gate.FINAL_ARTIFACT
    first_stage_path = tmp_path / gate.STAGE_ARTIFACTS["dataready"]
    final_path.parent.mkdir(parents=True)
    first_stage_path.parent.mkdir(parents=True)
    final_path.write_bytes(b'{"before":"final"}\n')
    first_stage_path.write_bytes(b'{"before":"dataready"}\n')

    def fail() -> None:
        raise RuntimeError("injected_before_publish_failure")

    with pytest.raises(
        RuntimeError,
        match="injected_before_publish_failure",
    ):
        _build(tmp_path, before_publish=fail)

    assert final_path.read_bytes() == b'{"before":"final"}\n'
    assert first_stage_path.read_bytes() == b'{"before":"dataready"}\n'
    assert not (tmp_path / gate.LOCK_PATH).exists()


def test_existing_single_writer_lock_blocks_overlap(
    tmp_path: Path,
) -> None:
    lock = tmp_path / gate.LOCK_PATH
    lock.parent.mkdir(parents=True)
    lock.write_text('{"owner":"other-writer"}\n', encoding="utf-8")

    with pytest.raises(
        gate.CNCurrentHeadGateError,
        match="writer_lock_conflict",
    ):
        _build(tmp_path)


def test_tampered_stage_hash_and_expired_report_are_blocked(
    tmp_path: Path,
) -> None:
    head = _head()
    operator = _operator(head)
    report = _build(tmp_path, operator_payload=operator)
    stage_path = tmp_path / gate.STAGE_ARTIFACTS["replay"]
    stage_path.write_text('{"tampered":true}\n', encoding="utf-8")

    with pytest.raises(
        gate.CNCurrentHeadGateError,
        match="input_hash_mismatch|artifact_hash_mismatch",
    ):
        gate.validate_gate_bundle(
            report,
            repo_root=REPO_ROOT,
            output_root=tmp_path,
            expected_head=head,
            evaluated_at=NOW,
            operator_payload=operator,
        )

    clean_root = tmp_path / "clean"
    clean_report = _build(clean_root, operator_payload=operator)
    with pytest.raises(
        gate.CNCurrentHeadGateError,
        match="artifact_stale",
    ):
        gate.validate_gate_bundle(
            clean_report,
            repo_root=REPO_ROOT,
            output_root=clean_root,
            expected_head=head,
            evaluated_at=NOW + gate.MAX_ARTIFACT_AGE + timedelta(seconds=1),
            operator_payload=operator,
        )


def test_builder_has_no_network_broker_sdk_or_secret_import_surface() -> None:
    path = REPO_ROOT / "scripts/build_cn_equity_current_head_gate_report.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", 1)[0])
    assert imports.isdisjoint(
        {
            "aiohttp",
            "httpx",
            "requests",
            "socket",
            "urllib",
            "xtquant",
        }
    )
