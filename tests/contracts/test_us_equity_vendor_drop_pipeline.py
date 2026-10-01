from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.run_us_equity_vendor_drop_pipeline import run_us_equity_vendor_drop_pipeline


SCHEMA = Path("schemas/us_equity_vendor_drop_pipeline_run_report.schema.json")


def test_vendor_drop_pipeline_blocks_before_import_when_readiness_fails(tmp_path: Path) -> None:
    calls: list[str] = []

    def manual_package_fn(**_: object) -> dict[str, object]:
        calls.append("manual")
        return {"status": "manual_vendor_drop_package_ready", "blockers": []}

    def preflight_fn(**_: object) -> dict[str, object]:
        calls.append("preflight")
        return {"status": "vendor_drop_preflight_ready_for_readiness_check", "blockers": []}

    def readiness_fn(**_: object) -> dict[str, object]:
        calls.append("readiness")
        return {"status": "incoming_drop_blocked", "blockers": ["source_dir_missing"]}

    def import_fn(**_: object) -> dict[str, object]:
        calls.append("import")
        raise AssertionError("import must not run after readiness blocks")

    payload = run_us_equity_vendor_drop_pipeline(
        repo_root=tmp_path,
        source_dir=Path("missing_drop"),
        output=Path("out/pipeline.json"),
        markdown_output=Path("out/pipeline.md"),
        generated_at="2026-06-28T00:00:00Z",
        manual_package_fn=manual_package_fn,
        preflight_fn=preflight_fn,
        incoming_readiness_fn=readiness_fn,
        import_fn=import_fn,
        acceptance_fn=_passed("acceptance_ready_for_manual_config_apply", calls, "acceptance"),
        progress_fn=_passed("operator_drop_blocked", calls, "progress"),
        handoff_fn=_passed("handoff_blocked", calls, "handoff"),
    )

    _validate_schema(payload)
    assert calls == ["manual", "preflight", "readiness", "progress", "handoff"]
    assert payload["status"] == "vendor_drop_pipeline_blocked"
    assert payload["current_blocking_step"] == "incoming_drop_readiness"
    steps = {item["step_id"]: item for item in payload["steps"]}
    assert steps["local_csv_production_bundle_import"]["status"] == "SKIPPED"
    assert steps["local_csv_production_bundle_import"]["skipped_due_to_step_id"] == "incoming_drop_readiness"
    assert steps["pit_bundle_acceptance"]["status"] == "SKIPPED"
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / "out/pipeline.json").exists()
    assert (tmp_path / "out/pipeline.md").exists()


def test_vendor_drop_pipeline_blocks_import_when_preflight_fails_even_if_readiness_passes(tmp_path: Path) -> None:
    calls: list[str] = []

    payload = run_us_equity_vendor_drop_pipeline(
        repo_root=tmp_path,
        source_dir=Path("drop"),
        output=Path("out/pipeline.json"),
        markdown_output=Path("out/pipeline.md"),
        generated_at="2026-06-28T00:00:00Z",
        manual_package_fn=_passed("manual_vendor_drop_package_ready", calls, "manual"),
        preflight_fn=_blocked("vendor_drop_preflight_waiting_for_vendor_files", ["required_vendor_csv_missing"], calls, "preflight"),
        incoming_readiness_fn=_passed("incoming_drop_ready_for_import", calls, "readiness"),
        import_fn=_must_not_run("import"),
        acceptance_fn=_must_not_run("acceptance"),
        progress_fn=_passed("operator_drop_blocked", calls, "progress"),
        handoff_fn=_passed("handoff_blocked", calls, "handoff"),
    )

    _validate_schema(payload)
    assert calls == ["manual", "preflight", "readiness", "progress", "handoff"]
    assert payload["status"] == "vendor_drop_pipeline_blocked"
    assert payload["current_blocking_step"] == "vendor_drop_preflight"
    steps = {item["step_id"]: item for item in payload["steps"]}
    assert steps["local_csv_production_bundle_import"]["skipped_due_to_step_id"] == "vendor_drop_preflight"


