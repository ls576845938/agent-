from __future__ import annotations

from pathlib import Path


MAKEFILE = Path("Makefile")
OPERATOR_GUIDE = Path("docs/btc_binance_usdm_public_data_operator_guide.md")


def test_btc_live_metadata_evidence_restore_target_is_explicit_and_live_only() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")

    assert "restore-btc-live-metadata-evidence" in makefile
    assert "scripts/build_btc_public_metadata_capture_attempt_report.py" in makefile
    assert "--execute-network" in makefile
    assert '--raw-capture-root "$(BTC_PUBLIC_METADATA_RAW_CAPTURE_ROOT)"' in makefile
    assert "scripts/build_btc_manual_metadata_capture_operator_packet.py" in makefile
    assert "scripts/build_btc_objective_completion_audit_report.py" in makefile
    assert "scripts/build_btc_data_status_report.py" in makefile
    assert "scripts/build_btc_cost_model_report.py" in makefile
    assert "scripts/build_btc_candidate_gate_audit.py" in makefile
    assert "scripts/build_btc_paper_readiness_report.py" in makefile
    assert "scripts/build_btc_paper_validation_start_report.py" in makefile
    assert "$(MAKE) rebuild-btc-paper-readiness-chain" in _target_body(
        makefile, "restore-btc-live-metadata-evidence"
    )
    assert "scripts/check_artifact_lineage_health.py --stale-after-hours 1000000" in makefile
    assert makefile.index("scripts/build_btc_research_registry.py") < makefile.index(
        "scripts/build_btc_paper_readiness_report.py"
    )
    assert makefile.index("scripts/build_global_research_registry.py") < makefile.index(
        "scripts/build_btc_paper_readiness_report.py"
    )
    assert makefile.index("scripts/build_btc_paper_readiness_report.py") < makefile.index(
        "scripts/build_btc_paper_validation_start_report.py"
    )


def test_btc_operator_guide_mentions_restore_target_after_dry_run_validation() -> None:
    guide = OPERATOR_GUIDE.read_text(encoding="utf-8")

    assert "make restore-btc-live-metadata-evidence" in guide
    assert "dry-run validation target" in guide


def _target_body(makefile: str, target: str) -> str:
    marker = f"\n{target}:"
    start = makefile.index(marker)
    rest = makefile[start + 1 :]
    next_target = rest.find("\n\n")
    return rest if next_target == -1 else rest[:next_target]
