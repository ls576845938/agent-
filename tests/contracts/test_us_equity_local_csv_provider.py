from __future__ import annotations

from pathlib import Path

from quant_us.data.lineage.local_csv_provider import verify_local_csv_provider
from tests.contracts.us_equity_local_csv_test_helpers import copy_fixture_bundle, provider_config


def test_local_csv_disabled_fails_closed(tmp_path: Path) -> None:
    report = verify_local_csv_provider(
        repo_root=tmp_path,
        config={"providers": {"local_csv": {"enabled": False}}},
    )

    assert report.promotion_clean is False
    assert "local_csv_provider_disabled" in report.blockers


def test_local_csv_missing_files_fail_closed(tmp_path: Path) -> None:
    config = {
        "providers": {
            "local_csv": {
                "enabled": True,
                "root": "lineage",
                "files": {},
            }
        }
    }

    report = verify_local_csv_provider(repo_root=tmp_path, config=config)

    assert report.required_tables_available is False
    assert "local_csv_universe_membership_events_file_missing" in report.blockers


def test_local_csv_missing_required_fields_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "lineage"
    root.mkdir()
    _write(root / "membership.csv", "security_id,ticker\nSEC1,ABC\n")
    config = _config(root_name="lineage", membership="membership.csv")

    report = verify_local_csv_provider(repo_root=tmp_path, config=config)

    assert report.required_fields_available is False
    assert "local_csv_universe_membership_events_universe_name_missing" in report.blockers


def test_local_csv_invalid_dates_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "lineage"
    _write_complete_files(root, invalid_date=True)
    config = _complete_config(root_name="lineage")

    report = verify_local_csv_provider(repo_root=tmp_path, config=config)

    assert report.sample_validation_pass is False
    assert "local_csv_universe_membership_events_effective_date_invalid_date" in report.blockers


def test_local_csv_valid_fixture_passes_structural_contract_but_not_promotion(tmp_path: Path) -> None:
    bundle_root = copy_fixture_bundle(tmp_path, source_type="fixture")

    report = verify_local_csv_provider(repo_root=tmp_path, config=provider_config(bundle_root))

    assert report.point_in_time_universe_confirmed is True
    assert report.delisting_coverage_confirmed is True
    assert report.corporate_action_event_source_available is True
    assert report.identifier_mapping_available is True
    assert report.adjustment_reproducibility_confirmed is True
    assert report.survivorship_clean is True
    assert report.promotion_clean is False
    assert "fixture_source_not_promotion_ready" in report.blockers


def _config(*, root_name: str, membership: str) -> dict[str, object]:
    return {
        "providers": {
            "local_csv": {
                "enabled": True,
                "root": root_name,
                "files": {
                    "universe_membership_events": membership,
                    "delisted_symbols": None,
                    "corporate_actions": None,
                    "symbol_mapping": None,
                },
            }
        }
    }


def _complete_config(*, root_name: str, adjustment_replay_report: str | None = None) -> dict[str, object]:
    provider = {
        "enabled": True,
        "root": root_name,
        "files": {
            "universe_membership_events": "membership.csv",
            "delisted_symbols": "delisted.csv",
            "corporate_actions": "actions.csv",
            "symbol_mapping": "mapping.csv",
        },
    }
    if adjustment_replay_report:
        provider["adjustment_replay_report"] = adjustment_replay_report
    return {"providers": {"local_csv": provider}}


def _write_complete_files(root: Path, *, invalid_date: bool = False) -> None:
    root.mkdir(parents=True, exist_ok=True)
    effective_date = "bad-date" if invalid_date else "2020-01-02"
    _write(
        root / "membership.csv",
        (
            "security_id,ticker,universe_name,event_type,effective_date,end_date,source_record_id\n"
            f"SEC1,ABC,us_core,add,{effective_date},,m1\n"
        ),
    )
    _write(
        root / "delisted.csv",
        (
            "security_id,ticker,delisting_date,delisting_reason,last_trade_date,source_record_id\n"
            "SEC2,XYZ,2021-01-03,merger,2021-01-02,d1\n"
        ),
    )
    _write(
        root / "actions.csv",
        (
            "security_id,ticker,event_type,ex_date,effective_date,ratio,cash_amount,old_symbol,new_symbol,source_record_id\n"
            "SEC1,ABC,split,2020-06-01,2020-06-01,2.0,,,,a1\n"
        ),
    )
    _write(
        root / "mapping.csv",
        (
            "security_id,ticker,start_date,end_date,figi,cik,cusip,permno,exchange,source_record_id\n"
            "SEC1,ABC,2020-01-01,,,,,,XNYS,s1\n"
        ),
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
