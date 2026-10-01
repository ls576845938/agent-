from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.research import btc_perpetual_execution_evidence as evidence


def test_perpetual_execution_evidence_blocks_when_real_execution_inputs_are_missing(tmp_path: Path) -> None:
    paths = _fixture_paths(tmp_path)
    _write_config(paths["config"], paths["root"], "current_bundle")
    _write_manifest(paths["root"], "current_bundle", sample_end="2026-06-23T00:00:00Z")
    _write_json(paths["provider"], _provider_report(bundle_id="old_bundle"))
    _write_json(paths["cost"], _cost_model_report(mark_current=False, mark_used=False, slippage_bps=0.0, depth_verified=False))
    _write_json(paths["funding"], {"funding_payment_in_ledger": True, "status": "present"})
    _write_json(paths["policy"], {"current_strategy_uses_perpetual": False, "gate": {"perpetual_allowed": False}, "status": "complete"})
    _write_json(paths["runtime"], {"status": "complete", "decision": "runtime_documented_only", "notes": {"evidence_type": "simulated_contract_probe"}})
    _write_json(paths["runtime_gap"], {"status": "incomplete_research_only", "decision": "runtime_replay_gap_incomplete_fail_closed_no_paper_no_live", "blockers": ["btc_runtime_contract_still_simulated_contract_probe"]})
    _write_json(paths["binance_book_depth"], _binance_book_depth_report())
    _write_json(paths["liquidation"], {"status": "complete", "decision": "liquidation_risk_contract_complete", "blockers": []})
    _write_strategy_reports(paths)

    report = evidence.build_btc_perpetual_execution_evidence_pack(
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
        config_path=paths["config"],
        provider_report_path=paths["provider"],
        cost_model_report_path=paths["cost"],
        funding_ledger_report_path=paths["funding"],
        perpetual_policy_report_path=paths["policy"],
        exchange_runtime_contract_path=paths["runtime"],
        exchange_runtime_replay_gap_report_path=paths["runtime_gap"],
        binance_vision_book_depth_report_path=paths["binance_book_depth"],
        liquidation_risk_contract_path=paths["liquidation"],
        long_short_observer_report_path=paths["long_short"],
        attack_observer_report_path=paths["attack"],
        high_yield_followup_report_path=paths["high_yield"],
    )

    assert report["status"] == "incomplete_research_only"
    assert report["decision"] == "perpetual_execution_evidence_incomplete_fail_closed_no_paper_no_live"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["gate"]["perpetual_promotion_allowed"] is False
    assert report["gate"]["leverage_promotion_allowed"] is False
    assert report["gate"]["liquidation_gap_disables_leverage_perp_promotion"] is True
    assert "btc_perp_exec_liquidation_history_or_snapshots_available" in report["gate"]["promotion_disable_reasons"]
    assert report["guardrails"]["broker_access_allowed"] is False

    blockers = set(report["blockers"])
    assert "btc_perp_exec_selected_provider_bundle_matches_config" in blockers
    assert "btc_perp_exec_perp_data_covers_latest_strategy_decision" in blockers
    assert "btc_perp_exec_current_mark_price_available" in blockers
    assert "btc_perp_exec_mark_used_for_liquidation_risk" in blockers
    assert "btc_perp_exec_slippage_positive_or_depth_aware" in blockers
    assert "btc_perp_exec_depth_aware_slippage_history_verified" in blockers
    assert "btc_perp_exec_exact_exchange_liquidation_formula_verified" in blockers
    assert "btc_perp_exec_liquidation_history_or_snapshots_available" not in blockers
    assert "btc_perp_exec_exchange_runtime_real_or_paper_replay_ready" in blockers
    assert "btc_perp_exec_perpetual_policy_allows_current_strategy" in blockers

    checks = {row["check_id"]: row for row in report["evidence_checklist"]}
    assert checks["liquidation_history_or_snapshots_available"]["status"] == "waived_fail_closed"
    assert report["fail_closed_waivers"] == ["btc_perp_exec_liquidation_history_or_snapshots_available"]
    assert report["l2_depth_diagnostics"]["free_public_cross_venue_depth_diagnostic_present"] is True
    assert report["l2_depth_diagnostics"]["free_public_cross_venue_depth_gate_eligible_for_selected_venue"] is False
    requirement_rows = {row["requirement_id"]: row for row in report["requirement_status_cn"]}
    assert requirement_rows["mark_index"]["status_cn"] == "阻断"
    assert requirement_rows["depth_slippage"]["status_cn"] == "阻断"
    assert requirement_rows["liquidation_history"]["status_cn"] == "fail_closed_waived"
    assert requirement_rows["runtime_outage"]["status_cn"] == "阻断"
    assert all(row["paper_queue_write_allowed"] is False for row in requirement_rows.values())
    assert all(row["live_unlock_allowed"] is False for row in requirement_rows.values())
    assert checks["funding_payment_in_ledger"]["status"] == "pass"
    assert checks["fee_tier_verified"]["status"] == "pass"
    assert json.loads(checks["selected_provider_bundle_matches_config"]["details"])["manifest_path"].endswith("current_bundle/btc_perpetual_bundle_manifest.json")
    assert (tmp_path / "out" / "btc_perpetual_execution_evidence_report.json").exists()
    assert (tmp_path / "out" / "paper_live_safety_status.json").exists()
    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["perpetual_promotion_allowed"] is False
    assert safety["leverage_promotion_allowed"] is False
    assert safety["liquidation_gap_disables_leverage_perp_promotion"] is True
    _assert_json_artifact_is_ascii_escaped_and_powershell_parseable(
        tmp_path / "out" / "btc_perpetual_execution_evidence_report.json"
    )


