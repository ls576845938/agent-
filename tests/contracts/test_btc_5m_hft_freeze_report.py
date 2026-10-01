from __future__ import annotations

import json
from pathlib import Path

from scripts.build_btc_5m_hft_freeze_report import build_btc_5m_hft_freeze_report


def test_btc_5m_hft_freeze_report_locks_rejected_strategy(tmp_path: Path) -> None:
    evaluation_90d = tmp_path / "eval_90d.json"
    evaluation_90d.write_text(
        json.dumps(
            {
                "status": "pass_with_strategy_rejected_as_high_frequency",
                "generated_at": "2026-06-23T00:00:00Z",
                "metrics": {
                    "system_passed": True,
                    "days_completed": 90,
                    "trade_days": 4,
                    "total_fills": 8,
                    "total_orders": 8,
                    "total_rejected": 0,
                    "total_signals": 43,
                    "no_trade_days": 86,
                    "max_consecutive_no_trade_days": 53,
                    "total_return_pct": -0.345612,
                    "max_drawdown_pct": 0.571744,
                },
                "high_frequency_fit": {
                    "status": "FAIL",
                    "entry_segments": 4,
                    "entry_segments_per_day": 0.044444,
                    "trade_day_ratio": 0.044444,
                    "reason": "Observed entry frequency is orders of magnitude below a high-frequency strategy.",
                },
                "conclusion": {
                    "high_frequency_fit": "FAIL_AS_HIGH_FREQUENCY: 90 days produced only 4 entry segments.",
                    "profitability": "NEGATIVE_EDGE_IN_SAMPLE",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = build_btc_5m_hft_freeze_report(
        repo_root=tmp_path,
        evaluation_30d=tmp_path / "missing_30d.json",
        evaluation_90d=evaluation_90d,
        output=tmp_path / "freeze.json",
        markdown_output=tmp_path / "freeze.md",
        generated_at="2026-06-23T01:00:00Z",
    )

    assert payload["status"] == "frozen_rejected_as_high_frequency"
    assert payload["decision"] == "freeze_strategy_no_more_parameter_tuning"
    assert payload["evidence"]["days_completed"] == 90
    assert payload["evidence"]["entry_segments"] == 4
    assert payload["evidence"]["total_rejected"] == 0
    assert payload["guardrails"]["parameter_tuning_allowed"] is False
    assert payload["guardrails"]["reuse_as_hft_candidate_allowed"] is False
    assert payload["guardrails"]["paper_or_live_unlock_allowed"] is False
    assert payload["guardrails"]["resume_180d_5m_pull_allowed"] is False
    assert payload["guardrails"]["private_endpoint_used"] is False
    assert payload["guardrails"]["order_endpoint_used"] is False

    markdown = (tmp_path / "freeze.md").read_text(encoding="utf-8")
    assert "不再作为高频策略调参" in markdown
    assert "90 天只有 4 个入场段" in markdown
