from __future__ import annotations

import json
from pathlib import Path

from scripts.build_btc_cost_model_report import build_btc_cost_model_report


def test_mark_premium_and_exchange_rules_are_required_for_candidate_gate() -> None:
    payload = build_btc_cost_model_report(generated_at="2026-05-19T00:00:00Z")
    mark = payload["mark_price_model"]
    rules = payload["exchange_rules"]

    assert mark["mark_price_klines_available"] is True
    assert mark["premium_index_klines_available"] is True
    assert mark["mark_price_alignment_pass"] is True
    assert rules["exchange_rules_available"] is True
    assert rules["tick_size"] == 0.1
    assert rules["step_size"] == 0.01
    assert rules["min_notional"] > 0
    assert "btc_exchange_info_missing" not in payload["blockers"]
    assert payload["candidate_pass_allowed"] is False


def test_future_mark_and_premium_rows_cannot_be_used_as_current_data(tmp_path: Path) -> None:
    _write_mark_fixture(tmp_path, available_time="2026-07-01T01:00:00Z")

    payload = build_btc_cost_model_report(repo_root=tmp_path, generated_at="2026-07-01T00:30:00Z")
    mark = payload["mark_price_model"]

    assert mark["mark_price_current_available"] is False
    assert mark["last_price_vs_mark_price_diagnostic_available"] is False
    assert payload["candidate_pass_allowed"] is False


def test_recent_completed_mark_and_premium_rows_can_supply_current_data(tmp_path: Path) -> None:
    _write_mark_fixture(tmp_path, available_time="2026-07-01T01:00:00Z")

    payload = build_btc_cost_model_report(repo_root=tmp_path, generated_at="2026-07-01T03:33:00+00:00")
    mark = payload["mark_price_model"]

    assert mark["mark_price_current_available"] is True
    assert mark["mark_price_used_for_liquidation_risk"] is True
    assert mark["last_price_vs_mark_price_diagnostic_available"] is True
    assert mark["current_mark_price"] > 0
    assert mark["current_index_price"] > 0
    assert mark["current_mark_price_age_hours"] <= 6.0
    assert mark["current_mark_price_source"].endswith("mark_price_klines_1h.csv")
    assert mark["liquidation_risk_contract_complete"] is True
    assert payload["candidate_pass_allowed"] is False


def _write_mark_fixture(root: Path, *, available_time: str) -> None:
    _write_text(
        root / "configs/data/btc_perpetual_sources.yaml",
        "\n".join(
            [
                "providers:",
                "  okx_swap:",
                "    enabled: true",
                "    root: data/external/btc_perpetual/okx_swap/",
                "    selected_bundle_id: mark_fixture",
                "selected_provider: okx_swap",
            ]
        ),
    )
    bundle = root / "data/external/btc_perpetual/okx_swap/bundles/mark_fixture"
    _write_text(
        bundle / "mark_price_klines_1h.csv",
        "\n".join(
            [
                "timestamp,event_time,available_time,ingested_at,processed_at,open_time,symbol,open,high,low,close,confirm,source_record_id",
                f"2026-07-01T00:00:00Z,2026-07-01T00:00:00Z,{available_time},{available_time},{available_time},1782864000000,BTCUSDT,58602.6,58724.2,58282.5,58551.2,1,fixture",
            ]
        ),
    )
    _write_text(
        bundle / "premium_index_klines_1h.csv",
        "\n".join(
            [
                "timestamp,event_time,available_time,ingested_at,processed_at,open_time,symbol,mark_close,index_close,premium,premium_rate,confirm,source_record_id",
                f"2026-07-01T00:00:00Z,2026-07-01T00:00:00Z,{available_time},{available_time},{available_time},1782864000000,BTCUSDT,58551.2,58576.7,-25.5,-0.000435326674258,1,fixture",
            ]
        ),
    )
    _write_json(
        root / "artifacts/btc_completion_evidence/latest/liquidation_risk_contract.json",
        {
            "status": "complete",
            "decision": "liquidation_risk_contract_complete",
            "mark_index_current_mark_required": True,
            "blockers": [],
            "decision_metadata": {
                "reference_prices": {
                    "mark_price": 58551.2,
                    "current_mark_price": 58551.2,
                    "index_price": 58576.7,
                }
            },
        },
    )


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
