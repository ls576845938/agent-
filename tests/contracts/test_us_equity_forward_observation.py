from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import jsonschema
import pytest

from quant_us.application.us_equity_forward_observation import (
    FileReceiptStore,
    ReceiptIntegrityError,
    build_forward_observation_receipt,
    run_current_day_forward_observation,
)


SCHEMA = Path("schemas/us_equity_forward_observation_receipt.schema.json")
HEAD_A = "a" * 40
HEAD_B = "b" * 40
TREE_A = "c" * 64


def test_windows_do_not_substitute_for_each_other() -> None:
    history: list[dict] = []
    start = date(2026, 7, 1)
    for offset in range(29):
        day = start + timedelta(days=offset)
        history.append(_build(day=day, history=history))
    current = _build(day=start + timedelta(days=29), history=history)

    _validate(current)
    assert current["status"] == "in_progress_natural_time"
    assert current["windows"]["paper_review_natural_days"] == {
        "required": 30,
        "observed": 30,
        "complete": True,
        "semantics": "paper_review_prerequisite_only",
    }
    confirmation = current["windows"][
        "independent_confirmation_trading_sessions"
    ]
    assert confirmation["observed"] == 17
    assert confirmation["complete"] is False
    assert current["windows"]["substitution_allowed"] is False
    assert current["guardrails"]["paper_allowed"] is False


def test_252_distinct_sessions_never_unlock_trading() -> None:
    history: list[dict] = []
    start = date(2026, 7, 14)
    for offset in range(251):
        day = start + timedelta(days=offset)
        history.append(_build(day=day, history=history))
    current = _build(day=start + timedelta(days=251), history=history)

    _validate(current)
    assert current["status"] == "complete_for_manual_review_only"
    assert current["windows"]["paper_review_natural_days"]["complete"] is True
    assert (
        current["windows"]["independent_confirmation_trading_sessions"]["complete"]
        is True
    )
    assert all(
        value is False
        for key, value in current["guardrails"].items()
        if key != "candidate_frozen"
    )


def test_gap_restarts_continuity_without_backfill() -> None:
    previous = _build(day=date(2026, 7, 20), history=[])
    current = _build(day=date(2026, 7, 22), history=[previous])

    _validate(current)
    assert current["status"] == "in_progress_natural_time"
    assert current["continuity"]["status"] == "restarted_after_interrupt"
    assert current["continuity"]["current_streak_natural_days"] == 1
    assert "natural_day_gap:2026-07-20:2026-07-22" in current["continuity"][
        "interrupts"
    ]
    assert current["continuity"]["backfill_used"] is False


def test_cross_head_and_code_tree_hash_restart_continuity() -> None:
    previous = _build(day=date(2026, 7, 20), history=[], head=HEAD_A)
    current = _build(
        day=date(2026, 7, 21),
        history=[previous],
        head=HEAD_B,
        code_tree_hash="d" * 64,
    )

    assert current["status"] == "in_progress_natural_time"
    assert current["continuity"]["current_streak_natural_days"] == 1
    assert "cross_head_continuity_interrupt" in current["continuity"]["interrupts"]
    assert "code_tree_hash_drift" in current["continuity"]["interrupts"]


def test_cross_strategy_restarts_continuity() -> None:
    previous = _build(day=date(2026, 7, 20), history=[])
    current = _build(
        day=date(2026, 7, 21),
        history=[previous],
        strategy_version="us_etf_complete_return_fixed_signal_v2",
    )

    assert current["status"] == "in_progress_natural_time"
    assert current["continuity"]["current_streak_natural_days"] == 1
    assert "cross_strategy_continuity_interrupt" in current["continuity"][
        "interrupts"
    ]


def test_missing_expected_session_blocks_without_state_credit() -> None:
    current = _build(
        day=date(2026, 7, 24),
        history=[],
        coverage_end="2026-07-10T15:59:00",
        expected_session="2026-07-23",
    )

    _validate(current)
    assert current["status"] == "blocked_external_data"
    assert "expected_finalized_session_missing:2026-07-23" in current["blockers"]
    assert current["continuity"]["current_streak_natural_days"] == 0
    assert all(
        value["status"] == "not_run_missing_finalized_session"
        for value in current["states"].values()
    )


