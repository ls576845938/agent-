from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_btc_fold_regime_contract_report import build_btc_fold_regime_contract_report


SCHEMA = Path("schemas/btc_fold_regime_contract.schema.json")
REPORT = Path("artifacts/btc_fold_regime/latest/fold_regime_contract_report.json")


def test_btc_fold_regime_contract_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_btc_fold_and_regime_versions_are_explicit() -> None:
    payload = build_btc_fold_regime_contract_report(generated_at="2026-05-19T00:00:00Z")
    fold = payload["fold_definition"]
    classifier = payload["regime_classifier"]

    assert fold["fold_definition_version"] == "btc_walk_forward_fold_contract_v1"
    assert fold["fold_count"] == 6
    assert all(row["test_start"] and row["test_end"] for row in fold["folds"])
    assert classifier["regime_classifier_version"] == "classify_btc_regimes_v1"
    assert "trending_up" in classifier["gate_regimes"]
    assert "trending_down" in classifier["diagnostic_regimes"]
    assert "liquidation_shock" in classifier["diagnostic_regimes"]


def test_btc_fold_regime_contract_distinguishes_contract_pass_from_gate_pass() -> None:
    payload = build_btc_fold_regime_contract_report(generated_at="2026-05-19T00:00:00Z")

    assert payload["fold_contract_status"] == "pass"
    assert payload["regime_contract_status"] == "pass"
    assert payload["regime_gate_pass_rate"] >= 0.75
    assert "btc_regime_contract_not_pass" not in payload["blockers"]
    assert payload["status"] == "pass"
    assert payload["promotion_ready"] is False
