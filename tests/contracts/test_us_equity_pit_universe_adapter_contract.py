from __future__ import annotations

import json

from quant_us.data.lineage.provider_contracts import (
    CorporateActionEvent,
    PointInTimeMembershipEvent,
    PointInTimeUniverseSnapshot,
    evaluate_provider_verification,
)


def test_missing_local_provider_data_fails_verification() -> None:
    report = evaluate_provider_verification(
        provider_id="local_csv",
        local_data_available=False,
        required_tables_available=False,
        required_fields_available=False,
        record_count=0,
        sample_validation_pass=False,
        identifier_mapping_available=False,
        point_in_time_universe_confirmed=False,
        delisting_coverage_confirmed=False,
        corporate_action_event_source_available=False,
        adjustment_reproducibility_confirmed=False,
        survivorship_clean=False,
    )

    assert report.promotion_clean is False
    assert "provider_local_data_missing" in report.blockers


def test_membership_events_missing_keeps_pit_universe_unconfirmed() -> None:
    report = evaluate_provider_verification(
        provider_id="local_csv",
        local_data_available=True,
        required_tables_available=True,
        required_fields_available=True,
        record_count=10,
        sample_validation_pass=True,
        identifier_mapping_available=True,
        point_in_time_universe_confirmed=False,
        delisting_coverage_confirmed=True,
        corporate_action_event_source_available=True,
        adjustment_reproducibility_confirmed=True,
        survivorship_clean=True,
    )

    assert report.point_in_time_universe_confirmed is False
    assert "membership_events_missing" in report.blockers


def test_delisted_coverage_missing_keeps_survivorship_unclean() -> None:
    report = evaluate_provider_verification(
        provider_id="local_csv",
        local_data_available=True,
        required_tables_available=True,
        required_fields_available=True,
        record_count=10,
        sample_validation_pass=True,
        identifier_mapping_available=True,
        point_in_time_universe_confirmed=True,
        delisting_coverage_confirmed=False,
        corporate_action_event_source_available=True,
        adjustment_reproducibility_confirmed=True,
        survivorship_clean=False,
    )

    assert report.survivorship_clean is False
    assert "delisting_coverage_missing" in report.blockers


def test_corporate_action_events_missing_keeps_promotion_unclean() -> None:
    report = evaluate_provider_verification(
        provider_id="local_csv",
        local_data_available=True,
        required_tables_available=True,
        required_fields_available=True,
        record_count=10,
        sample_validation_pass=True,
        identifier_mapping_available=True,
        point_in_time_universe_confirmed=True,
        delisting_coverage_confirmed=True,
        corporate_action_event_source_available=False,
        adjustment_reproducibility_confirmed=True,
        survivorship_clean=True,
    )

    assert report.promotion_clean is False
    assert "corporate_action_event_source_missing" in report.blockers


def test_complete_synthetic_fixture_passes_contract_but_not_promotion_ready() -> None:
    report = evaluate_provider_verification(
        provider_id="local_csv_fixture",
        local_data_available=True,
        required_tables_available=True,
        required_fields_available=True,
        record_count=20,
        sample_validation_pass=True,
        identifier_mapping_available=True,
        point_in_time_universe_confirmed=True,
        delisting_coverage_confirmed=True,
        corporate_action_event_source_available=True,
        adjustment_reproducibility_confirmed=True,
        survivorship_clean=True,
        source_type="fixture",
    )

    assert report.promotion_clean is False
    assert "fixture_source_not_promotion_ready" in report.blockers


def test_adapter_outputs_are_json_serializable() -> None:
    membership = PointInTimeMembershipEvent(
        provider_id="local_csv",
        security_id="SEC1",
        ticker="ABC",
        event_type="add",
        effective_date="2020-01-02",
    )
    snapshot = PointInTimeUniverseSnapshot(
        provider_id="local_csv",
        universe_name="us_core",
        as_of_date="2020-01-02",
        symbols=["ABC"],
        securities=["SEC1"],
        symbol_count=1,
        membership_event_count=1,
        delisted_symbol_count=0,
        point_in_time_confirmed=True,
        survivorship_clean=False,
        source_hash="hash",
        blockers=["delisting_coverage_missing"],
    )
    action = CorporateActionEvent(
        provider_id="local_csv",
        security_id="SEC1",
        ticker="ABC",
        event_type="split",
        ex_date="2020-06-01",
        ratio=2.0,
    )

    json.dumps(membership.to_json_dict())
    json.dumps(snapshot.to_json_dict())
    json.dumps(action.to_json_dict())
