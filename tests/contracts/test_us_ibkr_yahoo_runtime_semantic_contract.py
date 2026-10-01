from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from quant_us.live.ibkr_runtime_market_data import (
    compare_yahoo_research_to_ibkr_runtime,
    load_semantic_contract,
    stable_payload_sha256,
)


CONTRACT_PATH = Path("configs/data/us_ibkr_yahoo_runtime_semantic_contract_v1.json")
SCHEMA_PATH = Path("schemas/us_ibkr_yahoo_runtime_semantic_contract.schema.json")


def _normalized_ibkr_row(trading_date: str, close: float) -> dict[str, object]:
    provenance = "IBKR_ADJUSTED_LAST_TEST"
    digest = stable_payload_sha256(
        {
            "trading_date_et": trading_date,
            "close": close,
            "provenance": provenance,
        }
    )
    return {
        "source": "ibkr",
        "session": "regular",
        "trading_date_et": trading_date,
        "close": close,
        "adjusted": True,
        "semantic_parity_verified": True,
        "normalization_provenance": provenance,
        "normalization_sha256": digest,
    }


def test_semantic_contract_is_schema_valid_content_addressed_and_fail_closed() -> None:
    payload = load_semantic_contract(CONTRACT_PATH)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    jsonschema.Draft202012Validator(schema).validate(payload)
    assert payload["contract_sha256"] == stable_payload_sha256(payload["contract"])
    assert payload["contract"]["research_source"]["role"] == "research_only"
    assert payload["contract"]["runtime_source"]["role"] == "runtime_only"
    assert payload["contract"]["bar_availability_policy"]["warmup_yahoo_fallback_allowed"] is False
    assert payload["contract"]["corporate_action_policy"]["silent_ignore_allowed"] is False
    assert payload["contract"]["corporate_action_policy"]["verified_status_alone_sufficient"] is False
    assert payload["contract"]["promotion_semantics"] == {
        "semantic_contract_is_promotion_evidence": False,
        "paper_submit_allowed": False,
        "live_allowed": False,
        "promotion_allowed": False,
    }


def test_normal_sessions_compare_return_semantics_not_adjusted_raw_absolute_prices() -> None:
    yahoo = [
        {"source": "yahoo", "session": "regular", "trading_date_et": "2026-08-05", "close": 100.0},
        {"source": "yahoo", "session": "regular", "trading_date_et": "2026-08-06", "close": 101.0},
    ]
    ibkr = [
        _normalized_ibkr_row("2026-08-05", 500.0),
        _normalized_ibkr_row("2026-08-06", 505.0),
    ]

    result = compare_yahoo_research_to_ibkr_runtime(
        yahoo,
        ibkr,
        corporate_action_entitlement_verified=True,
    )

    assert result.passed is True
    assert result.return_pairs_compared == 1
    assert result.maximum_return_difference is not None
    assert result.maximum_return_difference < 1e-12


def test_split_dividend_missing_bar_and_after_hours_cases_are_explicit() -> None:
    yahoo = [
        {"source": "yahoo", "session": "regular", "trading_date_et": "2026-08-05", "close": 100.0},
        {"source": "yahoo", "session": "regular", "trading_date_et": "2026-08-06", "close": 101.0},
        {"source": "yahoo", "session": "after_hours", "trading_date_et": "2026-08-06", "close": 999.0},
    ]
    ibkr = [
        _normalized_ibkr_row("2026-08-05", 500.0),
    ]
    actions = [
        {"action_type": "split", "status": "unknown"},
        {"action_type": "dividend", "status": "unentitled"},
    ]

    result = compare_yahoo_research_to_ibkr_runtime(
        yahoo,
        ibkr,
        corporate_actions=actions,
    )

    assert result.status == "blocked_fail_closed"
    assert "semantic_parity_ibkr_session_missing" in result.blockers
    assert "semantic_parity_split_unverified_fail_closed" in result.blockers
    assert "semantic_parity_dividend_unverified_fail_closed" in result.blockers
    assert "semantic_parity_insufficient_shared_sessions" in result.blockers
    assert result.to_dict()["promotion_allowed"] is False


def test_semantic_parity_default_blocks_without_corporate_action_entitlement() -> None:
    rows = [
        {"source": "yahoo", "session": "regular", "trading_date_et": "2026-08-05", "close": 100.0},
        {"source": "yahoo", "session": "regular", "trading_date_et": "2026-08-06", "close": 101.0},
    ]
    ibkr = [
        _normalized_ibkr_row(str(row["trading_date_et"]), float(row["close"]) * 5.0)
        for row in rows
    ]

    result = compare_yahoo_research_to_ibkr_runtime(rows, ibkr)

    assert result.status == "blocked_fail_closed"
    assert "semantic_parity_corporate_action_entitlement_unverified_fail_closed" in result.blockers


def test_verified_action_status_without_adjusted_runtime_series_is_still_blocked() -> None:
    yahoo = [
        {"source": "yahoo", "session": "regular", "trading_date_et": "2026-08-05", "close": 100.0},
        {"source": "yahoo", "session": "regular", "trading_date_et": "2026-08-06", "close": 101.0},
    ]
    raw_ibkr = [
        {"source": "ibkr", "session": "regular", "trading_date_et": "2026-08-05", "close": 500.0},
        {"source": "ibkr", "session": "regular", "trading_date_et": "2026-08-06", "close": 252.5},
    ]

    result = compare_yahoo_research_to_ibkr_runtime(
        yahoo,
        raw_ibkr,
        corporate_actions=[{"action_type": "split", "status": "verified"}],
        corporate_action_entitlement_verified=True,
    )

    assert result.status == "blocked_fail_closed"
    assert "semantic_parity_ibkr_adjusted_daily_required" in result.blockers