def test_wrong_timezone_blocks_contract_and_continuity() -> None:
    config = _config()
    config["time_contract"]["timezone"] = "UTC"
    current = _build(
        day=date(2026, 7, 24),
        history=[],
        config=config,
        now_timezone=ZoneInfo("UTC"),
    )

    _validate(current)
    assert current["status"] == "blocked_contract"
    assert "observation_timezone_contract_mismatch" in current["blockers"]
    assert current["continuity"]["current_streak_natural_days"] == 0


def test_same_day_receipt_is_append_only_and_tamper_is_detected(
    tmp_path: Path,
) -> None:
    store = FileReceiptStore(
        root=tmp_path / "artifacts/us_equity_forward_observation",
        repo_root=tmp_path,
    )
    day = date(2026, 7, 24)
    report_path, manifest_path = store.paths_for(
        natural_day=day,
        run_id="us-forward-" + "1" * 16,
    )
    receipt = _build(
        day=day,
        history=[],
        report_path=report_path.relative_to(tmp_path).as_posix(),
        manifest_path=manifest_path.relative_to(tmp_path).as_posix(),
        run_id="us-forward-" + "1" * 16,
    )
    store.write_once(receipt)

    assert store.read_same_day(day) == receipt
    with pytest.raises(ReceiptIntegrityError, match="same_day_receipt_already_exists"):
        store.write_once(receipt)

    report_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ReceiptIntegrityError, match="same_day_receipt_tampered"):
        store.read_same_day(day)
    assert len(list((store.root / "runs" / day.isoformat()).glob("*/report.json"))) == 1


def test_dirty_latest_interrupts_next_day_continuity(tmp_path: Path) -> None:
    store = FileReceiptStore(
        root=tmp_path / "artifacts/us_equity_forward_observation",
        repo_root=tmp_path,
    )
    day = date(2026, 7, 23)
    report_path, manifest_path = store.paths_for(
        natural_day=day,
        run_id="us-forward-" + "2" * 16,
    )
    receipt = _build(
        day=day,
        history=[],
        report_path=report_path.relative_to(tmp_path).as_posix(),
        manifest_path=manifest_path.relative_to(tmp_path).as_posix(),
        run_id="us-forward-" + "2" * 16,
    )
    store.write_once(receipt)
    pointer = store.root / "latest/latest_pointer.json"
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    payload["receipt_sha256"] = "0" * 64
    pointer.write_text(json.dumps(payload), encoding="utf-8")

    history, issues = store.read_verified_history(before=date(2026, 7, 24))
    current = _build(
        day=date(2026, 7, 24),
        history=history,
        integrity_issues=issues,
    )

    assert "dirty_latest_identity_mismatch" in issues
    assert current["status"] == "blocked_evidence_integrity"
    assert current["continuity"]["current_streak_natural_days"] == 0


def test_before_recommended_time_writes_no_receipt(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_config()), encoding="utf-8")

    outcome = run_current_day_forward_observation(
        repo_root=tmp_path,
        config_path=config_path,
        output_root=tmp_path / "artifacts/us_equity_forward_observation",
        generated_at="2026-07-24T00:00:00Z",
    )

    assert outcome["status"] == "wait_until_recommended_local_time"
    assert outcome["write_status"] == "not_written_before_schedule"
    assert not (tmp_path / "artifacts/us_equity_forward_observation").exists()


