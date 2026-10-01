from __future__ import annotations

import json
from pathlib import Path

import jsonschema


CONFIG = Path("configs/risk/us_equity_live_risk_limits.json")
SCHEMA = Path("schemas/us_equity_live_risk_limits.schema.json")


def test_us_equity_live_risk_limits_config_matches_schema() -> None:
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["account_capital_usd"] == 10000.0
    assert payload["max_live_principal_usd"] <= 1000.0
    assert payload["manual_reviewer"] == ""


def test_us_equity_live_risk_limits_schema_rejects_full_account_live_principal() -> None:
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    payload["max_live_principal_usd"] = 10000.0
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted full-account live principal")
