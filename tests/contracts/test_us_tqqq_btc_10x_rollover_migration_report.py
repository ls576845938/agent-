from __future__ import annotations

import json
from pathlib import Path


REPORT_PATH = Path(
    "artifacts/us_tqqq_btc_10x_rollover_migration/latest/us_tqqq_btc_10x_rollover_migration_report.json"
)


def _payload() -> dict:
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def test_tqqq_migration_report_is_research_only_danger_reference() -> None:
    payload = _payload()

    assert payload["schema_version"] == "us_tqqq_btc_10x_rollover_migration_report_v1"
    assert payload["status"] == "complete_research_only"
    assert payload["decision"] == "tqqq_btc_10x_rollover_migration_danger_reference_research_only_no_paper_no_live"
    assert payload["gate"]["paper_queue_write_allowed"] is False
    assert payload["gate"]["paper_candidate_created"] is False
    assert payload["gate"]["forward_observation_allowed"] is False
    assert payload["gate"]["live_order_allowed"] is False
    assert payload["guardrails"]["broker_endpoint_used"] is False
    assert payload["guardrails"]["order_endpoint_used"] is False
    assert payload["guardrails"]["paper_or_live_unlock_allowed"] is False


def test_tqqq_migration_uses_tqqq_and_qqq_4h_intraday_data_when_available() -> None:
    payload = _payload()

    assert payload["data"]["traded_symbol"] == "TQQQ"
    assert payload["data"]["signal_symbol"] == "QQQ"
    assert payload["data"]["tqqq_rows"] >= 900
    assert payload["data"]["qqq_rows"] >= 900
    assert payload["data"]["tqqq_source"]["status"] == "available"
    assert payload["data"]["tqqq_source"]["source"] == "yahoo_chart_intraday_1h_derived_4h"
    assert payload["data"]["qqq_source"]["source"] == "yahoo_chart_intraday_1h_derived_4h"
    assert payload["data"]["bar_timeframe"] == "4H derived from Yahoo 1H research fallback"
    assert payload["data"]["periods_per_year"] == 504
    assert payload["data"]["pre_2010_tqqq_unavailable_no_2008_test"] is True
    assert payload["signal_rule"]["execution_time_rule"].startswith("TQQQ target exposure is effective")
    assert payload["signal_rule"]["bar_timeframe"] == "4H derived from Yahoo 1H research fallback"
    assert "prior completed session" in payload["signal_rule"]["decision_time_rule"]
    assert "shifted one session" in payload["signal_rule"]["trend_visibility_rule"]


def test_tqqq_migration_uses_formal_donchian_direction_grid_not_fixed_rule() -> None:
    payload = _payload()
    grid = payload["signal_rule"]["formal_grid"]
    selected = payload["signal_rule"]["selected_direction"]

    assert grid["candidate_count"] == 54
    assert grid["expected_candidate_count"] == 54
    assert payload["experiment_design"]["direction_candidate_count"] == 54
    assert grid["donchian_entry_windows"] == [120, 180, 240]
    assert grid["daily_trends"] == [{"ema_fast": 50, "ema_slow": 200}]
    assert selected["candidate_id"].startswith("formal_donchian_")
    assert selected["selected_by"] == "cost_adjusted_tqqq_1x_direction_score"
    assert selected["periods_per_year"] == 504
    assert len(selected["top5"]) == 5


def test_tqqq_migration_preserves_btc_ceiling_as_reference_only() -> None:
    payload = _payload()
    ceiling = payload["btc_danger_ceiling_reference"]

    assert ceiling["status"] == "complete_research_only"
    assert ceiling["decision"] == "path_dependent_not_forward_observation_ready"
    assert ceiling["no_rollover_total_return_pct"] == ceiling["split_2_total_return_pct"]
    assert ceiling["split_incremental_pct_of_no_rollover_equity"] == 0.0
    assert ceiling["paper_queue_write_allowed"] is False
    assert ceiling["live_unlock_allowed"] is False


def test_tqqq_migration_shows_margin_and_path_dependency_failures() -> None:
    payload = _payload()

    assert payload["experiment_design"]["candidate_count"] == 28
    assert "tqqq_path_dependent" in payload["warnings"]
    assert payload["analysis"]["path_dependency"]["status"] == "path_dependent"
    assert payload["analysis"]["source_attribution"]["main_driver"] == (
        "tqqq_trend_beta_and_margin_compounding_not_split_2_rollover"
    )
    assert payload["analysis"]["source_attribution"]["three_x_tqqq_margin_total_return_pct"] > 0.0
    assert payload["analysis"]["source_attribution"]["split_2_total_return_pct"] == (
        payload["analysis"]["source_attribution"]["three_x_tqqq_margin_total_return_pct"]
    )
    assert payload["analysis"]["source_attribution"]["split_incremental_final_equity_vs_no_rollover"] == 0.0


def test_tqqq_migration_cost_stress_and_ledger_outputs_exist() -> None:
    payload = _payload()

    cost = payload["analysis"]["cost_stress"]["1x_no_rollover"]
    assert {row["cost_bps"] for row in cost} == {0.0, 5.0, 10.0, 25.0, 50.0}
    for output_key in ("json", "grid_csv", "direction_grid_csv", "ledger_csv", "events_csv", "summary_cn"):
        path = Path(payload["outputs"][output_key])
        assert path.exists()
