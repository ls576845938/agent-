from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

import quant_us.live.paper_simulation_runner as paper_runner_service
from quant_us.live.paper_ledger_uow import PaperLedgerCommitError
from quant_us.live.paper_simulation_roll import (
    build_fills,
    build_rebalance,
    build_reconciliation,
    build_snapshot,
    paper_roll_guardrails,
)
from scripts.run_us_equity_paper_simulation_roll import run_us_equity_paper_simulation_roll


SCHEMA = Path("schemas/us_equity_paper_simulation_roll_report.schema.json")


def test_paper_simulation_runner_use_case_lives_in_live_service() -> None:
    assert run_us_equity_paper_simulation_roll.__module__ == "quant_us.live.paper_simulation_runner"


def test_paper_simulation_service_builds_ledger_rows_without_broker_or_filesystem() -> None:
    target = {
        "date": "2026-06-26",
        "gross_exposure": 1.0,
        "net_exposure": 1.0,
        "weights": {"SPY": 0.6, "SHV": 0.4},
        "prices": {"SPY": 500.0, "SHV": 110.0},
        "target_count": 2,
    }
    current = {"weights": {"SPY": 0.5}}

    rebalance = build_rebalance(
        current_position=current,
        target=target,
        prior_equity=10_000.0,
        slippage_bps=10.0,
    )
    fills = build_fills(
        timestamp="2026-06-26",
        generated_at="2026-06-28T00:00:00Z",
        target=target,
        rebalance=rebalance,
        prior_equity=10_000.0,
    )
    snapshot = build_snapshot(
        timestamp="2026-06-26",
        generated_at="2026-06-28T00:00:00Z",
        target=target,
        rebalance=rebalance,
        prior_equity=10_000.0,
        final_equity=9_995.0,
    )
    reconciliation = build_reconciliation(snapshot=snapshot, prior_equity=10_000.0, rebalance=rebalance)

    assert rebalance["turnover"] == 0.5
    assert rebalance["estimated_slippage"] == 5.0
    assert [fill["symbol"] for fill in fills] == ["SHV", "SPY"]
    assert all(fill["broker_order_id"] == "" and fill["simulated_only"] is True for fill in fills)
    assert reconciliation["passed"] is True
    guardrails = paper_roll_guardrails()
    assert guardrails["broker_calls_used"] is False
    assert guardrails["live_order_allowed"] is False


def test_paper_simulation_roll_blocks_when_readiness_not_ready_and_writes_no_ledger(tmp_path: Path) -> None:
    _write_readiness(tmp_path, status="paper_simulation_blocked", decision="do_not_start_paper_simulation")
    _write_forward_target(tmp_path)

    payload = run_us_equity_paper_simulation_roll(
        repo_root=tmp_path,
        output=Path("out/paper_roll.json"),
        generated_at="2026-06-28T00:00:00Z",
        manual_start_approved=True,
    )

    _validate_schema(payload)
    assert payload["status"] == "BLOCKED"
    assert "us_equity_paper_simulation_readiness_not_ready" in payload["blockers"]
    assert "us_equity_paper_simulation_manual_start_decision_missing" in payload["blockers"]
    assert payload["ledger_materialization"]["status"] == "blocked_before_ledger_write"
    assert payload["ledger_materialization"]["writes_performed"] is False
    assert payload["ledger_materialization"]["blocked_before_ledger_write"] is True
    assert payload["ledger_materialization"]["paper_ledger_is_independent"] is True
    assert payload["ledger_materialization"]["uses_forward_observation_as_source_only"] is True
    assert payload["ledger_materialization"]["rows_written_this_cycle"] == {
        "target_positions": 0,
        "fills": 0,
        "positions": 0,
        "cash_ledger": 0,
        "portfolio_snapshots": 0,
        "validation_state": 0,
        "daily_reports": 0,
    }
    assert not (tmp_path / "data/paper_ledger/us_equity_etf_rotation_v1/fills.jsonl").exists()
    assert not (tmp_path / "data/paper_ledger/us_equity_etf_rotation_v1/daily_reports/2026-06-26.json").exists()
    assert payload["guardrails"]["real_order_submitted"] is False