def test_perpetual_execution_evidence_complete_still_does_not_auto_promote(tmp_path: Path) -> None:
    paths = _fixture_paths(tmp_path)
    _write_config(paths["config"], paths["root"], "current_bundle")
    _write_manifest(paths["root"], "current_bundle", sample_end="2026-07-01T00:00:00Z")
    _write_json(
        paths["provider"],
        {
            **_provider_report(bundle_id="current_bundle"),
            "liquidation_formula_verified": True,
            "maintenance_margin_tiers_verified": True,
            "liquidation_snapshot_gate_eligible": True,
        },
    )
    _write_json(paths["cost"], _cost_model_report(mark_current=True, mark_used=True, slippage_bps=4.0, depth_verified=True, liquidation_history=True))
    _write_json(paths["funding"], {"funding_payment_in_ledger": True, "status": "present"})
    _write_json(paths["policy"], {"current_strategy_uses_perpetual": True, "gate": {"perpetual_allowed": True}, "status": "complete"})
    _write_json(paths["runtime"], {"status": "complete", "decision": "runtime_ready_for_paper", "notes": {"evidence_type": "real_public_ws_replay"}})
    _write_json(paths["runtime_gap"], {"status": "complete_research_only", "decision": "runtime_replay_ready_for_manual_review_research_only_no_auto_paper_no_live", "blockers": [], "summary": {"paper_runtime_replay_ready": True}, "gap_analysis": {"runtime_contract_is_simulated_probe": False, "public_ws_coverage_contract_satisfied": True, "paper_runtime_replay_ready": True}})
    _write_json(paths["binance_book_depth"], _binance_book_depth_report())
    _write_json(paths["liquidation"], {"status": "complete", "decision": "liquidation_risk_contract_complete", "blockers": []})
    _write_strategy_reports(paths)

    report = evidence.build_btc_perpetual_execution_evidence_pack(
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
        config_path=paths["config"],
        provider_report_path=paths["provider"],
        cost_model_report_path=paths["cost"],
        funding_ledger_report_path=paths["funding"],
        perpetual_policy_report_path=paths["policy"],
        exchange_runtime_contract_path=paths["runtime"],
        exchange_runtime_replay_gap_report_path=paths["runtime_gap"],
        binance_vision_book_depth_report_path=paths["binance_book_depth"],
        liquidation_risk_contract_path=paths["liquidation"],
        long_short_observer_report_path=paths["long_short"],
        attack_observer_report_path=paths["attack"],
        high_yield_followup_report_path=paths["high_yield"],
    )

    assert report["status"] == "complete_research_only"
    assert report["decision"] == "perpetual_execution_evidence_present_manual_review_required_no_auto_paper_no_live"
    assert report["blockers"] == []
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_candidate_created"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["gate"]["perpetual_promotion_allowed"] is False
    assert report["gate"]["leverage_promotion_allowed"] is False
    assert report["gate"]["liquidation_gap_disables_leverage_perp_promotion"] is False
    requirement_rows = {row["requirement_id"]: row for row in report["requirement_status_cn"]}
    assert set(requirement_rows) == {
        "mark_index",
        "funding",
        "fees",
        "depth_slippage",
        "liquidation_formula",
        "liquidation_history",
        "runtime_outage",
    }
    assert all(row["status_cn"] == "通过" for row in requirement_rows.values())
    assert all(row["paper_live_boundary"] == "paper_queue_write_allowed=false; live_unlock_allowed=false" for row in report["line_assessments"])


