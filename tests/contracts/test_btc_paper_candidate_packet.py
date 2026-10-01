from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.research.btc_paper_candidate_packet import (
    REQUIRED_PACKET_FIELDS,
    build_btc_paper_candidate_packet,
)


TS = datetime(2026, 7, 5, 9, 0, tzinfo=timezone.utc)


def test_btc_paper_candidate_packet_is_not_ready_when_promotion_gate_blocked(tmp_path: Path) -> None:
    promotion = _write_json(tmp_path / "promotion.json", _promotion_report(blocked=True))
    ledger = _write_json(tmp_path / "ledger.json", _strategy_ledger())

    report = build_btc_paper_candidate_packet(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        promotion_gate_path=promotion,
        strategy_ledger_path=ledger,
        generated_at_utc=TS,
    )

    assert report["schema_version"] == "btc_paper_candidate_packet_v1"
    assert report["decision"] == "btc_paper_candidate_packet_not_ready_no_paper_queue_write_no_live"
    assert report["paper_candidate_packet"]["packet_status"] == "not_ready"
    assert report["generation_authority"]["authority"] == "promotion_gate_control_only"
    assert report["generation_authority"]["packet_generation_allowed_by_promotion_gate"] is False
    assert report["generation_authority"]["manual_packet_write_allowed"] is False
    assert report["generation_authority"]["handwritten_packet_allowed"] is False
    assert set(report["required_packet_fields"]) == set(REQUIRED_PACKET_FIELDS)
    assert set(report["paper_candidate_packet"]).issuperset(REQUIRED_PACKET_FIELDS)
    packet = report["paper_candidate_packet"]
    assert packet["strategy_version"]["value"] == "stable_long_short"
    assert packet["strategy_version"]["status"] == "derived_from_strategy_ledger_blocked"
    assert packet["config_version"]["value"] == "btc_paper_runtime_config_from_promotion_gate"
    assert packet["config_version"]["aggregation_batch_id"] == "batch-ok"
    assert packet["data_version"]["value"] == "btc_market_data_freshness_passed_current_sources"
    assert packet["data_version"]["aggregation_batch_id"] == "batch-ok"
    assert packet["venue"]["value"] == "OKX"
    assert packet["instrument"]["value"] == "BTC-USDT-SWAP"
    assert report["missing_required_fields"] == ["reviewer"]
    assert "btc_paper_candidate_packet_promotion_gate_not_complete" in report["blockers"]
    assert any(gap["gap_id"] == "promotion_gate_not_complete" for gap in report["not_ready_gaps"])
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_candidate_created"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False

    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["paper_queue_write_allowed"] is False
    assert safety["paper_candidate_created"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["order_endpoint_used"] is False
    summary = (tmp_path / "out" / "btc_paper_candidate_packet_summary_cn.md").read_text(encoding="utf-8")
    assert "只读模板，不写 paper 队列，不解锁 live" in summary
    assert "为什么仍不能 paper" in summary
    assert "不能自动写 paper 队列或解锁 live" in summary


def test_btc_paper_candidate_packet_becomes_review_packet_only_after_promotion_gate_passes(tmp_path: Path) -> None:
    promotion = _write_json(tmp_path / "promotion.json", _promotion_report(blocked=False))
    ledger = _write_json(tmp_path / "ledger.json", _strategy_ledger())

    report = build_btc_paper_candidate_packet(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        promotion_gate_path=promotion,
        strategy_ledger_path=ledger,
        generated_at_utc=TS,
    )

    packet = report["paper_candidate_packet"]
    assert report["decision"] == "btc_paper_candidate_packet_ready_for_manual_review_no_queue_write_no_live"
    assert packet["packet_status"] == "ready_for_manual_review_packet"
    assert packet["packet_id"].startswith("btc_paper_candidate_packet:batch-ok")
    assert packet["strategy_version"]["value"] == "stable_long_short"
    assert packet["config_version"]["value"] == "btc_paper_runtime_config_from_promotion_gate"
    assert packet["config_version"]["aggregation_batch_id"] == "batch-ok"
    assert packet["data_version"]["freshness_status"] == "pass"
    assert packet["venue"]["value"] == "OKX"
    assert packet["instrument"]["value"] == "BTC-USDT-SWAP"
    assert packet["reviewer"]["status"] == "required_manual_review"
    assert report["missing_required_fields"] == ["reviewer"]
    assert report["generation_authority"]["packet_generation_allowed_by_promotion_gate"] is True
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    review_hash = report["reviewed_packet_hash"]
    assert review_hash["schema_version"] == "btc_paper_candidate_packet_review_hash_v1"
    assert review_hash["hash_method"] == "canonical_report_content_excluding_runtime_batch_fields_v1"
    assert len(review_hash["sha256"]) == 64


def test_btc_paper_candidate_packet_marks_old_code_approval_stale_without_unlocking(tmp_path: Path, monkeypatch) -> None:
    def fake_git(args, *, cwd):  # type: ignore[no-untyped-def]
        if list(args) == ["rev-parse", "--short", "HEAD"]:
            return "head123"
        if list(args) == ["branch", "--show-current"]:
            return "test"
        return ""

    monkeypatch.setattr("quant_crypto.research.btc_paper_candidate_packet._git", fake_git)
    promotion = _write_json(tmp_path / "promotion.json", _promotion_report(blocked=False))
    ledger = _write_json(tmp_path / "ledger.json", _strategy_ledger())
    manual = _write_json(
        tmp_path / "manual.json",
        {
            "status": "recorded_research_only",
            "manual_approval_recorded": True,
            "blockers": [],
            "approval_record": {
                "reviewer": "current_reviewer",
                "decision_date_utc": "2026-07-07T00:00:00Z",
                "decision": "approve_review_only_no_auto_paper_no_live",
                "approval_scope": "review_only_no_auto_paper_no_live",
                "reviewed_packet_hash": {"sha256": "f" * 64},
                "reviewed_source_code_commit": "old123",
            },
        },
    )

    report = build_btc_paper_candidate_packet(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        promotion_gate_path=promotion,
        strategy_ledger_path=ledger,
        manual_review_approval_path=manual,
        generated_at_utc=TS,
    )

    reviewer = report["paper_candidate_packet"]["reviewer"]
    assert report["code_commit"] == "head123"
    assert report["source_code_commit_current_head_match"] is True
    assert reviewer["status"] == "review_only_stale_code_version"
    assert reviewer["review_only_stale_code_version"] is True
    assert reviewer["review_record_current_and_hash_valid"] is False
    assert "reviewer" in report["missing_required_fields"]
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_btc_paper_candidate_packet_keeps_invalid_reviewer_metadata_without_unlocking(tmp_path: Path) -> None:
    promotion = _write_json(tmp_path / "promotion.json", _promotion_report(blocked=True))
    ledger = _write_json(tmp_path / "ledger.json", _strategy_ledger())
    manual = _write_json(
        tmp_path / "manual_review.json",
        {
            "status": "missing_or_invalid_research_only",
            "manual_approval_recorded": False,
            "blockers": ["btc_manual_paper_review_approval_packet_sha256_mismatch"],
            "approval_record": {
                "reviewer": "operator_review_only_record",
                "decision_date_utc": "2026-07-06T00:00:00Z",
                "decision": "approve_review_only_no_auto_paper_no_live",
                "approval_scope": "review_only_no_auto_paper_no_live",
                "reviewed_packet_sha256": "0" * 64,
            },
        },
    )

    report = build_btc_paper_candidate_packet(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        promotion_gate_path=promotion,
        strategy_ledger_path=ledger,
        manual_review_approval_path=manual,
        generated_at_utc=TS,
    )

    reviewer = report["paper_candidate_packet"]["reviewer"]
    assert reviewer["reviewer_id"] == "operator_review_only_record"
    assert reviewer["status"] == "manual_review_record_present_but_invalid_or_not_current"
    assert reviewer["review_record_current_and_hash_valid"] is False
    assert "btc_manual_paper_review_approval_packet_sha256_mismatch" in reviewer["review_blockers"]
    assert report["missing_required_fields"] == []
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_btc_paper_candidate_packet_review_hash_ignores_runtime_batch_fields(tmp_path: Path) -> None:
    promotion = _write_json(tmp_path / "promotion.json", _promotion_report(blocked=False))
    ledger = _write_json(tmp_path / "ledger.json", _strategy_ledger())

    first = build_btc_paper_candidate_packet(
        repo_root=tmp_path,
        output_dir=tmp_path / "out1",
        promotion_gate_path=promotion,
        strategy_ledger_path=ledger,
        generated_at_utc=TS,
        aggregation_batch_id="batch-runtime-1",
    )
    second = build_btc_paper_candidate_packet(
        repo_root=tmp_path,
        output_dir=tmp_path / "out2",
        promotion_gate_path=promotion,
        strategy_ledger_path=ledger,
        generated_at_utc=datetime(2026, 7, 6, 9, 0, tzinfo=timezone.utc),
        aggregation_batch_id="batch-runtime-2",
    )

    assert first["reviewed_packet_hash"]["sha256"] == second["reviewed_packet_hash"]["sha256"]


def test_btc_paper_candidate_packet_review_hash_ignores_manual_review_metadata(tmp_path: Path) -> None:
    promotion = _write_json(tmp_path / "promotion.json", _promotion_report(blocked=False))
    ledger = _write_json(tmp_path / "ledger.json", _strategy_ledger())
    old_manual = _write_json(
        tmp_path / "old_manual.json",
        {
            "status": "missing_or_invalid_research_only",
            "manual_approval_recorded": False,
            "blockers": ["btc_manual_paper_review_approval_packet_sha256_mismatch"],
            "approval_record": {
                "reviewer": "old_reviewer",
                "decision_date_utc": "2026-07-06T00:00:00Z",
                "decision": "approve_review_only_no_auto_paper_no_live",
                "approval_scope": "review_only_no_auto_paper_no_live",
                "reviewed_packet_sha256": "0" * 64,
            },
        },
    )
    current_manual = _write_json(
        tmp_path / "current_manual.json",
        {
            "status": "recorded_research_only",
            "manual_approval_recorded": True,
            "blockers": [],
            "approval_record": {
                "reviewer": "current_reviewer",
                "decision_date_utc": "2026-07-07T00:00:00Z",
                "decision": "approve_review_only_no_auto_paper_no_live",
                "approval_scope": "review_only_no_auto_paper_no_live",
                "reviewed_packet_hash": {"sha256": "f" * 64},
            },
        },
    )

    first = build_btc_paper_candidate_packet(
        repo_root=tmp_path,
        output_dir=tmp_path / "out1",
        promotion_gate_path=promotion,
        strategy_ledger_path=ledger,
        manual_review_approval_path=old_manual,
        generated_at_utc=TS,
    )
    second = build_btc_paper_candidate_packet(
        repo_root=tmp_path,
        output_dir=tmp_path / "out2",
        promotion_gate_path=promotion,
        strategy_ledger_path=ledger,
        manual_review_approval_path=current_manual,
        generated_at_utc=TS,
    )

    assert first["paper_candidate_packet"]["reviewer"]["reviewer_id"] == "old_reviewer"
    assert second["paper_candidate_packet"]["reviewer"]["reviewer_id"] == "current_reviewer"
    assert first["reviewed_packet_hash"]["sha256"] == second["reviewed_packet_hash"]["sha256"]


def test_btc_paper_candidate_packet_review_hash_ignores_manual_approval_root_cause_transition(tmp_path: Path) -> None:
    promotion = _write_json(
        tmp_path / "promotion.json",
        _promotion_report_with_root_causes(["manual_review_approval_missing", "data_wait"]),
    )
    ledger = _write_json(tmp_path / "ledger.json", _strategy_ledger())
    invalid_manual = _write_json(
        tmp_path / "invalid_manual.json",
        {
            "status": "missing_or_invalid_research_only",
            "manual_approval_recorded": False,
            "blockers": ["btc_manual_paper_review_approval_packet_sha256_mismatch"],
            "approval_record": {
                "reviewer": "old_reviewer",
                "decision_date_utc": "2026-07-06T00:00:00Z",
                "decision": "approve_review_only_no_auto_paper_no_live",
                "approval_scope": "review_only_no_auto_paper_no_live",
                "reviewed_packet_sha256": "0" * 64,
            },
        },
    )
    valid_manual = _write_json(
        tmp_path / "valid_manual.json",
        {
            "status": "recorded_research_only",
            "manual_approval_recorded": True,
            "blockers": [],
            "approval_record": {
                "reviewer": "current_reviewer",
                "decision_date_utc": "2026-07-07T00:00:00Z",
                "decision": "approve_review_only_no_auto_paper_no_live",
                "approval_scope": "review_only_no_auto_paper_no_live",
                "reviewed_packet_hash": {"sha256": "f" * 64},
            },
        },
    )

    first = build_btc_paper_candidate_packet(
        repo_root=tmp_path,
        output_dir=tmp_path / "out1",
        promotion_gate_path=promotion,
        strategy_ledger_path=ledger,
        manual_review_approval_path=invalid_manual,
        generated_at_utc=TS,
    )
    _write_json(promotion, _promotion_report_with_root_causes(["data_wait"]))
    second = build_btc_paper_candidate_packet(
        repo_root=tmp_path,
        output_dir=tmp_path / "out2",
        promotion_gate_path=promotion,
        strategy_ledger_path=ledger,
        manual_review_approval_path=valid_manual,
        generated_at_utc=TS,
    )

    assert "reviewer" in first["missing_required_fields"] or first["paper_candidate_packet"]["reviewer"]["reviewer_id"]
    assert "manual_review_approval_missing" not in json.dumps(second["root_cause_task_queue"])
    assert first["reviewed_packet_hash"]["sha256"] == second["reviewed_packet_hash"]["sha256"]


def test_btc_paper_candidate_packet_review_hash_ignores_legacy_approval_conflict_key_blocker(tmp_path: Path) -> None:
    promotion = _write_json(
        tmp_path / "promotion.json",
        _promotion_report_with_root_causes(["data_wait"]),
    )
    payload = json.loads(promotion.read_text(encoding="utf-8"))
    payload["key_blockers_cn"] = [
        "旧 paper readiness approval 与当前 gate blocked 冲突，继续 fail-closed。",
        "数据等待",
    ]
    _write_json(promotion, payload)
    ledger = _write_json(tmp_path / "ledger.json", _strategy_ledger())
    manual = _write_json(
        tmp_path / "manual.json",
        {
            "status": "recorded_research_only",
            "manual_approval_recorded": True,
            "blockers": [],
            "approval_record": {
                "reviewer": "current_reviewer",
                "decision_date_utc": "2026-07-07T00:00:00Z",
                "decision": "approve_review_only_no_auto_paper_no_live",
                "approval_scope": "review_only_no_auto_paper_no_live",
                "reviewed_packet_hash": {"sha256": "f" * 64},
            },
        },
    )

    first = build_btc_paper_candidate_packet(
        repo_root=tmp_path,
        output_dir=tmp_path / "out1",
        promotion_gate_path=promotion,
        strategy_ledger_path=ledger,
        manual_review_approval_path=manual,
        generated_at_utc=TS,
    )
    payload["key_blockers_cn"] = ["数据等待"]
    _write_json(promotion, payload)
    second = build_btc_paper_candidate_packet(
        repo_root=tmp_path,
        output_dir=tmp_path / "out2",
        promotion_gate_path=promotion,
        strategy_ledger_path=ledger,
        manual_review_approval_path=manual,
        generated_at_utc=TS,
    )

    assert first["reviewed_packet_hash"]["sha256"] == second["reviewed_packet_hash"]["sha256"]


def test_btc_paper_candidate_packet_fail_closed_when_sources_missing(tmp_path: Path) -> None:
    report = build_btc_paper_candidate_packet(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        promotion_gate_path=tmp_path / "missing_promotion.json",
        strategy_ledger_path=tmp_path / "missing_ledger.json",
        generated_at_utc=TS,
    )

    assert report["paper_candidate_packet"]["packet_status"] == "not_ready"
    assert "btc_paper_candidate_packet_missing_promotion_gate_report" in report["blockers"]
    assert "btc_paper_candidate_packet_missing_strategy_ledger_report" in report["blockers"]
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def _promotion_report(*, blocked: bool) -> dict:
    status = "blocked_research_only" if blocked else "complete_research_only_manual_review_required"
    blockers = ["runtime_not_connected"] if blocked else []
    root_matrix = [
        {
            "root_cause_id": "runtime_not_connected",
            "label_cn": "runtime 未接通",
            "owner": "runtime/replay engineer",
            "next_command": "py scripts/build_btc_gate_aggregation_chain.py",
            "acceptance_criteria": ["non-flat sample captures complete replay evidence"],
            "raw_blocker_count": 3,
        }
    ] if blocked else []
    return {
        "schema_version": "btc_promotion_gate_control_v1",
        "generated_at_utc": TS.isoformat(),
        "aggregation_batch_id": "batch-ok",
        "status": status,
        "decision": "promotion_decision",
        "code_commit": "abc123",
        "blockers": blockers,
        "safety_violations": [],
        "key_blockers_cn": ["runtime 证据不足"] if blocked else [],
        "artifact_freshness": {
            "status": "pass",
            "source_count": 2,
            "stale_source_count": 0,
            "dependency_newer_than_consumer_count": 0,
            "required_rebuild_reports": [],
            "sources": [
                {
                    "source_id": "paper_runtime_replay",
                    "path": "artifacts/runtime.json",
                    "status": "pass",
                    "source_generated_at_utc": TS.isoformat(),
                    "rebuild_command": "py scripts/build_runtime.py",
                }
            ],
        },
        "root_cause_dag": {"root_cause_matrix": root_matrix},
        "root_cause_task_queue": {
            "schema_version": "btc_root_cause_task_queue_v1",
            "immediate_development_items": root_matrix,
            "data_wait_items": [],
        },
        "source_paths": {
            "paper_exchange_rule": "artifacts/paper_exchange_rule.json",
            "kill_switch": "artifacts/kill_switch.json",
            "account_attestation": "artifacts/account_attestation.json",
            "api_key_audit": "artifacts/api_key_audit.json",
        },
        "gate": {
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
            "broker_or_order_allowed": False,
        },
    }


def _strategy_ledger() -> dict:
    return {
        "schema_version": "btc_strategy_ledger_v1",
        "generated_at_utc": TS.isoformat(),
        "code_commit": "abc123",
        "strategy_lines": [
            {
                "strategy_id": "stable_long_short",
                "display_name_cn": "稳健线 Long/Short Donchian Top5",
                "parameter_summary": "Donchian Top5 long/short",
                "latest_report_path": "artifacts/stable.json",
            }
        ],
        "gate": {
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        },
    }


def _promotion_report_with_root_causes(root_ids: list[str]) -> dict:
    root_matrix = [
        {
            "root_cause_id": root_id,
            "label_cn": root_id,
            "owner": "owner",
            "next_command": "next",
            "acceptance_criteria": ["criterion"],
            "raw_blocker_count": 1,
        }
        for root_id in root_ids
    ]
    report = _promotion_report(blocked=True)
    report["blockers"] = [f"blocker:{root_id}" for root_id in root_ids]
    report["key_blockers_cn"] = ["数据等待"]
    report["root_cause_dag"] = {"root_cause_matrix": root_matrix}
    report["root_cause_task_queue"] = {
        "schema_version": "btc_root_cause_task_queue_v1",
        "immediate_development_items": [row for row in root_matrix if row["root_cause_id"] == "manual_review_approval_missing"],
        "data_wait_items": [row for row in root_matrix if row["root_cause_id"] != "manual_review_approval_missing"],
    }
    return report


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
