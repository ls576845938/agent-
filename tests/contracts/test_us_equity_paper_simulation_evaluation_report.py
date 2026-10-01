from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import jsonschema
import pytest

from quant_us.live.paper_simulation_evaluation import (
    build_us_equity_paper_simulation_evaluation_report,
)
from scripts.run_us_equity_paper_simulation_roll import run_us_equity_paper_simulation_roll


SCHEMA = Path("schemas/us_equity_paper_simulation_evaluation_report.schema.json")


def test_paper_simulation_evaluation_reports_not_started_without_ledger(tmp_path: Path) -> None:
    _write_roll_report(
        tmp_path,
        status="BLOCKED",
        cycle_status="NOT_RUN",
        blockers=["us_equity_paper_simulation_readiness_not_ready"],
    )

    payload = build_us_equity_paper_simulation_evaluation_report(
        repo_root=tmp_path,
        output=Path("out/eval.json"),
        markdown_output=Path("out/eval.md"),
        generated_at="2026-06-28T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "paper_simulation_not_started"
    assert "us_equity_paper_simulation_ledger_not_started" not in payload["blockers"]
    assert "us_equity_paper_simulation_ledger_root_missing" not in payload["blockers"]
    assert "us_equity_paper_simulation_roll_blocked" in payload["blockers"]
    assert "us_equity_paper_simulation_readiness_not_ready" in payload["blockers"]
    assert "us_equity_paper_simulation_missing_ledger_file:target_positions" not in payload["blockers"]
    assert "us_equity_paper_simulation_no_portfolio_snapshots" not in payload["blockers"]
    assert payload["prestart_evidence"]["ledger_started"] is False
    assert payload["prestart_evidence"]["roll_report_status"] == "BLOCKED"
    assert payload["prestart_evidence"]["roll_ledger_materialization_status"] == "blocked_before_ledger_write"
    assert payload["prestart_evidence"]["roll_ledger_writes_performed"] is False
    assert payload["prestart_evidence"]["roll_ledger_rows_written_this_cycle"] == {
        "target_positions": 0,
        "fills": 0,
        "positions": 0,
        "cash_ledger": 0,
        "portfolio_snapshots": 0,
        "validation_state": 0,
        "daily_reports": 0,
    }
    assert payload["prestart_evidence"]["blocked_by_roll_report"] is True
    assert payload["prestart_evidence"]["ledger_write_expected"] is False
    assert payload["prestart_evidence"]["manual_start_approved"] is False
    assert payload["prestart_evidence"]["missing_ledger_files"] == [
        "target_positions",
        "fills",
        "positions",
        "cash_ledger",
        "portfolio_snapshots",
        "validation_state",
        "daily_reports",
    ]
    assert payload["prestart_evidence"]["ledger_file_statuses"]["target_positions"]["exists"] is False
    assert payload["ledger_checks"]["ledger_completeness"]["passed"] is False
    assert payload["ledger_checks"]["ledger_completeness"]["status"] == "blocked_before_write"
    assert payload["ledger_checks"]["ledger_completeness"]["missing_files"] == [
        "target_positions",
        "fills",
        "positions",
        "cash_ledger",
        "portfolio_snapshots",
        "validation_state",
        "daily_reports",
    ]
    assert payload["ledger_checks"]["ledger_completeness"]["blockers"] == []
    assert payload["metrics"]["paper_days"] == 0
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["live_ready_claim_allowed"] is False
    assert (tmp_path / "out/eval.md").exists()


def test_paper_simulation_evaluation_still_blocks_missing_roll_and_ledger(tmp_path: Path) -> None:
    payload = build_us_equity_paper_simulation_evaluation_report(
        repo_root=tmp_path,
        output=Path("out/eval.json"),
        markdown_output=Path("out/eval.md"),
        generated_at="2026-06-28T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "paper_simulation_not_started"
    assert "us_equity_paper_simulation_roll_report_missing_or_invalid" in payload["blockers"]
    assert "us_equity_paper_simulation_ledger_root_missing" in payload["blockers"]
    assert "us_equity_paper_simulation_missing_ledger_file:target_positions" in payload["blockers"]
    assert "us_equity_paper_simulation_completeness_missing_ledger_file:target_positions" in payload["blockers"]
    assert payload["ledger_checks"]["ledger_completeness"]["status"] == "not_started"
    assert payload["ledger_checks"]["ledger_completeness"]["ledger_write_expected"] is True
    assert payload["prestart_evidence"]["blocked_by_roll_report"] is False
    assert payload["prestart_evidence"]["ledger_write_expected"] is True


def test_paper_simulation_evaluation_observing_with_clean_ledger(tmp_path: Path) -> None:
    _write_roll_report(tmp_path, status="PASS", cycle_status="COMPLETED")
    _write_clean_ledger(tmp_path, days=2)

    payload = build_us_equity_paper_simulation_evaluation_report(
        repo_root=tmp_path,
        output=Path("out/eval.json"),
        markdown_output=Path("out/eval.md"),
        generated_at="2026-06-28T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "paper_simulation_observing"
    assert payload["blockers"] == []
    assert payload["metrics"]["paper_days"] == 2
    assert payload["metrics"]["target_position_count"] == 2
    assert payload["metrics"]["fill_count"] == 2
    assert payload["metrics"]["position_ledger_count"] == 2
    assert payload["metrics"]["cash_ledger_count"] == 2
    assert payload["ledger_checks"]["snapshot_reconciliation"]["passed"] is True
    assert payload["ledger_checks"]["ledger_completeness"]["passed"] is True
    assert payload["ledger_checks"]["ledger_completeness"]["status"] == "complete"
    assert payload["ledger_checks"]["ledger_completeness"]["row_counts"] == {
        "target_positions": 2,
        "fills": 2,
        "positions": 2,
        "cash_ledger": 2,
        "portfolio_snapshots": 2,
        "validation_state": 1,
        "daily_reports": 2,
    }
    assert payload["ledger_checks"]["target_fill_consistency"]["passed"] is True
    assert payload["ledger_checks"]["trade_reconciliation"]["passed"] is True
    assert payload["ledger_checks"]["position_cash_consistency"]["passed"] is True
    replay = payload["ledger_checks"]["ledger_pnl_replay"]
    assert replay["status"] == "passed"
    assert replay["canonical_replay_module"] == "quant_us.backtest.ledger_pnl"
    assert replay["source"] == "fills_positions_cash_ledger"
    assert replay["blockers"] == []
    assert replay["latest_equity"] == pytest.approx(payload["metrics"]["latest_equity"], abs=0.01)
    assert payload["prestart_evidence"]["ledger_started"] is True
    assert payload["prestart_evidence"]["roll_ledger_materialization_status"] == "ledger_rows_written"
    assert payload["prestart_evidence"]["roll_ledger_writes_performed"] is True
    assert payload["prestart_evidence"]["missing_ledger_files"] == []
    assert payload["latest_state"]["last_processed_timestamp"] == "2026-05-02"


def test_paper_simulation_evaluation_complete_after_30_days(tmp_path: Path) -> None:
    _write_roll_report(tmp_path, status="PASS", cycle_status="COMPLETED")
    _write_clean_ledger(tmp_path, days=30)

    payload = build_us_equity_paper_simulation_evaluation_report(
        repo_root=tmp_path,
        output=Path("out/eval.json"),
        markdown_output=Path("out/eval.md"),
        generated_at="2026-06-28T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "paper_simulation_complete_for_manual_review"
    assert payload["guardrails"]["paper_simulation_allowed"] is False
    assert payload["guardrails"]["real_order_submitted"] is False


def test_paper_simulation_evaluation_blocks_snapshot_reconciliation_mismatch(tmp_path: Path) -> None:
    _write_roll_report(tmp_path, status="PASS", cycle_status="COMPLETED")
    _write_clean_ledger(tmp_path, days=1, equity_offset=5.0)

    payload = build_us_equity_paper_simulation_evaluation_report(
        repo_root=tmp_path,
        output=Path("out/eval.json"),
        markdown_output=Path("out/eval.md"),
        generated_at="2026-06-28T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "paper_simulation_blocked"
    assert any(item.startswith("us_equity_paper_simulation_snapshot_reconciliation_failed") for item in payload["blockers"])
    assert "us_equity_paper_simulation_paper_ledger_pnl_snapshot_reconciliation_failed" in payload["blockers"]
    assert payload["ledger_checks"]["snapshot_reconciliation"]["passed"] is False


def test_paper_simulation_evaluation_blocks_position_not_reproducible_from_fills(tmp_path: Path) -> None:
    _write_roll_report(tmp_path, status="PASS", cycle_status="COMPLETED")
    _write_clean_ledger(tmp_path, days=1)
    ledger = tmp_path / "data/paper_ledger/us_equity_etf_rotation_v1"
    positions = _read_jsonl(ledger / "positions.jsonl")
    positions[-1]["positions"]["SPY"]["quantity"] = float(positions[-1]["positions"]["SPY"]["quantity"]) + 1.0
    _write_jsonl_rows(ledger / "positions.jsonl", positions)

    payload = build_us_equity_paper_simulation_evaluation_report(
        repo_root=tmp_path,
        output=Path("out/eval.json"),
        markdown_output=Path("out/eval.md"),
        generated_at="2026-06-28T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "paper_simulation_blocked"
    assert "us_equity_paper_simulation_paper_ledger_pnl_position_quantity_mismatch" in payload["blockers"]
    assert payload["ledger_checks"]["ledger_pnl_replay"]["status"] == "blocked"


def test_paper_simulation_evaluation_blocks_missing_snapshot_for_target(tmp_path: Path) -> None:
    _write_roll_report(tmp_path, status="PASS", cycle_status="COMPLETED")
    _write_clean_ledger(tmp_path, days=1)
    ledger = tmp_path / "data/paper_ledger/us_equity_etf_rotation_v1"
    _append_jsonl(
        ledger / "target_positions.jsonl",
        {"timestamp": "2026-06-28", "target_position": {"date": "2026-06-28", "weights": {"SPY": 1.0}}},
    )

    payload = build_us_equity_paper_simulation_evaluation_report(
        repo_root=tmp_path,
        output=Path("out/eval.json"),
        markdown_output=Path("out/eval.md"),
        generated_at="2026-06-28T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "paper_simulation_blocked"
    assert "us_equity_paper_simulation_missing_snapshot_for_target" in payload["blockers"]
    assert payload["ledger_checks"]["target_fill_consistency"]["passed"] is False


def test_paper_simulation_evaluation_blocks_trade_notional_mismatch_and_broker_ids(tmp_path: Path) -> None:
    _write_roll_report(tmp_path, status="PASS", cycle_status="COMPLETED")
    _write_clean_ledger(tmp_path, days=1)
    ledger = tmp_path / "data/paper_ledger/us_equity_etf_rotation_v1"
    (ledger / "fills.jsonl").write_text(
        json.dumps(
            {
                "timestamp": "2026-05-01",
                "symbol": "SPY",
                "notional": 500.0,
                "simulated_only": False,
                "broker_order_id": "BROKER-1",
                "exchange_order_id": "EXCHANGE-1",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    payload = build_us_equity_paper_simulation_evaluation_report(
        repo_root=tmp_path,
        output=Path("out/eval.json"),
        markdown_output=Path("out/eval.md"),
        generated_at="2026-06-28T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "paper_simulation_blocked"
    assert "us_equity_paper_simulation_trade_notional_mismatch:2026-05-01" in payload["blockers"]
    assert "us_equity_paper_simulation_fill_not_simulated_only:2026-05-01" in payload["blockers"]
    assert "us_equity_paper_simulation_fill_contains_broker_order_id:2026-05-01" in payload["blockers"]
    assert "us_equity_paper_simulation_fill_contains_exchange_order_id:2026-05-01" in payload["blockers"]
    assert payload["ledger_checks"]["trade_reconciliation"]["passed"] is False


def test_paper_simulation_evaluation_blocks_missing_position_or_cash_ledger(tmp_path: Path) -> None:
    _write_roll_report(tmp_path, status="PASS", cycle_status="COMPLETED")
    _write_clean_ledger(tmp_path, days=1)
    ledger = tmp_path / "data/paper_ledger/us_equity_etf_rotation_v1"
    (ledger / "positions.jsonl").unlink()
    (ledger / "cash_ledger.jsonl").unlink()

    payload = build_us_equity_paper_simulation_evaluation_report(
        repo_root=tmp_path,
        output=Path("out/eval.json"),
        markdown_output=Path("out/eval.md"),
        generated_at="2026-06-28T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "paper_simulation_blocked"
    assert "us_equity_paper_simulation_missing_position_ledger_for_target" in payload["blockers"]
    assert "us_equity_paper_simulation_missing_cash_ledger_for_target" in payload["blockers"]
    assert "us_equity_paper_simulation_completeness_missing_ledger_file:positions" in payload["blockers"]
    assert "us_equity_paper_simulation_completeness_missing_ledger_file:cash_ledger" in payload["blockers"]
    assert payload["ledger_checks"]["ledger_completeness"]["status"] == "incomplete"
    assert payload["ledger_checks"]["ledger_completeness"]["passed"] is False
    assert payload["ledger_checks"]["position_cash_consistency"]["passed"] is False


def test_paper_simulation_evaluation_blocks_missing_daily_report(tmp_path: Path) -> None:
    _write_roll_report(tmp_path, status="PASS", cycle_status="COMPLETED")
    _write_clean_ledger(tmp_path, days=1)
    ledger = tmp_path / "data/paper_ledger/us_equity_etf_rotation_v1"
    (ledger / "daily_reports/2026-05-01.json").unlink()

    payload = build_us_equity_paper_simulation_evaluation_report(
        repo_root=tmp_path,
        output=Path("out/eval.json"),
        markdown_output=Path("out/eval.md"),
        generated_at="2026-06-28T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "paper_simulation_blocked"
    assert "us_equity_paper_simulation_completeness_row_count_mismatch:daily_reports" in payload["blockers"]
    assert payload["ledger_checks"]["ledger_completeness"]["passed"] is False


def test_paper_simulation_evaluation_schema_rejects_live_ready_claim(tmp_path: Path) -> None:
    _write_roll_report(tmp_path, status="BLOCKED", cycle_status="NOT_RUN")
    payload = build_us_equity_paper_simulation_evaluation_report(
        repo_root=tmp_path,
        output=Path("out/eval.json"),
        markdown_output=Path("out/eval.md"),
        generated_at="2026-06-28T00:00:00Z",
    )
    payload["guardrails"]["live_ready_claim_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_ready_claim_allowed=true")


def test_paper_simulation_evaluation_schema_requires_ledger_completeness(tmp_path: Path) -> None:
    _write_roll_report(tmp_path, status="PASS", cycle_status="COMPLETED")
    _write_clean_ledger(tmp_path, days=1)
    payload = build_us_equity_paper_simulation_evaluation_report(
        repo_root=tmp_path,
        output=Path("out/eval.json"),
        markdown_output=Path("out/eval.md"),
        generated_at="2026-06-28T00:00:00Z",
    )
    del payload["ledger_checks"]["ledger_completeness"]

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted missing ledger_completeness check")


def _write_roll_report(root: Path, *, status: str, cycle_status: str, blockers: list[str] | None = None) -> None:
    writes_performed = status == "PASS" and cycle_status == "COMPLETED"
    rows_written = {
        "target_positions": 1 if writes_performed else 0,
        "fills": 1 if writes_performed else 0,
        "positions": 1 if writes_performed else 0,
        "cash_ledger": 1 if writes_performed else 0,
        "portfolio_snapshots": 1 if writes_performed else 0,
        "validation_state": 1 if writes_performed else 0,
        "daily_reports": 1 if writes_performed else 0,
    }
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_roll_report.json",
        {
            "status": status,
            "cycle_status": cycle_status,
            "blockers": blockers or [],
            "ledger_materialization": {
                "status": "ledger_rows_written" if writes_performed else "blocked_before_ledger_write",
                "writes_performed": writes_performed,
                "rows_written_this_cycle": rows_written,
                "operator_next_action": "run paper simulation evaluation" if writes_performed else "resolve paper readiness blockers",
            },
            "guardrails": {
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
                "private_endpoint_allowed": False,
                "order_endpoint_allowed": False,
                "real_order_submitted": False,
                "broker_calls_used": False,
            },
        },
    )


def _write_clean_ledger(root: Path, *, days: int, equity_offset: float = 0.0) -> None:
    readiness = root / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_readiness_report.json"
    _write_json(
        readiness,
        {
            "status": "paper_simulation_ready_for_manual_start",
            "decision": "manual_start_required",
            "required_runner_contract": {
                "independent_ledger_root": "data/paper_ledger/us_equity_etf_rotation_v1",
                "must_not_reuse_forward_observation_ledger": True,
            },
            "guardrails": {
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
                "private_endpoint_allowed": False,
                "order_endpoint_allowed": False,
                "real_order_submitted": False,
            },
        },
    )
    start = date(2026, 5, 1)
    for index in range(days):
        day = (start + timedelta(days=index)).isoformat()
        spy_price = 500.0 + index
        forward = root / "data/forward_observation/us_etf_rotation_v1/target_positions.jsonl"
        _write_jsonl(
            forward,
            {
                "timestamp": day,
                "target_position": {
                    "date": day,
                    "weights": {"SPY": 1.0},
                    "prices": {"SPY": spy_price},
                    "gross_exposure": 1.0,
                    "net_exposure": 1.0,
                    "target_count": 1,
                },
            },
        )
        payload = run_us_equity_paper_simulation_roll(
            repo_root=root,
            generated_at=f"{day}T23:00:00Z",
            manual_start_approved=True,
        )
        assert payload["status"] == "PASS"
    if equity_offset:
        ledger = root / "data/paper_ledger/us_equity_etf_rotation_v1"
        snapshots = _read_jsonl(ledger / "portfolio_snapshots.jsonl")
        snapshots[-1]["equity"] = float(snapshots[-1]["equity"]) + equity_offset
        _write_jsonl_rows(ledger / "portfolio_snapshots.jsonl", snapshots)


def _append_jsonl(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True))
        handle.write("\n")


def _write_jsonl(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        raise AssertionError(f"schema validation failed: {exc.message}") from exc
