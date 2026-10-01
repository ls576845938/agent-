from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.research.btc_external_framework_adoption_tickets import (
    build_btc_external_framework_adoption_tickets,
)


def test_framework_adoption_tickets_are_fixed_and_research_only(tmp_path: Path) -> None:
    repo_root, external_root = _make_fake_workspace(tmp_path)

    report = build_btc_external_framework_adoption_tickets(
        repo_root=repo_root,
        external_references_root=external_root,
        generated_at_utc=datetime(2026, 7, 8, tzinfo=timezone.utc),
    )

    assert report["status"] == "complete_research_only"
    assert report["ticket_ids"] == [
        "btc_nautilus_oms_replay_field_audit",
        "btc_freqtrade_style_leakage_cli",
        "btc_hummingbot_ccxt_okx_metadata_runtime_probe",
    ]
    assert report["gate"]["research_only"] is True
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["gate"]["broker_or_order_allowed"] is False
    assert report["adoption_policy"]["copy_third_party_source_into_agent"] == (
        "allowed_only_after_license_and_provenance_review"
    )
    assert report["adoption_policy"]["permissive_copy_allowed"] == ["Apache-2.0", "MIT"]
    assert report["adoption_policy"]["copyleft_core_copy_prohibited"] == ["GPL-3.0", "LGPL-3.0"]
    by_id = {ticket["ticket_id"]: ticket for ticket in report["tickets"]}
    assert by_id["btc_nautilus_oms_replay_field_audit"]["copy_allowed_after_review"] is False
    assert by_id["btc_freqtrade_style_leakage_cli"]["copy_allowed_after_review"] is False
    assert by_id["btc_hummingbot_ccxt_okx_metadata_runtime_probe"]["copy_allowed_after_review"] is True
    assert by_id["btc_nautilus_oms_replay_field_audit"]["implementation_status"] == "pending_or_stale_artifact"


def test_framework_adoption_tickets_write_outputs_and_chinese_summary(tmp_path: Path) -> None:
    repo_root, external_root = _make_fake_workspace(tmp_path)

    report = build_btc_external_framework_adoption_tickets(
        repo_root=repo_root,
        external_references_root=external_root,
        generated_at_utc=datetime(2026, 7, 8, tzinfo=timezone.utc),
    )

    json_path = repo_root / report["outputs"]["json"]
    csv_path = repo_root / report["outputs"]["tickets_csv"]
    markdown_path = repo_root / report["outputs"]["summary_cn"]
    safety_path = repo_root / report["outputs"]["paper_live_safety_status"]

    assert json_path.exists()
    assert csv_path.exists()
    assert safety_path.exists()
    summary = markdown_path.read_text(encoding="utf-8")
    assert "NautilusTrader" in summary
    assert "Freqtrade" in summary
    assert "Hummingbot" in summary
    assert "CCXT" in summary
    assert "不写 paper 队列" in summary
    assert "MIT/Apache" in summary
    assert "采纳状态" in summary
    safety = json.loads(safety_path.read_text(encoding="utf-8"))
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_unlock_allowed"] is False


def test_framework_adoption_tickets_record_current_implementation_status(tmp_path: Path) -> None:
    repo_root, external_root = _make_fake_workspace(tmp_path)
    _write_fake_implementation_artifacts(repo_root)

    report = build_btc_external_framework_adoption_tickets(
        repo_root=repo_root,
        external_references_root=external_root,
        generated_at_utc=datetime(2026, 7, 8, tzinfo=timezone.utc),
    )

    status = report["implementation_status"]
    assert status["btc_nautilus_oms_replay_field_audit"]["status"] == "implemented_with_deliberate_boundaries"
    assert status["btc_freqtrade_style_leakage_cli"]["status"] == "implemented_research_only_with_warnings"
    assert status["btc_hummingbot_ccxt_okx_metadata_runtime_probe"]["status"] == "implemented_public_runtime_verified"
    by_id = {ticket["ticket_id"]: ticket for ticket in report["tickets"]}
    assert by_id["btc_nautilus_oms_replay_field_audit"]["implementation_status"] == "implemented_with_deliberate_boundaries"
    assert by_id["btc_freqtrade_style_leakage_cli"]["implementation_status"] == "implemented_research_only_with_warnings"
    assert by_id["btc_hummingbot_ccxt_okx_metadata_runtime_probe"]["implementation_status"] == "implemented_public_runtime_verified"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_missing_external_references_fail_closed_without_paper_permissions(tmp_path: Path) -> None:
    repo_root, external_root = _make_fake_workspace(tmp_path)
    for child in external_root.iterdir():
        if child.is_dir():
            _remove_tree(child)

    report = build_btc_external_framework_adoption_tickets(
        repo_root=repo_root,
        external_references_root=external_root,
        generated_at_utc=datetime(2026, 7, 8, tzinfo=timezone.utc),
    )

    assert report["status"] == "blocked_research_only"
    assert "external_reference_repos_all_missing" in report["blockers"]
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["ticket_count"] == 3