def test_cross_venue_depth_diagnostic_cannot_satisfy_depth_aware_gate(tmp_path: Path) -> None:
    paths = _fixture_paths(tmp_path)
    _write_config(paths["config"], paths["root"], "current_bundle")
    _write_manifest(paths["root"], "current_bundle", sample_end="2026-07-01T00:00:00Z")
    _write_json(
        paths["provider"],
        {
            **_provider_report(bundle_id="current_bundle"),
            "liquidation_formula_verified": True,
            "maintenance_margin_tiers_verified": True,
            "liquidation_snapshot_gate_eligible": True,
        },
    )
    _write_json(
        paths["cost"],
        _cost_model_report(mark_current=True, mark_used=True, slippage_bps=4.0, depth_verified=False, liquidation_history=True),
    )
    _write_json(paths["funding"], {"funding_payment_in_ledger": True, "status": "present"})
    _write_json(paths["policy"], {"current_strategy_uses_perpetual": True, "gate": {"perpetual_allowed": True}, "status": "complete"})
    _write_json(paths["runtime"], {"status": "complete", "decision": "runtime_ready_for_paper", "notes": {"evidence_type": "real_public_ws_replay"}})
    _write_json(paths["runtime_gap"], {"status": "complete_research_only", "decision": "runtime_replay_ready_for_manual_review_research_only_no_auto_paper_no_live", "blockers": [], "summary": {"paper_runtime_replay_ready": True}, "gap_analysis": {"runtime_contract_is_simulated_probe": False, "public_ws_coverage_contract_satisfied": True, "paper_runtime_replay_ready": True}})
    _write_json(
        paths["binance_book_depth"],
        {
            **_binance_book_depth_report(),
            "execution_gate_interpretation": {
                "free_public_depth_diagnostic_available": True,
                "gate_eligible_for_selected_venue": True,
                "depth_aware_slippage_history_verified_for_selected_venue": True,
            },
        },
    )
    _write_json(paths["liquidation"], {"status": "complete", "decision": "liquidation_risk_contract_complete", "blockers": []})
    _write_strategy_reports(paths)

    report = evidence.build_btc_perpetual_execution_evidence_pack(
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
        config_path=paths["config"],
        provider_report_path=paths["provider"],
        cost_model_report_path=paths["cost"],
        funding_ledger_report_path=paths["funding"],
        perpetual_policy_report_path=paths["policy"],
        exchange_runtime_contract_path=paths["runtime"],
        exchange_runtime_replay_gap_report_path=paths["runtime_gap"],
        binance_vision_book_depth_report_path=paths["binance_book_depth"],
        liquidation_risk_contract_path=paths["liquidation"],
        long_short_observer_report_path=paths["long_short"],
        attack_observer_report_path=paths["attack"],
        high_yield_followup_report_path=paths["high_yield"],
    )

    checks = {row["check_id"]: row for row in report["evidence_checklist"]}
    assert checks["order_book_depth_diagnostic_present"]["status"] == "pass"
    assert checks["depth_aware_slippage_history_verified"]["status"] == "fail"
    details = json.loads(checks["depth_aware_slippage_history_verified"]["details"])
    assert details["free_public_cross_venue_depth_gate_eligible_for_selected_venue"] is True
    assert details["cost_model_depth_aware_slippage_history_verified"] is False
    assert details["cross_venue_l2_diagnostic_ignored_for_gate"] is True
    assert "btc_perp_exec_depth_aware_slippage_history_verified" in report["blockers"]
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_perp_data_coverage_uses_available_end_and_funding_freshness(tmp_path: Path) -> None:
    paths = _fixture_paths(tmp_path)
    _write_config(paths["config"], paths["root"], "current_bundle")
    _write_manifest(
        paths["root"],
        "current_bundle",
        sample_end="2026-07-01T03:00:00Z",
        available_end="2026-07-01T04:00:00Z",
        funding_sample_end="2026-07-01T00:00:00Z",
        funding_available_end="2026-07-01T00:00:00Z",
    )
    _write_json(
        paths["provider"],
        {
            **_provider_report(bundle_id="current_bundle"),
            "liquidation_formula_verified": True,
            "maintenance_margin_tiers_verified": True,
            "liquidation_snapshot_gate_eligible": True,
        },
    )
    _write_json(paths["cost"], _cost_model_report(mark_current=True, mark_used=True, slippage_bps=4.0, depth_verified=True, liquidation_history=True))
    _write_json(paths["funding"], {"funding_payment_in_ledger": True, "status": "present"})
    _write_json(paths["policy"], {"current_strategy_uses_perpetual": True, "gate": {"perpetual_allowed": True}, "status": "complete"})
    _write_json(paths["runtime"], {"status": "complete", "decision": "runtime_ready_for_paper", "notes": {"evidence_type": "real_public_ws_replay"}})
    _write_json(paths["runtime_gap"], {"status": "complete_research_only", "decision": "runtime_replay_ready_for_manual_review_research_only_no_auto_paper_no_live", "blockers": [], "summary": {"paper_runtime_replay_ready": True}, "gap_analysis": {"runtime_contract_is_simulated_probe": False, "public_ws_coverage_contract_satisfied": True, "paper_runtime_replay_ready": True}})
    _write_json(paths["binance_book_depth"], _binance_book_depth_report())
    _write_json(paths["liquidation"], {"status": "complete", "decision": "liquidation_risk_contract_complete", "blockers": []})
    _write_strategy_reports(paths, latest_decision_time="2026-07-01T03:59:59.999000+00:00")

    report = evidence.build_btc_perpetual_execution_evidence_pack(
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
        config_path=paths["config"],
        provider_report_path=paths["provider"],
        cost_model_report_path=paths["cost"],
        funding_ledger_report_path=paths["funding"],
        perpetual_policy_report_path=paths["policy"],
        exchange_runtime_contract_path=paths["runtime"],
        exchange_runtime_replay_gap_report_path=paths["runtime_gap"],
        binance_vision_book_depth_report_path=paths["binance_book_depth"],
        liquidation_risk_contract_path=paths["liquidation"],
        long_short_observer_report_path=paths["long_short"],
        attack_observer_report_path=paths["attack"],
        high_yield_followup_report_path=paths["high_yield"],
    )

    assert "btc_perp_exec_perp_data_covers_latest_strategy_decision" not in report["blockers"]
    assert report["data_lag_status"]["price_covers_latest_strategy_decision"] is True
    assert report["data_lag_status"]["funding_fresh_for_latest_strategy_decision"] is True
    assert report["data_lag_status"]["funding_lag_hours"] < 12.0


