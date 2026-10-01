from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import jsonschema
import pytest

import quant_us.application.us_equity_current_head_gate_rebuild as rebuild


HEAD = "a" * 40
OTHER_HEAD = "b" * 40
NOW = datetime(2026, 7, 24, 15, 0, tzinfo=timezone.utc)


def test_serialized_rebuild_publishes_blocked_current_head_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    builders = _fake_builders(calls)
    _patch_legacy_schema_validation(monkeypatch)
    _write_required_static_inputs(tmp_path)

    receipt = rebuild.rebuild_us_equity_current_head_gate(
        repo_root=tmp_path,
        current_head=HEAD,
        generated_at_utc=NOW,
        run_id="us-g10-contract",
        builder_overrides=builders,
    )

    assert calls == [
        *rebuild.PRIMARY_STEP_ORDER,
        "completion_dependency",
        "next_action_queue",
        "operator_unblock_packet",
        "completion_audit",
    ]
    assert receipt["step_order"] == [
        *rebuild.PRIMARY_STEP_ORDER,
        *rebuild.FINAL_CLOSURE_ORDER,
    ]
    assert receipt["status"] == "complete_blocked"
    assert receipt["wrapper_status"] == "success"
    assert receipt["decision"] == "blocked_fail_closed_no_paper_no_live"
    assert receipt["source_head"] == HEAD
    assert receipt["blocker_taxonomy"]["root_blocker_count"] == 1
    assert receipt["blocker_taxonomy"]["derived_reference_count"] == 4
    assert receipt["blockers"] == ["production_pit_evidence_unavailable"]
    assert len(receipt["outputs"]) == len(rebuild.LATEST_PATHS)
    assert all(
        row["source_head"] == HEAD for row in receipt["outputs"].values()
    )
    assert all(
        row["freshness"] == "current_head"
        for row in receipt["artifact_health"].values()
    )
    assert all(value is False for value in receipt["safety"].values())
    assert receipt["validation_checks"]["paper_ledger_written"] is False
    assert receipt["validation_checks"]["network_or_secret_used"] is False

    schema = _read_json(
        Path("schemas/us_equity_current_head_gate_rebuild.schema.json")
    )
    jsonschema.validate(receipt, schema)
    taxonomy = _read_json(tmp_path / rebuild.DEFAULT_TAXONOMY)
    taxonomy_schema = _read_json(
        Path("schemas/us_equity_current_head_blocker_taxonomy.schema.json")
    )
    jsonschema.validate(taxonomy, taxonomy_schema)


def test_builder_failure_restores_every_latest_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_legacy_schema_validation(monkeypatch)
    _write_required_static_inputs(tmp_path)
    original_path = tmp_path / rebuild.LATEST_PATHS["completion_dependency"]
    original_path.parent.mkdir(parents=True, exist_ok=True)
    original_path.write_text('{"before":true}\n', encoding="utf-8")

    builders = _fake_builders([])

    def fail(_context: rebuild.StepContext) -> dict[str, Any]:
        raise RuntimeError("injected_builder_failure")

    builders["portfolio_promotion"] = fail
    with pytest.raises(RuntimeError, match="injected_builder_failure"):
        rebuild.rebuild_us_equity_current_head_gate(
            repo_root=tmp_path,
            current_head=HEAD,
            generated_at_utc=NOW,
            run_id="us-g10-rollback",
            builder_overrides=builders,
        )

    assert original_path.read_text(encoding="utf-8") == '{"before":true}\n'
    assert not (tmp_path / rebuild.DEFAULT_RECEIPT).exists()
    assert not (tmp_path / rebuild.DEFAULT_TAXONOMY).exists()
    assert not (
        tmp_path / rebuild.LATEST_PATHS["portfolio_promotion"]
    ).exists()
    assert not (tmp_path / rebuild.DEFAULT_LOCK).exists()


def test_existing_writer_lock_stops_overlapping_rebuild(
    tmp_path: Path,
) -> None:
    lock = tmp_path / rebuild.DEFAULT_LOCK
    lock.parent.mkdir(parents=True)
    lock.write_text('{"owner":"other-writer"}', encoding="utf-8")

    with pytest.raises(
        rebuild.USCurrentHeadGateRebuildError,
        match="writer_lock_conflict",
    ):
        rebuild.rebuild_us_equity_current_head_gate(
            repo_root=tmp_path,
            current_head=HEAD,
            generated_at_utc=NOW,
            run_id="us-g10-lock-conflict",
            builder_overrides={},
        )


