from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_btc_tail_dependency_report import build_btc_tail_dependency_report


SCHEMA = Path("schemas/btc_tail_dependency_report.schema.json")
REPORT = Path("artifacts/btc_tail_dependency/latest/tail_dependency_report.json")


def test_btc_tail_dependency_report_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_tail_dependency_uses_real_ledger_trade_pnl_but_is_not_promotion_evidence() -> None:
    payload = build_btc_tail_dependency_report(generated_at="2026-05-19T00:00:00Z")

    assert payload["tail_event_count"] > 0
    assert payload["ledger_returns_source"].endswith("trade_ledger.csv")
    assert payload["promotion_evidence"] is False
    assert payload["tail_dependency_pass"] is True


def test_missing_ledger_returns_fail_closed(tmp_path: Path) -> None:
    payload = build_btc_tail_dependency_report(
        repo_root=tmp_path,
        source_run_dir=Path("missing_run"),
        generated_at="2026-05-19T00:00:00Z",
    )

    assert payload["tail_dependency_pass"] is False
    assert "btc_tail_dependency_ledger_returns_missing" in payload["blockers"]


def test_fixture_tail_report_cannot_be_promotion_evidence() -> None:
    payload = build_btc_tail_dependency_report(source_type="fixture", generated_at="2026-05-19T00:00:00Z")

    assert payload["promotion_evidence"] is False
    assert payload["tail_dependency_pass"] is False
    assert "btc_tail_dependency_source_type_fixture_not_promotion_evidence" in payload["blockers"]

