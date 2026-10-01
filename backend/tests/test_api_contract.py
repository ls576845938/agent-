from __future__ import annotations

import importlib.util
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from quant_us.data.cleaners.bar_cleaner import BarCleaner
from quant_us.data.minute_quality_gate import _expected_regular_timestamps
from quant_us.data.pipeline import DataLakeConfig, DataLakeService
from quant_us.execution.ledger import JsonlLedgerStore
from quant_us.core.enums import OrderSide
from quant_us.core.types import Fill
from quant_us.core.calendar import USEquityCalendar


TESTCLIENT_AVAILABLE = bool(importlib.util.find_spec("fastapi")) and bool(importlib.util.find_spec("httpx"))


def _write_portfolio_observability(data_root: Path) -> None:
    report_dir = data_root / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "portfolio_observability.json").write_text(
        """{
  "multi_strategy": {"status": "PASS", "strategies": ["trend_macd", "reversion_rsi"]},
  "multi_timeframe": {"status": "PASS", "timeframes": ["1d", "1h"]},
  "pnl_attribution": {"status": "PASS", "rows": [{"strategy_id": "trend_macd", "pnl": 1.0}]}
}""",
        encoding="utf-8",
    )


def _write_qlib_run(artifacts_root: Path, run_id: str, *, workflow_status: str = "completed", dataset_status: str = "completed") -> None:
    run_root = artifacts_root / run_id
    (run_root / "qlib_input").mkdir(parents=True, exist_ok=True)
    (run_root / "qlib_input" / "dataset_manifest.json").write_text(
        json.dumps({
            "status": dataset_status,
            "symbols_exported": ["AAPL", "MSFT"],
            "symbols_requested": ["AAPL", "MSFT"],
        }),
        encoding="utf-8",
    )
    (run_root / "provider_manifest.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
    (run_root / "workflow_run_result.json").write_text(json.dumps({"status": workflow_status}), encoding="utf-8")
    (run_root / "qlib_strategy_manifest.json").write_text(
        json.dumps({
            "status": "completed",
            "promotion_status": "READY_FOR_PAPER_REVIEW",
            "strategy_id": "trend_macd",
        }),
        encoding="utf-8",
    )


def _write_portfolio_run(artifacts_root: Path, run_id: str, *, optimizer: str = "max_sharpe") -> None:
    run_root = artifacts_root / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "run_manifest.json").write_text(
        json.dumps({
            "source_score_run_id": "qlib_run_20260511",
            "config": {"optimizer": optimizer},
            "fallback_used": False,
        }),
        encoding="utf-8",
    )
    pd.DataFrame(
        {
            "datetime": ["2026-05-11T00:00:00Z", "2026-05-11T00:00:00Z"],
            "symbol": ["AAPL", "MSFT"],
            "target_weight": [0.6, 0.4],
        }
    ).to_parquet(run_root / "target_weights.parquet", index=False)
    pd.DataFrame(
        {
            "timestamp_utc": ["2026-05-11T00:00:00Z"],
            "strategy_id": ["pypfopt_daily_only"],
            "symbol": ["AAPL"],
            "target_weight": [0.6],
            "target_quantity": [6],
        }
    ).to_parquet(run_root / "target_positions.parquet", index=False)


def _write_conflicting_registry(data_root: Path) -> None:
    registry_path = data_root / "research" / "evidence_registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps({
            "schema_version": "evidence_registry_v1",
            "generated_at": "2026-05-11T00:00:00Z",
            "registry_notes": ["conflicting_registry_evidence:paper_review:demo"],
            "counts": {},
            "evidence": {
                "paper_reviews": [
                    {
                        "id": "review_conflict_1",
                        "path": str(data_root / "research" / "paper_review" / "review_conflict_1.json"),
                        "integrity_status": "CONFLICT",
                        "details": {
                            "status": "CONFLICT",
                            "evidence_pack_path": str(data_root / "research" / "paper_review" / "pack.json"),
                        },
                    }
                ],
                "strategy_manifests": [
                    {
                        "id": "manifest_1",
                        "path": str(data_root / "research" / "strategy_manifests" / "manifest_1.json"),
                        "details": {"promotion_status": "READY_FOR_PAPER_REVIEW"},
                    }
                ],
            },
        }),
        encoding="utf-8",
    )


def _write_minute_partition(
    data_root: Path,
    *,
    root_subdir: str,
    symbol: str,
    bar_size: str,
    trading_day: str,
    timestamps: list[datetime],
) -> None:
    path = (
        data_root
        / root_subdir
        / "vendor=yfinance"
        / "asset_class=equity"
        / f"bar_size={bar_size}"
        / f"symbol={symbol}"
        / f"date={trading_day}.parquet"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            "symbol": [symbol] * len(timestamps),
            "open": [100.0] * len(timestamps),
            "high": [101.0] * len(timestamps),
            "low": [99.0] * len(timestamps),
            "close": [100.5] * len(timestamps),
            "volume": [1_000] * len(timestamps),
        }
    ).to_parquet(path, index=False)