def test_perp_data_coverage_blocks_stale_funding_even_when_price_available(tmp_path: Path) -> None:
    paths = _fixture_paths(tmp_path)
    _write_config(paths["config"], paths["root"], "current_bundle")
    _write_manifest(
        paths["root"],
        "current_bundle",
        sample_end="2026-07-01T03:00:00Z",
        available_end="2026-07-01T04:00:00Z",
        funding_sample_end="2026-06-30T08:00:00Z",
        funding_available_end="2026-06-30T08:00:00Z",
    )
    _write_json(
        paths["provider"],
        {
            **_provider_report(bundle_id="current_bundle"),
            "liquidation_formula_verified": True,
            "maintenance_margin_tiers_verified": True,
            "liquidation_snapshot_gate_eligible": True,
        },
    )
    _write_json(paths["cost"], _cost_model_report(mark_current=True, mark_used=True, slippage_bps=4.0, depth_verified=True, liquidation_history=True))
    _write_json(paths["funding"], {"funding_payment_in_ledger": True, "status": "present"})
    _write_json(paths["policy"], {"current_strategy_uses_perpetual": True, "gate": {"perpetual_allowed": True}, "status": "complete"})
    _write_json(paths["runtime"], {"status": "complete", "decision": "runtime_ready_for_paper", "notes": {"evidence_type": "real_public_ws_replay"}})
    _write_json(paths["runtime_gap"], {"status": "complete_research_only", "decision": "runtime_replay_ready_for_manual_review_research_only_no_auto_paper_no_live", "blockers": [], "summary": {"paper_runtime_replay_ready": True}, "gap_analysis": {"runtime_contract_is_simulated_probe": False, "public_ws_coverage_contract_satisfied": True, "paper_runtime_replay_ready": True}})
    _write_json(paths["binance_book_depth"], _binance_book_depth_report())
    _write_json(paths["liquidation"], {"status": "complete", "decision": "liquidation_risk_contract_complete", "blockers": []})
    _write_strategy_reports(paths, latest_decision_time="2026-07-01T03:59:59.999000+00:00")

    report = evidence.build_btc_perpetual_execution_evidence_pack(
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
        config_path=paths["config"],
        provider_report_path=paths["provider"],
        cost_model_report_path=paths["cost"],
        funding_ledger_report_path=paths["funding"],
        perpetual_policy_report_path=paths["policy"],
        exchange_runtime_contract_path=paths["runtime"],
        exchange_runtime_replay_gap_report_path=paths["runtime_gap"],
        binance_vision_book_depth_report_path=paths["binance_book_depth"],
        liquidation_risk_contract_path=paths["liquidation"],
        long_short_observer_report_path=paths["long_short"],
        attack_observer_report_path=paths["attack"],
        high_yield_followup_report_path=paths["high_yield"],
    )

    assert "btc_perp_exec_perp_data_covers_latest_strategy_decision" in report["blockers"]
    assert report["data_lag_status"]["price_covers_latest_strategy_decision"] is True
    assert report["data_lag_status"]["funding_fresh_for_latest_strategy_decision"] is False
    assert report["data_lag_status"]["funding_lag_hours"] > 12.0


