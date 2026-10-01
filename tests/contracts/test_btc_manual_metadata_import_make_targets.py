from __future__ import annotations

from pathlib import Path


MAKEFILE = Path("Makefile")


def test_btc_manual_metadata_import_make_targets_are_parameterized_and_fail_closed() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")

    assert "dry-run-btc-manual-metadata-import" in makefile
    assert "apply-btc-manual-metadata-import" in makefile
    assert "dry-run-btc-paper-gate-manual-inputs" in makefile
    assert "apply-btc-paper-gate-manual-inputs" in makefile
    assert "apply-and-validate-btc-paper-gate-manual-inputs" in makefile
    assert 'test -n "$(EXCHANGE_INFO_RAW)"' in makefile
    assert 'test -n "$(FUNDING_INFO_RAW)"' in makefile
    assert 'test -n "$(EXCHANGE_INFO_HTTP_STATUS)"' in makefile
    assert 'test -n "$(FUNDING_INFO_HTTP_STATUS)"' in makefile
    assert 'test -n "$(BTC_MANUAL_METADATA_CAPTURED_AT)"' in makefile
    assert '--exchange-info-raw "$(EXCHANGE_INFO_RAW)"' in makefile
    assert '--funding-info-raw "$(FUNDING_INFO_RAW)"' in makefile
    assert '--exchange-info-http-status "$(EXCHANGE_INFO_HTTP_STATUS)"' in makefile
    assert '--funding-info-http-status "$(FUNDING_INFO_HTTP_STATUS)"' in makefile
    assert "BTC_MANUAL_METADATA_IMPORT_REPORT ?= artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json" in makefile
    assert "BTC_MANUAL_METADATA_DRY_RUN_REPORT ?= artifacts/btc_data_status/latest/btc_manual_metadata_dry_run_report.json" in makefile
    assert "BTC_MANUAL_METADATA_CAPTURED_AT ?=" in makefile
    assert "BTC_PUBLIC_METADATA_RAW_CAPTURE_ROOT ?= artifacts/btc_data_status/latest/public_metadata_raw_capture" in makefile
    assert "capture-btc-public-metadata" in makefile
    assert "--raw-capture-root \"$(BTC_PUBLIC_METADATA_RAW_CAPTURE_ROOT)\"" in _target_body(
        makefile, "capture-btc-public-metadata"
    )
    assert '--report-output "$(BTC_MANUAL_METADATA_DRY_RUN_REPORT)"' in _target_body(
        makefile, "dry-run-btc-manual-metadata-import"
    )
    assert '--report-output "$(BTC_MANUAL_METADATA_IMPORT_REPORT)"' in _target_body(
        makefile, "apply-btc-manual-metadata-import"
    )
    assert '--report-output "$(BTC_MANUAL_METADATA_IMPORT_REPORT)"' not in _target_body(
        makefile, "dry-run-btc-manual-metadata-import"
    )
    assert '--captured-at "$(BTC_MANUAL_METADATA_CAPTURED_AT)"' in makefile
    assert "--dry-run" in _target_body(makefile, "dry-run-btc-manual-metadata-import")
    assert "--dry-run" not in _target_body(makefile, "apply-btc-manual-metadata-import")
    apply_manual_target = _target_body(makefile, "apply-btc-manual-metadata-import")
    assert apply_manual_target.count("$(MAKE) rebuild-btc-paper-readiness-chain") == 2
    assert "scripts/clear_btc_manual_metadata_import_marker.py" in apply_manual_target
    assert apply_manual_target.index("scripts/import_btc_manual_metadata_capture.py") < apply_manual_target.index(
        "$(MAKE) rebuild-btc-paper-readiness-chain"
    )
    assert apply_manual_target.index("$(MAKE) rebuild-btc-paper-readiness-chain") < apply_manual_target.index(
        "scripts/clear_btc_manual_metadata_import_marker.py"
    )
    assert apply_manual_target.index("scripts/clear_btc_manual_metadata_import_marker.py") < apply_manual_target.rindex(
        "$(MAKE) rebuild-btc-paper-readiness-chain"
    )
    assert "$(MAKE) rebuild-btc-paper-readiness-chain" not in _target_body(
        makefile, "dry-run-btc-manual-metadata-import"
    )
    dry_run_paper_gate = _target_body(makefile, "dry-run-btc-paper-gate-manual-inputs")
    apply_paper_gate = _target_body(makefile, "apply-btc-paper-gate-manual-inputs")
    apply_and_validate_paper_gate = _target_body(makefile, "apply-and-validate-btc-paper-gate-manual-inputs")
    for required_var in (
        "EXCHANGE_INFO_RAW",
        "FUNDING_INFO_RAW",
        "EXCHANGE_INFO_HTTP_STATUS",
        "FUNDING_INFO_HTTP_STATUS",
        "BTC_MANUAL_METADATA_CAPTURED_AT",
        "BTC_FEE_TIER_MAKER_BPS",
        "BTC_FEE_TIER_TAKER_BPS",
        "BTC_FEE_TIER_CAPTURED_AT",
    ):
        assert f'test -n "$({required_var})"' in dry_run_paper_gate
        assert f'test -n "$({required_var})"' in apply_paper_gate
    assert "$(MAKE) dry-run-btc-manual-metadata-import" in dry_run_paper_gate
    assert "$(MAKE) dry-run-btc-fee-tier-overlay-import" in dry_run_paper_gate
    assert "$(MAKE) dry-run-btc-manual-metadata-import" in apply_paper_gate
    assert "$(MAKE) dry-run-btc-fee-tier-overlay-import" in apply_paper_gate
    assert "$(MAKE) apply-btc-manual-metadata-import" in apply_paper_gate
    assert "$(MAKE) apply-btc-fee-tier-overlay-import" in apply_paper_gate
    assert "$(MAKE) apply-btc-manual-metadata-import" not in dry_run_paper_gate
    assert apply_paper_gate.index("$(MAKE) dry-run-btc-manual-metadata-import") < apply_paper_gate.index(
        "$(MAKE) apply-btc-manual-metadata-import"
    )
    assert apply_paper_gate.index("$(MAKE) dry-run-btc-fee-tier-overlay-import") < apply_paper_gate.index(
        "$(MAKE) apply-btc-fee-tier-overlay-import"
    )
    assert "$(MAKE) apply-btc-paper-gate-manual-inputs" in apply_and_validate_paper_gate
    assert "$(MAKE) validate-btc-evidence" in apply_and_validate_paper_gate
    assert "$(MAKE) check-btc-paper-validation-readiness" in apply_and_validate_paper_gate


def _target_body(makefile: str, target: str) -> str:
    marker = f"\n{target}:"
    start = makefile.index(marker)
    rest = makefile[start + 1 :]
    next_target = rest.find("\n\n")
    return rest if next_target == -1 else rest[:next_target]
