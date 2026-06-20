from __future__ import annotations

from pathlib import Path


READ_ONLY_BUILDERS = [
    Path("scripts/build_global_research_registry.py"),
    Path("scripts/build_us_equity_data_status_report.py"),
    Path("scripts/build_us_equity_factor_evidence_pack.py"),
    Path("scripts/build_us_equity_portfolio_canonical_report.py"),
    Path("scripts/build_us_equity_portfolio_fixture_event_ledger_report.py"),
    Path("scripts/build_us_equity_production_bundle_preflight_report.py"),
    Path("scripts/build_us_equity_provider_verification_report.py"),
    Path("scripts/build_btc_data_status_report.py"),
    Path("scripts/build_btc_perpetual_provider_verification_report.py"),
    Path("scripts/build_btc_funding_ledger_report.py"),
    Path("scripts/build_btc_cost_model_report.py"),
    Path("scripts/build_btc_fold_regime_contract_report.py"),
    Path("scripts/build_btc_tail_dependency_report.py"),
    Path("scripts/build_btc_candidate_gate_audit.py"),
    Path("scripts/build_btc_paper_readiness_report.py"),
    Path("scripts/build_btc_paper_validation_start_report.py"),
    Path("scripts/check_btc_paper_validation_readiness.py"),
    Path("scripts/build_btc_compression_expansion_attribution_bundle.py"),
    Path("scripts/build_btc_intraday_short_cycle_alpha_plan_report.py"),
    Path("scripts/build_btc_intraday_short_cycle_alpha_probe_report.py"),
    Path("scripts/build_btc_research_registry.py"),
    Path("scripts/check_artifact_lineage_health.py"),
]


def test_evidence_builders_do_not_import_broker_order_or_live_modules() -> None:
    forbidden_imports = [
        "from quant_us.live",
        "import quant_us.live",
        "from quant_us.execution",
        "import quant_us.execution",
        "from backend.app.services.us_quant",
        "import backend.app.services.us_quant",
    ]
    for path in READ_ONLY_BUILDERS:
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        for token in forbidden_imports:
            assert token not in source, f"{path} imports {token}"


def test_evidence_builders_do_not_call_order_submission_surfaces() -> None:
    forbidden_tokens = [
        "AlpacaBroker(",
        "IBKRBroker(",
        "LiveRuntime(",
        "PaperRuntime(",
        "submit_order(",
        "place_order(",
        "create_order(",
    ]
    for path in READ_ONLY_BUILDERS:
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            assert token not in source, f"{path} calls {token}"


def test_paper_queue_locked_in_global_registry_artifact() -> None:
    registry_path = Path("artifacts/global_research_registry/research_registry.json")
    if not registry_path.exists():
        return
    source = registry_path.read_text(encoding="utf-8")

    assert '"paper_queue_status": "locked"' in source
    assert '"live_status": "frozen"' in source