def _fixture_paths(tmp_path: Path) -> dict[str, Path]:
    return {
        "root": tmp_path / "perp" / "okx_swap",
        "config": tmp_path / "btc_perpetual_sources.yaml",
        "provider": tmp_path / "provider.json",
        "cost": tmp_path / "cost.json",
        "funding": tmp_path / "funding.json",
        "policy": tmp_path / "policy.json",
        "runtime": tmp_path / "runtime.json",
        "runtime_gap": tmp_path / "runtime_gap.json",
        "binance_book_depth": tmp_path / "binance_book_depth.json",
        "liquidation": tmp_path / "liquidation.json",
        "long_short": tmp_path / "long_short.json",
        "attack": tmp_path / "attack.json",
        "high_yield": tmp_path / "high_yield.json",
    }


def _write_config(path: Path, root: Path, bundle_id: str) -> None:
    path.write_text(
        "\n".join(
            [
                "providers:",
                "  okx_swap:",
                "    enabled: true",
                "    root: " + root.as_posix(),
                "    selected_bundle_id: " + bundle_id,
                "    allow_network: false",
                "    allow_private_endpoints: false",
                "    allow_order_endpoints: false",
                "selected_provider: okx_swap",
            ]
        ),
        encoding="utf-8",
    )


def _write_manifest(
    root: Path,
    bundle_id: str,
    *,
    sample_end: str,
    available_end: str | None = None,
    funding_sample_end: str | None = None,
    funding_available_end: str | None = None,
) -> None:
    bundle = root / "bundles" / bundle_id
    bundle.mkdir(parents=True, exist_ok=True)
    effective_available_end = available_end or sample_end
    effective_funding_sample_end = funding_sample_end or sample_end
    effective_funding_available_end = funding_available_end or effective_funding_sample_end
    _write_json(
        bundle / "btc_perpetual_bundle_manifest.json",
        {
            "bundle_id": bundle_id,
            "source_provider": "okx_swap",
            "source_type": "production",
            "market_type": "swap",
            "symbol": "BTCUSDT",
            "sample_start": "2026-01-01T00:00:00Z",
            "sample_end": sample_end,
            "blockers": [],
            "files": [
                {
                    "role": "order_book_depth",
                    "record_count": 1000,
                    "sample_start": "2026-01-01T00:00:00Z",
                    "sample_end": sample_end,
                    "available_start": "2026-01-01T01:00:00Z",
                    "available_end": effective_available_end,
                },
                {
                    "role": "klines_1h",
                    "record_count": 1000,
                    "sample_start": "2026-01-01T00:00:00Z",
                    "sample_end": sample_end,
                    "available_start": "2026-01-01T01:00:00Z",
                    "available_end": effective_available_end,
                },
                {
                    "role": "mark_price_klines_1h",
                    "record_count": 1000,
                    "sample_start": "2026-01-01T00:00:00Z",
                    "sample_end": sample_end,
                    "available_start": "2026-01-01T01:00:00Z",
                    "available_end": effective_available_end,
                },
                {
                    "role": "premium_index_klines_1h",
                    "record_count": 1000,
                    "sample_start": "2026-01-01T00:00:00Z",
                    "sample_end": sample_end,
                    "available_start": "2026-01-01T01:00:00Z",
                    "available_end": effective_available_end,
                },
                {
                    "role": "funding_rate",
                    "record_count": 1000,
                    "sample_start": "2026-01-01T00:00:00Z",
                    "sample_end": effective_funding_sample_end,
                    "available_start": "2026-01-01T00:00:00Z",
                    "available_end": effective_funding_available_end,
                },
            ],
        },
    )