def test_paper_simulation_roll_blocks_malformed_readiness_without_ledger_write(tmp_path: Path) -> None:
    readiness = tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_readiness_report.json"
    readiness.parent.mkdir(parents=True)
    readiness.write_text("{not-json", encoding="utf-8")
    _write_forward_target(tmp_path)

    payload = run_us_equity_paper_simulation_roll(
        repo_root=tmp_path,
        output=Path("out/paper_roll.json"),
        generated_at="2026-06-28T00:00:00Z",
        manual_start_approved=True,
    )

    _validate_schema(payload)
    assert payload["status"] == "BLOCKED"
    assert "us_equity_paper_simulation_readiness_not_ready" in payload["blockers"]
    assert not (tmp_path / "data/paper_ledger/us_equity_etf_rotation_v1").exists()
    assert payload["guardrails"]["live_order_allowed"] is False


def test_paper_simulation_roll_blocks_corrupt_state_without_appending_rows(tmp_path: Path) -> None:
    _write_readiness(tmp_path)
    _write_forward_target(tmp_path)
    ledger = tmp_path / "data/paper_ledger/us_equity_etf_rotation_v1"
    ledger.mkdir(parents=True)
    (ledger / "validation_state.json").write_text("{not-json", encoding="utf-8")

    payload = run_us_equity_paper_simulation_roll(
        repo_root=tmp_path,
        output=Path("out/paper_roll.json"),
        generated_at="2026-06-28T00:00:00Z",
        manual_start_approved=True,
    )

    _validate_schema(payload)
    assert payload["status"] == "BLOCKED"
    assert "us_equity_paper_simulation_validation_state_unreadable" in payload["blockers"]
    assert not (ledger / "target_positions.jsonl").exists()
    assert not (ledger / "fills.jsonl").exists()
    assert not (ledger / "positions.jsonl").exists()
    assert not (ledger / "cash_ledger.jsonl").exists()
    assert not (ledger / "portfolio_snapshots.jsonl").exists()
    assert not (ledger / "daily_reports").exists()
    assert payload["guardrails"]["live_order_allowed"] is False