def test_artifact_health_blocks_commit_expiry_hash_and_input_drift(
    tmp_path: Path,
) -> None:
    output = tmp_path / "artifact.json"
    source = tmp_path / "source.json"
    output.write_text('{"status":"blocked"}\n', encoding="utf-8")
    source.write_text('{"version":1}\n', encoding="utf-8")
    record = {
        "path": "artifact.json",
        "sha256": _sha256(output),
        "source_head": OTHER_HEAD,
        "generated_at_utc": (NOW - timedelta(days=2)).isoformat(),
        "input_hashes": {"source.json": "0" * 64},
    }

    health = rebuild.evaluate_artifact_health(
        record=record,
        repo_root=tmp_path,
        current_head=HEAD,
        now=NOW,
    )

    assert health["freshness"] == "stale_blocked"
    assert "artifact_commit_mismatch" in health["blockers"]
    assert "artifact_expired" in health["blockers"]
    assert "artifact_input_hash_drift:source.json" in health["blockers"]

    output.write_text('{"status":"changed"}\n', encoding="utf-8")
    changed = rebuild.evaluate_artifact_health(
        record=record,
        repo_root=tmp_path,
        current_head=OTHER_HEAD,
        now=NOW - timedelta(days=2),
    )
    assert "artifact_hash_mismatch" in changed["blockers"]


def test_taxonomy_collapses_175_pit_references_to_one_root() -> None:
    taxonomy = rebuild.build_root_blocker_taxonomy(
        source_payloads={
            "completion_audit": {
                "blockers": [
                    f"production_pit_missing_field_{index}"
                    for index in range(175)
                ]
            }
        },
        source_head=HEAD,
        generated_at_utc=NOW,
        output_path=rebuild.DEFAULT_TAXONOMY,
    )

    assert taxonomy["root_blocker_count"] == 1
    assert taxonomy["derived_reference_count"] == 175
    assert taxonomy["root_blockers"][0]["code"] == (
        "production_pit_evidence_unavailable"
    )
    assert taxonomy["root_blockers"][0]["derived_reference_count"] == 175


def test_unsafe_true_flag_aborts_and_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_legacy_schema_validation(monkeypatch)
    _write_required_static_inputs(tmp_path)
    builders = _fake_builders([])

    def unsafe(context: rebuild.StepContext) -> dict[str, Any]:
        payload = _payload(context, "production_line")
        payload["guardrails"] = {"live_order_allowed": True}
        _write_json(context.output_path, payload)
        return payload

    builders["production_line"] = unsafe
    with pytest.raises(
        rebuild.USCurrentHeadGateRebuildError,
        match="unsafe_flag:production_line",
    ):
        rebuild.rebuild_us_equity_current_head_gate(
            repo_root=tmp_path,
            current_head=HEAD,
            generated_at_utc=NOW,
            run_id="us-g10-unsafe",
            builder_overrides=builders,
        )
    assert not (tmp_path / rebuild.DEFAULT_RECEIPT).exists()


def _fake_builders(
    calls: list[str],
) -> dict[str, rebuild.StepBuilder]:
    builders: dict[str, rebuild.StepBuilder] = {}
    for step_id in rebuild.PRIMARY_STEP_ORDER:

        def build(
            context: rebuild.StepContext,
            *,
            name: str = step_id,
        ) -> dict[str, Any]:
            calls.append(name)
            payload = _payload(context, name)
            _write_json(context.output_path, payload)
            if name == "live_readiness":
                _write_json(
                    context.repo_root
                    / rebuild.LATEST_PATHS["live_readiness_compat"],
                    payload,
                )
            return payload

        builders[step_id] = build
    return builders


def _payload(
    context: rebuild.StepContext,
    step_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": f"{step_id}_fixture_v1",
        "generated_at_utc": context.generated_at_utc.isoformat().replace(
            "+00:00",
            "Z",
        ),
        "source_head": context.current_head,
        "status": "blocked",
        "decision": "fixture_blocked_fail_closed",
        "blockers": (
            ["production_pit_bundle_missing"]
            if step_id
            in {
                "completion_dependency",
                "next_action_queue",
                "operator_unblock_packet",
                "completion_audit",
            }
            else []
        ),
        "safety": {
            "promotion_allowed": False,
            "paper_allowed": False,
            "live_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "broker_access_allowed": False,
            "paper_runner_started": False,
            "paper_queue_write_allowed": False,
            "real_order_submitted": False,
            "withdraw_allowed": False,
            "network_used": False,
        },
    }


def _patch_legacy_schema_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual = rebuild._validate_json_schema

    def validate(*, payload: Any, schema_path: Path) -> None:
        if schema_path.name.startswith("us_equity_current_head_"):
            actual(
                payload=payload,
                schema_path=Path("schemas") / schema_path.name,
            )

    monkeypatch.setattr(rebuild, "_validate_json_schema", validate)


def _write_required_static_inputs(root: Path) -> None:
    for relative in (
        rebuild.DEFAULT_CONFIG,
        Path("configs/strategies/us_equity_strategy_registry.json"),
        Path(
            "configs/governance/"
            "us_equity_domain_read_model_sources_v1.json"
        ),
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"fixture":true}\n', encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()
