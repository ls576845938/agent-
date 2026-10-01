from __future__ import annotations

import json
from pathlib import Path

import jsonschema


ARTIFACT_ROOTS = [
    Path("artifacts/us_equity_data_lineage/latest"),
    Path("artifacts/us_equity_data_status/latest"),
    Path("artifacts/us_equity_etf_macro_rotation/latest"),
    Path("artifacts/us_equity_strategy_production_line/latest"),
    Path("artifacts/us_equity_strategy_registry/latest"),
]


def test_all_us_equity_non_test_json_artifacts_have_matching_schema() -> None:
    missing = []
    for root in ARTIFACT_ROOTS:
        for path in root.glob("*.json"):
            if path.name.startswith("test_"):
                continue
            schema_path = Path("schemas") / path.name.replace(".json", ".schema.json")
            if not schema_path.exists():
                missing.append(str(path))
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            jsonschema.validate(payload, schema)

    assert missing == []
