from __future__ import annotations

from quant_us.data.lineage.local_csv_provider import verify_local_csv_provider
from tests.contracts.us_equity_local_csv_test_helpers import copy_fixture_bundle, provider_config


def test_valid_fixture_confirms_corporate_action_and_adjustment_replay_structurally(tmp_path) -> None:
    bundle_root = copy_fixture_bundle(tmp_path)

    report = verify_local_csv_provider(repo_root=tmp_path, config=provider_config(bundle_root))

    assert report.corporate_action_validation["corporate_action_events_available"] is True
    assert report.corporate_action_validation["split_events_available"] is True
    assert report.corporate_action_validation["dividend_events_available"] is True
    assert report.corporate_action_validation["symbol_change_events_available"] is True
    assert report.adjustment_replay_validation["adjustment_replay_available"] is True
    assert report.adjustment_replay_validation["max_replay_error"] == 0.0
    assert report.adjustment_replay_validation["adjustment_reproducibility_confirmed"] is True
    assert report.promotion_clean is False


def test_missing_corporate_actions_blocks_event_source(tmp_path) -> None:
    bundle_root = copy_fixture_bundle(tmp_path)
    (bundle_root / "corporate_actions.csv").write_text(
        "security_id,ticker,event_type,ex_date,effective_date,ratio,cash_amount,old_symbol,new_symbol,source_record_id\n",
        encoding="utf-8",
    )

    report = verify_local_csv_provider(repo_root=tmp_path, config=provider_config(bundle_root))

    assert report.corporate_action_event_source_available is False
    assert "corporate_action_event_source_missing" in report.blockers


def test_adjustment_replay_missing_blocks_reproducibility(tmp_path) -> None:
    bundle_root = copy_fixture_bundle(tmp_path)
    (bundle_root / "adjustment_replay.csv").unlink()

    report = verify_local_csv_provider(repo_root=tmp_path, config=provider_config(bundle_root))

    assert report.adjustment_reproducibility_confirmed is False
    assert "local_csv_adjustment_replay_file_missing" in report.blockers


def test_replay_error_missing_blocks_reproducibility(tmp_path) -> None:
    bundle_root = copy_fixture_bundle(tmp_path)
    text = (bundle_root / "adjustment_replay.csv").read_text(encoding="utf-8").replace(",0.0,fixture-replay-1", ",,fixture-replay-1", 1)
    (bundle_root / "adjustment_replay.csv").write_text(text, encoding="utf-8")

    report = verify_local_csv_provider(repo_root=tmp_path, config=provider_config(bundle_root))

    assert report.adjustment_reproducibility_confirmed is False
    assert "adjustment_replay_error_missing" in report.blockers


def test_replay_error_above_tolerance_blocks_reproducibility(tmp_path) -> None:
    bundle_root = copy_fixture_bundle(tmp_path)
    text = (bundle_root / "adjustment_replay.csv").read_text(encoding="utf-8").replace(",0.0,fixture-replay-1", ",0.01,fixture-replay-1", 1)
    (bundle_root / "adjustment_replay.csv").write_text(text, encoding="utf-8")

    report = verify_local_csv_provider(repo_root=tmp_path, config=provider_config(bundle_root))

    assert report.adjustment_reproducibility_confirmed is False
    assert "adjustment_replay_error_above_tolerance" in report.blockers
