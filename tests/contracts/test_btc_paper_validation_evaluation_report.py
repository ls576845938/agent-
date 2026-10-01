from __future__ import annotations

from pathlib import Path

from scripts.build_btc_paper_validation_evaluation_report import build_btc_paper_validation_evaluation_report
from scripts.run_btc_daily_paper_roll import _daily_roll_blockers


def test_btc_paper_validation_evaluation_rejects_current_strategy_as_hft(tmp_path: Path) -> None:
    payload = build_btc_paper_validation_evaluation_report(
        generated_at="2026-06-23T00:00:00Z",
        output=tmp_path / "btc_paper_validation_evaluation_report.json",
        markdown_output=tmp_path / "btc_paper_validation_evaluation_report.md",
    )

    assert payload["status"] == "pass_with_strategy_rejected_as_high_frequency"
    assert payload["metrics"]["system_passed"] is True
    assert payload["metrics"]["days_completed"] == 30
    assert payload["metrics"]["total_fills"] == 4
    assert payload["high_frequency_fit"]["status"] == "FAIL"
    assert payload["high_frequency_fit"]["entry_segments"] == 2
    assert payload["high_frequency_fit"]["entry_segments_per_day"] < 0.1
    assert "FAIL_AS_HIGH_FREQUENCY" in payload["conclusion"]["high_frequency_fit"]

    markdown = (tmp_path / "btc_paper_validation_evaluation_report.md").read_text(encoding="utf-8")
    assert "当前策略作为高频策略不通过" in markdown
    assert "实际表现是低频事件过滤器" in markdown


def test_btc_daily_paper_roll_blocks_network_refresh_exception() -> None:
    blockers = _daily_roll_blockers(
        data_refresh={
            "status": "rejected",
            "network_called": True,
            "public_rest_only": True,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "blockers": ["btc_daily_paper_data_refresh_exception"],
        },
        data_quality={"blockers": []},
        validation_status="not_run",
        validation_result={},
        monitoring={},
        skip_data_refresh=False,
        execute_network=True,
    )

    assert blockers == [
        "btc_daily_paper_data_refresh_not_verified",
        "btc_daily_paper_data_refresh_exception",
    ]
