from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.research.btc_nautilus_oms_replay_field_audit import build_btc_nautilus_oms_replay_field_audit


def test_nautilus_audit_outputs_matrix_and_research_only_safety(tmp_path: Path) -> None:
    repo_root, external_root = _make_workspace(tmp_path)

    report = build_btc_nautilus_oms_replay_field_audit(
        repo_root=repo_root,
        external_references_root=external_root,
        generated_at_utc=datetime(2026, 7, 8, tzinfo=timezone.utc),
    )

    assert report["status"] == "complete_research_only"
    concept_ids = {row["concept_id"] for row in report["matrix"]}
    assert "order_lifecycle_and_reconciliation" in concept_ids
    assert "risk_mark_index_liquidation_fields" in concept_ids
    assert "post_only_maker_taker" in concept_ids
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["gate"]["broker_or_order_allowed"] is False
    assert report["adoption_boundary"]["copies_nautilus_source"] is False
    assert report["adoption_boundary"]["adds_nautilus_runtime_dependency"] is False
    assert all(row["paper_gate_credit"] is False for row in report["matrix"])


def test_nautilus_audit_records_expected_gap_types(tmp_path: Path) -> None:
    repo_root, external_root = _make_workspace(tmp_path)

    report = build_btc_nautilus_oms_replay_field_audit(
        repo_root=repo_root,
        external_references_root=external_root,
        generated_at_utc=datetime(2026, 7, 8, tzinfo=timezone.utc),
    )

    by_id = {row["concept_id"]: row for row in report["matrix"]}
    assert by_id["order_lifecycle_and_reconciliation"]["status"] == "covered"
    assert by_id["reduce_only_and_cancel_only"]["status"] == "partial"
    assert by_id["advanced_contingency_orders"]["status"] == "diagnostic_or_prohibited"
    assert report["summary"]["total_count"] == len(report["matrix"])
    assert report["required_followup_tickets"]


def test_nautilus_audit_writes_json_csv_markdown_and_safety(tmp_path: Path) -> None:
    repo_root, external_root = _make_workspace(tmp_path)

    report = build_btc_nautilus_oms_replay_field_audit(
        repo_root=repo_root,
        external_references_root=external_root,
        generated_at_utc=datetime(2026, 7, 8, tzinfo=timezone.utc),
    )

    json_path = repo_root / report["outputs"]["json"]
    csv_path = repo_root / report["outputs"]["matrix_csv"]
    markdown_path = repo_root / report["outputs"]["summary_cn"]
    safety_path = repo_root / report["outputs"]["paper_live_safety_status"]
    assert json_path.exists()
    assert csv_path.exists()
    assert markdown_path.exists()
    assert safety_path.exists()
    summary = markdown_path.read_text(encoding="utf-8")
    assert "Nautilus" in summary
    assert "不复制 NautilusTrader 源码" in summary
    safety = json.loads(safety_path.read_text(encoding="utf-8"))
    assert safety["paper_queue_write_allowed"] is False
    assert safety["third_party_runtime_dependency_added"] is False


def test_nautilus_audit_fail_closed_when_reference_missing(tmp_path: Path) -> None:
    repo_root, external_root = _make_workspace(tmp_path)
    (external_root / "nautilus_trader" / "README.md").unlink()

    report = build_btc_nautilus_oms_replay_field_audit(
        repo_root=repo_root,
        external_references_root=external_root,
        generated_at_utc=datetime(2026, 7, 8, tzinfo=timezone.utc),
    )

    assert report["status"] == "blocked_research_only"
    assert "source_missing:nautilus_readme" in report["blockers"]
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def _make_workspace(tmp_path: Path) -> tuple[Path, Path]:
    repo_root = tmp_path / "agent-"
    external_root = tmp_path / "external_references"
    (repo_root / "quant_us/core").mkdir(parents=True)
    (repo_root / "quant_crypto/oms").mkdir(parents=True)
    (repo_root / "quant_crypto/research").mkdir(parents=True)
    (external_root / "nautilus_trader/.git/refs/heads").mkdir(parents=True)
    (external_root / "nautilus_trader/.git/HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (external_root / "nautilus_trader/.git/refs/heads/main").write_text("c22f0a61234567890", encoding="utf-8")
    (external_root / "nautilus_trader/README.md").write_text(
        "deterministic event-driven runtime post-only reduce-only OCO OTO OUO",
        encoding="utf-8",
    )
    (repo_root / "quant_us/core/types.py").write_text(
        "OrderIntent order_type time_in_force symbol client_order_id AccountState account_id",
        encoding="utf-8",
    )
    (repo_root / "quant_crypto/oms/lifecycle.py").write_text(
        "submitted accepted partially_filled filled cancelled rejected expired reconciled",
        encoding="utf-8",
    )
    (repo_root / "quant_crypto/oms/paper_runtime_replay_session.py").write_text(
        "ordertype.market timeinforce.ioc order_records fill_records reconciliation_report unreconciled_count "
        "arrival_price fill_price benchmark_price fee",
        encoding="utf-8",
    )
    (repo_root / "quant_crypto/oms/execution_quality.py").write_text(
        "arrival_price fill_price benchmark_price implementation_shortfall fee maker taker",
        encoding="utf-8",
    )
    (repo_root / "quant_crypto/research/btc_perpetual_paper_runtime_replay.py").write_text(
        "fixture_capability_passed historical_drill_passed current_observe_only reduce_only cancel_only_mode "
        "blocked_by_cancel_only_mode mark_price index_price liquidation_buffer_bps risk_decision "
        "depth_fill_mapping no_gate_eligible_fill depth_not_visible mapping_logic_failed",
        encoding="utf-8",
    )
    return repo_root, external_root
