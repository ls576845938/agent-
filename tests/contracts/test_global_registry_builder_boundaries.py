from __future__ import annotations

from pathlib import Path


REGISTRY_BUILDER = Path("scripts/build_global_research_registry.py")
US_EQUITY_STATUS_BUILDER = Path("scripts/build_us_equity_data_status_report.py")
READ_ONLY_BUILDERS = [
    REGISTRY_BUILDER,
    US_EQUITY_STATUS_BUILDER,
    Path("scripts/build_us_equity_factor_evidence_pack.py"),
    Path("scripts/build_us_equity_portfolio_canonical_report.py"),
    Path("scripts/build_btc_data_status_report.py"),
    Path("scripts/build_btc_perpetual_provider_verification_report.py"),
    Path("scripts/build_btc_funding_ledger_report.py"),
    Path("scripts/build_btc_cost_model_report.py"),
    Path("scripts/build_btc_fold_regime_contract_report.py"),
    Path("scripts/build_btc_tail_dependency_report.py"),
    Path("scripts/build_btc_candidate_gate_audit.py"),
    Path("scripts/build_btc_compression_expansion_attribution_bundle.py"),
    Path("scripts/build_btc_intraday_short_cycle_alpha_plan_report.py"),
    Path("scripts/build_btc_intraday_short_cycle_alpha_probe_report.py"),
    Path("scripts/build_btc_intraday_short_cycle_alpha_refinement_report.py"),
    Path("scripts/build_btc_research_registry.py"),
]


def test_global_registry_builder_has_no_runtime_or_broker_imports() -> None:
    forbidden_imports = [
        "from quant_us.live",
        "import quant_us.live",
        "from quant_us.execution",
        "import quant_us.execution",
        "from backend.app.services.us_quant",
        "import backend.app.services.us_quant",
    ]
    for path in READ_ONLY_BUILDERS:
        source = path.read_text(encoding="utf-8")
        for forbidden in forbidden_imports:
            assert forbidden not in source, path


def test_global_registry_builder_does_not_call_order_submission_surfaces() -> None:
    forbidden_runtime_tokens = [
        "AlpacaBroker(",
        "LiveRuntime(",
        "PaperRuntime(",
        "submit_order(",
        "place_order(",
        "create_order(",
    ]
    for path in READ_ONLY_BUILDERS:
        source = path.read_text(encoding="utf-8")
        for forbidden in forbidden_runtime_tokens:
            assert forbidden not in source, path


def test_read_only_evidence_builders_exist() -> None:
    for path in READ_ONLY_BUILDERS:
        assert path.exists(), path
