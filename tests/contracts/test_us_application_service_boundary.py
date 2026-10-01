from __future__ import annotations

import ast
from datetime import date, datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import jsonschema
import pytest

from quant_us.application.service import (
    MinuteQualityRequest,
    USApplicationService,
)


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/governance/us_application_service_boundary_v1.json"
SCHEMA = ROOT / "schemas/us_application_service_boundary.schema.json"
FIXED_NOW = datetime(2026, 7, 24, 1, 30, tzinfo=timezone.utc)


class FakeCalendar:
    holidays = {date(2024, 1, 1): "New Year's Day"}

    def is_trading_day(self, value: date) -> bool:
        return value.weekday() < 5 and value not in self.holidays

    def is_early_close(self, value: date) -> bool:
        return value == date(2024, 11, 29)


class MemoryCalendarRepository:
    def __init__(self, *, fail_after: int | None = None) -> None:
        self.rows: dict[date, dict[str, object]] = {}
        self.fail_after = fail_after

    def upsert(self, rows) -> None:
        for index, row in enumerate(rows):
            self.rows[row["date"]] = dict(row)
            if self.fail_after is not None and index + 1 >= self.fail_after:
                raise OSError("injected partial write failure")


class FakeMinuteQualityRepository:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def inspect(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {
            "status": "PASS",
            "as_of_utc": kwargs["as_of"].isoformat(),
            "evaluated_symbols": list(kwargs["symbols"] or []),
            "bar_sizes": list(kwargs["bar_sizes"]),
            "root_subdirs": list(kwargs["root_subdirs"]),
            "paper_order_allowed": False,
            "live_order_allowed": False,
        }


class FakePromotionGateRepository:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def evaluate(self, candidate_id: str):
        self.calls.append(candidate_id)
        return SimpleNamespace(
            candidate_id=candidate_id,
            decision="BLOCKED",
            reasons=["fixture_blocker"],
            warnings=[],
            evidence={},
        )


class RecordingUnitOfWork:
    def __init__(
        self,
        *,
        calendar: MemoryCalendarRepository | None = None,
        fail_commit: bool = False,
    ) -> None:
        self.calendar = calendar or MemoryCalendarRepository()
        self.minute_quality = FakeMinuteQualityRepository()
        self.promotion_gate = FakePromotionGateRepository()
        self.fail_commit = fail_commit
        self.commit_count = 0
        self.rollback_count = 0
        self._calendar_snapshot: dict[date, dict[str, object]] = {}

    def snapshot(self) -> None:
        self._calendar_snapshot = {
            key: dict(value) for key, value in self.calendar.rows.items()
        }

    def commit(self) -> None:
        self.commit_count += 1
        if self.fail_commit:
            raise OSError("injected commit failure")

    def rollback(self) -> None:
        self.rollback_count += 1
        self.calendar.rows = {
            key: dict(value) for key, value in self._calendar_snapshot.items()
        }


def _service(uow: RecordingUnitOfWork) -> USApplicationService:
    uow.snapshot()
    return USApplicationService(
        uow_factory=lambda: uow,
        calendar_factory=lambda years: FakeCalendar(),
        clock=lambda: FIXED_NOW,
    )


def test_calendar_application_service_commits_with_fake_repository_and_uow() -> None:
    uow = RecordingUnitOfWork()

    count = _service(uow).populate_trading_calendar(2024, 2024)

    assert count == 366
    assert len(uow.calendar.rows) == 366
    assert uow.commit_count == 1
    assert uow.rollback_count == 0
    assert uow.calendar.rows[date(2024, 1, 1)]["holiday_name"] == "New Year's Day"


def test_commit_failure_rolls_back_all_staged_calendar_rows() -> None:
    uow = RecordingUnitOfWork(fail_commit=True)

    with pytest.raises(OSError, match="injected commit failure"):
        _service(uow).populate_trading_calendar(2024, 2024)

    assert uow.commit_count == 1
    assert uow.rollback_count == 1
    assert uow.calendar.rows == {}


def test_partial_repository_write_rolls_back_without_commit() -> None:
    uow = RecordingUnitOfWork(
        calendar=MemoryCalendarRepository(fail_after=2),
    )

    with pytest.raises(OSError, match="injected partial write failure"):
        _service(uow).populate_trading_calendar(2024, 2024)

    assert uow.commit_count == 0
    assert uow.rollback_count == 1
    assert uow.calendar.rows == {}


def test_repeated_calendar_run_is_idempotent_at_repository_boundary() -> None:
    uow = RecordingUnitOfWork()
    service = _service(uow)

    first = service.populate_trading_calendar(2024, 2024)
    uow.snapshot()
    second = service.populate_trading_calendar(2024, 2024)

    assert first == second == 366
    assert len(uow.calendar.rows) == 366
    assert uow.commit_count == 2
    assert uow.rollback_count == 0


def test_minute_quality_uses_injected_clock_and_normalizes_request() -> None:
    uow = RecordingUnitOfWork()

    payload = _service(uow).inspect_minute_quality(
        MinuteQualityRequest(
            symbols=("aapl", "AAPL", " msft "),
            bar_sizes=("5M", "5m"),
            lookback_trading_days=0,
            root_subdirs=("cleaned", "cleaned"),
        )
    )

    assert payload["as_of_utc"] == FIXED_NOW.isoformat()
    assert payload["evaluated_symbols"] == ["AAPL", "MSFT"]
    assert payload["bar_sizes"] == ["5m"]
    call = uow.minute_quality.calls[0]
    assert call["lookback_trading_days"] == 1
    assert call["root_subdirs"] == ["cleaned"]
    assert uow.commit_count == 1


def test_promotion_gate_uses_injected_repository_and_stays_blocked() -> None:
    uow = RecordingUnitOfWork()

    result = _service(uow).evaluate_promotion_gate("candidate-1")

    assert result.decision == "BLOCKED"
    assert uow.promotion_gate.calls == ["candidate-1"]
    assert uow.commit_count == 1
    assert uow.rollback_count == 0


def test_application_layer_has_no_adapter_or_environment_dependencies() -> None:
    modules: set[str] = set()
    for path in sorted((ROOT / "quant_us/application").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
            elif isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
        source = path.read_text(encoding="utf-8")
        assert "os.environ" not in source
        assert "Path(" not in source
    assert not any(
        module.startswith(
            (
                "backend",
                "fastapi",
                "flask",
                "requests",
                "httpx",
                "alpaca",
                "ib_insync",
                "quant_crypto",
                "quant_cn",
            )
        )
        for module in modules
    )


def test_contract_schema_and_validator_are_fail_closed() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    jsonschema.validate(config, json.loads(SCHEMA.read_text(encoding="utf-8")))
    assert all(value is False for value in config["safety"].values())
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/validate_us_application_service_boundary.py",
            "--config",
            str(CONFIG),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["status"] == "valid"