class ApiSchemaDefaultTests(unittest.TestCase):
    def test_backtest_request_defaults_are_us_equity(self) -> None:
        from backend.app.api.schemas import BaseBacktestRequest, DataQualityRequest

        payload = {
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-02-01T00:00:00Z",
        }
        backtest = BaseBacktestRequest.model_validate(payload)
        quality = DataQualityRequest.model_validate(payload)

        self.assertEqual(backtest.source, "yfinance")
        self.assertEqual(backtest.symbol, "SPY")
        self.assertEqual(backtest.interval, "1d")
        self.assertEqual(quality.source, "yfinance")
        self.assertEqual(quality.symbol, "SPY")
        self.assertEqual(quality.interval, "1d")

    def test_system_overview_payload_is_read_only_pre_live(self) -> None:
        from backend.app.api.app_factory import _system_overview_payload

        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_portfolio_observability(root)
            payload = _system_overview_payload(
                directory,
                pit_data_intake_report_path=str(root / "pit_intake.json"),
                pit_operator_handoff_summary_path=str(root / "pit_operator_handoff.json"),
                minute_quality_as_of="2026-05-08T21:00:00Z",
            )
            self.assertFalse((root / "research" / "evidence_registry.json").exists())

        self.assertEqual(payload["mode"], "pre_live")
        self.assertEqual(payload["execution"]["live_state"], "frozen")
        self.assertFalse(payload["execution"]["live_submit_allowed"])
        self.assertEqual(payload["execution"]["paper_submit_default"], "disabled")
        self.assertEqual(payload["portfolio_observability"]["live_state"], "FROZEN")
        self.assertEqual(payload["portfolio_observability"]["multi_strategy"]["status"], "PASS")
        self.assertEqual(payload["portfolio_observability"]["multi_timeframe"]["status"], "PASS")
        self.assertEqual(payload["portfolio_observability"]["pnl_attribution"]["status"], "PASS")
        self.assertEqual(payload["minute_data_quality"]["status"], "MISSING")
        self.assertEqual(len(payload["minute_data_quality"]["datasets"]), 2)
        self.assertEqual(
            {item["root_subdir"] for item in payload["minute_data_quality"]["datasets"]},
            {"raw", "cleaned"},
        )
        self.assertEqual(
            payload["portfolio_observability"]["paper_submit_gates"]["state"],
            "BLOCKED_BY_DEFAULT",
        )
        self.assertFalse(payload["execution"]["paper_network_submit_confirmation"])
        self.assertEqual(payload["registry"]["state"], "missing")
        self.assertIn("integrations", payload)
        self.assertIn("data_coverage", payload)
        self.assertEqual(payload["pit_data_intake"]["status"], "missing")
        self.assertEqual(payload["pit_data_intake"]["current_blocking_stage"], "pit_data_intake_status_report")
        self.assertEqual(payload["pit_operator_handoff"]["status"], "missing")
        self.assertEqual(payload["pit_operator_handoff"]["current_blocking_stage"], "pit_operator_handoff_report")
        self.assertFalse(payload["pit_operator_handoff"]["guardrails"]["live_order_allowed"])
        self.assertIn("diagnostics", payload["paper_review"])
        self.assertTrue(payload["next_actions"])

    def test_system_overview_payload_surfaces_pit_intake_blocker(self) -> None:
        from backend.app.api.app_factory import _system_overview_payload

        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_portfolio_observability(root)
            pit_report = root / "pit_intake.json"
            development_audit_report = root / "development_audit.json"
            live_readiness_report = root / "live_readiness.json"
            strategy_validation_report = root / "strategy_validation.json"
            forward_evaluation_report = root / "forward_evaluation.json"
            forward_health_report = root / "forward_health.json"
            manual_review_packet = root / "manual_review_packet.json"
            paper_simulation_readiness = root / "paper_simulation_readiness.json"
            small_account_preflight = root / "small_account_preflight.json"
            data_source_reconciliation = root / "data_source_reconciliation.json"
            data_lineage_remediation = root / "data_lineage_remediation.json"
            macro_release_lag_policy = root / "macro_release_lag_policy.json"
            production_data_acquisition_plan = root / "production_data_acquisition_plan.json"
            candidate_bundle_evidence = root / "candidate_bundle_evidence.json"
            production_bundle_intake_packet = root / "production_bundle_intake_packet.json"
            manual_vendor_drop_package = root / "manual_vendor_drop_package.json"
            pit_operator_handoff = root / "pit_operator_handoff.json"
            incoming_drop_readiness = root / "incoming_drop_readiness.json"
            local_csv_bundle_import = root / "local_csv_bundle_import.json"
            production_bundle_activation = root / "production_bundle_activation.json"
            schema_audit_report = root / "schema_audit.json"
            monitoring_rules_report = root / "monitoring_rules.json"
            replay_readiness_report = root / "replay_readiness.json"
            strategy_registry_report = root / "strategy_registry.json"
            strategy_registry_audit_report = root / "strategy_registry_audit.json"
            daily_production_line_report = root / "daily_production_line.json"
            pit_report.write_text(
                json.dumps(
                    {
                        "status": "production_pit_data_intake_blocked",
                        "current_blocking_stage": "incoming_drop_readiness",
                        "next_action": {
                            "stage_id": "incoming_drop_readiness",
                            "description": "Place the six licensed CSV files under data/external/us_equity_lineage/incoming/manual_vendor_drop.",
                            "first_blocker": "source_dir_missing",
                        },
                        "stages": [
                            {"stage_id": "manual_vendor_drop_package", "status": "pass"},
                            {"stage_id": "incoming_drop_readiness", "status": "blocked"},
                        ],
                        "blockers": ["source_dir_missing"],
                        "guardrails": {"live_order_allowed": False},
                    }
                ),
                encoding="utf-8",
            )
            pit_operator_handoff.write_text(
                json.dumps(
                    {
                        "status": "handoff_blocked",
                        "current_blocking_stage": "incoming_drop_readiness",
                        "current_blocking_step": "incoming_drop_readiness",
                        "incoming_drop_dir": "data/external/us_equity_lineage/incoming/manual_vendor_drop",
                        "default_bundle_id": "manual_vendor_bundle_v1",
                        "required_table_count": 6,
                        "required_tables": [
                            {
                                "table": "universe_membership_events",
                                "filename": "universe_membership_events.csv",
                                "required_fields": ["security_id", "ticker"],
                                "minimum_record_count": 1,
                                "empty_template_is_not_valid_drop": True,
                            }
                        ],
                        "operator_next_actions": [
                            "Create directory: data/external/us_equity_lineage/incoming/manual_vendor_drop",
                            "Copy the six licensed CSV files into the incoming drop directory using docs/us_equity_manual_vendor_drop_templates headers.",
                        ],
                        "commands": {
                            "preferred_import": "python scripts/import_us_equity_local_csv_production_bundle.py --source-dir data/external/us_equity_lineage/incoming/manual_vendor_drop --bundle-id manual_vendor_bundle_v1 --promotion-clean-allowed",
                            "daily_production_line": "python scripts/run_us_equity_daily_production_line.py",
                        },
                        "blockers": ["source_dir_missing", "pit_bundle_acceptance_not_ready"],
                        "outputs": {
                            "markdown": "../学习资料/量化交易业务闭环/系统评估/US Equity PIT 数据交付一页纸.md"
                        },
                        "source_reports": {
                            "pit_bundle_acceptance": {
                                "status": "acceptance_blocked",
                                "path": "artifacts/us_equity_data_lineage/latest/us_equity_pit_bundle_acceptance_run_report.json",
                            }
                        },
                        "guardrails": {
                            "operator_handoff_only": True,
                            "paper_or_live_unlock_allowed": False,
                            "paper_simulation_allowed": False,
                            "live_order_allowed": False,
                            "private_endpoint_allowed": False,
                            "order_endpoint_allowed": False,
                            "real_order_submitted": False,
                            "broker_calls_used": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            development_audit_report.write_text(
                json.dumps(
                    {
                        "status": "development_plan_blocked_by_production_pit_data",
                        "decision": "continue_building_production_line_do_not_unlock_live",
                        "summary": {"phase_count": 11, "complete_count": 6, "blocked_count": 4, "observing_count": 1},
                        "phase_checks": [
                            {
                                "phase_id": "phase_1_data_lineage_hardening",
                                "title": "数据链路硬化与 PIT 生产数据包",
                                "status": "blocked_external_data",
                                "blockers": ["production_bundle_missing", "explicit_bundle_selection_missing"],
                            },
                            {
                                "phase_id": "phase_3_forward_observation_evaluation",
                                "title": "Forward observation 30/60/90 日评估",
                                "status": "observing",
                                "blockers": [],
                            },
                        ],
                        "blockers": ["production_bundle_missing"],
                        "guardrails": {"live_order_allowed": False, "paper_or_live_unlock_allowed": False},
                    }
                ),
                encoding="utf-8",
            )
            live_readiness_report.write_text(
                json.dumps(
                    {
                        "status": "live_readiness_blocked",
                        "decision": "do_not_start_live_trading",
                        "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
                        "account_capital_usd": 10000.0,
                        "max_live_principal_usd": 0.0,
                        "live_order_allowed": False,
                        "paper_simulation_unlocked_by_this_report": False,
                        "blockers": [
                            "us_equity_live_readiness_strategy_validation_gate_not_passed",
                            "us_equity_live_readiness_forward_observation_less_than_30_days",
                        ],
                        "gate_checks": {"strategy_validation_gate_passed": False},
                        "guardrails": {"live_order_allowed": False, "real_order_submitted": False},
                    }
                ),
                encoding="utf-8",
            )
            strategy_validation_report.write_text(
                json.dumps(
                    {
                        "status": "blocked_data_quality",
                        "decision": "do_not_claim_strategy_validated_until_data_quality_gate_passes",
                        "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
                        "candidate_variant": "min_adv_10m_to_shv + vol_target_20pct_cap1.5x",
                        "allowed_next_action": "fix_blockers",
                        "forward_observation_allowed": True,
                        "paper_ready": False,
                        "live_ready": False,
                        "blockers": ["us_etf_strategy_validation_data_coverage_and_quality_failed"],
                        "checks": {
                            "data_coverage_and_quality": {
                                "passed": False,
                                "tiingo_status": "pass",
                                "kline_quality_status": "warn",
                                "fred_preflight_status": "fred_macro_preflight_warn",
                                "matched_data_quality_blockers": ["point_in_time_universe_not_confirmed"],
                            },
                            "walk_forward": {"passed": True, "fold_count": 6, "walk_forward_oos_cagr": 0.16},
                        },
                        "guardrails": {"live_order_allowed": False, "paper_simulation_allowed": False},
                    }
                ),
                encoding="utf-8",
            )
            forward_evaluation_report.write_text(
                json.dumps(
                    {
                        "status": "forward_observing",
                        "decision": "continue_observing",
                        "minimum_complete_days": 30,
                        "metrics": {
                            "observation_days": 1,
                            "latest_observation_date": "2026-06-23",
                            "simulated_fill_count": 3,
                        },
                        "blockers": [],
                        "guardrails": {"live_order_allowed": False, "paper_simulation_allowed": False},
                    }
                ),
                encoding="utf-8",
            )
            forward_health_report.write_text(
                json.dumps(
                    {
                        "status": "daily_health_pass",
                        "decision": "continue_forward_observation",
                        "ledger": {"target_position_rows": 1, "fill_rows": 3},
                        "warnings": [],
                    }
                ),
                encoding="utf-8",
            )
            manual_review_packet.write_text(
                json.dumps(
                    {
                        "status": "manual_review_pending",
                        "decision": "human_review_required",
                        "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
                        "blockers": [
                            "us_equity_manual_review_strategy_validation_not_passed",
                            "us_equity_manual_review_forward_observation_not_complete",
                        ],
                        "evidence_checklist": [
                            {"check_id": "strategy_validation_gate_passed", "passed": False},
                            {"check_id": "forward_ledger_recalculation_passed", "passed": True},
                        ],
                        "signoff_requirements": [
                            {"signoff_id": "strategy_research_review", "required": True, "recorded": False}
                        ],
                        "paper_or_live_unlock_decision": {
                            "manual_review_can_unlock_paper_by_itself": False,
                            "manual_review_can_unlock_live_by_itself": False,
                        },
                        "guardrails": {"live_order_allowed": False, "paper_simulation_allowed": False},
                    }
                ),
                encoding="utf-8",
            )
            paper_simulation_readiness.write_text(
                json.dumps(
                    {
                        "status": "paper_simulation_blocked",
                        "decision": "do_not_start_paper_simulation",
                        "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
                        "paper_ledger_root": "data/paper_ledger/us_equity_etf_rotation_v1",
                        "paper_runner_allowed": False,
                        "required_runner_contract": {
                            "independent_ledger_root": "data/paper_ledger/us_equity_etf_rotation_v1",
                            "must_not_reuse_forward_observation_ledger": True,
                            "order_endpoint_allowed": False,
                            "real_order_submitted": False,
                        },
                        "blockers": [
                            "us_equity_paper_readiness_manual_review_not_ready",
                            "us_equity_paper_readiness_strategy_validation_not_passed",
                            "us_equity_paper_readiness_production_pit_intake_not_ready",
                        ],
                        "manual_review_evidence": {
                            "forward_data_gate_no_blocked_runs": True,
                            "forward_data_gate_blocked_count": 0,
                        },
                        "unsafe_flags": [],
                        "source_reports": {
                            "manual_review": "manual_review_packet.json",
                            "production_pit_intake_status": "pit_status.json",
                        },
                        "guardrails": {
                            "readiness_report_only": True,
                            "paper_simulation_allowed": False,
                            "live_order_allowed": False,
                            "order_endpoint_allowed": False,
                            "private_endpoint_allowed": False,
                            "real_order_submitted": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            small_account_preflight.write_text(
                json.dumps(
                    {
                        "status": "pass_observation_only",
                        "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
                        "candidate_variant": "min_adv_10m_to_shv",
                        "timestamp": "2026-06-23",
                        "account_equity": 10000.0,
                        "annual_financing_rate": 0.055,
                        "slippage_bps": 10.0,
                        "min_trade_amount_usd": 25.0,
                        "latest_target": {"gross_exposure": 0.978, "symbols": ["DBMF", "SHV", "USO"]},
                        "scenarios": [
                            {
                                "scenario_id": "one_x_cash_only",
                                "gross_cap": 1.0,
                                "effective_gross": 0.978,
                                "allow_margin": False,
                                "passes_preflight": True,
                                "blockers": [],
                                "fractional_share_allowed_model": {
                                    "cash_after_orders": 210.32,
                                    "estimated_financing_daily": 0.0,
                                    "estimated_slippage": 9.78,
                                },
                                "whole_share_model": {
                                    "cash_after_orders": 234.15,
                                    "estimated_slippage": 9.76,
                                },
                            },
                            {
                                "scenario_id": "research_cap_1_5x",
                                "gross_cap": 1.5,
                                "effective_gross": 0.978,
                                "allow_margin": True,
                                "passes_preflight": True,
                                "blockers": [],
                                "fractional_share_allowed_model": {
                                    "cash_after_orders": 210.32,
                                    "estimated_financing_daily": 0.0,
                                    "estimated_slippage": 9.78,
                                },
                                "whole_share_model": {
                                    "cash_after_orders": 234.15,
                                    "estimated_slippage": 9.76,
                                },
                            },
                        ],
                        "blockers": [],
                        "guardrails": {
                            "simulated_only": True,
                            "initial_live_leverage_default": 1.0,
                            "research_cap_1_5x_not_live_default": True,
                            "live_order_allowed": False,
                            "order_endpoint_allowed": False,
                            "private_endpoint_allowed": False,
                            "real_order_submitted": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            data_source_reconciliation.write_text(
                json.dumps(
                    {
                        "status": "research_reconciled_promotion_blocked",
                        "selected_price_source": "tiingo_eod_adjusted",
                        "selected_price_root": "data/external/us_equity_eod/tiingo/kline",
                        "blockers": ["us_equity_data_lineage_not_promotion_clean"],
                        "guardrails": {"live_order_allowed": False},
                    }
                ),
                encoding="utf-8",
            )
            data_lineage_remediation.write_text(
                json.dumps(
                    {
                        "status": "remediation_required",
                        "data_lineage_maturity": "research_only",
                        "remediation_task_count": 5,
                        "remediation_groups": [
                            {
                                "group_id": "point_in_time_universe",
                                "status": "blocked",
                                "blockers": ["point_in_time_universe_not_confirmed"],
                            },
                            {
                                "group_id": "corporate_actions",
                                "status": "blocked",
                                "blockers": ["corporate_action_event_source_missing"],
                            },
                        ],
                        "blockers": ["point_in_time_universe_not_confirmed", "corporate_action_event_source_missing"],
                        "guardrails": {"live_order_allowed": False},
                    }
                ),
                encoding="utf-8",
            )
            macro_release_lag_policy.write_text(
                json.dumps(
                    {
                        "status": "research_lag_only_release_calendar_missing",
                        "macro_source": "FRED",
                        "accepted_evidence_for_promotion": False,
                        "blockers": ["fred_release_calendar_missing", "macro_release_lag_not_production_pit"],
                        "guardrails": {"live_order_allowed": False},
                    }
                ),
                encoding="utf-8",
            )
            production_data_acquisition_plan.write_text(
                json.dumps(
                    {
                        "status": "production_data_acquisition_required",
                        "acceptable_provider_ids": ["crsp", "sharadar", "norgate", "local_csv"],
                        "missing_contract_groups": ["pit_universe", "survivorship", "corporate_actions"],
                        "required_tables": [
                            {
                                "table": "universe_membership_events",
                                "filename": "universe_membership_events.csv",
                                "required_fields": ["security_id", "ticker", "effective_date"],
                            },
                            {
                                "table": "delisted_symbols",
                                "filename": "delisted_symbols.csv",
                                "required_fields": ["security_id", "ticker", "delisting_date"],
                            },
                        ],
                        "acceptance_commands": [
                            "python scripts/import_us_equity_local_csv_production_bundle.py --source-dir data/external/us_equity_lineage/incoming/manual_vendor_drop --bundle-id manual_vendor_bundle_v1"
                        ],
                        "blockers": ["production_bundle_missing", "explicit_bundle_selection_missing"],
                        "guardrails": {"live_order_allowed": False},
                    }
                ),
                encoding="utf-8",
            )
            candidate_bundle_evidence.write_text(
                json.dumps(
                    {
                        "status": "candidate_evidence_ready_for_manual_bundle_build",
                        "decision": "use_as_manual_bundle_build_input_only_do_not_promote",
                        "blockers": ["missing:pit_universe_membership_events"],
                        "guardrails": {"live_order_allowed": False},
                    }
                ),
                encoding="utf-8",
            )
            production_bundle_intake_packet.write_text(
                json.dumps(
                    {
                        "status": "intake_packet_ready_for_data_vendor_drop",
                        "decision": "prepare_external_pit_bundle_drop_do_not_unlock_trading",
                        "operator_steps": [
                            {
                                "step_id": "prepare_incoming_drop",
                                "command": "Place the six licensed CSV files in data/external/us_equity_lineage/incoming/manual_vendor_drop",
                                "expected_result": "incoming drop contains licensed CSV files",
                            },
                            {
                                "step_id": "run_importer",
                                "command": "python scripts/import_us_equity_local_csv_production_bundle.py --source-dir data/external/us_equity_lineage/incoming/manual_vendor_drop --bundle-id manual_vendor_bundle_v1",
                                "expected_result": "bundle created",
                            },
                        ],
                        "blockers": [],
                        "guardrails": {"live_order_allowed": False},
                    }
                ),
                encoding="utf-8",
            )
            manual_vendor_drop_package.write_text(
                json.dumps(
                    {
                        "status": "manual_vendor_drop_package_ready",
                        "incoming_drop_dir": "data/external/us_equity_lineage/incoming/manual_vendor_drop",
                        "default_bundle_id": "manual_vendor_bundle_v1",
                        "required_table_count": 6,
                        "field_count": 51,
                        "blockers": [],
                        "guardrails": {"live_order_allowed": False},
                    }
                ),
                encoding="utf-8",
            )
            incoming_drop_readiness.write_text(
                json.dumps(
                    {
                        "status": "incoming_drop_blocked",
                        "source_dir": "data/external/us_equity_lineage/incoming/manual_vendor_drop",
                        "required_table_count": 6,
                        "present_table_count": 0,
                        "missing_table_count": 6,
                        "blockers": ["source_dir_missing"],
                        "guardrails": {"live_order_allowed": False},
                    }
                ),
                encoding="utf-8",
            )
            local_csv_bundle_import.write_text(
                json.dumps(
                    {
                        "status": "production_bundle_import_blocked",
                        "bundle_id": "manual_vendor_bundle_v1",
                        "blockers": ["source_dir_missing"],
                        "guardrails": {"live_order_allowed": False},
                    }
                ),
                encoding="utf-8",
            )
            production_bundle_activation.write_text(
                json.dumps(
                    {
                        "status": "activation_blocked",
                        "candidate_bundle_id": "manual_vendor_bundle_v1",
                        "candidate_config_path": "artifacts/us_equity_data_lineage/latest/activation_candidates/us_equity_provider_sources.missing.candidate.yaml",
                        "blockers": [
                            "candidate_bundle_manifest_missing",
                            "manual_license_review_required_before_activation",
                        ],
                        "guardrails": {"live_order_allowed": False},
                    }
                ),
                encoding="utf-8",
            )
            schema_audit_report.write_text(
                json.dumps(
                    {
                        "status": "schema_audit_pass",
                        "decision": "standard_schema_ready_for_manual_review",
                        "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
                        "candidate_variant": "min_adv_10m_to_shv + vol_target_20pct_cap1.5x",
                        "required_fields": ["strategy_id", "metrics", "benchmarks"],
                        "coverage_summary": {
                            "required_field_count": 3,
                            "passed_field_count": 3,
                            "missing_input_count": 0,
                            "unsafe_flag_count": 0,
                        },
                        "field_checks": {
                            "strategy_id": {"passed": True, "sources": ["strategy_gate_report"]},
                            "metrics": {"passed": True, "sources": ["validation_report.standardized_report_schema.rows"]},
                            "benchmarks": {"passed": True, "sources": ["validation_report.standardized_report_schema.rows"]},
                        },
                        "blockers": [],
                        "guardrails": {"schema_audit_only": True, "live_order_allowed": False},
                    }
                ),
                encoding="utf-8",
            )
            monitoring_rules_report.write_text(
                json.dumps(
                    {
                        "status": "monitoring_rules_defined",
                        "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
                        "monitor_count": 18,
                        "required_before_paper_or_live": True,
                        "minimum_required_before_paper": ["structured_daily_run_report", "data_staleness_stop"],
                        "rules": {"data_monitors": {}, "retirement_rules": {}},
                        "blockers": [],
                        "guardrails": {"rules_only": True, "live_order_allowed": False},
                    }
                ),
                encoding="utf-8",
            )
            replay_readiness_report.write_text(
                json.dumps(
                    {
                        "status": "replay_readiness_pass",
                        "decision": "replay_inputs_available_for_manual_audit",
                        "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
                        "latest_observation": {"timestamp": "2026-06-23", "fill_count": 3},
                        "checks": {
                            "fixed_replay_contract": {"passed": True},
                            "unsafe_flags": {"passed": True},
                        },
                        "blockers": [],
                        "guardrails": {"replay_readiness_only": True, "live_order_allowed": False},
                    }
                ),
                encoding="utf-8",
            )
            strategy_registry_report.write_text(
                json.dumps(
                    {
                        "schema_version": "us_equity_strategy_registry_v1",
                        "policy": {
                            "paper_or_live_unlock_allowed_by_registry": False,
                            "private_endpoint_allowed": False,
                            "order_endpoint_allowed": False,
                            "live_order_allowed": False,
                        },
                        "strategies": [
                            {
                                "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
                                "family": "us_etf_macro_momentum_rotation",
                                "status": "forward_observation_only",
                                "current_stage": "forward_observation",
                                "primary_candidate": True,
                                "guardrails": {"paper_ready": False, "live_ready": False},
                            },
                            {
                                "strategy_id": "us_equity_dual_momentum_research_placeholder",
                                "family": "dual_momentum",
                                "status": "hypothesis_registered_only",
                                "current_stage": "strategy_hypothesis_registration",
                                "primary_candidate": False,
                                "guardrails": {"paper_ready": False, "live_ready": False},
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            strategy_registry_audit_report.write_text(
                json.dumps(
                    {
                        "schema_version": "us_equity_strategy_registry_report_v1",
                        "status": "pass",
                        "strategy_count": 2,
                        "primary_candidate_count": 1,
                        "formal_candidate_count": 1,
                        "required_families": ["us_etf_macro_momentum_rotation", "dual_momentum"],
                        "missing_required_families": [],
                        "blockers": [],
                        "warnings": [],
                        "guardrails": {
                            "unregistered_strategy_promotion_allowed": False,
                            "paper_or_live_unlock_allowed_by_registry": False,
                            "live_order_allowed": False,
                            "private_endpoint_allowed": False,
                            "order_endpoint_allowed": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            daily_production_line_report.write_text(
                json.dumps(
                    {
                        "schema_version": "us_equity_daily_production_line_run_v1",
                        "generated_at": "2026-06-26T01:55:51Z",
                        "pipeline": "us_equity_daily_production_line",
                        "status": "PASS",
                        "decision": "continue_forward_observation_and_keep_paper_live_locked",
                        "expected_external_blocker": {
                            "production_pit_data_required": True,
                            "production_line_status": "production_line_blocked_before_paper_or_live",
                            "development_plan_status": "development_plan_blocked_by_production_pit_data",
                        },
                        "forward_observation": {
                            "daily_health_status": "daily_health_pass",
                            "observation_days": 1,
                            "minimum_complete_days": 30,
                            "latest_observation_date": "2026-06-23",
                        },
                        "steps": [
                            {"step_id": "etf_kline_quality_daily", "status": "warn", "passed": True, "blockers": []},
                            {
                                "step_id": "forward_observation_daily",
                                "status": "PASS",
                                "passed": True,
                                "blockers": [],
                                "payload": {
                                    "steps": {
                                        "data_gate": {
                                            "status": "pass",
                                            "checks": [
                                                {
                                                    "check_id": "data_freshness",
                                                    "status": "pass",
                                                    "passed": True,
                                                    "blockers": [],
                                                    "source_report": "data_freshness.json",
                                                },
                                                {
                                                    "check_id": "kline_quality",
                                                    "status": "warn",
                                                    "passed": True,
                                                    "blockers": [],
                                                    "source_report": "kline_quality.json",
                                                },
                                                {
                                                    "check_id": "fred_preflight",
                                                    "status": "fred_macro_preflight_warn",
                                                    "passed": True,
                                                    "blockers": [],
                                                    "source_report": "fred_preflight.json",
                                                },
                                            ],
                                            "blockers": [],
                                            "guardrails": {"live_order_allowed": False},
                                        }
                                    }
                                },
                            },
                            {
                                "step_id": "strategy_production_line",
                                "status": "production_line_blocked_before_paper_or_live",
                                "passed": True,
                                "blockers": [],
                            },
                        ],
                        "blockers": [],
                        "unsafe_flags": [],
                        "guardrails": {
                            "daily_orchestration_only": True,
                            "paper_or_live_unlock_allowed": False,
                            "paper_simulation_allowed": False,
                            "live_order_allowed": False,
                            "private_endpoint_allowed": False,
                            "order_endpoint_allowed": False,
                            "real_order_submitted": False,
                            "broker_calls_used": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            payload = _system_overview_payload(
                directory,
                pit_data_intake_report_path=str(pit_report),
                pit_operator_handoff_summary_path=str(pit_operator_handoff),
                development_plan_audit_report_path=str(development_audit_report),
                live_readiness_report_path=str(live_readiness_report),
                strategy_validation_gate_report_path=str(strategy_validation_report),
                forward_observation_evaluation_report_path=str(forward_evaluation_report),
                forward_observation_daily_health_report_path=str(forward_health_report),
                manual_review_packet_path=str(manual_review_packet),
                paper_simulation_readiness_report_path=str(paper_simulation_readiness),
                small_account_execution_preflight_report_path=str(small_account_preflight),
                data_source_reconciliation_report_path=str(data_source_reconciliation),
                data_lineage_remediation_report_path=str(data_lineage_remediation),
                macro_release_lag_policy_report_path=str(macro_release_lag_policy),
                production_data_acquisition_plan_path=str(production_data_acquisition_plan),
                candidate_bundle_evidence_report_path=str(candidate_bundle_evidence),
                production_bundle_intake_packet_path=str(production_bundle_intake_packet),
                manual_vendor_drop_package_report_path=str(manual_vendor_drop_package),
                incoming_drop_readiness_report_path=str(incoming_drop_readiness),
                local_csv_production_bundle_import_report_path=str(local_csv_bundle_import),
                production_bundle_activation_report_path=str(production_bundle_activation),
                standard_report_schema_audit_path=str(schema_audit_report),
                monitoring_rules_report_path=str(monitoring_rules_report),
                replay_readiness_report_path=str(replay_readiness_report),
                strategy_registry_path=str(strategy_registry_report),
                strategy_registry_audit_report_path=str(strategy_registry_audit_report),
                daily_production_line_run_report_path=str(daily_production_line_report),
                minute_quality_as_of="2026-05-08T21:00:00Z",
            )

        self.assertEqual(payload["pit_data_intake"]["status"], "production_pit_data_intake_blocked")
        self.assertEqual(payload["pit_data_intake"]["current_blocking_stage"], "incoming_drop_readiness")
        self.assertEqual(payload["pit_data_intake"]["next_action"]["first_blocker"], "source_dir_missing")
        self.assertEqual(payload["pit_operator_handoff"]["status"], "handoff_blocked")
        self.assertEqual(payload["pit_operator_handoff"]["current_blocking_stage"], "incoming_drop_readiness")
        self.assertEqual(payload["pit_operator_handoff"]["required_table_count"], 6)
        self.assertEqual(payload["pit_operator_handoff"]["required_tables"][0]["field_count"], 2)
        self.assertIn("US Equity PIT 数据交付一页纸.md", payload["pit_operator_handoff"]["outputs"]["markdown"])
        self.assertIn("pit_bundle_acceptance_not_ready", payload["pit_operator_handoff"]["blockers"])
        self.assertFalse(payload["pit_operator_handoff"]["guardrails"]["live_order_allowed"])
        self.assertTrue(
            any("manual_vendor_drop" in item for item in payload["pit_operator_handoff"]["operator_next_actions"])
        )
        commands = [action["command"] for action in payload["pit_data_intake"]["operator_actions"]]
        self.assertIn("python scripts/build_us_equity_incoming_drop_readiness_report.py", commands)
        self.assertTrue(
            any("data/external/us_equity_lineage/incoming/manual_vendor_drop" in command for command in commands)
        )
        self.assertEqual(payload["development_plan_audit"]["status"], "development_plan_blocked_by_production_pit_data")
        self.assertEqual(payload["development_plan_audit"]["summary"]["blocked_count"], 4)
        self.assertEqual(payload["development_plan_audit"]["phase_checks"][0]["blocked_count"], 2)
        self.assertEqual(payload["live_readiness"]["status"], "live_readiness_blocked")
        self.assertFalse(payload["live_readiness"]["live_order_allowed"])
        self.assertIn("us_equity_live_readiness_strategy_validation_gate_not_passed", payload["live_readiness"]["blockers"])
        self.assertEqual(payload["strategy_validation_gate"]["status"], "blocked_data_quality")
        self.assertFalse(payload["strategy_validation_gate"]["paper_ready"])
        self.assertEqual(payload["strategy_validation_gate"]["checks"][0]["check_id"], "data_coverage_and_quality")
        self.assertFalse(payload["strategy_validation_gate"]["checks"][0]["passed"])
        self.assertEqual(payload["forward_observation"]["status"], "forward_observing")
        self.assertEqual(payload["forward_observation"]["daily_health_status"], "daily_health_pass")
        self.assertEqual(payload["forward_observation"]["observation_days"], 1)
        self.assertEqual(payload["manual_review_packet"]["status"], "manual_review_pending")
        self.assertIn("us_equity_manual_review_strategy_validation_not_passed", payload["manual_review_packet"]["blockers"])
        self.assertEqual(payload["paper_simulation_readiness"]["status"], "paper_simulation_blocked")
        self.assertEqual(payload["paper_simulation_readiness"]["paper_ledger_root"], "data/paper_ledger/us_equity_etf_rotation_v1")
        self.assertFalse(payload["paper_simulation_readiness"]["paper_runner_allowed"])
        self.assertIn(
            "us_equity_paper_readiness_strategy_validation_not_passed",
            payload["paper_simulation_readiness"]["blockers"],
        )
        self.assertIn(
            "us_equity_paper_readiness_production_pit_intake_not_ready",
            payload["paper_simulation_readiness"]["blockers"],
        )
        self.assertTrue(
            payload["paper_simulation_readiness"]["manual_review_evidence"]["forward_data_gate_no_blocked_runs"]
        )
        self.assertEqual(
            payload["paper_simulation_readiness"]["source_reports"]["production_pit_intake_status"],
            "pit_status.json",
        )
        self.assertFalse(payload["paper_simulation_readiness"]["guardrails"]["paper_simulation_allowed"])
        self.assertEqual(payload["small_account_execution_preflight"]["status"], "pass_observation_only")
        self.assertEqual(payload["small_account_execution_preflight"]["account_equity"], 10000.0)
        self.assertEqual(payload["small_account_execution_preflight"]["scenario_count"], 2)
        self.assertEqual(payload["small_account_execution_preflight"]["passed_scenario_count"], 2)
        self.assertEqual(payload["small_account_execution_preflight"]["scenarios"][0]["scenario_id"], "one_x_cash_only")
        self.assertFalse(payload["small_account_execution_preflight"]["scenarios"][0]["allow_margin"])
        self.assertFalse(payload["small_account_execution_preflight"]["guardrails"]["live_order_allowed"])
        self.assertEqual(payload["data_lineage_governance"]["reconciliation_status"], "research_reconciled_promotion_blocked")
        self.assertEqual(payload["data_lineage_governance"]["remediation_status"], "remediation_required")
        self.assertEqual(
            payload["data_lineage_governance"]["macro_release_lag_status"],
            "research_lag_only_release_calendar_missing",
        )
        self.assertEqual(payload["data_lineage_governance"]["selected_price_source"], "tiingo_eod_adjusted")
        self.assertEqual(payload["data_lineage_governance"]["remediation_task_count"], 5)
        self.assertIn("fred_release_calendar_missing", payload["data_lineage_governance"]["blockers"])
        self.assertEqual(
            payload["production_data_acquisition"]["acquisition_status"],
            "production_data_acquisition_required",
        )
        self.assertEqual(
            payload["production_data_acquisition"]["candidate_evidence_status"],
            "candidate_evidence_ready_for_manual_bundle_build",
        )
        self.assertEqual(
            payload["production_data_acquisition"]["intake_packet_status"],
            "intake_packet_ready_for_data_vendor_drop",
        )
        self.assertEqual(
            payload["production_data_acquisition"]["manual_package_status"],
            "manual_vendor_drop_package_ready",
        )
        self.assertEqual(payload["production_data_acquisition"]["default_bundle_id"], "manual_vendor_bundle_v1")
        self.assertIn("local_csv", payload["production_data_acquisition"]["acceptable_provider_ids"])
        self.assertIn("pit_universe", payload["production_data_acquisition"]["missing_contract_groups"])
        self.assertEqual(payload["production_data_acquisition"]["required_table_count"], 6)
        self.assertEqual(payload["production_data_acquisition"]["field_count"], 51)
        self.assertIn("production_bundle_missing", payload["production_data_acquisition"]["blockers"])
        self.assertEqual(
            payload["production_data_acquisition"]["required_tables"][0]["filename"],
            "universe_membership_events.csv",
        )
        self.assertEqual(
            payload["production_data_acquisition"]["operator_steps"][0]["step_id"],
            "prepare_incoming_drop",
        )
        self.assertEqual(payload["production_bundle_gate"]["status"], "production_bundle_gate_blocked")
        self.assertEqual(payload["production_bundle_gate"]["current_blocking_stage"], "incoming_drop_readiness")
        self.assertEqual(payload["production_bundle_gate"]["stages"][0]["status"], "incoming_drop_blocked")
        self.assertEqual(payload["production_bundle_gate"]["stages"][1]["summary"]["bundle_id"], "manual_vendor_bundle_v1")
        self.assertIn("source_dir_missing", payload["production_bundle_gate"]["blockers"])
        self.assertFalse(payload["production_bundle_gate"]["guardrails"]["live_order_allowed"])
        bundle_commands = [action["command"] for action in payload["production_bundle_gate"]["operator_actions"]]
        self.assertIn("python scripts/build_us_equity_incoming_drop_readiness_report.py", bundle_commands)
        self.assertTrue(
            any("scripts/import_us_equity_local_csv_production_bundle.py" in command for command in bundle_commands)
        )
        self.assertTrue(
            any("scripts/build_us_equity_production_bundle_activation_report.py" in command for command in bundle_commands)
        )
        self.assertEqual(payload["standard_report_schema_audit"]["status"], "schema_audit_pass")
        self.assertEqual(payload["standard_report_schema_audit"]["coverage_summary"]["passed_field_count"], 3)
        self.assertEqual(payload["standard_report_schema_audit"]["field_checks"][0]["field_id"], "strategy_id")
        self.assertEqual(payload["monitoring_rules"]["status"], "monitoring_rules_defined")
        self.assertEqual(payload["monitoring_rules"]["monitor_count"], 18)
        self.assertEqual(payload["replay_readiness"]["status"], "replay_readiness_pass")
        self.assertEqual(payload["replay_readiness"]["latest_observation"]["fill_count"], 3)
        self.assertEqual(payload["strategy_registry"]["status"], "present")
        self.assertEqual(payload["strategy_registry"]["strategy_count"], 2)
        self.assertEqual(
            payload["strategy_registry"]["primary_strategy_id"],
            "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
        )
        self.assertEqual(payload["strategy_registry"]["stage_counts"]["forward_observation"], 1)
        self.assertEqual(payload["strategy_registry"]["status_counts"]["hypothesis_registered_only"], 1)
        self.assertFalse(payload["strategy_registry"]["policy"]["live_order_allowed"])
        self.assertEqual(payload["strategy_registry"]["audit"]["status"], "pass")
        self.assertEqual(payload["strategy_registry"]["audit"]["formal_candidate_count"], 1)
        self.assertEqual(payload["strategy_registry"]["audit"]["primary_candidate_count"], 1)
        self.assertEqual(payload["strategy_registry"]["audit"]["missing_required_families"], [])
        self.assertEqual(payload["daily_production_line"]["status"], "PASS")
        self.assertEqual(payload["daily_production_line"]["step_count"], 3)
        self.assertEqual(payload["daily_production_line"]["passed_step_count"], 3)
        self.assertTrue(payload["daily_production_line"]["expected_external_blocker"]["production_pit_data_required"])
        self.assertEqual(payload["daily_production_line"]["forward_data_gate"]["status"], "pass")
        self.assertEqual(payload["daily_production_line"]["forward_data_gate"]["checks"][0]["check_id"], "data_freshness")
        self.assertTrue(payload["daily_production_line"]["forward_data_gate"]["checks"][1]["passed"])
        self.assertFalse(payload["daily_production_line"]["guardrails"]["live_order_allowed"])
        self.assertTrue(any("six licensed CSV" in action for action in payload["next_actions"]))

    def test_system_overview_payload_includes_latest_runs_and_conflict_diagnostics(self) -> None:
        from backend.app.api.app_factory import _system_overview_payload

        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_portfolio_observability(root)
            _write_conflicting_registry(root)
            qlib_root = root / "artifacts" / "qlib_runs"
            portfolio_root = root / "artifacts" / "portfolio_runs"
            _write_qlib_run(qlib_root, "qlib_run_20260510")
            _write_qlib_run(qlib_root, "qlib_run_20260511")
            _write_portfolio_run(portfolio_root, "portfolio_run_20260510")
            _write_portfolio_run(portfolio_root, "portfolio_run_20260511")

            payload = _system_overview_payload(
                directory,
                qlib_artifacts_root=str(qlib_root),
                portfolio_artifacts_root=str(portfolio_root),
            )

        self.assertEqual(payload["integrations"]["qlib"]["latest_run"]["run_id"], "qlib_run_20260511")
        self.assertEqual(payload["integrations"]["portfolio"]["latest_run"]["portfolio_run_id"], "portfolio_run_20260511")
        self.assertTrue(payload["paper_review"]["diagnostics"]["conflict_detected"])
        self.assertEqual(payload["paper_review"]["status"], "CONFLICT")
        self.assertIn("coverage_pct", payload["data_coverage"])

    def test_system_overview_payload_blocks_on_minute_quality_fail(self) -> None:
        from backend.app.api.app_factory import _system_overview_payload

        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_portfolio_observability(root)
            calendar = USEquityCalendar.with_holidays()
            trading_day = datetime(2026, 5, 8, tzinfo=timezone.utc).date()
            trading_days = [trading_day]
            while len(trading_days) < 5:
                trading_days.append(calendar.previous_trading_day(trading_days[-1]))
            for current_day in sorted(trading_days):
                for bar_size in ("1m", "5m", "15m"):
                    full = _expected_regular_timestamps(
                        current_day,
                        int(bar_size.removesuffix("m")),
                        calendar,
                    )
                    raw_timestamps = full[:100] if (bar_size == "1m" and current_day == trading_day) else full
                    _write_minute_partition(
                        root,
                        root_subdir="raw",
                        symbol="AAPL",
                        bar_size=bar_size,
                        trading_day=current_day.isoformat(),
                        timestamps=raw_timestamps,
                    )
                    _write_minute_partition(
                        root,
                        root_subdir="cleaned",
                        symbol="AAPL",
                        bar_size=bar_size,
                        trading_day=current_day.isoformat(),
                        timestamps=full,
                    )
            payload = _system_overview_payload(
                directory,
                minute_quality_as_of="2026-05-08T21:00:00Z",
            )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["stage"], "registry_blocked")
        self.assertEqual(payload["minute_data_quality"]["status"], "FAIL")
        dataset_statuses = payload["minute_data_quality"]["dataset_statuses"]
        self.assertEqual(dataset_statuses["raw"]["status"], "FAIL")
        self.assertEqual(dataset_statuses["cleaned"]["status"], "PASS")

    def test_system_overview_payload_does_not_block_on_placeholder_minute_layout(self) -> None:
        from quant_us.reports.paper_validation import PaperValidationEvidence
        from backend.app.api.app_factory import _system_overview_payload

        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_portfolio_observability(root)
            for bar_size in ("1m", "5m", "15m"):
                (
                    root
                    / "raw"
                    / "vendor=yfinance"
                    / "asset_class=equity"
                    / f"bar_size={bar_size}"
                ).mkdir(parents=True, exist_ok=True)

            paper_evidence = PaperValidationEvidence(
                data_root=directory,
                ledger_root=str(root / "paper_ledger"),
                validation_state_path=str(root / "reports" / "paper_production" / "validation_state.json"),
                days_required=30,
                days_completed=30,
                consecutive_clean_days=30,
                paper_submit_orders="disabled",
                readiness_state="PASS",
                audit_blocker_status="PASS",
                data_strict_status="PASS",
                recovery_status="PASS",
                gaps=[],
                evidence=[],
            )

            with (
                patch(
                    "backend.app.api.app_factory._fast_saved_evidence_registry",
                    return_value={
                        "registry_status": "present",
                        "registry_integrity_status": "PASS/STABLE",
                        "registry_path": str(root / "research" / "evidence_registry.json"),
                        "counts": {},
                        "registry_notes": [],
                        "rebuild_available": True,
                    },
                ),
                patch(
                    "backend.app.api.app_factory._fast_paper_review_status",
                    return_value={
                        "status": "APPROVED",
                        "entry_allowed": True,
                        "manual_review_pending": False,
                        "summary": "approved",
                        "evidence_path": str(root / "reports" / "paper_review.json"),
                        "diagnostics": {},
                    },
                ),
                patch(
                    "quant_us.reports.paper_validation.inspect_paper_validation_evidence",
                    return_value=paper_evidence,
                ),
                patch(
                    "quant_us.live.paper_adapter_contract.audit_apca_paper_credentials",
                    return_value={
                        "credentials_present": True,
                        "base_url_valid": True,
                    },
                ),
            ):
                payload = _system_overview_payload(directory)

        self.assertEqual(payload["minute_data_quality"]["status"], "MISSING")
        self.assertEqual(payload["stage"], "paper_ready_for_manual_gate")
        self.assertEqual(payload["status"], "reviewable")
        self.assertGreaterEqual(payload["minute_data_quality"]["remediation_summary"]["action_count"], 1)
        self.assertTrue(
            any("ingest_intraday.py" in step for step in payload["next_actions"]),
        )


@unittest.skipUnless(TESTCLIENT_AVAILABLE, "FastAPI TestClient dependencies are not installed in the current environment")
class ApiContractTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from backend.app.api.app_factory import create_app

        self.client = TestClient(create_app())

    def test_health_endpoint(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")

    def test_btc_domain_read_model_endpoint_is_get_only_no_store_and_fail_closed(self) -> None:
        response = self.client.get("/api/research/btc/domain-read-model")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["pragma"], "no-cache")
        payload = response.json()["detail"]
        self.assertEqual(payload["status"], "unavailable_fail_closed")
        self.assertEqual(payload["error"], "runtime_artifact_root_unavailable")
        self.assertFalse(payload["paper_queue_write_allowed"])
        self.assertFalse(payload["paper_allowed"])
        self.assertFalse(payload["live_unlock_allowed"])
        self.assertFalse(payload["broker_or_order_allowed"])

        post_response = self.client.post("/api/research/btc/domain-read-model")
        self.assertEqual(post_response.status_code, 405)

    def test_us_domain_read_model_endpoint_is_get_only_no_store_and_fail_closed(self) -> None:
        response = self.client.get("/api/research/us-equity/domain-read-model")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["pragma"], "no-cache")
        payload = response.json()
        self.assertEqual(payload["status"], "blocked")
        self.assertFalse(payload["promotion_evidence_ready"])
        self.assertFalse(payload["paper_ready"])
        self.assertFalse(payload["live_ready"])
        self.assertFalse(payload["api_contract"]["side_effects"])
        self.assertFalse(payload["api_contract"]["builder_triggered"])
        self.assertFalse(payload["api_contract"]["runtime_triggered"])
        self.assertFalse(payload["api_contract"]["order_path_registered"])

        post_response = self.client.post(
            "/api/research/us-equity/domain-read-model"
        )
        self.assertEqual(post_response.status_code, 405)

    def test_cn_domain_read_model_endpoint_is_get_only_no_store_and_fail_closed(self) -> None:
        response = self.client.get("/api/research/cn-equity/domain-read-model")

        self.assertIn(response.status_code, {200, 503})
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["pragma"], "no-cache")
        payload = response.json()
        self.assertEqual(payload["status"], "blocked")
        self.assertTrue(payload["safety"])
        self.assertTrue(all(value is False for value in payload["safety"].values()))

        post_response = self.client.post(
            "/api/research/cn-equity/domain-read-model"
        )
        self.assertEqual(post_response.status_code, 405)

    def test_crypto_resample_endpoint_serializes_dataclass_result(self) -> None:
        from backend.app.services.data_management import CryptoResampleResult

        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(hours=1)
        fake_result = CryptoResampleResult(
            status="completed",
            db_path="data/market_data.sqlite",
            exchange="binance_spot",
            symbol="BTCUSDT",
            source_interval="1m",
            target_interval="1h",
            start=start,
            end=end,
            source_rows=60,
            expected_source_rows=60,
            rows_written=1,
            coverage_pct=100.0,
            quality_score=100.0,
            data_version="btc-resample-test",
            quality_summary={"issues": 0},
        )
        with patch(
            "backend.app.api.app_factory.market_data_service.resample_crypto_klines",
            return_value=fake_result,
        ):
            response = self.client.post(
                "/api/data/resample",
                json={
                    "exchange": "binance_spot",
                    "symbol": "BTCUSDT",
                    "source_interval": "1m",
                    "target_interval": "1h",
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "persist_manifest": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["target_interval"], "1h")
        self.assertEqual(payload["rows_written"], 1)

    def test_crypto_event_backtest_endpoint_uses_research_service(self) -> None:
        from backend.app.domain.models import BacktestArtifacts

        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(hours=2)
        fake_artifacts = BacktestArtifacts(
            mode="crypto_event",
            summary={
                "total_return_pct": 0.0,
                "annual_return_pct": 0.0,
                "annual_volatility_pct": 0.0,
                "sharpe_ratio": 0.0,
                "sortino_ratio": 0.0,
                "max_drawdown_pct": 0.0,
                "calmar_ratio": 0.0,
                "win_rate_pct": 0.0,
                "profit_factor": 0.0,
                "trade_count": 0,
            },
            chart={"candles": [], "markers": [], "equity": [], "drawdown": [], "exposure": [], "net_units": []},
            strategy_details=[],
            latest_weights=[],
            diagnostics={"engine": "event_driven"},
        )
        with patch(
            "backend.app.api.app_factory.research_service.run_crypto_event",
            return_value=fake_artifacts,
        ) as run_crypto_event:
            response = self.client.post(
                "/api/backtests/crypto-event",
                json={
                    "source": "sqlite",
                    "symbol": "BTCUSDT",
                    "interval": "1h",
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "capital": 100000,
                    "commission_rate": 0.0004,
                    "slippage": 4,
                    "leverage": 1,
                    "strategy_id": "trend_macd",
                    "strategy_params": {},
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["mode"], "crypto_event")
        self.assertEqual(payload["diagnostics"]["engine"], "event_driven")
        self.assertTrue(run_crypto_event.called)

    def test_system_overview_is_pre_live_and_read_only(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_portfolio_observability(root)
            response = self.client.get(
                "/api/system/overview",
                params={"data_root": directory},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["mode"], "pre_live")
        self.assertEqual(payload["execution"]["live_state"], "frozen")
        self.assertFalse(payload["execution"]["live_submit_allowed"])
        self.assertEqual(payload["execution"]["paper_submit_default"], "disabled")
        self.assertEqual(payload["portfolio_observability"]["live_state"], "FROZEN")
        self.assertEqual(payload["portfolio_observability"]["multi_strategy"]["strategy_count"], 2)
        self.assertEqual(payload["portfolio_observability"]["multi_timeframe"]["timeframe_count"], 2)
        self.assertEqual(payload["portfolio_observability"]["pnl_attribution"]["row_count"], 1)
        self.assertIn("paper --data-root", payload["portfolio_observability"]["next_paper_command"])
        self.assertEqual(payload["minute_data_quality"]["status"], "MISSING")
        self.assertEqual(len(payload["minute_data_quality"]["datasets"]), 2)
        self.assertEqual(payload["registry"]["state"], "missing")
        self.assertIn("integrations", payload)
        self.assertIn("qlib", payload["integrations"])
        self.assertIn("portfolio", payload["integrations"])
        self.assertIn("data_coverage", payload)
        self.assertIn("next_actions", payload)

    def test_system_overview_api_surface_latest_runs(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_portfolio_observability(root)
            _write_conflicting_registry(root)
            qlib_root = root / "artifacts" / "qlib_runs"
            portfolio_root = root / "artifacts" / "portfolio_runs"
            _write_qlib_run(qlib_root, "qlib_run_20260510")
            _write_qlib_run(qlib_root, "qlib_run_20260511")
            _write_portfolio_run(portfolio_root, "portfolio_run_20260510")
            _write_portfolio_run(portfolio_root, "portfolio_run_20260511")
            response = self.client.get(
                "/api/system/overview",
                params={
                    "data_root": directory,
                    "qlib_artifacts_root": str(qlib_root),
                    "portfolio_artifacts_root": str(portfolio_root),
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["integrations"]["qlib"]["latest_run"]["run_id"], "qlib_run_20260511")
        self.assertEqual(payload["integrations"]["portfolio"]["latest_run"]["portfolio_run_id"], "portfolio_run_20260511")
        self.assertTrue(payload["paper_review"]["diagnostics"]["conflict_detected"])
        self.assertEqual(payload["paper_review"]["status"], "CONFLICT")

    def test_metrics_endpoint(self) -> None:
        response = self.client.get("/metrics")
        self.assertEqual(response.status_code, 200)
        self.assertIn("quantstation_up 1", response.text)

    def test_single_backtest_endpoint(self) -> None:
        response = self.client.post(
            "/api/backtests/single",
            json={
                "strategy_id": "trend_macd",
                "source": "fixture",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-02-15T23:00:00Z",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertIn("summary", payload)

    def test_strategy_optimization_endpoint(self) -> None:
        response = self.client.post(
            "/api/backtests/optimize",
            json={
                "strategy_id": "trend_macd",
                "source": "fixture",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-02-15T23:00:00Z",
                "max_candidates": 1,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["framework"][0]["status"], "selected")
        self.assertLessEqual(len(payload["candidates"]), 1)
        self.assertIsNotNone(payload["best"])

    def test_cost_stress_endpoint(self) -> None:
        response = self.client.post(
            "/api/backtests/cost-stress",
            json={
                "strategy_id": "trend_macd",
                "source": "fixture",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-02-15T23:00:00Z",
                "max_scenarios": 1,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["selected_priority"], "交易成本压力测试")
        self.assertEqual(len(payload["scenarios"]), 1)
        self.assertIsNotNone(payload["baseline"])

    def test_walk_forward_endpoint(self) -> None:
        response = self.client.post(
            "/api/backtests/walk-forward",
            json={
                "strategy_id": "trend_macd",
                "source": "fixture",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-02-15T23:00:00Z",
                "windows": 2,
                "max_candidates": 1,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["selected_priority"], "Walk-forward 与市场状态切片")
        self.assertGreaterEqual(len(payload["windows"]), 1)
        self.assertIn("pass_rate_pct", payload["stability"])

    def test_portfolio_optimization_endpoint(self) -> None:
        response = self.client.post(
            "/api/backtests/portfolio-optimize",
            json={
                "source": "fixture",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-02-15T23:00:00Z",
                "weights": [
                    {"strategy_id": "trend_macd", "weight": 0.5},
                    {"strategy_id": "reversion_rsi", "weight": 0.25},
                    {"strategy_id": "donchian_breakout", "weight": 0.25},
                ],
                "max_single_weight": 0.6,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["selected_priority"], "组合层相关性与资金分配")
        self.assertIn("optimized_weights", payload)
        self.assertIn("risk_budget", payload)

    def test_research_promotion_gate_endpoint(self) -> None:
        response = self.client.post(
            "/api/research/promotion-gate",
            json={
                "mode": "portfolio",
                "source": "fixture",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-02-15T23:00:00Z",
                "weights": [
                    {"strategy_id": "trend_macd", "weight": 0.5},
                    {"strategy_id": "reversion_rsi", "weight": 0.25},
                    {"strategy_id": "donchian_breakout", "weight": 0.25},
                ],
                "skip_deep_checks": True,
                "persist_manifest": False,
                "register_experiment": False,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["selected_priority"], "研究准入与实验晋级门")
        self.assertIn(payload["decision"], {"pass", "warn", "fail"})
        self.assertTrue(payload["strategy_version"].startswith("strategy_"))
        self.assertEqual(payload["experiment_record"], {})
        self.assertGreaterEqual(len(payload["gates"]), 4)

    def test_data_database_endpoint_initializes_sqlite(self) -> None:
        with TemporaryDirectory() as directory:
            response = self.client.get(
                "/api/data/database",
                params={"db_path": f"{directory}/market.sqlite"},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["initialized"])
        self.assertIn("market.sqlite", payload["db_path"])

    def test_data_quality_endpoint_returns_versioned_gate(self) -> None:
        response = self.client.post(
            "/api/data/quality",
            json={
                "source": "fixture",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-01-10T00:00:00Z",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["selected_priority"], "数据质量与特征版本治理")
        self.assertTrue(payload["is_usable"])
        self.assertIn("data_version", payload)

    def test_paper_review_create_accepts_portfolio_evidence_pack(self) -> None:
        class FakeReview:
            paper_review_id = "prev_001"
            status = "PENDING_HUMAN_REVIEW"
            evidence_pack_path = "/tmp/research/evidence_packs/psim_001/evidence_pack.json"
            evidence_gate_status = "READY_FOR_REVIEW"
            proposed_symbols = ["SPY", "QQQ"]
            proposed_capital = 101500.0
            created_at = "2026-05-11T00:00:00+00:00"

        with patch(
            "quant_us.research.paper_review_bridge.PaperReviewManager.create_from_portfolio_evidence",
            return_value=FakeReview(),
        ) as create_from_pack:
            response = self.client.post(
                "/api/research/paper-review/create",
                json={
                    "portfolio_evidence_pack_id": "psim_001",
                    "data_root": "/tmp/quant-data",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["paper_review_id"], "prev_001")
        self.assertEqual(payload["evidence_gate_status"], "READY_FOR_REVIEW")
        self.assertTrue(payload["evidence_pack_path"].endswith("/psim_001/evidence_pack.json"))
        create_from_pack.assert_called_once_with("psim_001")

    def test_paper_review_create_accepts_candidate_or_manifest_preparation_path(self) -> None:
        class FakeReview:
            paper_review_id = "prev_prepare_001"
            status = "PENDING_HUMAN_REVIEW"
            evidence_pack_path = "/tmp/research/evidence_packs/pending_review_sman_001/evidence_pack.json"
            evidence_gate_status = "READY_FOR_REVIEW"
            proposed_symbols = ["SPY"]
            proposed_capital = 100000.0
            source_candidate_ids = ["cand_001"]
            created_at = "2026-05-11T00:00:00+00:00"

        with patch(
            "quant_us.research.paper_review_bridge.PaperReviewManager.create_from_candidate_evidence",
            return_value=FakeReview(),
        ) as create_from_candidate:
            response = self.client.post(
                "/api/research/paper-review/create",
                json={
                    "strategy_manifest_id": "sman_001",
                    "prepared_evidence_pack_id": "pending_review_sman_001",
                    "data_root": "/tmp/quant-data",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["paper_review_id"], "prev_prepare_001")
        self.assertEqual(payload["source_candidate_ids"], ["cand_001"])
        self.assertIn("never approves or submits paper orders", payload["note"])
        create_from_candidate.assert_called_once_with(
            candidate_id="",
            strategy_manifest_id="sman_001",
            portfolio_evidence_pack_id="pending_review_sman_001",
        )

    def test_paper_review_pending_uses_requested_data_root(self) -> None:
        class FakeReview:
            paper_review_id = "prev_pending_001"
            strategy_manifest_id = "sman_001"
            portfolio_sim_id = "psim_001"
            status = "PENDING_HUMAN_REVIEW"
            proposed_symbols = ["SPY"]
            proposed_capital = 100000.0
            created_at = "2026-05-11T00:00:00+00:00"

        with patch("quant_us.research.paper_review_bridge.PaperReviewManager") as manager_cls:
            manager = manager_cls.return_value
            manager.list_pending.return_value = [FakeReview()]
            response = self.client.get(
                "/api/research/paper-review/pending",
                params={"data_root": "/tmp/quant-data"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload[0]["paper_review_id"], "prev_pending_001")
        manager_cls.assert_called_once_with(data_root="/tmp/quant-data")
        manager.list_pending.assert_called_once_with()

    def test_factor_mine_and_run_endpoint_is_research_only(self) -> None:
        class FakeMiningResult:
            strategy_configs = [
                {
                    "strategy_id": "factor_rank",
                    "timeframe": "1d",
                    "bar_size": "1d",
                    "params": {"factor_name": "momentum_20d", "top_n": 1},
                }
            ]

            def to_dict(self) -> dict:
                return {
                    "run_id": "fmine_test",
                    "selected_factors": [{"factor_id": "momentum_20d"}],
                    "strategy_configs": list(self.strategy_configs),
                }

        with (
            patch(
                "quant_us.research.automation.factor_mining.FactorMiningEngine.mine",
                return_value=FakeMiningResult(),
            ) as mine,
            patch(
                "quant_us.research.automation.pipeline.ResearchAutomationPipeline.run",
                return_value={"status": "completed", "candidate_ids": ["cand_factor"]},
            ) as run_pipeline,
            patch(
                "quant_us.research.evidence_registry.rebuild_evidence_registry",
                return_value={"counts": {"candidate_count": 1}},
            ),
        ):
            response = self.client.post(
                "/api/research/factors/mine-and-run",
                json={
                    "symbols": ["AAPL", "MSFT"],
                    "start": "2024-01-01",
                    "end": "2024-02-01",
                    "bar_sizes": ["1d"],
                    "factor_ids": ["momentum_20d"],
                    "max_runs": 1,
                    "skip_registry_rebuild": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["candidate_ids"], ["cand_factor"])
        self.assertIn("no paper/live order path", payload["note"])
        mine.assert_called_once()
        run_pipeline.assert_called_once()

    def test_qlib_pypfopt_integration_endpoints_are_research_only(self) -> None:
        from tests.integrations.helpers import write_portfolio_config, write_qlib_run_inputs

        with TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = root / "artifacts"
            score_dates = pd.to_datetime(["2026-01-05", "2026-01-06"], utc=True)
            scores = pd.DataFrame(
                [
                    {"datetime": score_dates[0], "symbol": "AAPL", "score": 0.70, "model_id": "lgbm_alpha158", "feature_set": "Alpha158"},
                    {"datetime": score_dates[0], "symbol": "MSFT", "score": 0.55, "model_id": "lgbm_alpha158", "feature_set": "Alpha158"},
                    {"datetime": score_dates[1], "symbol": "AAPL", "score": 0.50, "model_id": "lgbm_alpha158", "feature_set": "Alpha158"},
                    {"datetime": score_dates[1], "symbol": "MSFT", "score": 0.82, "model_id": "lgbm_alpha158", "feature_set": "Alpha158"},
                ]
            )
            write_qlib_run_inputs(artifacts, "qlib_http", scores)
            qlib_root = artifacts / "qlib_runs"

            response = self.client.post(
                "/api/integrations/qlib/import-pred-score",
                json={"run_id": "qlib_http", "artifacts_root": str(qlib_root)},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["research_only"])
            self.assertFalse(payload["live_enabled"])
            self.assertEqual(payload["status"], "completed")

            config_path = root / "qlib.yaml"
            config_path.write_text(
                "model:\n  name: lgbm_alpha158\n  feature_set: Alpha158\n  strategy_version: qlib_lgbm_alpha158_us_daily_v1\n",
                encoding="utf-8",
            )
            response = self.client.post(
                "/api/integrations/qlib/compile-strategy-manifest",
                json={"run_id": "qlib_http", "artifacts_root": str(qlib_root), "config": str(config_path)},
            )
            self.assertEqual(response.status_code, 200)
            manifest_payload = response.json()["strategy_manifest"]
            self.assertEqual(manifest_payload["promotion_status"], "candidate")
            self.assertEqual(manifest_payload["execution_freq"], "deferred_to_system")

            portfolio_root = artifacts / "portfolio_runs" / "pf_http"
            portfolio_root.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(
                [
                    {
                        "portfolio_run_id": "pf_http",
                        "source_score_run_id": "qlib_http",
                        "datetime": "2026-01-06T00:00:00+00:00",
                        "symbol": "AAPL",
                        "target_weight": 0.15,
                        "raw_weight": 0.20,
                        "clipped_weight": 0.15,
                        "optimizer": "max_sharpe",
                        "constraints_hash": "abc123",
                        "fallback": "equal_weight_topk",
                        "created_at": "2026-05-11T00:00:00+00:00",
                    }
                ]
            ).to_parquet(portfolio_root / "target_weights.parquet", index=False)
            (portfolio_root / "run_manifest.json").write_text(
                '{"source_score_run_id": "qlib_http", "config": {"optimizer": "max_sharpe", "strategy_id": "pypfopt_daily_only"}}',
                encoding="utf-8",
            )
            portfolio_config = write_portfolio_config(
                root / "portfolio.yaml",
                score_runs_root=qlib_root,
                portfolio_runs_root=artifacts / "portfolio_runs",
                portfolio_run_id="pf_http",
            )
            response = self.client.post(
                "/api/integrations/portfolio/import-target-weights",
                json={"portfolio_run_id": "pf_http", "config": str(portfolio_config)},
            )
            self.assertEqual(response.status_code, 200)
            target_payload = response.json()
            self.assertEqual(target_payload["order_generation"], "disabled")
            self.assertTrue(target_payload["research_only"])
            self.assertNotIn("side", target_payload["preview"][0])
            self.assertNotIn("order_type", target_payload["preview"][0])

    def test_us_event_backtest_endpoint_uses_local_data_lake(self) -> None:
        with TemporaryDirectory() as directory:
            timestamp = datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc)
            price = 100.0
            rows = []
            while len(rows) < 80:
                if timestamp.weekday() < 5:
                    price *= 1.004
                    rows.append(
                        {
                            "timestamp": timestamp,
                            "symbol": "AAPL",
                            "open": price * 0.99,
                            "high": price * 1.01,
                            "low": price * 0.98,
                            "close": price,
                            "volume": 10_000_000,
                        }
                    )
                timestamp += timedelta(days=1)
            service = DataLakeService(DataLakeConfig(data_root=Path(directory)))
            cleaned = BarCleaner().clean(pd.DataFrame(rows), symbol="AAPL", source="unit").frame
            service.cleaned_store.write_bars(cleaned, vendor="yfinance", asset_class="equity", bar_size="1d", symbol="AAPL")
            msft_rows = [{**row, "symbol": "MSFT", "close": row["close"] * 1.01} for row in rows]
            cleaned_msft = BarCleaner().clean(pd.DataFrame(msft_rows), symbol="MSFT", source="unit").frame
            service.cleaned_store.write_bars(cleaned_msft, vendor="yfinance", asset_class="equity", bar_size="1d", symbol="MSFT")

            response = self.client.post(
                "/api/us/backtests/event",
                json={
                    "symbol": "AAPL",
                    "symbols": ["AAPL", "MSFT"],
                    "bar_size": "1d",
                    "strategy_params": {"lookback_bars": 5, "entry_threshold": 0.01},
                    "default_strategy_weight": 0.12,
                    "cash_reserve_weight": 0.10,
                    "min_trade_notional": 50.0,
                    "min_weight_change": 0.001,
                    "start": "2024-01-01T00:00:00Z",
                    "end": "2024-06-30T00:00:00Z",
                    "data_root": directory,
                    "auto_sync": False,
                    "corporate_actions": [
                        {"symbol": "AAPL", "action_type": "split", "ex_date": "2024-03-01", "ratio": 2.0}
                    ],
                    "earnings_events": [
                        {"symbol": "AAPL", "event_date": "2024-04-01", "source": "unit"}
                    ],
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertGreater(payload["fill_count"], 0)
        self.assertEqual(payload["diagnostics"]["symbols"], ["AAPL", "MSFT"])
        self.assertEqual(payload["diagnostics"]["strategy_params"]["lookback_bars"], 5)
        self.assertEqual(payload["diagnostics"]["backtest_parameters"]["cash_reserve_weight"], 0.10)
        self.assertEqual(payload["diagnostics"]["data_filters"]["corporate_action_count"], 1)
        self.assertGreater(payload["diagnostics"]["data_filters"]["earnings_blackout_removed_rows"], 0)

    def test_us_reconcile_endpoint_checks_local_ledger(self) -> None:
        with TemporaryDirectory() as directory:
            ledger = JsonlLedgerStore(directory)
            ledger.append_fill(
                Fill(
                    order_id="order_1",
                    symbol="AAPL",
                    side=OrderSide.BUY,
                    quantity=1.0,
                    price=100.0,
                    commission=0.0,
                    filled_at=datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc),
                )
            )
            response = self.client.post(
                "/api/us/reconcile",
                json={"ledger_dir": directory},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "clean")
        self.assertEqual(payload["break_count"], 0)


if __name__ == "__main__":
    unittest.main()
