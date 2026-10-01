from __future__ import annotations

from pathlib import Path

from quant_crypto.data.pit_contract import evaluate_pit_contract, filter_rows_available_at


def test_filter_rows_available_at_excludes_future_visible_rows() -> None:
    rows = [
        {
            "event_time": "2026-01-01T00:00:00Z",
            "available_time": "2026-01-01T00:00:05Z",
            "ingested_at": "2026-01-01T00:00:06Z",
            "processed_at": "2026-01-01T00:00:07Z",
            "value": 1,
        },
        {
            "event_time": "2026-01-01T00:01:00Z",
            "available_time": "2026-01-01T00:01:05Z",
            "ingested_at": "2026-01-01T00:01:06Z",
            "processed_at": "2026-01-01T00:01:07Z",
            "value": 2,
        },
    ]

    visible = filter_rows_available_at(rows, decision_time="2026-01-01T00:01:00Z")

    assert [row["value"] for row in visible] == [1]


def test_evaluate_pit_contract_requires_all_four_times_for_btc_gate_data(tmp_path: Path) -> None:
    path = tmp_path / "funding_rate.csv"
    path.write_text("event_time,available_time,value\n2026-01-01T00:00:00Z,2026-01-01T00:00:01Z,1\n", encoding="utf-8")

    status = evaluate_pit_contract(path, role="funding_rate")

    assert status["required"] is True
    assert status["present"] is False
    assert status["missing_fields"] == ["ingested_at", "processed_at"]
    assert status["blockers"] == ["btc_pit_contract_required_fields_missing"]


def test_evaluate_pit_contract_detects_available_time_before_event_time(tmp_path: Path) -> None:
    path = tmp_path / "klines_1m.csv"
    path.write_text(
        "\n".join(
            [
                "event_time,available_time,ingested_at,processed_at,value",
                "2026-01-01T00:01:00Z,2026-01-01T00:00:59Z,2026-01-01T00:01:01Z,2026-01-01T00:01:02Z,1",
            ]
        ),
        encoding="utf-8",
    )

    status = evaluate_pit_contract(path, role="klines_1m")

    assert status["present"] is True
    assert status["available_time_order_violation_count"] == 1
    assert status["blockers"] == ["btc_pit_contract_available_time_before_event_time_violation"]
