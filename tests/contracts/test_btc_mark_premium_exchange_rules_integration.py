from __future__ import annotations

from scripts.build_btc_cost_model_report import build_btc_cost_model_report


def test_mark_premium_and_exchange_rules_are_required_for_candidate_gate() -> None:
    payload = build_btc_cost_model_report(generated_at="2026-05-19T00:00:00Z")
    mark = payload["mark_price_model"]
    rules = payload["exchange_rules"]

    assert mark["mark_price_klines_available"] is True
    assert mark["premium_index_klines_available"] is True
    assert mark["mark_price_alignment_pass"] is True
    assert rules["exchange_rules_available"] is False
    assert rules["tick_size"] is None
    assert rules["step_size"] is None
    assert rules["min_notional"] is None
    assert "btc_exchange_info_missing" in payload["blockers"]
    assert payload["candidate_pass_allowed"] is False


def test_current_or_diagnostic_data_cannot_replace_historical_mark_and_premium() -> None:
    payload = build_btc_cost_model_report(generated_at="2026-05-19T00:00:00Z")
    mark = payload["mark_price_model"]

    assert mark["mark_price_current_available"] is False
    assert mark["last_price_vs_mark_price_diagnostic_available"] is False
    assert payload["candidate_pass_allowed"] is False