def test_schema_rejects_any_paper_unlock() -> None:
    current = _build(day=date(2026, 7, 24), history=[])
    current["guardrails"]["paper_allowed"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(current, _schema(), format_checker=jsonschema.FormatChecker())


def _build(
    *,
    day: date,
    history: list[dict],
    head: str = HEAD_A,
    code_tree_hash: str = TREE_A,
    strategy_version: str = "us_etf_complete_return_fixed_signal_v1",
    coverage_end: str = "2027-12-31T15:59:00",
    expected_session: str | None = None,
    integrity_issues: list[str] | None = None,
    config: dict | None = None,
    now_timezone: ZoneInfo | None = None,
    report_path: str = "artifacts/us_equity_forward_observation/runs/day/run/report.json",
    manifest_path: str = "artifacts/us_equity_forward_observation/runs/day/run/manifest.json",
    run_id: str = "us-forward-" + "f" * 16,
) -> dict:
    timezone_value = now_timezone or ZoneInfo("Asia/Shanghai")
    now_local = datetime(day.year, day.month, day.day, 10, 0, tzinfo=timezone_value)
    session = expected_session or (day - timedelta(days=1)).isoformat()
    candidate = _candidate(strategy_version)
    evidence = {
        name: {
            "status": "verified",
            "session": session,
            "source_head": head,
            "artifact_path": f"fixtures/{name}.json",
            "sha256": str(index + 1) * 64,
        }
        for index, name in enumerate(("signal", "target", "fill", "ledger"))
    }
    return build_forward_observation_receipt(
        config=config or _config(),
        candidate=candidate,
        manifest_state=_manifest(coverage_end),
        state_evidence=evidence,
        history=history,
        integrity_issues=integrity_issues or [],
        generated_at_utc=now_local.astimezone(timezone.utc),
        now_local=now_local,
        expected_finalized_session=session,
        source_head=head,
        code_tree_hash=code_tree_hash,
        report_path=report_path,
        manifest_path=manifest_path,
        run_id=run_id,
    )


def _config() -> dict:
    return {
        "schema_version": "us_v3_forward_observation_config_v1",
        "candidate": {
            "config_path": "candidate.json",
            "parameters_frozen": True,
            "candidate_reselection_allowed": False,
        },
        "data": {
            "pit_consumer_config_path": "pit.json",
            "producer_role": "data_steward",
            "committed_immutable_successor_required": True,
            "consumer_read_only": True,
        },
        "time_contract": {
            "timezone": "Asia/Shanghai",
            "recommended_local_time": "09:20",
            "calendar": "XNYS",
            "calendar_provider": "builtin_nyse_rules",
            "expected_finalized_session_rule": "previous_xnys_trading_session",
        },
        "windows": {
            "paper_review_natural_days": 30,
            "independent_confirmation_trading_sessions": 252,
            "substitution_allowed": False,
            "backfill_allowed": False,
            "evaluation_before_confirmation_window_end_allowed": False,
        },
        "receipt_store": {
            "root": "artifacts/us_equity_forward_observation",
            "one_receipt_per_natural_day": True,
            "append_only": True,
            "latest_pointer_requires_hash_verification": True,
        },
        "identity": {
            "cross_head_interrupts_continuity": True,
            "cross_strategy_interrupts_continuity": True,
            "code_tree_hash_drift_interrupts_continuity": True,
            "natural_day_gap_interrupts_continuity": True,
            "code_tree_paths": ["x"],
        },
        "state_evidence": {},
        "safety": {},
    }


def _candidate(strategy_version: str) -> dict:
    return {
        "schema_version": "us_etf_26_candidate_freeze_config_v1",
        "candidate_id": "us-etf26-complete-return-qqq-1d-v1",
        "strategy_version": strategy_version,
        "status": "frozen_exploratory_research_only",
        "selection": {"symbol": "QQQ", "timeframe": "1D"},
        "parameters": {"ema_fast_days": 50, "ema_slow_days": 200},
        "signal_rule": {"input_visibility": "completed bars only"},
        "execution_rule": {"fill_proxy": "next daily bar open"},
        "independent_confirmation_window": {
            "start": "2026-07-13",
            "end": "2027-07-12",
        },
    }


def _manifest(coverage_end: str) -> dict:
    return {
        "state": "research_ready",
        "producer_role": "data_steward",
        "producer_commit": "e" * 40,
        "manifest_git_spec": "deadbeef:.agent/data_manifests/etf26.json",
        "manifest_sha256": "d" * 64,
        "dataset_id": "us-equity-hf-etf26-1min",
        "dataset_version": "hf-data-library-etf26-clean-1min-fixture",
        "readiness_class": "research_ready",
        "coverage": {
            "start": "2002-12-30T09:30:00",
            "end": coverage_end,
        },
        "constraints": [],
        "errors": [],
    }


def _schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def _validate(payload: dict) -> None:
    jsonschema.validate(
        payload,
        _schema(),
        format_checker=jsonschema.FormatChecker(),
    )
