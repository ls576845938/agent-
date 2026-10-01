from __future__ import annotations

from quant_us.data.lineage.local_csv_provider import verify_local_csv_provider
from tests.contracts.us_equity_local_csv_test_helpers import copy_fixture_bundle, provider_config


def test_valid_fixture_confirms_pit_and_survivorship_structurally(tmp_path) -> None:
    bundle_root = copy_fixture_bundle(tmp_path)

    report = verify_local_csv_provider(repo_root=tmp_path, config=provider_config(bundle_root))

    assert report.pit_validation["membership_events_available"] is True
    assert report.pit_validation["membership_event_count"] == 3
    assert report.pit_validation["point_in_time_universe_confirmed"] is True
    assert report.survivorship_validation["delisted_symbols_available"] is True
    assert report.survivorship_validation["delisted_symbol_count"] == 1
    assert report.survivorship_validation["delisting_coverage_confirmed"] is True
    assert report.survivorship_validation["survivorship_clean"] is True
    assert report.promotion_clean is False


def test_no_membership_events_blocks_pit(tmp_path) -> None:
    bundle_root = copy_fixture_bundle(tmp_path)
    (bundle_root / "universe_membership_events.csv").write_text(
        "security_id,ticker,universe_name,event_type,effective_date,end_date,source_record_id\n",
        encoding="utf-8",
    )

    report = verify_local_csv_provider(repo_root=tmp_path, config=provider_config(bundle_root))

    assert report.point_in_time_universe_confirmed is False
    assert "membership_events_missing" in report.blockers


def test_membership_delist_requires_delisted_symbol_record(tmp_path) -> None:
    bundle_root = copy_fixture_bundle(tmp_path)
    (bundle_root / "delisted_symbols.csv").write_text(
        "security_id,ticker,delisting_date,delisting_reason,last_trade_date,delisting_return,source_record_id\n",
        encoding="utf-8",
    )

    report = verify_local_csv_provider(repo_root=tmp_path, config=provider_config(bundle_root))

    assert report.delisting_coverage_confirmed is False
    assert "membership_delist_without_delisted_symbol_record" in report.blockers


def test_delisted_symbol_requires_membership_remove_or_delist(tmp_path) -> None:
    bundle_root = copy_fixture_bundle(tmp_path)
    text = (bundle_root / "universe_membership_events.csv").read_text(encoding="utf-8").replace(",delist,", ",exchange_change,")
    (bundle_root / "universe_membership_events.csv").write_text(text, encoding="utf-8")

    report = verify_local_csv_provider(repo_root=tmp_path, config=provider_config(bundle_root))

    assert report.survivorship_clean is False
    assert "delisted_symbol_without_membership_remove_or_delist" in report.blockers
