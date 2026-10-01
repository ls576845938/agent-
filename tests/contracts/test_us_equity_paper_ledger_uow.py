from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from quant_us.live.paper_ledger_uow import (
    PaperLedgerCommitError,
    commit_paper_ledger_cycle,
    prepare_paper_ledger_transaction,
    recover_incomplete_paper_ledger_transactions,
)


def test_paper_ledger_uow_commits_all_seven_evidence_files(tmp_path: Path) -> None:
    ledger = tmp_path / "paper"

    result = commit_paper_ledger_cycle(
        ledger_root=ledger,
        timestamp="2026-06-26",
        generated_at="2026-06-28T00:00:00Z",
        jsonl_rows={
            "target_positions.jsonl": [{"id": "target-1"}],
            "fills.jsonl": [{"id": "fill-1"}, {"id": "fill-2"}],
            "positions.jsonl": [{"id": "position-1"}],
            "cash_ledger.jsonl": [{"id": "cash-1"}],
            "portfolio_snapshots.jsonl": [{"id": "snapshot-1"}],
        },
        json_documents={
            "validation_state.json": {"last_processed_timestamp": "2026-06-26"},
            "daily_reports/2026-06-26.json": {"status": "clean"},
        },
    )

    assert result["status"] == "COMMITTED"
    assert result["operation_count"] == 7
    assert _jsonl_count(ledger / "fills.jsonl") == 2
    assert json.loads((ledger / "validation_state.json").read_text(encoding="utf-8"))["last_processed_timestamp"] == "2026-06-26"
    assert json.loads((ledger / "daily_reports/2026-06-26.json").read_text(encoding="utf-8"))["status"] == "clean"
    journal = json.loads(Path(result["journal_path"]).read_text(encoding="utf-8"))
    assert journal["status"] == "COMMITTED"
    assert not (Path(result["journal_path"]).parent / "staged").exists()
    assert not (Path(result["journal_path"]).parent / "backup").exists()


def test_paper_ledger_uow_rolls_back_every_file_when_apply_fails(tmp_path: Path) -> None:
    ledger = tmp_path / "paper"
    ledger.mkdir(parents=True)
    original = '{"id":"old-target"}\n'
    (ledger / "target_positions.jsonl").write_text(original, encoding="utf-8")
    replace_count = 0

    def fail_second_replace(source: object, destination: object) -> None:
        nonlocal replace_count
        replace_count += 1
        if replace_count == 2:
            raise OSError("simulated apply interruption")
        os.replace(source, destination)

    with pytest.raises(PaperLedgerCommitError) as exc_info:
        commit_paper_ledger_cycle(
            ledger_root=ledger,
            timestamp="2026-06-26",
            generated_at="2026-06-28T00:00:00Z",
            jsonl_rows={
                "target_positions.jsonl": [{"id": "new-target"}],
                "fills.jsonl": [{"id": "fill-1"}],
                "positions.jsonl": [{"id": "position-1"}],
                "cash_ledger.jsonl": [{"id": "cash-1"}],
                "portfolio_snapshots.jsonl": [{"id": "snapshot-1"}],
            },
            json_documents={
                "validation_state.json": {"last_processed_timestamp": "2026-06-26"},
                "daily_reports/2026-06-26.json": {"status": "clean"},
            },
            apply_replace=fail_second_replace,
        )

    error = exc_info.value
    assert error.rollback_succeeded is True
    assert (ledger / "target_positions.jsonl").read_text(encoding="utf-8") == original
    for relative in (
        "fills.jsonl",
        "positions.jsonl",
        "cash_ledger.jsonl",
        "portfolio_snapshots.jsonl",
        "validation_state.json",
        "daily_reports/2026-06-26.json",
    ):
        assert not (ledger / relative).exists()
    journal = json.loads(error.journal_path.read_text(encoding="utf-8"))
    assert journal["status"] == "ROLLED_BACK"
    assert journal["rollback_blockers"] == []


def test_paper_ledger_uow_recovers_applying_transaction_after_restart(tmp_path: Path) -> None:
    ledger = tmp_path / "paper"
    ledger.mkdir(parents=True)
    original = '{"id":"old-target"}\n'
    (ledger / "target_positions.jsonl").write_text(original, encoding="utf-8")
    transaction = prepare_paper_ledger_transaction(
        ledger_root=ledger,
        timestamp="2026-06-26",
        generated_at="2026-06-28T00:00:00Z",
        jsonl_rows={"target_positions.jsonl": [{"id": "new-target"}]},
        json_documents={},
    )
    transaction._write_status("APPLYING")
    operation = transaction.journal["operations"][0]
    os.replace(
        transaction.transaction_dir / operation["staged_path"],
        ledger / operation["relative_path"],
    )
    assert "new-target" in (ledger / "target_positions.jsonl").read_text(encoding="utf-8")

    recovery = recover_incomplete_paper_ledger_transactions(ledger)

    assert recovery.status == "recovered"
    assert recovery.recovered_transaction_ids == [transaction.transaction_id]
    assert recovery.blockers == []
    assert (ledger / "target_positions.jsonl").read_text(encoding="utf-8") == original
    journal = json.loads(transaction.journal_path.read_text(encoding="utf-8"))
    assert journal["status"] == "ROLLED_BACK"


def _jsonl_count(path: Path) -> int:
    return len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])
