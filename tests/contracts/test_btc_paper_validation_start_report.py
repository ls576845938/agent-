from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path

import jsonschema
import pytest

import scripts.build_btc_paper_validation_start_report as btc_start_report_builder
from quant_us.backtest.ledger_pnl import compute_ledger_reconciliation_artifact_hash
from scripts.build_btc_paper_validation_start_report import (
    APPROVED_PREFLIGHT_COMMAND,
    APPROVED_RESUME_COMMAND,
    APPROVED_START_COMMAND,
    build_btc_paper_validation_start_report,
    write_btc_paper_validation_start_report,
)


REPORT = Path("artifacts/btc_paper_readiness/latest/btc_paper_validation_start_report.json")
SCHEMA = Path("schemas/btc_paper_validation_start_report.schema.json")


def test_btc_paper_validation_start_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_btc_paper_validation_start_report_write_is_atomic_on_replace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ControlledAtomicReplaceCrash(RuntimeError):
        pass

    output_root = tmp_path / "artifacts/btc_paper_readiness/latest"
    output_path = output_root / "btc_paper_validation_start_report.json"
    old_payload = {"schema_version": "old_start_report", "status": "blocked"}
    new_payload = {"schema_version": "new_start_report", "status": "ready_to_start_paper_validation"}
    output_root.mkdir(parents=True)
    output_path.write_text(json.dumps(old_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    original_text = output_path.read_text(encoding="utf-8")
    original_replace = btc_start_report_builder.os.replace

    def crash_start_report_replace(src: object, dst: object) -> None:
        if Path(dst).name == "btc_paper_validation_start_report.json":
            raise ControlledAtomicReplaceCrash("stop before atomic start report replace")
        original_replace(src, dst)

    monkeypatch.setattr(btc_start_report_builder.os, "replace", crash_start_report_replace)

    with pytest.raises(ControlledAtomicReplaceCrash):
        write_btc_paper_validation_start_report(new_payload, output_root)

    assert output_path.read_text(encoding="utf-8") == original_text
    assert json.loads(output_path.read_text(encoding="utf-8")) == old_payload
    assert not list(output_root.glob(".btc_paper_validation_start_report.json.*.tmp"))


def test_current_btc_paper_validation_start_is_fail_closed() -> None:
    payload = build_btc_paper_validation_start_report(generated_at="2026-05-23T00:00:00Z")

    assert payload["status"] == "blocked"
    assert payload["paper_start_allowed"] is False
    assert payload["paper_execution_authorized"] is False
    assert payload["commands"]["start_command"] == ""
    assert payload["commands"]["resume_command"] == ""
    assert payload["commands"]["preflight_command"] == ""
    assert payload["runtime"]["runner_supports_btc_usdm_perpetual"] is True
    assert payload["runtime"]["preflight_supports_btc_usdm_perpetual"] is True
    assert payload["readiness"]["manual_inputs_status"] == "manual_inputs_verified"
    assert payload["readiness"]["paper_gate_manual_inputs_complete"] is True
    assert payload["manual_inputs"]["manual_inputs_status"] == "manual_inputs_verified"
    assert payload["manual_inputs"]["paper_gate_manual_inputs_complete"] is True
    assert len(payload["manual_inputs"]["required_manual_inputs"]) == payload["readiness"]["required_manual_input_count"]
    operator = payload["operator_manual_unblock"]
    assert operator["packet_path"] == "artifacts/btc_data_status/latest/btc_manual_metadata_capture_operator_packet.json"
    assert operator["packet_exists"] is True
    assert operator["manual_inputs_status"] == "manual_inputs_verified"
    assert operator["paper_gate_manual_inputs_complete"] is True
    assert len(operator["required_manual_inputs"]) == 3
    assert operator["dry_run_command"].startswith("make dry-run-btc-paper-gate-manual-inputs")
    assert operator["apply_command"].startswith("make apply-btc-paper-gate-manual-inputs")
    assert operator["apply_and_validate_command"].startswith("make apply-and-validate-btc-paper-gate-manual-inputs")
    assert "BTC_FEE_TIER_SOURCE=manual_public_okx_swap_fee_schedule" in operator["dry_run_command"]
    assert "BTC_FEE_TIER_SOURCE_URL_OR_DOC=https://www.okx.com/en-us/fees" in operator["dry_run_command"]
    assert "BTC_FEE_TIER_SOURCE=manual_public_okx_swap_fee_schedule" in operator["apply_command"]
    assert "BTC_FEE_TIER_SOURCE_URL_OR_DOC=https://www.okx.com/en-us/fees" in operator["apply_command"]
    assert "BTC_FEE_TIER_SOURCE=manual_public_okx_swap_fee_schedule" in operator["apply_and_validate_command"]
    assert "BTC_FEE_TIER_SOURCE_URL_OR_DOC=https://www.okx.com/en-us/fees" in (
        operator["apply_and_validate_command"]
    )
    assert operator["post_apply_validation_command"] == "make validate-btc-evidence"
    assert {item["name"] for item in operator["capture_requests"]} == {"exchange_info", "funding_info"}
    assert operator["fee_tier_dry_run_command"].startswith("make dry-run-btc-fee-tier-overlay-import")
    assert operator["fee_tier_apply_command"].startswith("make apply-btc-fee-tier-overlay-import")
    assert "BTC_FEE_TIER_SOURCE=manual_public_okx_swap_fee_schedule" in operator["fee_tier_dry_run_command"]
    assert "BTC_FEE_TIER_SOURCE_URL_OR_DOC=https://www.okx.com/en-us/fees" in operator["fee_tier_dry_run_command"]
    assert operator["safety"]["api_key_required"] is False
    assert operator["safety"]["order_endpoints_allowed"] is False
    assert payload["preflight_probe"]["status"] == "BLOCKED"
    assert payload["preflight_probe"]["start_report_ready_required"] is False
    assert payload["preflight_probe"]["ready_without_start_report"] is False
    sequence = payload["unblock_sequence"]
    assert [step["gate"] for step in sequence] == [
        "manual_paper_gate_inputs",
        "perpetual_data_cost_evidence",
        "candidate_metric_gate",
        "human_paper_review",
        "paper_validation_start",
    ]
    assert [step["order"] for step in sequence] == [1, 2, 3, 4, 5]
    assert sequence[0]["status"] == "complete"
    assert sequence[0]["is_next_action"] is False
    assert sequence[0]["action"] == "none"
    assert sequence[0]["command"] == ""
    assert sequence[0]["blockers"] == []
    assert sequence[1]["gate"] == "perpetual_data_cost_evidence"
    assert sequence[1]["status"] == "blocked"
    assert sequence[1]["is_next_action"] is True
    assert sequence[1]["command"] == "make validate-btc-data-cost-repair"
    assert "btc_regime_contract_not_pass" in sequence[1]["blockers"]
    assert sequence[2]["gate"] == "candidate_metric_gate"
    assert sequence[2]["status"] == "blocked"
    assert sequence[2]["action"] == "design_new_fold_specific_hypothesis_or_select_better_candidate"
    assert sequence[2]["command"] == ""
    assert "artifacts/btc_candidate_gate/latest/candidate_bounded_retest_plan.json" in sequence[2]["evidence"]
    assert "artifacts/btc_candidate_gate/latest/candidate_bounded_retest_outcome_report.json" in sequence[2]["evidence"]
    assert sequence[3]["gate"] == "human_paper_review"
    assert sequence[3]["status"] == "pending_review"
    assert sequence[4]["gate"] == "paper_validation_start"
    assert sequence[4]["status"] == "blocked"
    assert sequence[4]["command"] == ""
    assert "btc_paper_validation_readiness_not_ready" in payload["blockers"]
    assert "btc_paper_validation_preflight_probe_not_pass" in payload["blockers"]
    assert "btc_paper_validation_runtime_missing" not in payload["blockers"]
    assert "btc_paper_validation_preflight_missing" not in payload["blockers"]


def test_start_report_missing_operator_packet_is_schema_valid_fail_closed(tmp_path: Path) -> None:
    _write_awaiting_manual_inputs_readiness(tmp_path)
    _write_compatible_btc_runtime(tmp_path)

    payload = build_btc_paper_validation_start_report(
        repo_root=tmp_path,
        generated_at="2026-05-23T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    manual_step = payload["unblock_sequence"][0]

    jsonschema.validate(payload, schema)
    assert payload["status"] == "blocked"
    assert payload["paper_start_allowed"] is False
    assert payload["paper_execution_authorized"] is False
    assert payload["next_required_action"] == "rebuild_btc_paper_readiness_chain"
    assert payload["commands"]["start_command"] == ""
    assert payload["commands"]["resume_command"] == ""
    assert payload["operator_manual_unblock"]["packet_path"] is None
    assert payload["operator_manual_unblock"]["packet_exists"] is False
    assert payload["operator_manual_unblock"]["apply_and_validate_command"] == ""
    assert "btc_paper_validation_operator_packet_missing" in payload["operator_manual_unblock"]["blockers"]
    assert "btc_paper_validation_operator_packet_missing" in payload["blockers"]
    assert manual_step["gate"] == "manual_paper_gate_inputs"
    assert manual_step["status"] == "blocked"
    assert manual_step["is_next_action"] is True
    assert manual_step["command"] == ""
    assert "btc_paper_validation_operator_packet_missing" in manual_step["blockers"]


def test_start_report_blocks_unsafe_operator_packet_before_start_command(tmp_path: Path) -> None:
    _write_ready_readiness(tmp_path)
    _write_compatible_btc_runtime(tmp_path)
    _write_operator_packet(
        tmp_path,
        safety_overrides={
            "private_endpoints_allowed": True,
            "order_endpoints_allowed": True,
        },
        capture_request_overrides={
            "endpoint": "GET /fapi/v2/account",
            "url": "https://fapi.binance.com/fapi/v2/account",
            "command": 'curl -sS -H "X-MBX-APIKEY: secret" "https://fapi.binance.com/fapi/v2/account"',
        },
    )

    payload = build_btc_paper_validation_start_report(
        repo_root=tmp_path,
        generated_at="2026-05-23T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    manual_step = payload["unblock_sequence"][0]
    blockers = payload["operator_manual_unblock"]["blockers"]

    jsonschema.validate(payload, schema)
    assert payload["status"] == "blocked"
    assert payload["paper_start_allowed"] is False
    assert payload["paper_execution_authorized"] is False
    assert payload["next_required_action"] == "repair_btc_manual_metadata_operator_packet"
    assert payload["commands"]["start_command"] == ""
    assert payload["commands"]["resume_command"] == ""
    assert "btc_paper_validation_operator_packet_private_endpoints_allowed" in blockers
    assert "btc_paper_validation_operator_packet_order_endpoints_allowed" in blockers
    assert "btc_paper_validation_operator_packet_unsafe_capture_request" in blockers
    assert "btc_paper_validation_operator_packet_private_endpoints_allowed" in payload["blockers"]
    assert manual_step["gate"] == "manual_paper_gate_inputs"
    assert manual_step["status"] == "blocked"
    assert manual_step["is_next_action"] is True
    assert "btc_paper_validation_operator_packet_order_endpoints_allowed" in manual_step["blockers"]


def test_start_report_blocks_operator_packet_capture_command_injection(tmp_path: Path) -> None:
    _write_ready_readiness(tmp_path)
    _write_compatible_btc_runtime(tmp_path)
    _write_operator_packet(
        tmp_path,
        capture_request_overrides={
            "command": (
                'curl -sS -o exchange_info_raw.json -w "%{http_code}\\n" '
                '"https://fapi.binance.com/fapi/v1/exchangeInfo" > exchange_info_http_status.txt; '
                'curl -sS "https://example.com/override" > exchange_info_raw.json'
            ),
        },
    )

    payload = build_btc_paper_validation_start_report(
        repo_root=tmp_path,
        generated_at="2026-05-23T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    assert payload["commands"]["start_command"] == ""
    assert "btc_paper_validation_operator_packet_unsafe_capture_request" in payload["operator_manual_unblock"]["blockers"]


def test_ready_readiness_still_blocks_without_btc_runtime(tmp_path: Path) -> None:
    _write_ready_readiness(tmp_path)

    payload = build_btc_paper_validation_start_report(
        repo_root=tmp_path,
        generated_at="2026-05-23T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    assert payload["next_required_action"] == "implement_btc_paper_validation_runtime"
    assert payload["readiness"]["status"] == "ready_for_paper_start"
    assert payload["approved_paper_review"]["approved"] is True
    assert payload["preflight_probe"]["status"] == "NOT_RUN"
    assert payload["commands"]["start_command"] == ""
    assert payload["commands"]["resume_command"] == ""
    assert payload["blockers"] == [
        "btc_paper_validation_runtime_missing",
        "btc_paper_validation_preflight_missing",
    ]


def test_ready_readiness_with_btc_runtime_emits_authorized_start_command(tmp_path: Path) -> None:
    _write_ready_readiness(tmp_path)
    _write_compatible_btc_runtime(tmp_path)

    payload = build_btc_paper_validation_start_report(
        repo_root=tmp_path,
        generated_at="2026-05-23T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "ready_to_start_paper_validation"
    assert payload["paper_start_allowed"] is True
    assert payload["paper_execution_authorized"] is True
    assert payload["next_required_action"] == "start_paper_validation"
    assert payload["ledger_session"]["status"] == "clean_start"
    assert payload["readiness"]["manual_inputs_status"] == "manual_inputs_verified"
    assert payload["readiness"]["paper_gate_manual_inputs_complete"] is True
    assert payload["manual_inputs"]["manual_inputs_status"] == "manual_inputs_verified"
    assert payload["manual_inputs"]["paper_gate_manual_inputs_complete"] is True
    assert {item["status"] for item in payload["manual_inputs"]["required_manual_inputs"]} == {"verified"}
    assert payload["operator_manual_unblock"]["manual_inputs_status"] == "manual_inputs_verified"
    assert payload["operator_manual_unblock"]["paper_gate_manual_inputs_complete"] is True
    assert payload["preflight_probe"]["status"] == "PASS"
    assert payload["preflight_probe"]["ready_without_start_report"] is True
    assert payload["preflight_probe"]["blocking_reasons"] == []
    start_step = payload["unblock_sequence"][-1]
    assert start_step["gate"] == "paper_validation_start"
    assert start_step["status"] == "ready"
    assert start_step["action"] == "start_paper_validation"
    assert start_step["command"] == APPROVED_START_COMMAND
    assert start_step["blockers"] == []
    assert payload["commands"]["start_command"] == APPROVED_START_COMMAND
    assert payload["commands"]["resume_command"] == ""
    assert payload["commands"]["preflight_command"] == APPROVED_PREFLIGHT_COMMAND
    assert payload["approved_paper_review"]["approval"]["valid"] is True
    assert payload["blockers"] == []


def test_start_report_blocks_unapproved_runner_overrides(tmp_path: Path) -> None:
    _write_ready_readiness(tmp_path)
    _write_compatible_btc_runtime(tmp_path)
    custom_runner = tmp_path / "tools/fake_run_btc_paper_validation.py"
    custom_preflight = tmp_path / "tools/fake_check_btc_paper_validation_readiness.py"
    custom_runner.parent.mkdir(parents=True, exist_ok=True)
    custom_runner.write_text(
        "\n".join(
            [
                "# btc_paper_validation_runtime_v1",
                'MARKET_TYPE = "usds_m_perpetual"',
                'SYMBOL = "BTCUSDT"',
            ]
        ),
        encoding="utf-8",
    )
    custom_preflight.write_text(
        "\n".join(
            [
                "# btc_paper_validation_preflight_v1",
                "import json",
                'MARKET_TYPE = "usds_m_perpetual"',
                'SYMBOL = "BTCUSDT"',
                (
                    'print(json.dumps({"schema_version": "btc_paper_validation_preflight_v1", '
                    '"status": "PASS", "blocking_reasons": []}))'
                ),
            ]
        ),
        encoding="utf-8",
    )

    payload = build_btc_paper_validation_start_report(
        repo_root=tmp_path,
        validation_runner=Path("tools/fake_run_btc_paper_validation.py"),
        preflight_runner=Path("tools/fake_check_btc_paper_validation_readiness.py"),
        generated_at="2026-05-23T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    assert payload["commands"]["start_command"] == ""
    assert "btc_paper_validation_unapproved_validation_runner" in payload["blockers"]
    assert "btc_paper_validation_unapproved_preflight_runner" in payload["blockers"]
    assert payload["runtime"]["checks"]["validation_runner_is_approved_default"] is False
    assert payload["runtime"]["checks"]["preflight_runner_is_approved_default"] is False


def test_start_report_blocks_readiness_with_invalid_approved_review_contract(tmp_path: Path) -> None:
    _write_ready_readiness(tmp_path)
    _write_compatible_btc_runtime(tmp_path)
    readiness_path = tmp_path / "artifacts/btc_paper_readiness/latest/btc_paper_readiness_report.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    review = readiness["approved_paper_review"]
    review["status"] = "APPROVED_FOR_LIVE"
    review["proposed_symbols"] = ["ETHUSDT"]
    review["approval"]["schema_version"] = ""
    review["approval"]["reviewer"] = ""
    review["approval"]["candidate_id"] = "btc_candidate_v2"
    review["approval"]["gate_snapshot"]["paper_execution_authorized"] = True
    review["approval"]["gate_snapshot"]["authorization_scope"] = "paper_execution"
    readiness_path.write_text(json.dumps(readiness, indent=2, sort_keys=True), encoding="utf-8")

    payload = build_btc_paper_validation_start_report(
        repo_root=tmp_path,
        generated_at="2026-05-23T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    assert payload["commands"]["start_command"] == ""
    assert "btc_paper_validation_approved_review_status_not_paper_only" in payload["blockers"]
    assert "btc_paper_validation_approved_review_symbol_scope_mismatch" in payload["blockers"]
    assert "btc_paper_validation_approved_review_approval_schema_invalid" in payload["blockers"]
    assert "btc_paper_validation_approved_review_reviewer_missing" in payload["blockers"]
    assert "btc_paper_validation_approved_review_candidate_snapshot_mismatch" in payload["blockers"]
    assert "btc_paper_validation_approved_review_scope_not_record_only" in payload["blockers"]
    assert "btc_paper_validation_approved_review_scope_not_human_review_only" in payload["blockers"]


def test_start_report_accepts_cli_style_approved_review_utc_offset(tmp_path: Path) -> None:
    _write_ready_readiness(tmp_path)
    _write_compatible_btc_runtime(tmp_path)
    readiness_path = tmp_path / "artifacts/btc_paper_readiness/latest/btc_paper_readiness_report.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    readiness["approved_paper_review"]["approval"]["timestamp"] = "2026-05-23T00:00:00+00:00"
    readiness_path.write_text(json.dumps(readiness, indent=2, sort_keys=True), encoding="utf-8")

    payload = build_btc_paper_validation_start_report(
        repo_root=tmp_path,
        generated_at="2026-05-23T00:00:00Z",
    )

    assert payload["status"] == "ready_to_start_paper_validation"
    assert payload["commands"]["start_command"] == APPROVED_START_COMMAND


def test_start_report_blocks_active_ledger_root_start_lock(tmp_path: Path) -> None:
    _write_ready_readiness(tmp_path)
    _write_compatible_btc_runtime(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    lock_fd = _hold_start_lock(ledger)

    try:
        payload = build_btc_paper_validation_start_report(
            repo_root=tmp_path,
            generated_at="2026-05-23T00:00:00Z",
        )
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)

    assert payload["status"] == "blocked"
    assert payload["paper_start_allowed"] is False
    assert payload["commands"]["start_command"] == ""
    assert payload["ledger_session"]["status"] == "clean_start"
    assert payload["ledger_session"]["start_lock_status"] == "active"
    assert payload["ledger_session"]["start_lock_claimable"] is False
    assert "btc_paper_validation_ledger_start_lock_active" in payload["blockers"]
    assert "btc_paper_validation_ledger_start_lock_active" in payload["unblock_sequence"][-1]["blockers"]


def test_start_report_reports_stale_ledger_root_start_lock_without_blocking(tmp_path: Path) -> None:
    _write_ready_readiness(tmp_path)
    _write_compatible_btc_runtime(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    _write_json(
        ledger / "audit/btc_paper_validation_start.lock.json",
        {
            "schema_version": "btc_paper_validation_ledger_start_lock_v1",
            "claim_id": "stale-start",
            "owner_pid": 999999999,
            "status": "start_claimed",
        },
    )

    payload = build_btc_paper_validation_start_report(
        repo_root=tmp_path,
        generated_at="2026-05-23T00:00:00Z",
    )

    assert payload["status"] == "ready_to_start_paper_validation"
    assert payload["paper_start_allowed"] is True
    assert payload["ledger_session"]["start_lock_status"] == "stale"
    assert payload["ledger_session"]["start_lock_claimable"] is True
    assert payload["commands"]["start_command"] == APPROVED_START_COMMAND
    assert payload["blockers"] == []


def test_ready_readiness_with_existing_session_emits_resume_command_only(tmp_path: Path) -> None:
    _write_ready_readiness(tmp_path)
    _write_compatible_btc_runtime(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    recon_path, recon_hash = _write_reconciliation_artifact(ledger)
    _write_json(
        ledger / "validation_state.json",
        {
            "schema_version": "btc_paper_validation_state_v1",
            "asset": "btc",
            "symbol": "BTCUSDT",
            "market_type": "usds_m_perpetual",
            "days_required": 30,
            "days_completed": 1,
            "consecutive_clean_days": 1,
            "completed_cycle_keys": ["previous_cycle"],
            "daily_results": [
                {
                    "run_id": "btc_paper_previous",
                    "cycle_key": "previous_cycle",
                    "clean": True,
                    "equity_consistent": True,
                    "reconciliation_status": "clean",
                    "ledger_reconciliation_artifact_path": str(recon_path),
                    "ledger_reconciliation_artifact_hash": recon_hash,
                    "orders": 0,
                    "fills": 0,
                }
            ],
        },
    )

    payload = build_btc_paper_validation_start_report(
        repo_root=tmp_path,
        generated_at="2026-05-23T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    start_step = payload["unblock_sequence"][-1]

    jsonschema.validate(payload, schema)
    assert payload["status"] == "ready_to_start_paper_validation"
    assert payload["next_required_action"] == "resume_paper_validation"
    assert payload["ledger_session"]["status"] == "resumable"
    assert payload["ledger_session"]["validation_state_exists"] is True
    assert payload["ledger_session"]["latest_reconciliation_artifact_verified"] is True
    assert payload["commands"]["start_command"] == ""
    assert payload["commands"]["resume_command"] == APPROVED_RESUME_COMMAND
    assert start_step["action"] == "resume_paper_validation"
    assert start_step["command"] == APPROVED_RESUME_COMMAND
    assert payload["blockers"] == []


def test_ready_readiness_with_malformed_validation_state_blocks_resume_command(tmp_path: Path) -> None:
    _write_ready_readiness(tmp_path)
    _write_compatible_btc_runtime(tmp_path)
    _write_json(tmp_path / "data/paper_ledger/btc/validation_state.json", {"foo": "bar"})

    payload = build_btc_paper_validation_start_report(
        repo_root=tmp_path,
        generated_at="2026-05-23T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "blocked"
    assert payload["ledger_session"]["status"] == "dirty"
    assert payload["ledger_session"]["validation_state_exists"] is True
    assert payload["ledger_session"]["validation_state_valid"] is False
    assert payload["commands"]["start_command"] == ""
    assert payload["commands"]["resume_command"] == ""
    assert "btc_paper_validation_ledger_session_dirty" in payload["blockers"]


def test_ready_readiness_with_manifest_only_requires_recovery_not_resume(tmp_path: Path) -> None:
    _write_ready_readiness(tmp_path)
    _write_compatible_btc_runtime(tmp_path)
    _write_json(
        tmp_path / "data/paper_ledger/btc/audit/paper_session_manifest.json",
        {
            "schema_version": "btc_paper_validation_session_manifest_v1",
            "run_id": "stale_manifest_without_state",
        },
    )

    payload = build_btc_paper_validation_start_report(
        repo_root=tmp_path,
        generated_at="2026-05-23T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "blocked"
    assert payload["ledger_session"]["status"] == "recovery_required"
    assert payload["ledger_session"]["session_manifest_count"] == 1
    assert payload["ledger_session"]["validation_state_exists"] is False
    assert payload["commands"]["start_command"] == ""
    assert payload["commands"]["resume_command"] == ""
    assert "btc_paper_validation_ledger_recovery_required" in payload["blockers"]


def test_ready_readiness_with_in_progress_marker_reports_marker_details(tmp_path: Path) -> None:
    _write_ready_readiness(tmp_path)
    _write_compatible_btc_runtime(tmp_path)
    marker = tmp_path / "data/paper_ledger/btc/audit/paper_validation_in_progress/btc_paper_partial.json"
    _write_json(
        marker,
        {
            "schema_version": "btc_paper_validation_in_progress_cycle_v1",
            "run_id": "btc_paper_partial",
            "cycle_key": "partial_cycle",
            "status": "ledger_write_pending",
            "start": "2026-05-22T00:00:00Z",
            "end": "2026-05-22T01:00:00Z",
        },
    )

    payload = build_btc_paper_validation_start_report(
        repo_root=tmp_path,
        generated_at="2026-05-23T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "blocked"
    assert payload["ledger_session"]["status"] == "recovery_required"
    assert payload["ledger_session"]["in_progress_cycle_markers"] == [
        "data/paper_ledger/btc/audit/paper_validation_in_progress/btc_paper_partial.json"
    ]
    assert payload["ledger_session"]["in_progress_cycle_marker_details"] == [
        {
            "path": "data/paper_ledger/btc/audit/paper_validation_in_progress/btc_paper_partial.json",
            "parse_ok": True,
            "schema_version": "btc_paper_validation_in_progress_cycle_v1",
            "run_id": "btc_paper_partial",
            "cycle_key": "partial_cycle",
            "status": "ledger_write_pending",
            "start": "2026-05-22T00:00:00Z",
            "end": "2026-05-22T01:00:00Z",
            "blockers": [],
        }
    ]
    assert "btc_paper_validation_ledger_recovery_required" in payload["blockers"]


def test_ready_readiness_with_malformed_in_progress_marker_reports_parse_error(tmp_path: Path) -> None:
    _write_ready_readiness(tmp_path)
    _write_compatible_btc_runtime(tmp_path)
    marker = tmp_path / "data/paper_ledger/btc/audit/paper_validation_in_progress/btc_paper_partial.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("{not-json\n", encoding="utf-8")

    payload = build_btc_paper_validation_start_report(
        repo_root=tmp_path,
        generated_at="2026-05-23T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "blocked"
    assert payload["ledger_session"]["status"] == "recovery_required"
    assert payload["ledger_session"]["in_progress_cycle_marker_details"] == [
        {
            "path": "data/paper_ledger/btc/audit/paper_validation_in_progress/btc_paper_partial.json",
            "parse_ok": False,
            "schema_version": "",
            "run_id": "",
            "cycle_key": "",
            "status": "unknown",
            "start": "",
            "end": "",
            "blockers": ["btc_paper_validation_in_progress_marker_invalid_json"],
        }
    ]
    assert payload["commands"]["start_command"] == ""
    assert payload["commands"]["resume_command"] == ""
    assert "btc_paper_validation_ledger_recovery_required" in payload["blockers"]


def test_ready_readiness_with_unclean_previous_reconciliation_blocks_resume(tmp_path: Path) -> None:
    _write_ready_readiness(tmp_path)
    _write_compatible_btc_runtime(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    recon_path, recon_hash = _write_reconciliation_artifact(ledger)
    _write_json(
        ledger / "validation_state.json",
        {
            "schema_version": "btc_paper_validation_state_v1",
            "asset": "btc",
            "symbol": "BTCUSDT",
            "market_type": "usds_m_perpetual",
            "days_required": 30,
            "days_completed": 1,
            "consecutive_clean_days": 0,
            "completed_cycle_keys": ["previous_cycle"],
            "daily_results": [
                {
                    "run_id": "btc_paper_previous",
                    "cycle_key": "previous_cycle",
                    "clean": False,
                    "equity_consistent": False,
                    "reconciliation_status": "breaks_detected",
                    "ledger_reconciliation_artifact_path": str(recon_path),
                    "ledger_reconciliation_artifact_hash": recon_hash,
                    "orders": 1,
                    "fills": 1,
                }
            ],
        },
    )

    payload = build_btc_paper_validation_start_report(
        repo_root=tmp_path,
        generated_at="2026-05-23T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "blocked"
    assert payload["ledger_session"]["status"] == "resumable"
    assert payload["ledger_session"]["reconciliation_clean"] is False
    assert payload["ledger_session"]["latest_reconciliation_artifact_verified"] is True
    assert payload["ledger_session"]["latest_reconciliation_status"] == "breaks_detected"
    assert payload["commands"]["start_command"] == ""
    assert payload["commands"]["resume_command"] == ""
    assert "btc_paper_validation_reconciliation_not_clean" in payload["blockers"]


def test_ready_readiness_with_unclean_history_blocks_resume_even_when_latest_clean(tmp_path: Path) -> None:
    _write_ready_readiness(tmp_path)
    _write_compatible_btc_runtime(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    unclean_recon_path, unclean_recon_hash = _write_reconciliation_artifact(ledger, passed=False)
    clean_recon_path, clean_recon_hash = _write_reconciliation_artifact(ledger)
    _write_json(
        ledger / "validation_state.json",
        {
            "schema_version": "btc_paper_validation_state_v1",
            "asset": "btc",
            "symbol": "BTCUSDT",
            "market_type": "usds_m_perpetual",
            "days_required": 30,
            "days_completed": 2,
            "consecutive_clean_days": 1,
            "completed_cycle_keys": ["unclean_cycle", "clean_cycle"],
            "daily_results": [
                {
                    "run_id": "btc_paper_unclean",
                    "cycle_key": "unclean_cycle",
                    "clean": False,
                    "equity_consistent": False,
                    "reconciliation_status": "breaks_detected",
                    "ledger_reconciliation_artifact_path": str(unclean_recon_path),
                    "ledger_reconciliation_artifact_hash": unclean_recon_hash,
                    "orders": 1,
                    "fills": 1,
                },
                {
                    "run_id": "btc_paper_clean",
                    "cycle_key": "clean_cycle",
                    "clean": True,
                    "equity_consistent": True,
                    "reconciliation_status": "clean",
                    "ledger_reconciliation_artifact_path": str(clean_recon_path),
                    "ledger_reconciliation_artifact_hash": clean_recon_hash,
                    "orders": 0,
                    "fills": 0,
                },
            ],
        },
    )

    payload = build_btc_paper_validation_start_report(
        repo_root=tmp_path,
        generated_at="2026-05-23T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "blocked"
    assert payload["ledger_session"]["status"] == "resumable"
    assert payload["ledger_session"]["reconciliation_clean"] is False
    assert payload["commands"]["start_command"] == ""
    assert payload["commands"]["resume_command"] == ""
    assert "btc_paper_validation_reconciliation_not_clean" in payload["blockers"]
    assert "btc_validation_state_daily_not_clean" in payload["ledger_session"]["latest_reconciliation_artifact_blockers"]


def test_ready_readiness_with_blocked_preflight_probe_does_not_emit_start_command(tmp_path: Path) -> None:
    _write_ready_readiness(tmp_path)
    _write_compatible_btc_runtime(
        tmp_path,
        preflight_status="BLOCKED",
        preflight_blocking_reasons=["btc_paper_validation_cost_model_blocked"],
    )

    payload = build_btc_paper_validation_start_report(
        repo_root=tmp_path,
        generated_at="2026-05-23T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    assert payload["preflight_probe"]["status"] == "BLOCKED"
    assert payload["preflight_probe"]["ready_without_start_report"] is False
    assert payload["commands"]["start_command"] == ""
    assert payload["commands"]["resume_command"] == ""
    assert "btc_paper_validation_preflight_probe_not_pass" in payload["blockers"]
    assert "btc_paper_validation_cost_model_blocked" in payload["blockers"]


def test_blocked_candidate_gate_uses_bounded_retest_ready_command(tmp_path: Path) -> None:
    _write_candidate_blocked_readiness(tmp_path)
    _write_btc_candidate_bounded_retest_plan(
        tmp_path,
        execution_status="ready",
        retest_command="python3 scripts/research/run_btc_eventpf_wf_stabilization.py --run-id fixture",
    )
    _write_compatible_btc_runtime(tmp_path)

    payload = build_btc_paper_validation_start_report(
        repo_root=tmp_path,
        generated_at="2026-05-23T00:00:00Z",
    )
    candidate_step = payload["unblock_sequence"][2]

    assert payload["status"] == "blocked"
    assert candidate_step["gate"] == "candidate_metric_gate"
    assert candidate_step["status"] == "blocked"
    assert candidate_step["command"] == "python3 scripts/research/run_btc_eventpf_wf_stabilization.py --run-id fixture"
    assert "artifacts/btc_candidate_gate/latest/candidate_bounded_retest_plan.json" in candidate_step["evidence"]


def test_blocked_candidate_gate_uses_bounded_retest_readiness_check_when_not_ready(tmp_path: Path) -> None:
    _write_candidate_blocked_readiness(tmp_path)
    _write_btc_candidate_bounded_retest_plan(
        tmp_path,
        execution_status="blocked",
        retest_command="",
    )
    _write_compatible_btc_runtime(tmp_path)

    payload = build_btc_paper_validation_start_report(
        repo_root=tmp_path,
        generated_at="2026-05-23T00:00:00Z",
    )
    candidate_step = payload["unblock_sequence"][2]

    assert payload["status"] == "blocked"
    assert candidate_step["gate"] == "candidate_metric_gate"
    assert candidate_step["status"] == "blocked"
    assert candidate_step["command"] == "make check-btc-candidate-bounded-retest-readiness"
    assert "artifacts/btc_candidate_gate/latest/candidate_bounded_retest_plan.json" in candidate_step["evidence"]


def test_completed_failed_bounded_retest_blocks_same_retest_repeat(tmp_path: Path) -> None:
    _write_candidate_blocked_readiness(tmp_path)
    _write_btc_candidate_bounded_retest_plan(
        tmp_path,
        execution_status="ready",
        retest_command="python3 scripts/research/run_btc_eventpf_wf_stabilization.py --run-id fixture",
    )
    _write_btc_candidate_bounded_retest_failed_outcome(tmp_path)
    _write_compatible_btc_runtime(tmp_path)

    payload = build_btc_paper_validation_start_report(
        repo_root=tmp_path,
        generated_at="2026-05-23T00:00:00Z",
    )
    candidate_step = payload["unblock_sequence"][2]

    assert payload["status"] == "blocked"
    assert candidate_step["gate"] == "candidate_metric_gate"
    assert candidate_step["status"] == "blocked"
    assert candidate_step["action"] == "design_new_fold_specific_hypothesis_or_select_better_candidate"
    assert candidate_step["command"] == ""
    assert "artifacts/btc_candidate_gate/latest/candidate_bounded_retest_plan.json" in candidate_step["evidence"]
    assert "artifacts/btc_candidate_gate/latest/candidate_bounded_retest_outcome_report.json" in candidate_step["evidence"]
    assert "btc_candidate_bounded_retest_event_profit_factor_failed" in candidate_step["blockers"]


def test_schema_rejects_ready_start_without_evidence_pack(tmp_path: Path) -> None:
    _write_ready_readiness(tmp_path)
    _write_compatible_btc_runtime(tmp_path)
    payload = build_btc_paper_validation_start_report(
        repo_root=tmp_path,
        generated_at="2026-05-23T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["approved_paper_review"]["evidence_pack_exists"] = False

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_schema_rejects_ready_start_without_recorded_approval(tmp_path: Path) -> None:
    _write_ready_readiness(tmp_path)
    _write_compatible_btc_runtime(tmp_path)
    payload = build_btc_paper_validation_start_report(
        repo_root=tmp_path,
        generated_at="2026-05-23T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["approved_paper_review"]["approval"]["valid"] = False
    payload["approved_paper_review"]["approval"]["blockers"] = [
        "btc_paper_readiness_approved_paper_review_approval_missing"
    ]

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_schema_rejects_ready_start_without_preflight_probe_pass(tmp_path: Path) -> None:
    _write_ready_readiness(tmp_path)
    _write_compatible_btc_runtime(tmp_path)
    payload = build_btc_paper_validation_start_report(
        repo_root=tmp_path,
        generated_at="2026-05-23T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["preflight_probe"]["status"] = "BLOCKED"
    payload["preflight_probe"]["ready_without_start_report"] = False
    payload["preflight_probe"]["blocking_reasons"] = ["btc_paper_validation_cost_model_blocked"]

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_schema_rejects_resumable_ledger_session_without_valid_state(tmp_path: Path) -> None:
    _write_ready_readiness(tmp_path)
    _write_compatible_btc_runtime(tmp_path)
    payload = build_btc_paper_validation_start_report(
        repo_root=tmp_path,
        generated_at="2026-05-23T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["ledger_session"]["status"] = "resumable"
    payload["ledger_session"]["validation_state_exists"] = False
    payload["ledger_session"]["validation_state_valid"] = False

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_schema_rejects_blocked_start_with_command() -> None:
    payload = build_btc_paper_validation_start_report(generated_at="2026-05-23T00:00:00Z")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["commands"]["start_command"] = APPROVED_START_COMMAND

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_schema_rejects_blocked_manual_input_state_without_unblock_command() -> None:
    payload = build_btc_paper_validation_start_report(generated_at="2026-05-23T00:00:00Z")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["readiness"]["manual_inputs_status"] = "awaiting_manual_inputs"
    payload["manual_inputs"]["manual_inputs_status"] = "awaiting_manual_inputs"
    payload["operator_manual_unblock"]["manual_inputs_status"] = "awaiting_manual_inputs"
    payload["operator_manual_unblock"]["paper_gate_manual_inputs_complete"] = False
    payload["operator_manual_unblock"]["blockers"] = ["btc_paper_validation_operator_manual_inputs_incomplete"]
    payload["operator_manual_unblock"]["dry_run_command"] = ""

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def _write_ready_readiness(root: Path) -> None:
    _write_json(
        root / "artifacts/btc_paper_readiness/latest/btc_paper_readiness_report.json",
        {
            "schema_version": "btc_paper_readiness_report_v1",
            "generated_at": "2026-05-23T00:00:00Z",
            "commit": "fixture",
            "branch": "fixture",
            "asset": "btc",
            "symbol": "BTCUSDT",
            "status": "ready_for_paper_start",
            "paper_queue_status": "approved",
            "paper_start_allowed": True,
            "paper_execution_authorized": True,
            "live_status": "frozen",
            "next_required_action": "start_paper_validation",
            "manual_inputs_status": "manual_inputs_verified",
            "paper_gate_manual_inputs_complete": True,
            "required_manual_inputs": [
                {
                    "name": "exchange_info",
                    "required_for": "exchange_info_verification",
                    "status": "verified",
                    "action": "none",
                    "blockers": [],
                },
                {
                    "name": "funding_info",
                    "required_for": "funding_info_endpoint_verification",
                    "status": "verified",
                    "action": "none",
                    "blockers": [],
                },
                {
                    "name": "fee_tier_overlay",
                    "required_for": "maker_taker_fee_tier_verification",
                    "status": "verified",
                    "action": "none",
                    "blockers": [],
                },
            ],
            "fee_tier_status": {
                "cost_model_report": "artifacts/btc_cost_model/latest/btc_cost_model_report.json",
                "cost_model_status": "pass",
                "fee_tier_verified": True,
                "manual_capture_required": False,
                "maker_fee_bps": 2.0,
                "taker_fee_bps": 4.0,
                "fee_tier_import_report_verified": True,
                "fee_blockers": [],
            },
            "requirements": {},
            "approved_paper_review": {
                "approved": True,
                "paper_review_id": "btc_review_001",
                "status": "APPROVED_FOR_PAPER_ONLY",
                "path": "data/research/paper_reviews/btc_review_001/review.json",
                "strategy_manifest_id": "btc_candidate_v1",
                "proposed_symbols": ["BTCUSDT"],
                "proposed_capital": 25000.0,
                "evidence_pack_path": "data/research/evidence_packs/btc_review_001/evidence_pack.json",
                "evidence_pack_exists": True,
                "approval": {
                    "valid": True,
                    "schema_version": "paper_review_approval_v1",
                    "reviewer": "risk_reviewer",
                    "reason": "paper validation approval only",
                    "timestamp": "2026-05-23T00:00:00Z",
                    "candidate_id": "btc_candidate_v1",
                    "commit_hash": "fixture",
                    "source": "data/research/evidence_packs/btc_review_001/evidence_pack.json",
                    "source_sha256": "fixture_sha256",
                    "gate_snapshot": {
                        "candidate_id": "btc_candidate_v1",
                        "decision": "READY_FOR_PAPER_REVIEW",
                        "paper_execution_authorized": False,
                        "authorization_scope": "human_review_only",
                    },
                    "blockers": [],
                },
            },
            "blockers": [],
            "evidence": {},
        },
    )


def _write_awaiting_manual_inputs_readiness(root: Path) -> None:
    readiness = _ready_readiness_payload()
    readiness["status"] = "blocked"
    readiness["paper_queue_status"] = "locked"
    readiness["paper_start_allowed"] = False
    readiness["paper_execution_authorized"] = False
    readiness["next_required_action"] = "complete_btc_manual_paper_gate_inputs"
    readiness["manual_inputs_status"] = "awaiting_manual_inputs"
    readiness["paper_gate_manual_inputs_complete"] = False
    readiness["required_manual_inputs"] = [
        {
            "name": "exchange_info",
            "required_for": "exchange_info_verification",
            "status": "awaiting_capture",
            "action": "manual_capture_from_allowed_network",
            "blockers": ["btc_paper_readiness_exchange_info_manual_capture_required"],
        },
        {
            "name": "funding_info",
            "required_for": "funding_info_endpoint_verification",
            "status": "awaiting_capture",
            "action": "manual_capture_from_allowed_network",
            "blockers": ["btc_paper_readiness_funding_info_manual_capture_required"],
        },
        {
            "name": "fee_tier_overlay",
            "required_for": "maker_taker_fee_tier_verification",
            "status": "awaiting_capture",
            "action": "capture_public_fee_schedule_and_import",
            "blockers": ["btc_paper_readiness_fee_tier_overlay_manual_capture_required"],
        },
    ]
    readiness["fee_tier_status"] = {
        "cost_model_report": "artifacts/btc_cost_model/latest/btc_cost_model_report.json",
        "cost_model_status": "blocked",
        "fee_tier_verified": False,
        "manual_capture_required": True,
        "maker_fee_bps": None,
        "taker_fee_bps": None,
        "fee_tier_import_report_verified": False,
        "fee_blockers": ["btc_fee_tier_overlay_import_missing"],
    }
    readiness["requirements"] = {
        "manual_input_gate": _requirement_fixture(
            "blocked",
            {"operator_packet": "artifacts/btc_data_status/latest/btc_manual_metadata_capture_operator_packet.json"},
            ["btc_paper_readiness_manual_inputs_incomplete"],
        ),
        "data_source_gate": _requirement_fixture("complete", {}, {}),
        "cost_ledger_gate": _requirement_fixture("complete", {}, {}),
        "candidate_gate": _requirement_fixture("complete", {}, {}),
        "paper_review_gate": _requirement_fixture("complete", {}, {}),
        "runtime_boundary_gate": _requirement_fixture("complete", {}, {}),
    }
    readiness["blockers"] = ["btc_paper_readiness_manual_inputs_incomplete"]
    _write_json(root / "artifacts/btc_paper_readiness/latest/btc_paper_readiness_report.json", readiness)


def _write_operator_packet(
    root: Path,
    *,
    safety_overrides: dict[str, object] | None = None,
    capture_request_overrides: dict[str, object] | None = None,
) -> None:
    inputs = [
        {
            "name": "exchange_info",
            "required_for": "exchange_info_verification",
            "status": "verified",
            "action": "none",
            "blockers": [],
        },
        {
            "name": "funding_info",
            "required_for": "funding_info_endpoint_verification",
            "status": "verified",
            "action": "none",
            "blockers": [],
        },
        {
            "name": "fee_tier_overlay",
            "required_for": "maker_taker_fee_tier_verification",
            "status": "verified",
            "action": "none",
            "blockers": [],
        },
    ]
    exchange_request = {
        "name": "exchange_info",
        "required_for": "exchange_info_verification",
        "endpoint": "GET /fapi/v1/exchangeInfo",
        "url": "https://fapi.binance.com/fapi/v1/exchangeInfo",
        "command": (
            'curl -sS -o exchange_info_raw.json -w "%{http_code}\\n" '
            '"https://fapi.binance.com/fapi/v1/exchangeInfo" > exchange_info_http_status.txt'
        ),
        "output_file": "exchange_info_raw.json",
        "http_status_file": "exchange_info_http_status.txt",
        "required_http_status": 200,
    }
    if capture_request_overrides:
        exchange_request.update(capture_request_overrides)
    safety = {
        "api_key_required": False,
        "private_endpoints_allowed": False,
        "order_endpoints_allowed": False,
        "writes_bundle_files_during_capture": False,
        "strategy_retest_allowed": False,
        "paper_or_live_unlock_allowed": False,
    }
    safety.update(safety_overrides or {})
    _write_json(
        root / "artifacts/btc_data_status/latest/btc_manual_metadata_capture_operator_packet.json",
        {
            "schema_version": "btc_manual_metadata_capture_operator_packet_v1",
            "status": "metadata_verified",
            "manual_inputs_status": "manual_inputs_verified",
            "paper_gate_manual_inputs_complete": True,
            "required_manual_inputs": inputs,
            "paper_gate_manual_inputs_request": {
                "dry_run_command": "make dry-run-btc-paper-gate-manual-inputs",
                "apply_command": "make apply-btc-paper-gate-manual-inputs",
                "apply_and_validate_command": "make apply-and-validate-btc-paper-gate-manual-inputs",
                "post_apply_rebuild_command": "make rebuild-btc-paper-readiness-chain",
                "post_apply_validation_command": "make validate-btc-evidence",
                "post_apply_readiness_command": "make check-btc-paper-validation-readiness",
            },
            "fee_tier_overlay_request": {
                "dry_run_command": "make dry-run-btc-fee-tier-overlay-import",
                "import_command": "make apply-btc-fee-tier-overlay-import",
            },
            "capture_requests": [
                exchange_request,
                {
                    "name": "funding_info",
                    "required_for": "funding_info_endpoint_verification",
                    "endpoint": "GET /fapi/v1/fundingInfo",
                    "url": "https://fapi.binance.com/fapi/v1/fundingInfo",
                    "command": (
                        'curl -sS -o funding_info_raw.json -w "%{http_code}\\n" '
                        '"https://fapi.binance.com/fapi/v1/fundingInfo" > funding_info_http_status.txt'
                    ),
                    "output_file": "funding_info_raw.json",
                    "http_status_file": "funding_info_http_status.txt",
                    "required_http_status": 200,
                },
            ],
            "safety": safety,
            "blockers": [],
        },
    )


def _write_candidate_blocked_readiness(root: Path) -> None:
    readiness = _ready_readiness_payload()
    readiness["status"] = "blocked"
    readiness["paper_queue_status"] = "locked"
    readiness["paper_start_allowed"] = False
    readiness["paper_execution_authorized"] = False
    readiness["next_required_action"] = "run_bounded_candidate_retest_after_data_cost"
    readiness["approved_paper_review"] = {
        "approved": False,
        "paper_review_id": "",
        "status": "missing",
        "path": "",
        "strategy_manifest_id": "",
        "proposed_symbols": [],
        "proposed_capital": 0.0,
        "evidence_pack_path": "",
        "evidence_pack_exists": False,
        "approval": {},
    }
    readiness["requirements"] = {
        "manual_input_gate": _requirement_fixture("complete", {}, {}),
        "data_source_gate": _requirement_fixture("complete", {}, {}),
        "cost_ledger_gate": _requirement_fixture("complete", {}, {}),
        "candidate_gate": _requirement_fixture(
            "blocked",
            {
                "candidate_gate": "artifacts/btc_candidate_gate/latest/candidate_gate_audit_report.json",
                "candidate_metric_repair": "artifacts/btc_candidate_gate/latest/candidate_metric_repair_report.json",
            },
            ["btc_paper_readiness_candidate_metric_repair_not_pass"],
        ),
        "paper_review_gate": _requirement_fixture(
            "pending_review",
            {},
            ["btc_paper_readiness_approved_paper_review_missing"],
        ),
        "runtime_boundary_gate": _requirement_fixture("complete", {}, {}),
    }
    readiness["blockers"] = [
        "btc_paper_readiness_candidate_metric_repair_not_pass",
        "btc_paper_readiness_approved_paper_review_missing",
    ]
    _write_json(root / "artifacts/btc_paper_readiness/latest/btc_paper_readiness_report.json", readiness)


def _ready_readiness_payload() -> dict[str, object]:
    return {
        "schema_version": "btc_paper_readiness_report_v1",
        "generated_at": "2026-05-23T00:00:00Z",
        "commit": "fixture",
        "branch": "fixture",
        "asset": "btc",
        "symbol": "BTCUSDT",
        "status": "ready_for_paper_start",
        "paper_queue_status": "approved",
        "paper_start_allowed": True,
        "paper_execution_authorized": True,
        "live_status": "frozen",
        "next_required_action": "start_paper_validation",
        "manual_inputs_status": "manual_inputs_verified",
        "paper_gate_manual_inputs_complete": True,
        "required_manual_inputs": [
            {
                "name": "exchange_info",
                "required_for": "exchange_info_verification",
                "status": "verified",
                "action": "none",
                "blockers": [],
            },
            {
                "name": "funding_info",
                "required_for": "funding_info_endpoint_verification",
                "status": "verified",
                "action": "none",
                "blockers": [],
            },
            {
                "name": "fee_tier_overlay",
                "required_for": "maker_taker_fee_tier_verification",
                "status": "verified",
                "action": "none",
                "blockers": [],
            },
        ],
        "fee_tier_status": {
            "cost_model_report": "artifacts/btc_cost_model/latest/btc_cost_model_report.json",
            "cost_model_status": "pass",
            "fee_tier_verified": True,
            "manual_capture_required": False,
            "maker_fee_bps": 2.0,
            "taker_fee_bps": 4.0,
            "fee_tier_import_report_verified": True,
            "fee_blockers": [],
        },
        "requirements": {},
        "approved_paper_review": {
            "approved": True,
            "paper_review_id": "btc_review_001",
            "status": "APPROVED_FOR_PAPER_ONLY",
            "path": "data/research/paper_reviews/btc_review_001/review.json",
            "strategy_manifest_id": "btc_candidate_v1",
            "proposed_symbols": ["BTCUSDT"],
            "proposed_capital": 25000.0,
            "evidence_pack_path": "data/research/evidence_packs/btc_review_001/evidence_pack.json",
            "evidence_pack_exists": True,
            "approval": {
                "valid": True,
                "schema_version": "paper_review_approval_v1",
                "reviewer": "risk_reviewer",
                "reason": "paper validation approval only",
                "timestamp": "2026-05-23T00:00:00Z",
                "candidate_id": "btc_candidate_v1",
                "commit_hash": "fixture",
                "source": "data/research/evidence_packs/btc_review_001/evidence_pack.json",
                "source_sha256": "fixture_sha256",
                "gate_snapshot": {
                    "candidate_id": "btc_candidate_v1",
                    "decision": "READY_FOR_PAPER_REVIEW",
                    "paper_execution_authorized": False,
                    "authorization_scope": "human_review_only",
                },
                "blockers": [],
            },
        },
        "blockers": [],
        "evidence": {},
    }


def _write_btc_candidate_bounded_retest_plan(
    root: Path,
    *,
    execution_status: str,
    retest_command: str,
) -> None:
    _write_json(
        root / "artifacts/btc_candidate_gate/latest/candidate_bounded_retest_plan.json",
        {
            "schema_version": "btc_candidate_bounded_retest_plan_v1",
            "status": "ready_for_bounded_retest" if execution_status == "ready" else "blocked_by_perpetual_data_cost",
            "retest_allowed": execution_status == "ready",
            "execution_plan": {
                "status": execution_status,
                "readiness_check_command": "make check-btc-candidate-bounded-retest-readiness",
                "retest_command": retest_command,
                "post_retest_validation_command": "make validate-btc-evidence",
            },
            "blockers": [] if execution_status == "ready" else ["btc_candidate_repair_perpetual_evidence_not_ready"],
        },
    )


def _write_btc_candidate_bounded_retest_failed_outcome(root: Path) -> None:
    _write_json(
        root / "artifacts/btc_candidate_gate/latest/candidate_bounded_retest_outcome_report.json",
        {
            "schema_version": "btc_candidate_bounded_retest_outcome_report_v1",
            "status": "completed_candidate_gate_failed",
            "run_id": "fixture_retest",
            "same_retest_repeat_allowed": False,
            "next_required_action": "design_new_fold_specific_hypothesis_or_select_better_candidate",
            "failed_metrics": ["event_profit_factor", "walk_forward_pass_rate"],
            "blockers": [
                "btc_candidate_bounded_retest_event_profit_factor_failed",
                "btc_candidate_bounded_retest_walk_forward_pass_rate_failed",
            ],
        },
    )


def _requirement_fixture(status: str, evidence: dict[str, object], blockers: list[str]) -> dict[str, object]:
    return {
        "status": status,
        "checks": {},
        "evidence": evidence,
        "blockers": blockers,
    }


def _write_compatible_btc_runtime(
    root: Path,
    *,
    preflight_status: str = "PASS",
    preflight_blocking_reasons: list[str] | None = None,
) -> None:
    runner = root / "scripts/run_btc_paper_validation.py"
    preflight = root / "scripts/check_btc_paper_validation_readiness.py"
    runner.parent.mkdir(parents=True, exist_ok=True)
    runner.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "# btc_paper_validation_runtime_v1",
                'MARKET_TYPE = "usds_m_perpetual"',
                'SYMBOL = "BTCUSDT"',
            ]
        ),
        encoding="utf-8",
    )
    preflight.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "# btc_paper_validation_preflight_v1",
                "import json",
                "import sys",
                'MARKET_TYPE = "usds_m_perpetual"',
                'SYMBOL = "BTCUSDT"',
                "if '--json' in sys.argv:",
                "    print(json.dumps({",
                '        "schema_version": "btc_paper_validation_preflight_v1",',
                f'        "status": "{preflight_status}",',
                f'        "blocking_reasons": {json.dumps(preflight_blocking_reasons or [])},',
                "    }))",
                f"    raise SystemExit({0 if preflight_status == 'PASS' else 1})",
            ]
        ),
        encoding="utf-8",
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _hold_start_lock(ledger: Path) -> int:
    lock = ledger / "audit/btc_paper_validation_start.lock.json"
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    payload = {
        "schema_version": "btc_paper_validation_ledger_start_lock_v1",
        "claim_id": "active-start",
        "owner_pid": os.getpid(),
        "status": "start_claimed",
    }
    os.write(fd, (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    os.fsync(fd)
    return fd


def _write_reconciliation_artifact(ledger: Path, *, passed: bool = True) -> tuple[Path, str]:
    payload: dict[str, object] = {
        "artifact_version": "ledger_reconciliation_v1",
        "generated_at": "2026-05-22T01:00:00+00:00",
        "as_of_utc": "2026-05-22T01:00:00+00:00",
        "initial_cash": 25000.0,
        "orders": {},
        "fills": {},
        "positions": {},
        "cash": {},
        "fees": {},
        "slippage": {},
        "pnl": {},
        "hashes": {},
        "integrity": {"passed": passed},
        "reconciliation": {"summary": {"passed": passed, "snapshot_count": 1}},
    }
    artifact_hash = compute_ledger_reconciliation_artifact_hash(payload)
    payload["artifact_hash"] = artifact_hash
    path = ledger / "reconciliation" / f"ledger_recon_artifact_{artifact_hash[:16]}.json"
    _write_json(path, payload)
    return path, artifact_hash
