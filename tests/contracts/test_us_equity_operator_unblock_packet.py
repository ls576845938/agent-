from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from quant_us.monitoring.operator_unblock_packet import build_us_equity_operator_unblock_packet


SCHEMA = Path("schemas/us_equity_operator_unblock_packet.schema.json")


def test_operator_unblock_packet_aggregates_external_manual_and_time_inputs(tmp_path: Path) -> None:
    _write_sources(tmp_path)

    payload = build_us_equity_operator_unblock_packet(
        repo_root=tmp_path,
        output=Path("out/unblock.json"),
        markdown_output=Path("out/unblock.md"),
        generated_at="2026-06-28T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "operator_unblock_open"
    assert payload["summary"] == {
        "open_count": 5,
        "external_input_count": 1,
        "manual_input_count": 2,
        "natural_time_count": 2,
        "paper_or_live_unlock_allowed": False,
        "live_order_allowed": False,
    }
    assert payload["next_operator_action"]["item_id"] == "production_pit_csv_drop"
    assert payload["external_inputs"][0]["required_files"] == [
        "universe_membership_events.csv",
        "delisted_symbols.csv",
    ]
    external = payload["external_inputs"][0]
    assert external["reason"] == "source_files_missing"
    assert external["next_action"].startswith("Place licensed PIT CSV files")
    assert external["evidence_path"].endswith("us_equity_local_pit_file_discovery_report.json")
    assert external["source_report"] == "pit_discovery"
    assert {item["route_id"] for item in external["acceptable_source_routes"]} == {"crsp", "curated_local_csv"}
    supplemental = {item["route_id"]: item for item in external["supplemental_source_boundaries"]}
    assert {"tiingo_eod", "ibkr_market_data", "fred"} <= set(supplemental)
    assert "standalone L4 promotion-clean approval" in supplemental["tiingo_eod"]["not_sufficient_for"]
    manual_ids = [item["item_id"] for item in payload["manual_inputs"]]
    assert manual_ids == ["broker_credentials_local_review", "manual_strategy_decision_record"]
    assert payload["manual_inputs"][0]["reason"] == "broker_credentials_local_review_missing"
    assert payload["manual_inputs"][0]["evidence_path"].endswith("us_equity_broker_credentials_review_report.json")
    connectivity = payload["manual_inputs"][0]["connectivity_evidence"]
    assert connectivity["evidence_role"] == "read_only_ibkr_market_data_connectivity_only"
    assert connectivity["operator_interpretation"]["connection_proven"] is True
    assert connectivity["operator_interpretation"]["can_satisfy_credential_review"] is False
    assert connectivity["operator_interpretation"]["can_unlock_paper_or_live"] is False
    assert connectivity["guardrails"]["order_endpoint_used"] is False
    assert payload["manual_inputs"][1]["reason"] == "us_equity_manual_decision_record_missing"
    assert payload["manual_inputs"][1]["evidence_path"].endswith("us_equity_manual_decision_record_report.json")
    natural_ids = [item["item_id"] for item in payload["natural_time_inputs"]]
    assert natural_ids == ["forward_observation_30d", "paper_simulation_evaluation"]
    assert payload["natural_time_inputs"][0]["reason"] == "forward_observation_less_than_30_days"
    assert payload["natural_time_inputs"][0]["source_report"] == "next_action_queue"
    for item in [*payload["external_inputs"], *payload["manual_inputs"], *payload["natural_time_inputs"]]:
        assert item["owner"]
        assert item["reason"]
        assert item["next_action"]
        assert item["evidence_path"]
        assert item["source_report"]
    assert payload["guardrails"]["files_copied"] is False
    assert payload["guardrails"]["local_review_mutated"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / "out/unblock.json").exists()
    assert (tmp_path / "out/unblock.md").exists()


def test_operator_unblock_packet_complete_when_no_inputs_are_open(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/us_equity_strategy_production_line/latest/us_equity_next_action_queue_report.json",
        {"status": "next_actions_complete", "actions": []},
    )
    _write_json(
        tmp_path / "artifacts/us_equity_data_lineage/latest/us_equity_local_pit_file_discovery_report.json",
        {"status": "pit_file_discovery_ready_for_copy", "missing_filenames": [], "ready_filenames": []},
    )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_broker_credentials_operator_handoff.json",
        {"status": "broker_credentials_handoff_ready_for_manual_review", "blockers": []},
    )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_broker_credentials_review_report.json",
        {"status": "broker_credentials_review_proven", "blockers": []},
    )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_decision_record_report.json",
        {"status": "manual_decision_record_valid", "blockers": []},
    )

    payload = build_us_equity_operator_unblock_packet(
        repo_root=tmp_path,
        output=Path("out/unblock.json"),
        markdown_output=Path("out/unblock.md"),
        generated_at="2026-06-28T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "operator_unblock_complete"
    assert payload["next_operator_action"] is None
    assert payload["summary"]["open_count"] == 0


def test_operator_unblock_packet_schema_rejects_live_unlock(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    payload = build_us_equity_operator_unblock_packet(
        repo_root=tmp_path,
        output=Path("out/unblock.json"),
        markdown_output=Path("out/unblock.md"),
        generated_at="2026-06-28T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def test_operator_unblock_packet_schema_rejects_item_without_evidence_path(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    payload = build_us_equity_operator_unblock_packet(
        repo_root=tmp_path,
        output=Path("out/unblock.json"),
        markdown_output=Path("out/unblock.md"),
        generated_at="2026-06-28T00:00:00Z",
    )
    payload["external_inputs"][0]["evidence_path"] = ""

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted unblock item without evidence_path")


def test_operator_unblock_packet_uses_blocked_gate_record_evidence_source(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    queue_path = tmp_path / "artifacts/us_equity_strategy_production_line/latest/us_equity_next_action_queue_report.json"
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    queue["actions"][0]["blocked_gate_records"] = [
        {
            "record_id": "production_pit_data:1",
            "milestone_id": "production_pit_data",
            "gate_id": "production_pit_data",
            "blocker": "source_universe_membership_events_file_missing",
            "owner": "operator_data_vendor",
            "reason": "Blocked by source_universe_membership_events_file_missing",
            "next_action": "Copy licensed PIT CSV files into incoming drop.",
            "evidence_path": "artifacts/us_equity_data_lineage/latest/us_equity_pit_procurement_readiness_report.json",
            "source_report": "pit_procurement_readiness",
            "actionability": "waiting",
            "dependency_type": "external_input",
        }
    ]
    queue_path.write_text(json.dumps(queue), encoding="utf-8")

    payload = build_us_equity_operator_unblock_packet(
        repo_root=tmp_path,
        output=Path("out/unblock.json"),
        markdown_output=Path("out/unblock.md"),
        generated_at="2026-06-28T00:00:00Z",
    )

    _validate_schema(payload)
    external = payload["external_inputs"][0]
    assert external["evidence_path"] == "artifacts/us_equity_data_lineage/latest/us_equity_pit_procurement_readiness_report.json"
    assert external["source_report"] == "pit_procurement_readiness"


def _write_sources(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/us_equity_strategy_production_line/latest/us_equity_next_action_queue_report.json",
        {
            "status": "next_actions_open",
            "actions": [
                _action("production_pit_data", "operator_data_vendor", "external_input", ["source_files_missing"]),
                _action("manual_review_signoff", "human_reviewer", "manual_review", ["manual_review_not_ready"]),
                _action("forward_observation_30d", "daily_forward_observation_scheduler", "natural_time", ["forward_observation_less_than_30_days"]),
                _action("paper_simulation_evaluation", "paper_simulation_scheduler", "natural_time", ["paper_simulation_ledger_not_started"]),
            ],
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_data_lineage/latest/us_equity_local_pit_file_discovery_report.json",
        {
            "status": "pit_file_discovery_no_complete_candidate_set",
            "missing_filenames": ["universe_membership_events.csv", "delisted_symbols.csv"],
            "ready_filenames": ["corporate_actions.csv"],
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_data_lineage/latest/us_equity_pit_procurement_readiness_report.json",
        {
            "status": "pit_procurement_ready_for_vendor_order",
            "acceptable_source_routes": [
                {"route_id": "crsp", "label": "CRSP / WRDS or CRSP direct export"},
                {"route_id": "curated_local_csv", "label": "Manually curated licensed local CSV bundle"},
            ],
            "supplemental_source_routes": [
                {
                    "route_id": "tiingo_eod",
                    "label": "Tiingo EOD price and adjusted bar data",
                    "not_sufficient_for": ["standalone L4 promotion-clean approval"],
                },
                {
                    "route_id": "ibkr_market_data",
                    "label": "Interactive Brokers market data",
                    "not_sufficient_for": ["survivorship-bias-free research universe"],
                },
                {
                    "route_id": "fred",
                    "label": "FRED macro time series and release metadata",
                    "not_sufficient_for": ["equity universe membership"],
                },
            ],
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_broker_credentials_operator_handoff.json",
        {
            "status": "broker_credentials_handoff_blocked",
            "blockers": ["broker_credentials_local_review_missing"],
            "broker_connectivity_evidence": {
                "evidence_role": "read_only_ibkr_market_data_connectivity_only",
                "operator_interpretation": {
                    "connection_proven": True,
                    "can_satisfy_credential_review": False,
                    "can_unlock_paper_or_live": False,
                    "manual_review_still_required": True,
                },
                "guardrails": {
                    "market_data_probe_only": True,
                    "private_account_endpoint_used": False,
                    "order_endpoint_used": False,
                    "broker_order_endpoint_used": False,
                    "real_order_submitted": False,
                    "paper_or_live_unlock_allowed": False,
                    "live_order_allowed": False,
                },
            },
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_broker_credentials_review_report.json",
        {"status": "broker_credentials_review_blocked", "blockers": ["broker_credentials_reviewer_missing"]},
    )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_decision_record_report.json",
        {"status": "manual_decision_record_missing_or_invalid", "blockers": ["us_equity_manual_decision_record_missing"]},
    )


def _action(milestone_id: str, owner: str, dependency_type: str, blockers: list[str]) -> dict[str, object]:
    return {
        "milestone_id": milestone_id,
        "owner": owner,
        "dependency_type": dependency_type,
        "recommended_command": "python scripts/run_us_equity_daily_production_line.py",
        "blockers": blockers,
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