def _provider_report(*, bundle_id: str) -> dict:
    return {
        "schema_version": "btc_perpetual_provider_verification_report_v1",
        "selected_provider": "okx_swap",
        "selected_bundle_id": bundle_id,
        "mark_price_klines_verified": True,
        "premium_index_klines_verified": True,
        "funding_rate_verified": True,
        "funding_info_verified": True,
        "status": "pass",
        "blockers": [],
    }


def _cost_model_report(*, mark_current: bool, mark_used: bool, slippage_bps: float, depth_verified: bool, liquidation_history: bool = False) -> dict:
    return {
        "status": "pass",
        "mark_price_model": {
            "mark_price_klines_available": True,
            "premium_index_klines_available": True,
            "mark_price_current_available": mark_current,
            "mark_price_used_for_liquidation_risk": mark_used,
        },
        "funding_model": {
            "funding_rate_available": True,
            "funding_info_available": True,
            "funding_payment_in_ledger": True,
        },
        "fee_model": {
            "fee_tier_verified": True,
            "fee_in_ledger": True,
        },
        "slippage_model": {
            "slippage_bps": slippage_bps,
            "depth_aware_slippage_history_verified": depth_verified,
        },
        "liquidation_data": {
            "complete_liquidation_history_available": liquidation_history,
            "liquidation_snapshot_available": liquidation_history,
        },
    }


def _binance_book_depth_report() -> dict:
    return {
        "schema_version": "btc_binance_vision_book_depth_diagnostic_v1",
        "status": "complete_diagnostic_only",
        "decision": "binance_vision_book_depth_cross_venue_diagnostic_only_not_okx_gate_evidence",
        "source_provider": "binance_vision_usdm_daily_bookDepth",
        "row_count": 40320,
        "coverage": {"coverage_days": 14.0},
        "execution_gate_interpretation": {
            "free_public_depth_diagnostic_available": True,
            "gate_eligible_for_selected_venue": False,
            "depth_aware_slippage_history_verified_for_selected_venue": False,
        },
        "blockers": ["btc_binance_vision_book_depth_cross_venue_not_okx_execution_gate"],
    }


def _write_strategy_reports(paths: dict[str, Path], *, latest_decision_time: str = "2026-06-28T23:59:59.999000+00:00") -> None:
    _write_json(paths["long_short"], {"status": "complete_research_only", "holdout_lock": {"latest_decision_time": latest_decision_time}})
    _write_json(paths["attack"], {"status": "complete_research_only", "holdout_lock": {"latest_decision_time": latest_decision_time}})
    _write_json(paths["high_yield"], {"status": "complete_research_only", "step_1_daily_observation_automation": {"latest_decision_time": latest_decision_time}})


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _assert_json_artifact_is_ascii_escaped_and_powershell_parseable(path: Path) -> None:
    raw = path.read_text(encoding="utf-8")
    assert "\\u" in raw
    assert all(ord(char) < 128 for char in raw)
    assert "阻断" not in raw
    assert "\\u963b\\u65ad" in raw
    payload = json.loads(raw)
    assert payload["requirement_status_cn"]
    assert "阻断" in {row.get("status_cn") for row in payload["requirement_status_cn"]}

    powershell = shutil.which("powershell") or shutil.which("powershell.exe") or shutil.which("pwsh")
    if powershell is None:
        return
    command = "$p=$env:BTC_EVIDENCE_JSON_PATH; Get-Content -Raw -LiteralPath $p | ConvertFrom-Json | Select-Object -ExpandProperty status"
    result = subprocess.run(
        [powershell, "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "BTC_EVIDENCE_JSON_PATH": str(path)},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "incomplete_research_only" in result.stdout
