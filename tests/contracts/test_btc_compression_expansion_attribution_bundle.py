from __future__ import annotations

import json
from pathlib import Path

from scripts.build_btc_compression_expansion_attribution_bundle import (
    build_btc_compression_expansion_attribution_bundle,
    write_btc_compression_expansion_attribution_bundle,
)
from scripts.build_global_research_registry import build_global_registry


def test_btc_compression_expansion_attribution_bundle_schema_file_exists() -> None:
    assert Path("schemas/btc_compression_expansion_attribution_bundle.schema.json").exists()


def test_btc_compression_expansion_attribution_bundle_splits_diagnostics(tmp_path: Path) -> None:
    run_dir = tmp_path / "artifacts/btc_candidate_validation/run_fixture"
    _write_json(
        run_dir / "compression_expansion_failure_mode_report.json",
        {
            "strategy_id": "btc_compression_expansion_breakout_v1",
            "gate_status": "candidate_gate_failed",
            "gate_fail_reasons": ["event_profit_factor"],
            "candidate_metrics": {
                "ordinary_pf": 1.56,
                "event_pf": 1.02,
                "walk_forward_pass_rate": 0.50,
                "regime_pass_rate": 0.25,
            },
            "full_vs_active_exposure": {
                "full_ledger": {"event_pf": 1.02},
                "active_exposure": {"event_pf": 1.18},
                "full_event_pf_gate_passes": False,
                "active_event_pf_gate_passes": True,
            },
            "failed_fold_autopsy": [{"fold_id": "3", "event_pf": 0.91}],
            "regime_drag": {"dragging_regimes": ["trending_down"]},
            "entry_exit_timing": {"by_entry_hour": [{"entry_hour_utc": "2", "net_pnl": -100.0}]},
            "decision": {"paper_review_pending_created": False, "live_changed": False},
        },
    )
    _write_json(
        run_dir / "event_ledger_attribution_report.json",
        {
            "gate_status": "candidate_gate_failed",
            "paper_queue": "LOCKED",
            "live": "FROZEN",
            "ordinary_pf": 1.56,
            "event_pf": 1.02,
            "gate_fail_reasons": ["event_profit_factor"],
            "root_cause_summary": ["ordinary PF is diagnostic only"],
            "by_regime": [{"regime": "trending_down", "event_pf": 0.70}],
        },
    )
    _write_json(
        run_dir / "fold_regime_contract_audit.json",
        {
            "fold_contract": {"status": "pass", "fold_count": 4},
            "regime_contract": {"status": "fail", "pass_rate": 0.25},
        },
    )
    _write_json(
        run_dir / "btc_data_fold_regime_status_report.json",
        {"regime_status": {"status": "fail", "dragging_regimes": ["trending_down"]}},
    )
    _write_json(run_dir / "candidate_validation_result.json", {"status": "candidate_gate_failed"})

    payload = build_btc_compression_expansion_attribution_bundle(
        repo_root=tmp_path,
        source_run_dir=Path("artifacts/btc_candidate_validation/run_fixture"),
        generated_at="2026-05-18T00:00:00Z",
    )
    report = payload["attribution_report"]

    assert report["schema_version"] == "btc_compression_expansion_attribution_bundle_v1"
    assert report["status"] == "archived"
    assert report["allowed_next_action"] == "archive_only"
    assert report["paper_review_pending_allowed"] is False
    assert report["archive_recommended"] is True
    assert report["stable_repair_pattern_found"] is False
    assert report["paper_queue"] == "LOCKED"
    assert report["live"] == "FROZEN"
    assert report["promotion_ready"] is False
    assert report["paper_review_pending_created"] is False
    assert report["candidate_metrics"]["event_pf"] == 1.02
    assert payload["fold_failure_report"]["failed_folds"] == ["3"]
    assert payload["active_vs_full_ledger_report"]["active_event_pf"] == 1.18
    assert payload["active_vs_full_ledger_report"]["active_vs_full_ledger_gap"] == 0.16
    assert payload["cost_funding_drag_report"]["funding_payment_in_ledger"] is False
    assert "btc_compression_expansion_archived" in report["blockers"]

    paths = write_btc_compression_expansion_attribution_bundle(
        payload,
        tmp_path / "artifacts/btc_candidate_attribution/latest_compression_expansion_attribution",
    )
    persisted = json.loads(Path(paths["attribution_report"]).read_text(encoding="utf-8"))
    assert persisted["child_reports"]["fold_failure_report"].endswith("fold_failure_report.json")


def test_global_registry_surfaces_compression_expansion_attribution_report(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/btc_candidate_attribution/latest_compression_expansion_attribution/attribution_report.json",
        {"schema_version": "btc_compression_expansion_attribution_bundle_v1"},
    )

    registry = build_global_registry(
        repo_root=tmp_path,
        generated_at="2026-05-18T00:00:00Z",
    )
    btc = registry["assets"]["btc"]

    assert btc["current_candidates"] == []
    assert btc["attribution_only"] == []
    assert "compression_expansion_breakout" in btc["archived_or_rejected"]
    assert btc["latest_compression_attribution"] == (
        "artifacts/btc_candidate_attribution/latest_compression_expansion_attribution/attribution_report.json"
    )
    assert btc["paper_queue_status"] == "locked"
    assert btc["live_status"] == "frozen"


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