def _make_fake_workspace(tmp_path: Path) -> tuple[Path, Path]:
    repo_root = tmp_path / "agent-"
    external_root = tmp_path / "external_references"
    (repo_root / "quant_crypto/oms").mkdir(parents=True)
    (repo_root / "quant_crypto/research").mkdir(parents=True)
    (repo_root / "quant_crypto/exchange").mkdir(parents=True)
    (repo_root / "scripts/research").mkdir(parents=True)
    (repo_root / "scripts").mkdir(parents=True, exist_ok=True)
    external_root.mkdir()
    (repo_root / "quant_crypto/oms/lifecycle.py").write_text(
        "PARTIALLY_FILLED CANCEL_REQUESTED REJECTED EXPIRED RECONCILED",
        encoding="utf-8",
    )
    (repo_root / "quant_crypto/research/btc_perpetual_paper_runtime_replay.py").write_text(
        "mark_price index_price liquidation_buffer_bps risk_decision order_ledger fill_ledger",
        encoding="utf-8",
    )
    (repo_root / "quant_crypto/research/btc_strategy_leakage_overfit_audit.py").write_text("", encoding="utf-8")
    (repo_root / "quant_crypto/research/btc_strategy_bar_replay_visibility.py").write_text("", encoding="utf-8")
    (repo_root / "quant_crypto/exchange/runtime.py").write_text(
        "server_time ws gapfill rate limit metadata",
        encoding="utf-8",
    )
    (repo_root / "scripts/build_btc_exchange_public_runtime_dry_probe.py").write_text("", encoding="utf-8")
    (repo_root / "scripts/build_btc_exchange_runtime_contract.py").write_text("", encoding="utf-8")
    (external_root / "btc_framework_reuse_notes.md").write_text("notes", encoding="utf-8")
    for name, commit in {
        "nautilus_trader": "c22f0a61234567890",
        "freqtrade": "0a5bbf61234567890",
        "hummingbot": "816b8ab1234567890",
        "ccxt": "2ef15da1234567890",
    }.items():
        repo = external_root / name
        (repo / ".git/refs/heads").mkdir(parents=True)
        (repo / ".git/HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (repo / ".git/refs/heads/main").write_text(commit, encoding="utf-8")
        (repo / "README.md").write_text(name, encoding="utf-8")
    return repo_root, external_root


def _write_fake_implementation_artifacts(repo_root: Path) -> None:
    nautilus = repo_root / "artifacts/btc_nautilus_oms_replay_field_audit/latest/btc_nautilus_oms_replay_field_audit_report.json"
    freqtrade = repo_root / "artifacts/btc_freqtrade_style_leakage_cli/latest/btc_freqtrade_style_leakage_cli_report.json"
    runtime = repo_root / "artifacts/btc_exchange_runtime/latest/btc_exchange_public_runtime_dry_probe_report.json"
    nautilus.parent.mkdir(parents=True, exist_ok=True)
    freqtrade.parent.mkdir(parents=True, exist_ok=True)
    runtime.parent.mkdir(parents=True, exist_ok=True)
    nautilus.write_text(
        json.dumps(
            {
                "status": "complete_research_only",
                "decision": "done",
                "summary": {
                    "covered_count": 8,
                    "partial_count": 1,
                    "missing_count": 0,
                    "diagnostic_or_prohibited_count": 1,
                },
            }
        ),
        encoding="utf-8",
    )
    freqtrade.write_text(
        json.dumps(
            {
                "status": "complete_research_only",
                "decision": "done",
                "summary": {"check_count": 9, "fail_count": 0, "warn_count": 6},
            }
        ),
        encoding="utf-8",
    )
    runtime.write_text(
        json.dumps(
            {
                "status": "verified_research_only",
                "decision": "done",
                "runtime_layer": {"status": "passed"},
                "normalized_market_metadata_contract": {"contract_valid": True},
            }
        ),
        encoding="utf-8",
    )


def _remove_tree(path: Path) -> None:
    for child in path.iterdir():
        if child.is_dir():
            _remove_tree(child)
        else:
            child.unlink()
    path.rmdir()
