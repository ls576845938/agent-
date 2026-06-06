from __future__ import annotations

from pathlib import Path

from quant_us.data.lineage.local_csv_provider import verify_local_csv_provider
from tests.contracts.us_equity_local_csv_test_helpers import copy_fixture_bundle, load_manifest, provider_config, write_manifest


def test_missing_required_file_fails(tmp_path: Path) -> None:
    bundle_root = copy_fixture_bundle(tmp_path)
    (bundle_root / "corporate_actions.csv").unlink()

    report = verify_local_csv_provider(repo_root=tmp_path, config=provider_config(bundle_root))

    assert report.required_tables_available is False
    assert "local_csv_corporate_actions_file_missing" in report.blockers


def test_missing_required_field_fails(tmp_path: Path) -> None:
    bundle_root = copy_fixture_bundle(tmp_path)
    (bundle_root / "universe_membership_events.csv").write_text("security_id,ticker\nSEC1,ABC\n", encoding="utf-8")

    report = verify_local_csv_provider(repo_root=tmp_path, config=provider_config(bundle_root))

    assert report.required_fields_available is False
    assert "local_csv_universe_membership_events_universe_name_missing" in report.blockers


def test_invalid_date_fails(tmp_path: Path) -> None:
    bundle_root = copy_fixture_bundle(tmp_path)
    text = (bundle_root / "universe_membership_events.csv").read_text(encoding="utf-8").replace("2020-01-01", "bad-date", 1)
    (bundle_root / "universe_membership_events.csv").write_text(text, encoding="utf-8")

    report = verify_local_csv_provider(repo_root=tmp_path, config=provider_config(bundle_root))

    assert report.structural_validation["date_validation_pass"] is False
    assert "local_csv_universe_membership_events_effective_date_invalid_date" in report.blockers


def test_invalid_event_type_fails(tmp_path: Path) -> None:
    bundle_root = copy_fixture_bundle(tmp_path)
    text = (bundle_root / "corporate_actions.csv").read_text(encoding="utf-8").replace("split", "bad_event", 1)
    (bundle_root / "corporate_actions.csv").write_text(text, encoding="utf-8")

    report = verify_local_csv_provider(repo_root=tmp_path, config=provider_config(bundle_root))

    assert report.structural_validation["event_type_validation_pass"] is False
    assert "local_csv_corporate_actions_event_type_invalid" in report.blockers


def test_duplicated_source_record_id_fails(tmp_path: Path) -> None:
    bundle_root = copy_fixture_bundle(tmp_path)
    text = (bundle_root / "delisted_symbols.csv").read_text(encoding="utf-8").replace("fixture-delisted-1", "fixture-membership-1")
    (bundle_root / "delisted_symbols.csv").write_text(text, encoding="utf-8")

    report = verify_local_csv_provider(repo_root=tmp_path, config=provider_config(bundle_root))

    assert report.structural_validation["duplicate_source_record_id_validation_pass"] is False
    assert "duplicate_source_record_id" in report.blockers


def test_empty_csv_fails(tmp_path: Path) -> None:
    bundle_root = copy_fixture_bundle(tmp_path)
    (bundle_root / "delisted_symbols.csv").write_text(
        "security_id,ticker,delisting_date,delisting_reason,last_trade_date,delisting_return,source_record_id\n",
        encoding="utf-8",
    )

    report = verify_local_csv_provider(repo_root=tmp_path, config=provider_config(bundle_root))

    assert report.required_tables_available is False
    assert "local_csv_delisted_symbols_empty" in report.blockers


def test_missing_symbol_mapping_fails(tmp_path: Path) -> None:
    bundle_root = copy_fixture_bundle(tmp_path)
    (bundle_root / "symbol_mapping.csv").unlink()

    report = verify_local_csv_provider(repo_root=tmp_path, config=provider_config(bundle_root))

    assert report.identifier_mapping_available is False
    assert "local_csv_symbol_mapping_file_missing" in report.blockers


def test_overlapping_symbol_mapping_fails(tmp_path: Path) -> None:
    bundle_root = copy_fixture_bundle(tmp_path)
    with (bundle_root / "symbol_mapping.csv").open("a", encoding="utf-8") as handle:
        handle.write("SEC3,ABC,2020-06-01,2022-01-01,,,,,,XNYS,fixture-map-3\n")

    report = verify_local_csv_provider(repo_root=tmp_path, config=provider_config(bundle_root))

    assert report.structural_validation["symbol_mapping_validation_pass"] is False
    assert "local_csv_symbol_mapping_overlap:ABC" in report.blockers


def test_valid_fixture_passes_structural_validation_but_not_promotion_clean(tmp_path: Path) -> None:
    bundle_root = copy_fixture_bundle(tmp_path, source_type="fixture")

    report = verify_local_csv_provider(repo_root=tmp_path, config=provider_config(bundle_root))

    assert report.required_tables_available is True
    assert report.required_fields_available is True
    assert report.structural_validation["symbol_mapping_validation_pass"] is True
    assert report.promotion_clean is False
    assert "fixture_source_not_promotion_ready" in report.blockers
