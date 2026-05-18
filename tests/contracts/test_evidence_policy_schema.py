from __future__ import annotations

from pathlib import Path

import yaml


EVIDENCE_POLICY = Path("configs/evidence/evidence_policy.yaml")


def test_evidence_policy_exists_and_has_required_sections() -> None:
    assert EVIDENCE_POLICY.exists()

    policy = yaml.safe_load(EVIDENCE_POLICY.read_text(encoding="utf-8"))

    assert set(policy) >= {"global", "promotion", "us_equity", "btc"}

    expected_true_flags = {
        "global": [
            "require_event_ledger",
            "require_fills",
            "require_ledger_pnl",
            "require_cost_stress",
            "require_walk_forward",
            "require_regime_report",
            "require_registry_status",
            "forbid_signal_equity_promotion",
            "forbid_target_active_promotion",
            "forbid_plain_pf_promotion",
        ],
        "promotion": [
            "paper_queue_locked_by_default",
            "live_frozen_by_default",
            "candidate_passed_internal_gate_required",
        ],
        "us_equity": [
            "require_data_manifest",
            "require_universe_manifest",
            "require_corporate_action_status",
            "require_survivorship_status",
            "require_factor_evidence_pack",
            "require_portfolio_canonical_report",
            "require_exposure_report",
            "require_turnover_report",
            "require_capacity_proxy",
        ],
        "btc": [
            "require_sqlite_completeness_report",
            "require_fold_definition_version",
            "require_regime_classifier_version",
            "require_funding_cost_model",
            "require_fee_model",
            "require_tail_dependency_report",
        ],
    }

    for section, keys in expected_true_flags.items():
        assert section in policy
        for key in keys:
            assert policy[section][key] is True, (section, key)
