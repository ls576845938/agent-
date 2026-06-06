from __future__ import annotations

from pathlib import Path

from quant_us.data.lineage.local_csv_provider import verify_local_csv_provider
from tests.contracts.us_equity_local_csv_test_helpers import FIXTURE_ROOT, provider_config


def test_fixture_bundle_exists_for_tests_only() -> None:
    assert (FIXTURE_ROOT / "provider_bundle_manifest.json").exists()
    assert (FIXTURE_ROOT / "universe_membership_events.csv").exists()
    assert (FIXTURE_ROOT / "delisted_symbols.csv").exists()
    assert (FIXTURE_ROOT / "corporate_actions.csv").exists()
    assert (FIXTURE_ROOT / "symbol_mapping.csv").exists()
    assert (FIXTURE_ROOT / "adjustment_replay.csv").exists()


def test_fixture_bundle_structural_pass_but_never_promotion_clean() -> None:
    config = provider_config(FIXTURE_ROOT.resolve())

    report = verify_local_csv_provider(repo_root=Path.cwd(), config=config)

    assert report.source_type == "fixture"
    assert report.required_tables_available is True
    assert report.required_fields_available is True
    assert report.point_in_time_universe_confirmed is True
    assert report.adjustment_reproducibility_confirmed is True
    assert report.promotion_clean is False
    assert "fixture_source_not_promotion_ready" in report.blockers
