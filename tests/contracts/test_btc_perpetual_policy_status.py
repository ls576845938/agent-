from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.monitoring.artifact_schema import validate_btc_artifact_schema
from quant_crypto.monitoring.perpetual_policy_status import (
    build_btc_perpetual_policy_status,
    render_btc_perpetual_policy_status_markdown,
)
from scripts.build_btc_perpetual_policy_status import build_btc_perpetual_policy_status_file


TS = datetime(2026, 6, 29, 8, 0, tzinfo=timezone.utc)


def test_btc_perpetual_policy_status_completes_when_current_path_disables_perp() -> None:
    payload = build_btc_perpetual_policy_status(
        generated_at_utc=TS,
        sources=_disabled_sources(),
        source_paths={name: f"artifacts/{name}.json" for name in _disabled_sources()},
        report_paths={"json": "artifacts/btc_perpetual_policy/latest/report.json"},
    )

    assert payload["status"] == "complete"
    assert payload["decision"] == "btc_perpetual_path_disabled_for_current_strategy"
    assert payload["current_route"] == "spot_or_unlevered_path_perpetual_disabled"
    assert payload["current_strategy_uses_perpetual"] is False
    assert payload["target_policy"]["perpetual_allowed"] is False
    assert payload["target_policy"]["risk_state_perp_decision_status"] == "not_required_spot_or_unlevered_path"
    assert payload["paper_replay_policy"]["perpetual_allowed"] is False
    assert payload["live_constitution_policy"]["perpetual_allowed"] is False
    assert payload["perpetual_evidence"]["evidence_required_for_current_route"] is False
    assert payload["perpetual_evidence"]["diagnostic_only_when_perpetual_disabled"] is True
    assert payload["gate"]["perpetual_allowed"] is False
    assert payload["gate"]["paper_queue_write_allowed"] is False
    assert payload["gate"]["live_unlock_allowed"] is False
    assert payload["guardrails"] == {
        "live_order_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
    }
    assert validate_btc_artifact_schema(payload) == []

    markdown = render_btc_perpetual_policy_status_markdown(payload)
    assert "BTC 永续路径策略状态" in markdown
    assert "不写 paper 队列" in markdown
    assert "不解锁 live" in markdown
    assert "submit_order" not in markdown


def test_btc_perpetual_policy_status_blocks_inconsistent_missing_policy() -> None:
    sources = _disabled_sources()
    target = dict(sources["latest_target"])
    target["target"] = {
        **target["target"],
        "metadata": {
            **target["target"]["metadata"],
            "perpetual_risk_policy": {},
        },
    }
    sources["latest_target"] = target

    payload = build_btc_perpetual_policy_status(
        generated_at_utc=TS,
        sources=sources,
    )

    assert payload["status"] == "blocked"
    assert "btc_perpetual_policy_target_policy_missing" in payload["blockers"]
    assert payload["gate"]["paper_queue_write_allowed"] is False
    assert payload["gate"]["live_unlock_allowed"] is False


def test_btc_perpetual_policy_status_blocks_enabled_perp_without_liquidation_contract() -> None:
    sources = _disabled_sources()
    target = dict(sources["latest_target"])
    target["target"] = {
        **target["target"],
        "metadata": {
            **target["target"]["metadata"],
            "perpetual_risk_policy": {
                "perpetual_allowed": True,
                "liquidation_risk_required": True,
                "funding_rate_required": True,
                "status": "perpetual_risk_required",
            },
            "risk_state": {
                **target["target"]["metadata"]["risk_state"],
                "perp_risk_decision_status": "missing_required",
            },
        },
    }
    sources["latest_target"] = target
    sources["liquidation_risk_contract"] = {}

    payload = build_btc_perpetual_policy_status(
        generated_at_utc=TS,
        sources=sources,
    )

    assert payload["status"] == "blocked"
    assert payload["current_strategy_uses_perpetual"] is True
    assert payload["gate"]["perpetual_allowed"] is True
    assert "btc_perpetual_policy_liquidation_contract_not_complete_for_enabled_perp" in payload["blockers"]
    assert payload["gate"]["paper_queue_write_allowed"] is False
    assert payload["gate"]["live_unlock_allowed"] is False


def test_btc_perpetual_policy_status_uses_research_route_request_without_paper_or_live() -> None:
    sources = _disabled_sources()
    sources["perpetual_route_request"] = {
        "status": "complete_research_only",
        "decision": "perpetual_route_requested_research_only_execution_evidence_required_no_paper_no_live",
        "perpetual_route_requested": True,
        "current_strategy_uses_perpetual": True,
        "eligible_strategy_line_count": 2,
        "strategy_line_count": 3,
        "gate": {
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        },
        "blockers": [],
    }

    payload = build_btc_perpetual_policy_status(
        generated_at_utc=TS,
        sources=sources,
    )

    assert payload["status"] == "complete"
    assert payload["current_route"] == "perpetual_requires_full_risk_evidence"
    assert payload["current_strategy_uses_perpetual"] is True
    assert payload["perpetual_route_request"]["perpetual_route_requested"] is True
    assert payload["perpetual_route_request"]["eligible_strategy_line_count"] == 2
    assert payload["gate"]["perpetual_allowed"] is True
    assert payload["gate"]["paper_queue_write_allowed"] is False
    assert payload["gate"]["live_unlock_allowed"] is False
    assert validate_btc_artifact_schema(payload) == []