def test_vendor_drop_pipeline_ready_for_manual_config_review_without_unlocking_paper_or_live(tmp_path: Path) -> None:
    calls: list[str] = []
    payload = run_us_equity_vendor_drop_pipeline(
        repo_root=tmp_path,
        source_dir=Path("drop"),
        output=Path("out/pipeline.json"),
        markdown_output=Path("out/pipeline.md"),
        generated_at="2026-06-28T00:00:00Z",
        manual_package_fn=_passed("manual_vendor_drop_package_ready", calls, "manual"),
        preflight_fn=_passed("vendor_drop_preflight_ready_for_readiness_check", calls, "preflight"),
        incoming_readiness_fn=_passed("incoming_drop_ready_for_import", calls, "readiness"),
        import_fn=_passed("production_bundle_imported", calls, "import"),
        acceptance_fn=_passed("acceptance_ready_for_manual_config_apply", calls, "acceptance"),
        progress_fn=_passed("operator_drop_complete_for_manual_review", calls, "progress"),
        handoff_fn=_passed("handoff_ready_for_operator_drop", calls, "handoff"),
    )

    _validate_schema(payload)
    assert calls == ["manual", "preflight", "readiness", "import", "acceptance", "progress", "handoff"]
    assert payload["status"] == "vendor_drop_pipeline_ready_for_manual_config_review"
    assert payload["current_blocking_step"] == "none"
    assert payload["blockers"] == []
    assert payload["guardrails"]["paper_or_live_unlock_allowed"] is False
    assert payload["guardrails"]["paper_simulation_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False


def test_vendor_drop_pipeline_blocks_unsafe_nested_live_flag(tmp_path: Path) -> None:
    calls: list[str] = []

    def unsafe_preflight_fn(**_: object) -> dict[str, object]:
        calls.append("preflight")
        return {
            "status": "vendor_drop_preflight_ready_for_readiness_check",
            "blockers": [],
            "guardrails": {"live_order_allowed": True},
        }

    payload = run_us_equity_vendor_drop_pipeline(
        repo_root=tmp_path,
        source_dir=Path("drop"),
        output=Path("out/pipeline.json"),
        markdown_output=Path("out/pipeline.md"),
        generated_at="2026-06-28T00:00:00Z",
        manual_package_fn=_passed("manual_vendor_drop_package_ready", calls, "manual"),
        preflight_fn=unsafe_preflight_fn,
        incoming_readiness_fn=_passed("incoming_drop_ready_for_import", calls, "readiness"),
        import_fn=_passed("production_bundle_imported", calls, "import"),
        acceptance_fn=_passed("acceptance_ready_for_manual_config_apply", calls, "acceptance"),
        progress_fn=_passed("operator_drop_complete_for_manual_review", calls, "progress"),
        handoff_fn=_passed("handoff_ready_for_operator_drop", calls, "handoff"),
    )

    _validate_schema(payload)
    assert payload["status"] == "vendor_drop_pipeline_blocked"
    assert payload["current_blocking_step"] == "unsafe_guardrail"
    assert payload["unsafe_flags"] == ["vendor_drop_preflight.guardrails.live_order_allowed=true"]
    assert "unsafe_flag:vendor_drop_preflight.guardrails.live_order_allowed=true" in payload["blockers"]


def test_vendor_drop_pipeline_schema_rejects_live_flag(tmp_path: Path) -> None:
    payload = run_us_equity_vendor_drop_pipeline(
        repo_root=tmp_path,
        source_dir=Path("missing_drop"),
        output=Path("out/pipeline.json"),
        markdown_output=Path("out/pipeline.md"),
        generated_at="2026-06-28T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def _passed(status: str, calls: list[str], label: str):
    def fn(**_: object) -> dict[str, object]:
        calls.append(label)
        return {"status": status, "blockers": [], "guardrails": {"live_order_allowed": False}}

    return fn


def _blocked(status: str, blockers: list[str], calls: list[str], label: str):
    def fn(**_: object) -> dict[str, object]:
        calls.append(label)
        return {"status": status, "blockers": blockers, "guardrails": {"live_order_allowed": False}}

    return fn


def _must_not_run(label: str):
    def fn(**_: object) -> dict[str, object]:
        raise AssertionError(f"{label} must not run")

    return fn


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