def test_paper_simulation_roll_reports_uow_failure_without_partial_ledger(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    _write_readiness(tmp_path)
    _write_forward_target(tmp_path)

    def fail_commit(**kwargs: object) -> dict[str, object]:
        ledger_root = Path(kwargs["ledger_root"])
        raise PaperLedgerCommitError(
            "simulated commit failure",
            transaction_id="test-transaction",
            journal_path=ledger_root / ".transactions/test-transaction/transaction.json",
            rollback_succeeded=True,
        )

    monkeypatch.setattr(paper_runner_service, "commit_paper_ledger_cycle", fail_commit)

    payload = run_us_equity_paper_simulation_roll(
        repo_root=tmp_path,
        output=Path("out/paper_roll.json"),
        generated_at="2026-06-28T00:00:00Z",
        manual_start_approved=True,
    )

    _validate_schema(payload)
    assert payload["status"] == "BLOCKED"
    assert "us_equity_paper_simulation_ledger_commit_failed:rollback_succeeded=true" in payload["blockers"]
    ledger = tmp_path / "data/paper_ledger/us_equity_etf_rotation_v1"
    assert not (ledger / "target_positions.jsonl").exists()
    assert not (ledger / "fills.jsonl").exists()
    assert not (ledger / "positions.jsonl").exists()
    assert not (ledger / "cash_ledger.jsonl").exists()
    assert not (ledger / "portfolio_snapshots.jsonl").exists()
    assert not (ledger / "validation_state.json").exists()
    assert not (ledger / "daily_reports").exists()
    assert payload["guardrails"]["live_order_allowed"] is False


def test_paper_simulation_roll_requires_explicit_manual_start_approval(tmp_path: Path) -> None:
    _write_readiness(tmp_path)
    _write_forward_target(tmp_path)

    payload = run_us_equity_paper_simulation_roll(
        repo_root=tmp_path,
        output=Path("out/paper_roll.json"),
        generated_at="2026-06-28T00:00:00Z",
        manual_start_approved=False,
    )

    _validate_schema(payload)
    assert payload["status"] == "BLOCKED"
    assert "us_equity_paper_simulation_manual_start_not_approved" in payload["blockers"]
    assert not (tmp_path / "data/paper_ledger/us_equity_etf_rotation_v1/target_positions.jsonl").exists()


def test_paper_simulation_roll_rejects_forward_ledger_reuse(tmp_path: Path) -> None:
    _write_readiness(tmp_path)
    _write_forward_target(tmp_path)

    payload = run_us_equity_paper_simulation_roll(
        repo_root=tmp_path,
        ledger_root=Path("data/forward_observation/us_etf_rotation_v1"),
        output=Path("out/paper_roll.json"),
        generated_at="2026-06-28T00:00:00Z",
        manual_start_approved=True,
    )

    assert payload["status"] == "BLOCKED"
    assert "us_equity_paper_simulation_ledger_root_not_canonical" in payload["blockers"]
    assert "us_equity_paper_simulation_reuses_forward_ledger_root" in payload["blockers"]


def test_paper_simulation_roll_writes_independent_simulated_ledger_when_ready(tmp_path: Path) -> None:
    _write_readiness(tmp_path)
    _write_forward_target(tmp_path)

    payload = run_us_equity_paper_simulation_roll(
        repo_root=tmp_path,
        output=Path("out/paper_roll.json"),
        generated_at="2026-06-28T00:00:00Z",
        manual_start_approved=True,
    )

    _validate_schema(payload)
    assert payload["status"] == "PASS"
    assert payload["cycle_status"] == "COMPLETED"
    assert payload["ledger_root"] == "data/paper_ledger/us_equity_etf_rotation_v1"
    assert payload["forward_ledger_root"] == "data/forward_observation/us_etf_rotation_v1"
    assert payload["reconciliation"]["passed"] is True
    assert len(payload["fills"]) == 2
    assert payload["ledger_materialization"]["status"] == "ledger_rows_written"
    assert payload["ledger_materialization"]["writes_performed"] is True
    assert payload["ledger_materialization"]["paper_ledger_is_independent"] is True
    assert payload["ledger_materialization"]["canonical_ledger_root_verified"] is True
    assert payload["ledger_materialization"]["uses_forward_observation_as_source_only"] is True
    assert payload["ledger_materialization"]["simulated_fills_only"] is True
    assert payload["ledger_materialization"]["broker_order_ids_absent"] is True
    assert payload["ledger_materialization"]["exchange_order_ids_absent"] is True
    assert payload["ledger_materialization"]["rows_written_this_cycle"] == {
        "target_positions": 1,
        "fills": 2,
        "positions": 1,
        "cash_ledger": 1,
        "portfolio_snapshots": 1,
        "validation_state": 1,
        "daily_reports": 1,
    }
    assert payload["guardrails"]["paper_simulation_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    ledger = tmp_path / "data/paper_ledger/us_equity_etf_rotation_v1"
    assert _jsonl_count(ledger / "target_positions.jsonl") == 1
    assert _jsonl_count(ledger / "fills.jsonl") == 2
    assert _jsonl_count(ledger / "positions.jsonl") == 1
    assert _jsonl_count(ledger / "cash_ledger.jsonl") == 1
    assert _jsonl_count(ledger / "portfolio_snapshots.jsonl") == 1
    daily_report = json.loads((ledger / "daily_reports/2026-06-26.json").read_text(encoding="utf-8"))
    assert daily_report["schema_version"] == "us_equity_paper_simulation_daily_report_v1"
    assert daily_report["reconciliation"]["passed"] is True
    assert daily_report["guardrails"]["live_order_allowed"] is False
    assert payload["outputs"]["daily_report"] == "data/paper_ledger/us_equity_etf_rotation_v1/daily_reports/2026-06-26.json"
    state = json.loads((ledger / "validation_state.json").read_text(encoding="utf-8"))
    assert state["last_processed_timestamp"] == "2026-06-26"
    assert state["position_ledger_count"] == 1
    assert state["cash_ledger_count"] == 1
    assert state["real_order_submitted"] is False


def test_paper_simulation_roll_is_idempotent_for_same_target_timestamp(tmp_path: Path) -> None:
    _write_readiness(tmp_path)
    _write_forward_target(tmp_path)

    first = run_us_equity_paper_simulation_roll(
        repo_root=tmp_path,
        output=Path("out/paper_roll.json"),
        generated_at="2026-06-28T00:00:00Z",
        manual_start_approved=True,
    )
    second = run_us_equity_paper_simulation_roll(
        repo_root=tmp_path,
        output=Path("out/paper_roll.json"),
        generated_at="2026-06-28T00:05:00Z",
        manual_start_approved=True,
    )

    _validate_schema(first)
    _validate_schema(second)
    assert second["status"] == "PASS"
    assert second["cycle_status"] == "SKIPPED_ALREADY_COMPLETED"
    assert second["ledger_materialization"]["status"] == "already_processed_no_new_rows"
    assert second["ledger_materialization"]["writes_performed"] is False
    assert second["ledger_materialization"]["skipped_already_completed"] is True
    assert second["ledger_materialization"]["rows_written_this_cycle"] == {
        "target_positions": 0,
        "fills": 0,
        "positions": 0,
        "cash_ledger": 0,
        "portfolio_snapshots": 0,
        "validation_state": 0,
        "daily_reports": 0,
    }
    ledger = tmp_path / "data/paper_ledger/us_equity_etf_rotation_v1"
    assert _jsonl_count(ledger / "target_positions.jsonl") == 1
    assert _jsonl_count(ledger / "fills.jsonl") == 2
    assert _jsonl_count(ledger / "positions.jsonl") == 1
    assert _jsonl_count(ledger / "cash_ledger.jsonl") == 1
    assert _jsonl_count(ledger / "portfolio_snapshots.jsonl") == 1
    assert len(list((ledger / "daily_reports").glob("*.json"))) == 1


def test_paper_simulation_roll_marks_prior_positions_to_current_prices(tmp_path: Path) -> None:
    _write_readiness(tmp_path)
    _write_forward_target(tmp_path, date="2026-06-26", spy_price=500.0)
    first = run_us_equity_paper_simulation_roll(
        repo_root=tmp_path,
        output=Path("out/paper_roll.json"),
        generated_at="2026-06-28T00:00:00Z",
        manual_start_approved=True,
    )
    _write_forward_target(tmp_path, date="2026-06-27", spy_price=550.0)
    second = run_us_equity_paper_simulation_roll(
        repo_root=tmp_path,
        output=Path("out/paper_roll.json"),
        generated_at="2026-06-29T00:00:00Z",
        manual_start_approved=True,
    )

    _validate_schema(first)
    _validate_schema(second)
    assert first["status"] == "PASS"
    assert second["status"] == "PASS"
    assert second["portfolio_snapshot"]["prior_equity"] > first["portfolio_snapshot"]["equity"]
    assert second["portfolio_snapshot"]["equity"] > first["portfolio_snapshot"]["equity"]
    assert second["portfolio_snapshot"]["cash"] + second["portfolio_snapshot"]["position_value"] == pytest.approx(
        second["portfolio_snapshot"]["equity"],
        abs=0.01,
    )
    state = json.loads(
        (tmp_path / "data/paper_ledger/us_equity_etf_rotation_v1/validation_state.json").read_text(encoding="utf-8")
    )
    assert state["current_cash"] == pytest.approx(second["portfolio_snapshot"]["cash"], abs=0.01)
    assert state["current_quantities"]


def test_paper_simulation_roll_schema_rejects_live_order_flag(tmp_path: Path) -> None:
    _write_readiness(tmp_path)
    _write_forward_target(tmp_path)
    payload = run_us_equity_paper_simulation_roll(
        repo_root=tmp_path,
        output=Path("out/paper_roll.json"),
        generated_at="2026-06-28T00:00:00Z",
        manual_start_approved=True,
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def _write_readiness(
    root: Path,
    *,
    status: str = "paper_simulation_ready_for_manual_start",
    decision: str = "manual_start_required",
) -> None:
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_readiness_report.json",
        {
            "status": status,
            "decision": decision,
            "required_runner_contract": {
                "independent_ledger_root": "data/paper_ledger/us_equity_etf_rotation_v1",
                "must_not_reuse_forward_observation_ledger": True,
                "broker_private_endpoint_allowed": False,
                "order_endpoint_allowed": False,
                "real_order_submitted": False,
            },
            "guardrails": {
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
                "private_endpoint_allowed": False,
                "order_endpoint_allowed": False,
                "real_order_submitted": False,
            },
            "unsafe_flags": [],
        },
    )


def _write_forward_target(root: Path, *, date: str = "2026-06-26", spy_price: float = 500.0) -> None:
    target = {
        "timestamp": date,
        "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
        "candidate_variant": "min_adv_10m_to_shv",
        "target_position": {
            "date": date,
            "gross_exposure": 1.0,
            "net_exposure": 1.0,
            "weights": {"SPY": 0.6, "SHV": 0.4},
            "prices": {"SPY": spy_price, "SHV": 110.0},
            "shares": {"SPY": 12.0, "SHV": 36.3636363636},
            "notionals": {"SPY": 6000.0, "SHV": 4000.0},
            "target_count": 2,
        },
    }
    path = root / "data/forward_observation/us_etf_rotation_v1/target_positions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(target, sort_keys=True) + "\n", encoding="utf-8")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _jsonl_count(path: Path) -> int:
    return len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        raise AssertionError(f"schema validation failed: {exc.message}") from exc