def test_btc_perpetual_policy_status_file_builder_reads_latest_target_from_daily_chain(tmp_path: Path) -> None:
    _write_fixture_tree(tmp_path)
    payload = build_btc_perpetual_policy_status_file(repo_root=tmp_path)

    assert payload["status"] == "complete"
    assert payload["source_report_details"]["latest_target"]["path"].endswith("target.json")
    assert (
        tmp_path
        / "artifacts/btc_perpetual_policy/latest/btc_perpetual_policy_status_report.json"
    ).exists()
    assert (
        tmp_path
        / "artifacts/btc_perpetual_policy/latest/btc_perpetual_policy_status_summary_cn.md"
    ).exists()


def _disabled_sources() -> dict[str, dict[str, object] | None]:
    return {
        "latest_target": {
            "target": {
                "strategy_id": "btc_trend_raw_t01_twelve_month_momentum",
                "timestamp_utc": "2026-06-29T00:00:00+00:00",
                "metadata": {
                    "perpetual_risk_policy": {
                        "perpetual_allowed": False,
                        "liquidation_risk_required": False,
                        "funding_rate_required": False,
                        "status": "not_applicable_spot_or_unlevered_path",
                        "reason": "current BTC target path is spot or unlevered",
                    },
                    "risk_state": {
                        "perp_risk_decision": None,
                        "perp_risk_decision_status": "not_required_spot_or_unlevered_path",
                    },
                },
            }
        },
        "paper_validation_replay": {
            "status": "replay_pass",
            "metadata": {
                "current_realtime_data_accessed": False,
                "perpetual_risk_policy": {
                    "perpetual_allowed": False,
                    "liquidation_risk_required": False,
                    "perp_risk_decision_status": "not_required_spot_or_unlevered_path",
                    "status": "not_applicable_spot_or_unlevered_path",
                    "reason": "spot or unlevered path",
                },
            },
        },
        "live_readiness": {
            "status": "live_readiness_blocked",
            "risk_constitution": {
                "instrument_limits": {
                    "btc_spot_allowed_for_future_pilot": True,
                    "perpetual_allowed": False,
                    "leverage_cap": 1.0,
                    "shorting_allowed": False,
                }
            },
            "live_order_allowed": False,
            "real_order_submitted": False,
        },
        "funding_ledger": {
            "funding_info_available": True,
            "funding_rate_available": True,
            "funding_payment_in_ledger": True,
            "funding_adjusted_net_pnl_reconciled": True,
            "funding_events_count": 94,
            "promotion_evidence": False,
            "blockers": [],
        },
        "cost_model": {
            "status": "pass",
            "funding_model": {"funding_rate_available": True, "funding_payment_in_ledger": True},
            "mark_price_model": {
                "mark_price_available": True,
                "mark_price_klines_available": True,
                "mark_price_current_available": False,
                "premium_index_available": True,
                "mark_price_used_for_liquidation_risk": False,
                "mark_price_blockers": [],
            },
            "liquidation_data": {"liquidation_snapshot_status": "diagnostic_missing_not_complete_history"},
        },
        "liquidation_risk_contract": {
            "status": "complete",
            "decision": "liquidation_contract_complete",
            "blockers": [],
        },
    }


def _write_fixture_tree(root: Path) -> None:
    sources = _disabled_sources()
    target_path = Path("data/forward_observation/btc_trend_raw_v1/artifacts/target.json")
    _write_json(
        root / "artifacts/btc_trend_v0/latest/btc_trend_raw_forward_observation_daily_run_report.json",
        {"forecast_target_order_chain": {"target_artifact": target_path.as_posix()}},
    )
    _write_json(root / target_path, sources["latest_target"] or {})
    _write_json(
        root / "artifacts/btc_paper_validation/latest/btc_paper_validation_replay_report.json",
        sources["paper_validation_replay"] or {},
    )
    _write_json(
        root / "artifacts/btc_live_readiness/latest/btc_live_readiness_risk_constitution_report.json",
        sources["live_readiness"] or {},
    )
    _write_json(root / "artifacts/btc_cost_model/latest/btc_funding_ledger_report.json", sources["funding_ledger"] or {})
    _write_json(root / "artifacts/btc_cost_model/latest/btc_cost_model_report.json", sources["cost_model"] or {})
    _write_json(
        root / "artifacts/btc_completion_evidence/latest/liquidation_risk_contract.json",
        sources["liquidation_risk_contract"] or {},
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
