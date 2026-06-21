PYTHON ?= python3
BTC_MANUAL_METADATA_IMPORT_REPORT ?= artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json
BTC_MANUAL_METADATA_DRY_RUN_REPORT ?= artifacts/btc_data_status/latest/btc_manual_metadata_dry_run_report.json
BTC_MANUAL_METADATA_CAPTURED_AT ?=
EXCHANGE_INFO_HTTP_STATUS ?= exchange_info_http_status.txt
FUNDING_INFO_HTTP_STATUS ?= funding_info_http_status.txt
BTC_PUBLIC_METADATA_RAW_CAPTURE_ROOT ?= artifacts/btc_data_status/latest/public_metadata_raw_capture
BTC_FEE_TIER_IMPORT_REPORT ?= artifacts/btc_cost_model/latest/btc_fee_tier_overlay_import_report.json
BTC_FEE_TIER_DRY_RUN_REPORT ?= artifacts/btc_cost_model/latest/btc_fee_tier_overlay_dry_run_report.json
BTC_FEE_TIER_OVERLAY ?= artifacts/btc_cost_model/latest/btc_fee_tier_overlay.json
BTC_FEE_TIER_CAPTURED_AT ?=
BTC_FEE_TIER_MAKER_BPS ?=
BTC_FEE_TIER_TAKER_BPS ?=
BTC_FEE_TIER_SOURCE ?= manual_public_okx_swap_fee_schedule
BTC_FEE_TIER_SOURCE_URL_OR_DOC ?= https://www.okx.com/en-us/fees
BTC_PAPER_SYMBOLS ?= BTCUSDT
BTC_PAPER_MARKET_TYPE ?= usds_m_perpetual
BTC_PAPER_INTERVAL ?= 1h
BTC_PAPER_LEDGER_ROOT ?= data/paper_ledger/btc
BTC_PAPER_DATA_ROOT ?= data
BTC_PAPER_START ?=
BTC_PAPER_END ?=
BTC_PAPER_CYCLE_HOURS ?= 24
BTC_PAPER_DAYS_REQUIRED ?= 30
BTC_OKX_HISTORY_DAYS ?= 365
BTC_OKX_HISTORY_BUNDLE_ID ?= btc_okx_swap_btcusdt_history_365d_v1
BTC_OKX_L2_SAMPLE_COUNT ?= 5
BTC_OKX_L2_REQUEST_SLEEP_SECONDS ?= 0.2
BTC_OKX_ALIGNED_L2_SAMPLE_COUNT ?= 6
BTC_OKX_ALIGNED_L2_REQUEST_SLEEP_SECONDS ?= 0.25
BTC_OKX_PUBLIC_WS_L2_DURATION_SECONDS ?= 10
BTC_OKX_PUBLIC_WS_L2_MAX_MESSAGES ?= 2000
BTC_OKX_PUBLIC_WS_L2_FORCED_RECONNECT_AFTER_MESSAGES ?= 0
BTC_OKX_PUBLIC_WS_L2_SEGMENT_ID ?=

.PHONY: test test-unit test-integration test-e2e frontend-build ci-local \
	validate-contracts validate-us-equity-evidence validate-btc-evidence \
	validate-candidate-gate validate-us-equity-production-bundle \
	validate-us-equity-production-bundle-strict build-artifact-health \
	validate-portfolio-fixture-ledger validate-no-production-data-hardening \
	validate-btc-data-cost-repair validate-btc-public-data-bundle \
	validate-btc-public-data-bundle-strict restore-btc-live-metadata-evidence \
	capture-btc-okx-public-bundle capture-btc-okx-public-history \
	dry-run-btc-okx-microstructure-capture capture-btc-okx-microstructure \
	dry-run-btc-okx-l2-microstructure-samples capture-btc-okx-l2-microstructure-samples \
	dry-run-btc-okx-timestamp-aligned-l2-capture capture-btc-okx-timestamp-aligned-l2-capture \
	dry-run-btc-okx-public-ws-l2-raw-capture capture-btc-okx-public-ws-l2-raw-capture \
	dry-run-btc-okx-public-ws-l2-segment-capture capture-btc-okx-public-ws-l2-segment-capture \
	dry-run-btc-manual-metadata-import apply-btc-manual-metadata-import \
	dry-run-btc-fee-tier-overlay-import apply-btc-fee-tier-overlay-import \
	dry-run-btc-paper-gate-manual-inputs apply-btc-paper-gate-manual-inputs \
	apply-and-validate-btc-paper-gate-manual-inputs \
	check-btc-candidate-bounded-retest-readiness build-btc-candidate-bounded-retest-outcome \
	build-btc-next-hypothesis-decision build-btc-strategy-family-roadmap \
	build-btc-intraday-short-cycle-alpha-plan \
	build-btc-intraday-short-cycle-alpha-probe \
	build-btc-intraday-short-cycle-alpha-refinement \
	build-btc-intraday-short-cycle-event-ledger \
	build-btc-intraday-short-cycle-event-definition-repair \
	build-btc-intraday-short-cycle-repaired-event-ledger \
	build-btc-intraday-short-cycle-drift-guarded-event-ledger \
	build-btc-intraday-short-cycle-promotion-gate \
	build-btc-intraday-short-cycle-manual-review-packet \
	build-btc-intraday-short-cycle-research-candidate-definition-preflight \
	build-btc-intraday-short-cycle-research-candidate-definition-manifest \
	build-btc-intraday-short-cycle-remaining-external-evidence-status \
	build-btc-intraday-drift-guarded-fold-regime-source-reports \
	build-btc-true-scalping-microstructure-models \
	build-btc-true-scalping-microstructure-readiness \
	build-btc-true-scalping-l2-sample-quality \
	build-btc-true-scalping-l2-feature-diagnostics \
	build-btc-true-scalping-timestamp-aligned-l2-data-contract \
	build-btc-true-scalping-l2-aligned-capture-quality \
	build-btc-true-scalping-ws-l2-raw-capture-quality \
	build-btc-true-scalping-ws-order-book-replay \
	build-btc-true-scalping-ws-reconnect-resync-policy \
	build-btc-true-scalping-ws-latency-queue-diagnostics \
	build-btc-true-scalping-ws-l2-capture-coverage \
	build-btc-true-scalping-long-horizon-l2-tick-import-contract \
	build-btc-true-scalping-execution-queue-external-evidence-contract \
	build-btc-true-scalping-1m-proxy-feature-redesign \
	build-btc-true-scalping-research-design-review \
	build-btc-true-scalping-research-design \
	build-btc-true-scalping-event-ledger-prototype \
	build-btc-true-scalping-event-definition-redesign \
	run-btc-scalping-research-backtest \
	build-btc-data-source-decision \
	capture-btc-public-metadata build-global-registry build-btc-paper-readiness \
	build-btc-paper-validation-start rebuild-btc-paper-readiness-chain \
	check-btc-paper-validation-static-preflight \
	check-btc-paper-validation-readiness start-btc-paper-validation \
	resume-btc-paper-validation

test:
	$(PYTHON) -m pytest backend/tests/ -q -m "not integration_live and not slow" --tb=short

test-unit:
	$(PYTHON) -m pytest backend/tests/ -q -m "not integration and not integration_live and not slow" --tb=short

test-integration:
	$(PYTHON) -m pytest backend/tests/ -q -m "integration and not integration_live" --tb=short

test-e2e:
	cd frontend && npx playwright test

frontend-build:
	cd frontend && npm ci && npx tsc --noEmit && npm run build

build-global-registry:
	$(PYTHON) scripts/build_us_equity_data_status_report.py
	$(PYTHON) scripts/run_us_equity_factor_evidence.py
	$(PYTHON) scripts/build_us_equity_portfolio_canonical_report.py
	$(PYTHON) scripts/build_btc_perpetual_bundle_preflight_report.py
	$(PYTHON) scripts/build_btc_funding_rate_gap_report.py
	$(PYTHON) scripts/build_btc_perpetual_provider_verification_report.py
	$(PYTHON) scripts/build_btc_public_metadata_capture_attempt_report.py
	$(PYTHON) scripts/build_btc_manual_metadata_capture_readiness_report.py
	$(PYTHON) scripts/build_btc_manual_metadata_capture_operator_packet.py
	$(PYTHON) scripts/build_btc_perpetual_data_source_decision_report.py
	$(PYTHON) scripts/build_btc_objective_completion_audit_report.py
	$(PYTHON) scripts/build_btc_data_status_report.py
	$(PYTHON) scripts/build_btc_funding_ledger_report.py
	$(PYTHON) scripts/build_btc_cost_model_report.py
	$(PYTHON) scripts/build_btc_fold_regime_contract_report.py
	$(PYTHON) scripts/build_btc_tail_dependency_report.py
	$(PYTHON) scripts/build_btc_candidate_gate_audit.py
	$(PYTHON) scripts/build_btc_candidate_metric_repair_report.py
	$(PYTHON) scripts/build_btc_candidate_bounded_retest_plan.py
	$(PYTHON) scripts/build_btc_candidate_bounded_retest_outcome_report.py
	$(PYTHON) scripts/build_btc_next_hypothesis_decision_report.py
	$(PYTHON) scripts/build_btc_strategy_family_roadmap_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_alpha_plan_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_alpha_probe_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_alpha_refinement_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_event_definition_repair_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_repaired_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_drift_guarded_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_drift_guarded_fold_regime_source_reports.py
	$(PYTHON) scripts/build_btc_fold_regime_contract_report.py
	$(PYTHON) scripts/build_btc_data_status_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_drift_guarded_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_promotion_gate_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_manual_review_packet.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_research_candidate_definition_preflight.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_research_candidate_definition_manifest.py
	$(PYTHON) scripts/build_btc_true_scalping_long_horizon_l2_tick_import_contract_report.py
	$(PYTHON) scripts/build_btc_true_scalping_execution_queue_external_evidence_contract_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_remaining_external_evidence_status.py
	$(PYTHON) scripts/build_btc_true_scalping_microstructure_readiness_report.py
	$(PYTHON) scripts/build_btc_compression_expansion_attribution_bundle.py
	$(PYTHON) scripts/build_btc_research_registry.py
	$(PYTHON) scripts/build_global_research_registry.py
	$(PYTHON) scripts/build_btc_paper_readiness_report.py
	$(PYTHON) scripts/build_btc_paper_validation_start_report.py

build-btc-paper-readiness:
	$(PYTHON) scripts/build_btc_paper_readiness_report.py

build-btc-paper-validation-start:
	$(PYTHON) scripts/build_btc_paper_validation_start_report.py

check-btc-paper-validation-static-preflight:
	$(MAKE) rebuild-btc-paper-readiness-chain
	$(PYTHON) scripts/check_btc_paper_validation_readiness.py \
		--repo-root "." \
		--symbols "$(BTC_PAPER_SYMBOLS)" \
		--market-type "$(BTC_PAPER_MARKET_TYPE)" \
		--interval "$(BTC_PAPER_INTERVAL)" \
		--ledger-root "$(BTC_PAPER_LEDGER_ROOT)" \
		--data-root "$(BTC_PAPER_DATA_ROOT)" \
		--no-start-report-ready-required \
		--json

check-btc-paper-validation-readiness:
	$(MAKE) rebuild-btc-paper-readiness-chain
	$(PYTHON) scripts/check_btc_paper_validation_readiness.py \
		--repo-root "." \
		--symbols "$(BTC_PAPER_SYMBOLS)" \
		--market-type "$(BTC_PAPER_MARKET_TYPE)" \
		--interval "$(BTC_PAPER_INTERVAL)" \
		--ledger-root "$(BTC_PAPER_LEDGER_ROOT)" \
		--data-root "$(BTC_PAPER_DATA_ROOT)" \
		--json

start-btc-paper-validation:
	$(MAKE) rebuild-btc-paper-readiness-chain
	$(PYTHON) scripts/run_btc_paper_validation.py \
		--repo-root "." \
		--symbols "$(BTC_PAPER_SYMBOLS)" \
		--market-type "$(BTC_PAPER_MARKET_TYPE)" \
		--interval "$(BTC_PAPER_INTERVAL)" \
		--ledger-root "$(BTC_PAPER_LEDGER_ROOT)" \
		--data-root "$(BTC_PAPER_DATA_ROOT)" \
		--days-required "$(BTC_PAPER_DAYS_REQUIRED)" \
		--cycle-hours "$(BTC_PAPER_CYCLE_HOURS)" \
		--start "$(BTC_PAPER_START)" \
		--end "$(BTC_PAPER_END)" \
		--json

resume-btc-paper-validation:
	$(MAKE) rebuild-btc-paper-readiness-chain
	$(PYTHON) scripts/run_btc_paper_validation.py \
		--repo-root "." \
		--symbols "$(BTC_PAPER_SYMBOLS)" \
		--market-type "$(BTC_PAPER_MARKET_TYPE)" \
		--interval "$(BTC_PAPER_INTERVAL)" \
		--ledger-root "$(BTC_PAPER_LEDGER_ROOT)" \
		--data-root "$(BTC_PAPER_DATA_ROOT)" \
		--days-required "$(BTC_PAPER_DAYS_REQUIRED)" \
		--cycle-hours "$(BTC_PAPER_CYCLE_HOURS)" \
		--start "$(BTC_PAPER_START)" \
		--end "$(BTC_PAPER_END)" \
		--resume \
		--json

rebuild-btc-paper-readiness-chain:
	$(PYTHON) scripts/build_btc_perpetual_bundle_preflight_report.py
	$(PYTHON) scripts/build_btc_perpetual_provider_verification_report.py
	$(PYTHON) scripts/build_btc_manual_metadata_capture_readiness_report.py
	$(PYTHON) scripts/build_btc_manual_metadata_capture_operator_packet.py
	$(PYTHON) scripts/build_btc_perpetual_data_source_decision_report.py
	$(PYTHON) scripts/build_btc_objective_completion_audit_report.py
	$(PYTHON) scripts/build_btc_data_status_report.py
	$(PYTHON) scripts/build_btc_funding_ledger_report.py
	$(PYTHON) scripts/build_btc_cost_model_report.py
	$(PYTHON) scripts/build_btc_fold_regime_contract_report.py
	$(PYTHON) scripts/build_btc_tail_dependency_report.py
	$(PYTHON) scripts/build_btc_candidate_gate_audit.py
	$(PYTHON) scripts/build_btc_candidate_metric_repair_report.py
	$(PYTHON) scripts/build_btc_candidate_bounded_retest_plan.py
	$(PYTHON) scripts/build_btc_candidate_bounded_retest_outcome_report.py
	$(PYTHON) scripts/build_btc_next_hypothesis_decision_report.py
	$(PYTHON) scripts/build_btc_strategy_family_roadmap_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_alpha_plan_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_alpha_probe_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_alpha_refinement_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_event_definition_repair_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_repaired_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_drift_guarded_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_drift_guarded_fold_regime_source_reports.py
	$(PYTHON) scripts/build_btc_fold_regime_contract_report.py
	$(PYTHON) scripts/build_btc_data_status_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_drift_guarded_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_promotion_gate_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_manual_review_packet.py
	$(PYTHON) scripts/build_btc_compression_expansion_attribution_bundle.py
	$(PYTHON) scripts/build_btc_research_registry.py
	$(PYTHON) scripts/build_global_research_registry.py
	$(PYTHON) scripts/build_btc_paper_readiness_report.py
	$(PYTHON) scripts/build_btc_paper_validation_start_report.py

build-artifact-health:
	$(PYTHON) scripts/check_artifact_lineage_health.py

validate-portfolio-fixture-ledger:
	$(PYTHON) scripts/build_us_equity_portfolio_fixture_event_ledger_report.py
	$(PYTHON) scripts/build_us_equity_portfolio_canonical_report.py
	$(PYTHON) -m pytest tests/contracts/test_us_equity_portfolio_fixture_event_ledger.py tests/contracts/test_us_equity_portfolio_ledger_required.py -q

validate-contracts:
	$(PYTHON) -m pytest tests/contracts -q

validate-us-equity-evidence:
	$(PYTHON) scripts/build_us_equity_production_bundle_preflight_report.py
	$(PYTHON) scripts/build_us_equity_data_status_report.py
	$(PYTHON) scripts/run_us_equity_factor_evidence.py
	$(PYTHON) scripts/build_us_equity_portfolio_canonical_report.py
	$(PYTHON) scripts/build_global_research_registry.py
	$(PYTHON) -m pytest tests/contracts/test_us_equity_data_status_report.py tests/contracts/test_us_equity_factor_evidence_pack.py tests/contracts/test_us_equity_portfolio_canonical_report.py tests/contracts/test_us_equity_global_registry_contract.py -q

validate-us-equity-production-bundle:
	$(PYTHON) scripts/build_us_equity_production_bundle_preflight_report.py
	$(PYTHON) scripts/build_us_equity_provider_verification_report.py
	$(PYTHON) -m pytest tests/contracts/test_us_equity_production_bundle_preflight_report.py tests/contracts/test_us_equity_local_csv_bundle_selection_config.py tests/contracts/test_us_equity_provider_verification_preflight_integration.py -q

validate-us-equity-production-bundle-strict:
	$(PYTHON) scripts/build_us_equity_production_bundle_preflight_report.py --strict
	$(PYTHON) scripts/build_us_equity_provider_verification_report.py
	$(PYTHON) -m pytest tests/contracts/test_us_equity_production_bundle_preflight_report.py tests/contracts/test_us_equity_local_csv_bundle_selection_config.py tests/contracts/test_us_equity_provider_verification_preflight_integration.py -q

validate-btc-evidence:
	$(PYTHON) scripts/build_btc_perpetual_bundle_preflight_report.py
	$(PYTHON) scripts/build_btc_funding_rate_gap_report.py
	$(PYTHON) scripts/build_btc_perpetual_provider_verification_report.py
	$(PYTHON) scripts/build_btc_public_metadata_capture_attempt_report.py
	$(PYTHON) scripts/build_btc_manual_metadata_capture_readiness_report.py
	$(PYTHON) scripts/build_btc_manual_metadata_capture_operator_packet.py
	$(PYTHON) scripts/build_btc_perpetual_data_source_decision_report.py
	$(PYTHON) scripts/build_btc_objective_completion_audit_report.py
	$(PYTHON) scripts/build_btc_data_status_report.py
	$(PYTHON) scripts/build_btc_funding_ledger_report.py
	$(PYTHON) scripts/build_btc_cost_model_report.py
	$(PYTHON) scripts/build_btc_fold_regime_contract_report.py
	$(PYTHON) scripts/build_btc_tail_dependency_report.py
	$(PYTHON) scripts/build_btc_candidate_gate_audit.py
	$(PYTHON) scripts/build_btc_candidate_metric_repair_report.py
	$(PYTHON) scripts/build_btc_candidate_bounded_retest_plan.py
	$(PYTHON) scripts/build_btc_candidate_bounded_retest_outcome_report.py
	$(PYTHON) scripts/build_btc_next_hypothesis_decision_report.py
	$(PYTHON) scripts/build_btc_strategy_family_roadmap_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_alpha_plan_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_alpha_probe_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_alpha_refinement_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_event_definition_repair_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_repaired_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_drift_guarded_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_drift_guarded_fold_regime_source_reports.py
	$(PYTHON) scripts/build_btc_fold_regime_contract_report.py
	$(PYTHON) scripts/build_btc_data_status_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_drift_guarded_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_promotion_gate_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_manual_review_packet.py
	$(PYTHON) scripts/build_btc_compression_expansion_attribution_bundle.py
	$(PYTHON) scripts/build_btc_research_registry.py
	$(PYTHON) scripts/build_global_research_registry.py
	$(PYTHON) scripts/build_btc_paper_readiness_report.py
	$(PYTHON) scripts/build_btc_paper_validation_start_report.py
	$(PYTHON) -m pytest tests/contracts/test_btc_funding_rate_gap_report.py tests/contracts/test_btc_funding_rate_archive_repair_diagnostics.py tests/contracts/test_btc_funding_rate_manual_patch_validation.py tests/contracts/test_btc_data_status_report.py tests/contracts/test_btc_data_source_coverage_contract.py tests/contracts/test_btc_perpetual_data_source_decision_report.py tests/contracts/test_btc_cost_model_contract.py tests/contracts/test_btc_fee_tier_overlay_import.py tests/contracts/test_btc_manual_metadata_capture_operator_packet.py tests/contracts/test_btc_fold_regime_contract.py tests/contracts/test_btc_candidate_gate_requires_full_ledger.py tests/contracts/test_btc_candidate_metric_repair_report.py tests/contracts/test_btc_candidate_bounded_retest_plan.py tests/contracts/test_btc_candidate_bounded_retest_outcome_report.py tests/contracts/test_btc_next_hypothesis_decision_report.py tests/contracts/test_btc_strategy_family_roadmap_report.py tests/contracts/test_btc_intraday_short_cycle_alpha_plan_report.py tests/contracts/test_btc_intraday_short_cycle_alpha_probe_report.py tests/contracts/test_btc_intraday_short_cycle_alpha_refinement_report.py tests/contracts/test_btc_intraday_short_cycle_event_ledger_report.py tests/contracts/test_btc_intraday_short_cycle_event_definition_repair_report.py tests/contracts/test_btc_intraday_short_cycle_repaired_event_ledger_report.py tests/contracts/test_btc_intraday_short_cycle_drift_guarded_event_ledger_report.py tests/contracts/test_btc_intraday_drift_guarded_fold_regime_source_reports.py tests/contracts/test_btc_true_scalping_microstructure_readiness_report.py tests/contracts/test_btc_compression_expansion_attribution_bundle.py tests/contracts/test_btc_okx_public_collector_boundaries.py tests/contracts/test_btc_perpetual_provider_verification_report.py tests/contracts/test_btc_tail_dependency_report.py tests/contracts/test_btc_paper_readiness_report.py tests/contracts/test_btc_paper_validation_start_report.py tests/contracts/test_btc_paper_validation_runtime_preflight.py tests/research/test_btc_data_fold_regime_status_report.py tests/research/test_btc_fold_regime_contract_audit.py tests/research/test_compression_expansion_event_ledger_attribution_artifact.py tests/research/test_btc_intraday_short_cycle_event_ledger.py -q

validate-btc-data-cost-repair:
	$(PYTHON) scripts/build_btc_perpetual_bundle_preflight_report.py
	$(PYTHON) scripts/build_btc_funding_rate_gap_report.py
	$(PYTHON) scripts/build_btc_perpetual_provider_verification_report.py
	$(PYTHON) scripts/build_btc_public_metadata_capture_attempt_report.py
	$(PYTHON) scripts/build_btc_manual_metadata_capture_readiness_report.py
	$(PYTHON) scripts/build_btc_manual_metadata_capture_operator_packet.py
	$(PYTHON) scripts/build_btc_perpetual_data_source_decision_report.py
	$(PYTHON) scripts/build_btc_data_status_report.py
	$(PYTHON) scripts/build_btc_funding_ledger_report.py
	$(PYTHON) scripts/build_btc_cost_model_report.py
	$(PYTHON) scripts/build_btc_tail_dependency_report.py
	$(PYTHON) scripts/build_btc_candidate_gate_audit.py
	$(PYTHON) scripts/build_btc_candidate_metric_repair_report.py
	$(PYTHON) scripts/build_btc_candidate_bounded_retest_plan.py
	$(PYTHON) scripts/build_btc_candidate_bounded_retest_outcome_report.py
	$(PYTHON) scripts/build_btc_next_hypothesis_decision_report.py
	$(PYTHON) scripts/build_btc_strategy_family_roadmap_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_alpha_plan_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_alpha_probe_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_alpha_refinement_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_event_definition_repair_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_repaired_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_drift_guarded_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_drift_guarded_fold_regime_source_reports.py
	$(PYTHON) scripts/build_btc_fold_regime_contract_report.py
	$(PYTHON) scripts/build_btc_data_status_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_drift_guarded_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_promotion_gate_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_manual_review_packet.py
	$(PYTHON) scripts/build_btc_true_scalping_microstructure_readiness_report.py
	$(PYTHON) scripts/build_btc_research_registry.py
	$(PYTHON) scripts/build_global_research_registry.py
	$(PYTHON) -m pytest tests/contracts/test_btc_funding_rate_gap_report.py tests/contracts/test_btc_funding_rate_archive_repair_diagnostics.py tests/contracts/test_btc_funding_rate_manual_patch_validation.py tests/contracts/test_btc_funding_info_overlay_policy.py tests/contracts/test_btc_exchange_info_overlay_policy.py tests/contracts/test_btc_perpetual_data_bundle_manifest.py tests/contracts/test_btc_binance_usdm_public_collector_boundaries.py tests/contracts/test_btc_okx_public_collector_boundaries.py tests/contracts/test_btc_perpetual_provider_verification_report.py tests/contracts/test_btc_funding_payment_ledger_replay.py tests/contracts/test_btc_mark_premium_exchange_rules_integration.py tests/contracts/test_btc_tail_dependency_report.py tests/contracts/test_btc_candidate_gate_requires_full_ledger.py tests/contracts/test_btc_compression_archive_recommended_boundary.py -q

check-btc-candidate-bounded-retest-readiness:
	$(PYTHON) scripts/build_btc_candidate_bounded_retest_plan.py
	$(PYTHON) -m pytest tests/contracts/test_btc_candidate_bounded_retest_plan.py -q

build-btc-candidate-bounded-retest-outcome:
	$(PYTHON) scripts/build_btc_candidate_bounded_retest_outcome_report.py
	$(PYTHON) -m pytest tests/contracts/test_btc_candidate_bounded_retest_outcome_report.py -q

build-btc-next-hypothesis-decision:
	$(PYTHON) scripts/build_btc_next_hypothesis_decision_report.py
	$(PYTHON) -m pytest tests/contracts/test_btc_next_hypothesis_decision_report.py -q

build-btc-strategy-family-roadmap:
	$(PYTHON) scripts/build_btc_strategy_family_roadmap_report.py
	$(PYTHON) -m pytest tests/contracts/test_btc_strategy_family_roadmap_report.py -q

build-btc-intraday-short-cycle-alpha-plan:
	$(PYTHON) scripts/build_btc_intraday_short_cycle_alpha_plan_report.py
	$(PYTHON) scripts/build_btc_research_registry.py
	$(PYTHON) -m pytest tests/contracts/test_btc_intraday_short_cycle_alpha_plan_report.py tests/research/test_btc_research_registry.py -q

build-btc-intraday-short-cycle-alpha-probe:
	$(PYTHON) scripts/build_btc_intraday_short_cycle_alpha_plan_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_alpha_probe_report.py
	$(PYTHON) scripts/build_btc_research_registry.py
	$(PYTHON) scripts/build_global_research_registry.py
	$(PYTHON) -m pytest tests/contracts/test_btc_intraday_short_cycle_alpha_probe_report.py tests/research/test_btc_research_registry.py tests/contracts/test_global_research_registry_schema.py -q

build-btc-intraday-short-cycle-alpha-refinement:
	$(PYTHON) scripts/build_btc_intraday_short_cycle_alpha_plan_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_alpha_probe_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_alpha_refinement_report.py
	$(PYTHON) scripts/build_btc_research_registry.py
	$(PYTHON) scripts/build_global_research_registry.py
	$(PYTHON) -m pytest tests/contracts/test_btc_intraday_short_cycle_alpha_refinement_report.py tests/research/test_btc_research_registry.py tests/contracts/test_global_research_registry_schema.py -q

build-btc-intraday-short-cycle-event-ledger:
	$(PYTHON) scripts/build_btc_intraday_short_cycle_alpha_plan_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_alpha_probe_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_alpha_refinement_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_event_definition_repair_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_repaired_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_drift_guarded_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_drift_guarded_fold_regime_source_reports.py
	$(PYTHON) scripts/build_btc_fold_regime_contract_report.py
	$(PYTHON) scripts/build_btc_data_status_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_drift_guarded_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_promotion_gate_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_manual_review_packet.py
	$(PYTHON) scripts/build_btc_true_scalping_microstructure_readiness_report.py
	$(PYTHON) scripts/build_btc_research_registry.py
	$(PYTHON) scripts/build_global_research_registry.py
	$(PYTHON) -m pytest tests/contracts/test_btc_intraday_short_cycle_event_ledger_report.py tests/contracts/test_btc_intraday_short_cycle_event_definition_repair_report.py tests/contracts/test_btc_intraday_short_cycle_repaired_event_ledger_report.py tests/contracts/test_btc_intraday_short_cycle_drift_guarded_event_ledger_report.py tests/contracts/test_btc_intraday_drift_guarded_fold_regime_source_reports.py tests/research/test_btc_intraday_short_cycle_event_ledger.py tests/research/test_btc_research_registry.py tests/contracts/test_global_research_registry_schema.py -q

build-btc-intraday-short-cycle-event-definition-repair:
	$(PYTHON) scripts/build_btc_intraday_short_cycle_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_event_definition_repair_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_repaired_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_drift_guarded_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_drift_guarded_fold_regime_source_reports.py
	$(PYTHON) scripts/build_btc_fold_regime_contract_report.py
	$(PYTHON) scripts/build_btc_data_status_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_drift_guarded_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_promotion_gate_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_manual_review_packet.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_research_candidate_definition_preflight.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_research_candidate_definition_manifest.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_remaining_external_evidence_status.py
	$(PYTHON) scripts/build_btc_research_registry.py
	$(PYTHON) scripts/build_global_research_registry.py
	$(PYTHON) -m pytest tests/contracts/test_btc_intraday_short_cycle_event_definition_repair_report.py tests/contracts/test_btc_intraday_short_cycle_repaired_event_ledger_report.py tests/contracts/test_btc_intraday_short_cycle_drift_guarded_event_ledger_report.py tests/research/test_btc_research_registry.py tests/contracts/test_global_research_registry_schema.py -q

build-btc-intraday-short-cycle-repaired-event-ledger:
	$(PYTHON) scripts/build_btc_intraday_short_cycle_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_event_definition_repair_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_repaired_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_drift_guarded_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_drift_guarded_fold_regime_source_reports.py
	$(PYTHON) scripts/build_btc_fold_regime_contract_report.py
	$(PYTHON) scripts/build_btc_data_status_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_drift_guarded_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_promotion_gate_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_manual_review_packet.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_research_candidate_definition_preflight.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_research_candidate_definition_manifest.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_remaining_external_evidence_status.py
	$(PYTHON) scripts/build_btc_research_registry.py
	$(PYTHON) scripts/build_global_research_registry.py
	$(PYTHON) -m pytest tests/contracts/test_btc_intraday_short_cycle_repaired_event_ledger_report.py tests/contracts/test_btc_intraday_short_cycle_drift_guarded_event_ledger_report.py tests/research/test_btc_intraday_short_cycle_event_ledger.py tests/research/test_btc_research_registry.py tests/contracts/test_global_research_registry_schema.py -q

build-btc-intraday-short-cycle-drift-guarded-event-ledger:
	$(PYTHON) scripts/build_btc_intraday_short_cycle_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_event_definition_repair_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_repaired_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_drift_guarded_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_drift_guarded_fold_regime_source_reports.py
	$(PYTHON) scripts/build_btc_fold_regime_contract_report.py
	$(PYTHON) scripts/build_btc_data_status_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_drift_guarded_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_promotion_gate_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_manual_review_packet.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_research_candidate_definition_preflight.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_research_candidate_definition_manifest.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_remaining_external_evidence_status.py
	$(PYTHON) scripts/build_btc_research_registry.py
	$(PYTHON) scripts/build_global_research_registry.py
	$(PYTHON) -m pytest tests/contracts/test_btc_intraday_short_cycle_drift_guarded_event_ledger_report.py tests/contracts/test_btc_intraday_drift_guarded_fold_regime_source_reports.py tests/research/test_btc_intraday_short_cycle_event_ledger.py tests/research/test_btc_research_registry.py tests/contracts/test_global_research_registry_schema.py -q

build-btc-intraday-short-cycle-promotion-gate:
	$(PYTHON) scripts/build_btc_intraday_short_cycle_drift_guarded_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_promotion_gate_report.py
	$(PYTHON) -m pytest tests/contracts/test_btc_intraday_short_cycle_promotion_gate_report.py tests/contracts/test_no_broker_import_in_evidence_builders.py tests/contracts/test_global_registry_builder_boundaries.py -q

build-btc-intraday-short-cycle-manual-review-packet:
	$(PYTHON) scripts/build_btc_intraday_short_cycle_promotion_gate_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_manual_review_packet.py
	$(PYTHON) -m pytest tests/contracts/test_btc_intraday_short_cycle_manual_review_packet.py tests/contracts/test_no_broker_import_in_evidence_builders.py tests/contracts/test_global_registry_builder_boundaries.py -q

build-btc-intraday-short-cycle-research-candidate-definition-preflight:
	$(PYTHON) scripts/build_btc_intraday_short_cycle_promotion_gate_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_manual_review_packet.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_research_candidate_definition_preflight.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_research_candidate_definition_manifest.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_remaining_external_evidence_status.py
	$(PYTHON) scripts/build_btc_research_registry.py
	$(PYTHON) scripts/build_global_research_registry.py
	$(PYTHON) -m pytest tests/contracts/test_btc_intraday_short_cycle_research_candidate_definition_preflight.py tests/contracts/test_btc_intraday_short_cycle_research_candidate_definition_manifest.py tests/contracts/test_btc_intraday_short_cycle_remaining_external_evidence_status.py tests/research/test_btc_research_registry.py tests/contracts/test_global_research_registry_schema.py tests/contracts/test_no_broker_import_in_evidence_builders.py tests/contracts/test_global_registry_builder_boundaries.py -q

build-btc-intraday-short-cycle-research-candidate-definition-manifest:
	$(PYTHON) scripts/build_btc_intraday_short_cycle_promotion_gate_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_manual_review_packet.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_research_candidate_definition_preflight.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_research_candidate_definition_manifest.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_remaining_external_evidence_status.py
	$(PYTHON) scripts/build_btc_research_registry.py
	$(PYTHON) scripts/build_global_research_registry.py
	$(PYTHON) -m pytest tests/contracts/test_btc_intraday_short_cycle_research_candidate_definition_preflight.py tests/contracts/test_btc_intraday_short_cycle_research_candidate_definition_manifest.py tests/contracts/test_btc_intraday_short_cycle_remaining_external_evidence_status.py tests/research/test_btc_research_registry.py tests/contracts/test_global_research_registry_schema.py tests/contracts/test_no_broker_import_in_evidence_builders.py tests/contracts/test_global_registry_builder_boundaries.py -q

build-btc-intraday-short-cycle-remaining-external-evidence-status:
	$(PYTHON) scripts/build_btc_intraday_short_cycle_promotion_gate_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_manual_review_packet.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_research_candidate_definition_preflight.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_research_candidate_definition_manifest.py
	$(PYTHON) scripts/build_btc_true_scalping_ws_l2_capture_coverage_report.py
	$(PYTHON) scripts/build_btc_true_scalping_long_horizon_l2_tick_import_contract_report.py
	$(PYTHON) scripts/build_btc_true_scalping_execution_queue_external_evidence_contract_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_remaining_external_evidence_status.py
	$(PYTHON) scripts/build_btc_research_registry.py
	$(PYTHON) scripts/build_global_research_registry.py
	$(PYTHON) -m pytest tests/contracts/test_btc_true_scalping_long_horizon_l2_tick_import_contract_report.py tests/contracts/test_btc_true_scalping_execution_queue_external_evidence_contract_report.py tests/contracts/test_btc_intraday_short_cycle_remaining_external_evidence_status.py tests/research/test_btc_research_registry.py tests/contracts/test_global_research_registry_schema.py tests/contracts/test_no_broker_import_in_evidence_builders.py tests/contracts/test_global_registry_builder_boundaries.py -q

build-btc-intraday-drift-guarded-fold-regime-source-reports:
	$(PYTHON) scripts/build_btc_intraday_short_cycle_drift_guarded_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_drift_guarded_fold_regime_source_reports.py
	$(PYTHON) scripts/build_btc_fold_regime_contract_report.py
	$(PYTHON) scripts/build_btc_data_status_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_drift_guarded_event_ledger_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_promotion_gate_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_manual_review_packet.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_research_candidate_definition_preflight.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_research_candidate_definition_manifest.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_remaining_external_evidence_status.py
	$(PYTHON) scripts/build_btc_research_registry.py
	$(PYTHON) scripts/build_global_research_registry.py
	$(PYTHON) -m pytest tests/contracts/test_btc_intraday_drift_guarded_fold_regime_source_reports.py tests/contracts/test_btc_data_status_report.py tests/contracts/test_btc_fold_regime_contract.py tests/contracts/test_btc_intraday_short_cycle_drift_guarded_event_ledger_report.py tests/contracts/test_btc_true_scalping_microstructure_readiness_report.py tests/contracts/test_global_research_registry_schema.py -q

build-btc-true-scalping-microstructure-readiness:
	$(PYTHON) scripts/build_btc_intraday_drift_guarded_fold_regime_source_reports.py
	$(PYTHON) scripts/build_btc_data_status_report.py
	$(PYTHON) scripts/build_btc_true_scalping_microstructure_models.py
	$(PYTHON) scripts/build_btc_true_scalping_microstructure_readiness_report.py
	$(PYTHON) -m pytest tests/contracts/test_btc_true_scalping_microstructure_models.py tests/contracts/test_btc_true_scalping_microstructure_readiness_report.py tests/contracts/test_btc_data_status_report.py tests/contracts/test_btc_intraday_drift_guarded_fold_regime_source_reports.py -q

build-btc-true-scalping-microstructure-models:
	$(PYTHON) scripts/build_btc_true_scalping_microstructure_models.py
	$(PYTHON) scripts/build_btc_true_scalping_microstructure_readiness_report.py
	$(PYTHON) -m pytest tests/contracts/test_btc_true_scalping_microstructure_models.py tests/contracts/test_btc_true_scalping_microstructure_readiness_report.py -q

build-btc-true-scalping-research-design-review:
	$(MAKE) build-btc-true-scalping-microstructure-readiness
	$(PYTHON) scripts/build_btc_true_scalping_research_design_review.py
	$(PYTHON) -m pytest tests/contracts/test_btc_true_scalping_research_design_review.py tests/contracts/test_btc_true_scalping_microstructure_readiness_report.py -q

build-btc-true-scalping-research-design:
	$(MAKE) build-btc-true-scalping-research-design-review
	$(PYTHON) scripts/build_btc_true_scalping_research_design_report.py
	$(PYTHON) -m pytest tests/contracts/test_btc_true_scalping_research_design_report.py tests/contracts/test_btc_true_scalping_research_design_review.py -q

build-btc-true-scalping-event-ledger-prototype:
	$(MAKE) build-btc-true-scalping-research-design
	$(PYTHON) scripts/build_btc_true_scalping_event_ledger_prototype_report.py
	$(PYTHON) -m pytest tests/contracts/test_btc_true_scalping_event_ledger_prototype_report.py tests/contracts/test_btc_true_scalping_research_design_report.py -q

build-btc-true-scalping-event-definition-redesign:
	$(MAKE) build-btc-true-scalping-event-ledger-prototype
	$(PYTHON) scripts/build_btc_true_scalping_event_definition_redesign_report.py
	$(PYTHON) -m pytest tests/contracts/test_btc_true_scalping_event_definition_redesign_report.py tests/contracts/test_btc_true_scalping_event_ledger_prototype_report.py -q

run-btc-scalping-research-backtest:
	$(PYTHON) scripts/run_btc_scalping_research_backtest.py
	$(PYTHON) -m pytest tests/contracts/test_btc_scalping_research_backtest_report.py tests/contracts/test_btc_true_scalping_event_ledger_prototype_report.py tests/contracts/test_btc_intraday_short_cycle_drift_guarded_event_ledger_report.py tests/contracts/test_no_broker_import_in_evidence_builders.py -q

build-btc-data-source-decision:
	$(PYTHON) scripts/build_btc_perpetual_data_source_decision_report.py
	$(PYTHON) -m pytest tests/contracts/test_btc_perpetual_data_source_decision_report.py -q

validate-btc-public-data-bundle:
	$(PYTHON) scripts/build_btc_perpetual_bundle_preflight_report.py
	$(PYTHON) scripts/build_btc_funding_rate_gap_report.py
	$(PYTHON) scripts/build_btc_perpetual_provider_verification_report.py
	$(PYTHON) scripts/build_btc_public_metadata_capture_attempt_report.py
	$(PYTHON) scripts/build_btc_manual_metadata_capture_readiness_report.py
	$(PYTHON) scripts/build_btc_manual_metadata_capture_operator_packet.py
	$(PYTHON) scripts/build_btc_objective_completion_audit_report.py
	$(PYTHON) scripts/build_btc_data_status_report.py
	$(PYTHON) scripts/build_btc_funding_ledger_report.py
	$(PYTHON) scripts/build_btc_cost_model_report.py
	$(PYTHON) scripts/build_btc_tail_dependency_report.py
	$(PYTHON) scripts/build_btc_candidate_gate_audit.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_alpha_plan_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_alpha_probe_report.py
	$(PYTHON) scripts/build_btc_intraday_short_cycle_alpha_refinement_report.py
	$(PYTHON) scripts/build_btc_research_registry.py
	$(PYTHON) scripts/build_global_research_registry.py
	$(PYTHON) -m pytest tests/contracts/test_btc_funding_rate_gap_report.py tests/contracts/test_btc_funding_rate_archive_repair_diagnostics.py tests/contracts/test_btc_funding_rate_manual_patch_validation.py tests/contracts/test_btc_funding_info_overlay_policy.py tests/contracts/test_btc_exchange_info_overlay_policy.py tests/contracts/test_btc_manual_metadata_import.py tests/contracts/test_btc_public_data_landing_mode.py tests/contracts/test_btc_public_metadata_capture_attempt_report.py tests/contracts/test_btc_manual_metadata_capture_operator_packet.py tests/contracts/test_btc_objective_completion_audit_report.py tests/contracts/test_btc_perpetual_data_bundle_manifest.py tests/contracts/test_btc_binance_usdm_public_collector_boundaries.py tests/contracts/test_btc_okx_public_collector_boundaries.py tests/contracts/test_btc_perpetual_bundle_preflight_report.py tests/contracts/test_btc_perpetual_provider_verification_report.py tests/contracts/test_btc_manual_metadata_capture_readiness_report.py tests/contracts/test_btc_funding_payment_ledger_replay.py tests/contracts/test_btc_public_data_landing_no_strategy_side_effect.py tests/contracts/test_btc_candidate_gate_requires_full_ledger.py -q

validate-btc-public-data-bundle-strict:
	$(PYTHON) scripts/build_btc_perpetual_bundle_preflight_report.py --strict
	$(PYTHON) scripts/build_btc_perpetual_provider_verification_report.py
	$(PYTHON) -m pytest tests/contracts/test_btc_perpetual_bundle_preflight_report.py tests/contracts/test_btc_perpetual_provider_verification_report.py -q

restore-btc-live-metadata-evidence:
	$(PYTHON) scripts/build_btc_public_metadata_capture_attempt_report.py \
		--execute-network \
		--raw-capture-root "$(BTC_PUBLIC_METADATA_RAW_CAPTURE_ROOT)"
	$(MAKE) rebuild-btc-paper-readiness-chain
	$(PYTHON) scripts/check_artifact_lineage_health.py --stale-after-hours 1000000

capture-btc-public-metadata:
	$(PYTHON) scripts/build_btc_public_metadata_capture_attempt_report.py \
		--execute-network \
		--raw-capture-root "$(BTC_PUBLIC_METADATA_RAW_CAPTURE_ROOT)"

capture-btc-okx-public-bundle:
	$(PYTHON) scripts/fetch_btc_okx_swap_public_data.py --execute-network
	$(PYTHON) scripts/build_btc_perpetual_bundle_preflight_report.py
	$(PYTHON) scripts/build_btc_perpetual_provider_verification_report.py

capture-btc-okx-public-history:
	$(PYTHON) scripts/fetch_btc_okx_swap_public_data.py \
		--execute-network \
		--bundle-id "$(BTC_OKX_HISTORY_BUNDLE_ID)" \
		--history-days "$(BTC_OKX_HISTORY_DAYS)"
	$(PYTHON) scripts/build_btc_perpetual_bundle_preflight_report.py
	$(PYTHON) scripts/build_btc_perpetual_provider_verification_report.py

dry-run-btc-okx-microstructure-capture:
	$(PYTHON) scripts/fetch_btc_okx_microstructure_public_data.py \
		--capture-report artifacts/btc_scalping_readiness/latest/btc_okx_microstructure_capture_dry_run_report.json
	$(PYTHON) -m pytest tests/contracts/test_btc_okx_public_collector_boundaries.py -q

capture-btc-okx-microstructure:
	$(PYTHON) scripts/fetch_btc_okx_microstructure_public_data.py --execute-network
	$(PYTHON) scripts/build_btc_true_scalping_microstructure_models.py
	$(PYTHON) scripts/build_btc_true_scalping_microstructure_readiness_report.py
	$(PYTHON) -m pytest tests/contracts/test_btc_okx_public_collector_boundaries.py tests/contracts/test_btc_true_scalping_microstructure_models.py tests/contracts/test_btc_true_scalping_microstructure_readiness_report.py -q

dry-run-btc-okx-l2-microstructure-samples:
	$(PYTHON) scripts/fetch_btc_okx_l2_microstructure_public_samples.py \
		--sample-count "$(BTC_OKX_L2_SAMPLE_COUNT)" \
		--capture-report artifacts/btc_scalping_readiness/latest/btc_okx_l2_microstructure_sample_capture_dry_run_report.json
	$(PYTHON) -m pytest tests/contracts/test_btc_okx_public_collector_boundaries.py -q

capture-btc-okx-l2-microstructure-samples:
	$(PYTHON) scripts/fetch_btc_okx_l2_microstructure_public_samples.py \
		--execute-network \
		--sample-count "$(BTC_OKX_L2_SAMPLE_COUNT)" \
		--request-sleep-seconds "$(BTC_OKX_L2_REQUEST_SLEEP_SECONDS)"
	$(PYTHON) scripts/build_btc_true_scalping_l2_sample_quality_report.py
	$(PYTHON) scripts/build_btc_true_scalping_l2_feature_diagnostics_report.py
	$(PYTHON) scripts/build_btc_true_scalping_timestamp_aligned_l2_data_contract_report.py
	$(PYTHON) -m pytest tests/contracts/test_btc_okx_public_collector_boundaries.py tests/contracts/test_btc_true_scalping_l2_sample_quality_report.py tests/contracts/test_btc_true_scalping_l2_feature_diagnostics_report.py tests/contracts/test_btc_true_scalping_timestamp_aligned_l2_data_contract_report.py -q

dry-run-btc-okx-timestamp-aligned-l2-capture:
	$(PYTHON) scripts/fetch_btc_okx_timestamp_aligned_l2_public_capture.py \
		--sample-count "$(BTC_OKX_ALIGNED_L2_SAMPLE_COUNT)" \
		--capture-report artifacts/btc_scalping_readiness/latest/btc_okx_timestamp_aligned_l2_capture_dry_run_report.json
	$(PYTHON) -m pytest tests/contracts/test_btc_okx_public_collector_boundaries.py -q

capture-btc-okx-timestamp-aligned-l2-capture:
	$(PYTHON) scripts/fetch_btc_okx_timestamp_aligned_l2_public_capture.py \
		--execute-network \
		--sample-count "$(BTC_OKX_ALIGNED_L2_SAMPLE_COUNT)" \
		--request-sleep-seconds "$(BTC_OKX_ALIGNED_L2_REQUEST_SLEEP_SECONDS)"
	$(PYTHON) scripts/build_btc_true_scalping_l2_aligned_capture_quality_report.py
	$(PYTHON) -m pytest tests/contracts/test_btc_okx_public_collector_boundaries.py tests/contracts/test_btc_true_scalping_l2_aligned_capture_quality_report.py tests/contracts/test_no_broker_import_in_evidence_builders.py -q

dry-run-btc-okx-public-ws-l2-raw-capture:
	$(PYTHON) scripts/fetch_btc_okx_public_ws_l2_raw_capture.py \
		--duration-seconds "$(BTC_OKX_PUBLIC_WS_L2_DURATION_SECONDS)" \
		--max-messages "$(BTC_OKX_PUBLIC_WS_L2_MAX_MESSAGES)" \
		--forced-reconnect-after-messages "$(BTC_OKX_PUBLIC_WS_L2_FORCED_RECONNECT_AFTER_MESSAGES)" \
		--capture-report artifacts/btc_scalping_readiness/latest/btc_okx_public_ws_l2_raw_capture_dry_run_report.json
	$(PYTHON) -m pytest tests/contracts/test_btc_okx_public_collector_boundaries.py -q

capture-btc-okx-public-ws-l2-raw-capture:
	$(PYTHON) scripts/fetch_btc_okx_public_ws_l2_raw_capture.py \
		--execute-network \
		--duration-seconds "$(BTC_OKX_PUBLIC_WS_L2_DURATION_SECONDS)" \
		--max-messages "$(BTC_OKX_PUBLIC_WS_L2_MAX_MESSAGES)" \
		--forced-reconnect-after-messages "$(BTC_OKX_PUBLIC_WS_L2_FORCED_RECONNECT_AFTER_MESSAGES)"
	$(PYTHON) scripts/build_btc_true_scalping_ws_l2_raw_capture_quality_report.py
	$(PYTHON) scripts/build_btc_true_scalping_ws_order_book_replay_report.py
	$(PYTHON) scripts/build_btc_true_scalping_ws_reconnect_resync_policy_report.py
	$(PYTHON) scripts/build_btc_true_scalping_ws_latency_queue_diagnostics_report.py
	$(PYTHON) scripts/build_btc_true_scalping_ws_l2_capture_coverage_report.py
	$(PYTHON) -m pytest tests/contracts/test_btc_okx_public_collector_boundaries.py tests/contracts/test_btc_true_scalping_ws_l2_raw_capture_quality_report.py tests/contracts/test_btc_true_scalping_ws_order_book_replay_report.py tests/contracts/test_btc_true_scalping_ws_reconnect_resync_policy_report.py tests/contracts/test_btc_true_scalping_ws_latency_queue_diagnostics_report.py tests/contracts/test_btc_true_scalping_ws_l2_capture_coverage_report.py tests/contracts/test_no_broker_import_in_evidence_builders.py -q

dry-run-btc-okx-public-ws-l2-segment-capture:
	$(PYTHON) scripts/run_btc_okx_public_ws_l2_segment_capture.py $(if $(BTC_OKX_PUBLIC_WS_L2_SEGMENT_ID),--segment-id "$(BTC_OKX_PUBLIC_WS_L2_SEGMENT_ID)") \
		--duration-seconds "$(BTC_OKX_PUBLIC_WS_L2_DURATION_SECONDS)" \
		--max-messages "$(BTC_OKX_PUBLIC_WS_L2_MAX_MESSAGES)" \
		--forced-reconnect-after-messages "$(BTC_OKX_PUBLIC_WS_L2_FORCED_RECONNECT_AFTER_MESSAGES)"
	$(PYTHON) -m pytest tests/contracts/test_btc_okx_public_collector_boundaries.py tests/contracts/test_no_broker_import_in_evidence_builders.py -q

capture-btc-okx-public-ws-l2-segment-capture:
	$(PYTHON) scripts/run_btc_okx_public_ws_l2_segment_capture.py $(if $(BTC_OKX_PUBLIC_WS_L2_SEGMENT_ID),--segment-id "$(BTC_OKX_PUBLIC_WS_L2_SEGMENT_ID)") \
		--execute-network \
		--duration-seconds "$(BTC_OKX_PUBLIC_WS_L2_DURATION_SECONDS)" \
		--max-messages "$(BTC_OKX_PUBLIC_WS_L2_MAX_MESSAGES)" \
		--forced-reconnect-after-messages "$(BTC_OKX_PUBLIC_WS_L2_FORCED_RECONNECT_AFTER_MESSAGES)"
	$(PYTHON) -m pytest tests/contracts/test_btc_okx_public_collector_boundaries.py tests/contracts/test_btc_true_scalping_ws_l2_raw_capture_quality_report.py tests/contracts/test_btc_true_scalping_ws_order_book_replay_report.py tests/contracts/test_btc_true_scalping_ws_reconnect_resync_policy_report.py tests/contracts/test_btc_true_scalping_ws_latency_queue_diagnostics_report.py tests/contracts/test_btc_true_scalping_ws_l2_capture_coverage_report.py tests/contracts/test_no_broker_import_in_evidence_builders.py -q

build-btc-true-scalping-l2-sample-quality:
	$(PYTHON) scripts/build_btc_true_scalping_l2_sample_quality_report.py
	$(PYTHON) -m pytest tests/contracts/test_btc_true_scalping_l2_sample_quality_report.py -q

build-btc-true-scalping-l2-feature-diagnostics:
	$(PYTHON) scripts/build_btc_true_scalping_l2_sample_quality_report.py
	$(PYTHON) scripts/build_btc_true_scalping_l2_feature_diagnostics_report.py
	$(PYTHON) -m pytest tests/contracts/test_btc_true_scalping_l2_sample_quality_report.py tests/contracts/test_btc_true_scalping_l2_feature_diagnostics_report.py -q

build-btc-true-scalping-timestamp-aligned-l2-data-contract:
	$(PYTHON) scripts/build_btc_true_scalping_l2_sample_quality_report.py
	$(PYTHON) scripts/build_btc_true_scalping_l2_feature_diagnostics_report.py
	$(PYTHON) scripts/build_btc_true_scalping_timestamp_aligned_l2_data_contract_report.py
	$(PYTHON) -m pytest tests/contracts/test_btc_true_scalping_l2_sample_quality_report.py tests/contracts/test_btc_true_scalping_l2_feature_diagnostics_report.py tests/contracts/test_btc_true_scalping_timestamp_aligned_l2_data_contract_report.py tests/contracts/test_no_broker_import_in_evidence_builders.py -q

build-btc-true-scalping-l2-aligned-capture-quality:
	$(PYTHON) scripts/build_btc_true_scalping_timestamp_aligned_l2_data_contract_report.py
	$(PYTHON) scripts/build_btc_true_scalping_l2_aligned_capture_quality_report.py
	$(PYTHON) -m pytest tests/contracts/test_btc_true_scalping_timestamp_aligned_l2_data_contract_report.py tests/contracts/test_btc_true_scalping_l2_aligned_capture_quality_report.py tests/contracts/test_no_broker_import_in_evidence_builders.py -q

build-btc-true-scalping-ws-l2-raw-capture-quality:
	$(PYTHON) scripts/build_btc_true_scalping_ws_l2_raw_capture_quality_report.py
	$(PYTHON) -m pytest tests/contracts/test_btc_true_scalping_ws_l2_raw_capture_quality_report.py tests/contracts/test_no_broker_import_in_evidence_builders.py -q

build-btc-true-scalping-ws-order-book-replay:
	$(PYTHON) scripts/build_btc_true_scalping_ws_l2_raw_capture_quality_report.py
	$(PYTHON) scripts/build_btc_true_scalping_ws_order_book_replay_report.py
	$(PYTHON) scripts/build_btc_true_scalping_ws_reconnect_resync_policy_report.py
	$(PYTHON) scripts/build_btc_true_scalping_ws_latency_queue_diagnostics_report.py
	$(PYTHON) scripts/build_btc_true_scalping_ws_l2_capture_coverage_report.py
	$(PYTHON) -m pytest tests/contracts/test_btc_true_scalping_ws_l2_raw_capture_quality_report.py tests/contracts/test_btc_true_scalping_ws_order_book_replay_report.py tests/contracts/test_btc_true_scalping_ws_reconnect_resync_policy_report.py tests/contracts/test_btc_true_scalping_ws_latency_queue_diagnostics_report.py tests/contracts/test_btc_true_scalping_ws_l2_capture_coverage_report.py tests/contracts/test_no_broker_import_in_evidence_builders.py -q

build-btc-true-scalping-ws-reconnect-resync-policy:
	$(PYTHON) scripts/build_btc_true_scalping_ws_order_book_replay_report.py
	$(PYTHON) scripts/build_btc_true_scalping_ws_reconnect_resync_policy_report.py
	$(PYTHON) -m pytest tests/contracts/test_btc_true_scalping_ws_order_book_replay_report.py tests/contracts/test_btc_true_scalping_ws_reconnect_resync_policy_report.py tests/contracts/test_no_broker_import_in_evidence_builders.py -q

build-btc-true-scalping-ws-latency-queue-diagnostics:
	$(PYTHON) scripts/build_btc_true_scalping_ws_order_book_replay_report.py
	$(PYTHON) scripts/build_btc_true_scalping_ws_latency_queue_diagnostics_report.py
	$(PYTHON) -m pytest tests/contracts/test_btc_true_scalping_ws_order_book_replay_report.py tests/contracts/test_btc_true_scalping_ws_latency_queue_diagnostics_report.py tests/contracts/test_no_broker_import_in_evidence_builders.py -q

build-btc-true-scalping-ws-l2-capture-coverage:
	$(PYTHON) scripts/build_btc_true_scalping_ws_l2_capture_coverage_report.py
	$(PYTHON) -m pytest tests/contracts/test_btc_true_scalping_ws_l2_capture_coverage_report.py tests/contracts/test_no_broker_import_in_evidence_builders.py -q

build-btc-true-scalping-long-horizon-l2-tick-import-contract:
	$(PYTHON) scripts/build_btc_true_scalping_long_horizon_l2_tick_import_contract_report.py
	$(PYTHON) -m pytest tests/contracts/test_btc_true_scalping_long_horizon_l2_tick_import_contract_report.py tests/contracts/test_no_broker_import_in_evidence_builders.py -q

build-btc-true-scalping-execution-queue-external-evidence-contract:
	$(PYTHON) scripts/build_btc_true_scalping_execution_queue_external_evidence_contract_report.py
	$(PYTHON) -m pytest tests/contracts/test_btc_true_scalping_execution_queue_external_evidence_contract_report.py tests/contracts/test_no_broker_import_in_evidence_builders.py -q

build-btc-true-scalping-1m-proxy-feature-redesign:
	$(PYTHON) scripts/build_btc_true_scalping_l2_sample_quality_report.py
	$(PYTHON) scripts/build_btc_true_scalping_l2_feature_diagnostics_report.py
	$(PYTHON) scripts/build_btc_true_scalping_1m_proxy_feature_redesign_report.py
	$(PYTHON) -m pytest tests/contracts/test_btc_true_scalping_l2_feature_diagnostics_report.py tests/contracts/test_btc_true_scalping_1m_proxy_feature_redesign_report.py -q

dry-run-btc-manual-metadata-import:
	@test -n "$(EXCHANGE_INFO_RAW)" || (echo "EXCHANGE_INFO_RAW is required" >&2; exit 2)
	@test -n "$(FUNDING_INFO_RAW)" || (echo "FUNDING_INFO_RAW is required" >&2; exit 2)
	@test -n "$(EXCHANGE_INFO_HTTP_STATUS)" || (echo "EXCHANGE_INFO_HTTP_STATUS is required" >&2; exit 2)
	@test -n "$(FUNDING_INFO_HTTP_STATUS)" || (echo "FUNDING_INFO_HTTP_STATUS is required" >&2; exit 2)
	@test -n "$(BTC_MANUAL_METADATA_CAPTURED_AT)" || (echo "BTC_MANUAL_METADATA_CAPTURED_AT is required" >&2; exit 2)
	$(PYTHON) scripts/import_btc_manual_metadata_capture.py \
		--exchange-info-raw "$(EXCHANGE_INFO_RAW)" \
		--funding-info-raw "$(FUNDING_INFO_RAW)" \
		--exchange-info-http-status "$(EXCHANGE_INFO_HTTP_STATUS)" \
		--funding-info-http-status "$(FUNDING_INFO_HTTP_STATUS)" \
		--report-output "$(BTC_MANUAL_METADATA_DRY_RUN_REPORT)" \
		--captured-at "$(BTC_MANUAL_METADATA_CAPTURED_AT)" \
		--dry-run \
		--operator-note "Manual public metadata capture from an accessible network environment. No API key, no private/account/order endpoint."

apply-btc-manual-metadata-import:
	@test -n "$(EXCHANGE_INFO_RAW)" || (echo "EXCHANGE_INFO_RAW is required" >&2; exit 2)
	@test -n "$(FUNDING_INFO_RAW)" || (echo "FUNDING_INFO_RAW is required" >&2; exit 2)
	@test -n "$(EXCHANGE_INFO_HTTP_STATUS)" || (echo "EXCHANGE_INFO_HTTP_STATUS is required" >&2; exit 2)
	@test -n "$(FUNDING_INFO_HTTP_STATUS)" || (echo "FUNDING_INFO_HTTP_STATUS is required" >&2; exit 2)
	@test -n "$(BTC_MANUAL_METADATA_CAPTURED_AT)" || (echo "BTC_MANUAL_METADATA_CAPTURED_AT is required" >&2; exit 2)
	$(PYTHON) scripts/import_btc_manual_metadata_capture.py \
		--exchange-info-raw "$(EXCHANGE_INFO_RAW)" \
		--funding-info-raw "$(FUNDING_INFO_RAW)" \
		--exchange-info-http-status "$(EXCHANGE_INFO_HTTP_STATUS)" \
		--funding-info-http-status "$(FUNDING_INFO_HTTP_STATUS)" \
		--report-output "$(BTC_MANUAL_METADATA_IMPORT_REPORT)" \
		--captured-at "$(BTC_MANUAL_METADATA_CAPTURED_AT)" \
		--operator-note "Manual public metadata capture from an accessible network environment. No API key, no private/account/order endpoint."
	$(MAKE) rebuild-btc-paper-readiness-chain
	$(PYTHON) scripts/clear_btc_manual_metadata_import_marker.py \
		--repo-root "." \
		--import-report "$(BTC_MANUAL_METADATA_IMPORT_REPORT)" \
		--provider-report "artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json" \
		--readiness-report "artifacts/btc_paper_readiness/latest/btc_paper_readiness_report.json" \
		--selected-bundle-config "configs/data/btc_perpetual_sources.yaml"
	$(MAKE) rebuild-btc-paper-readiness-chain

dry-run-btc-fee-tier-overlay-import:
	@test -n "$(BTC_FEE_TIER_MAKER_BPS)" || (echo "BTC_FEE_TIER_MAKER_BPS is required" >&2; exit 2)
	@test -n "$(BTC_FEE_TIER_TAKER_BPS)" || (echo "BTC_FEE_TIER_TAKER_BPS is required" >&2; exit 2)
	@test -n "$(BTC_FEE_TIER_SOURCE)" || (echo "BTC_FEE_TIER_SOURCE is required" >&2; exit 2)
	@test -n "$(BTC_FEE_TIER_SOURCE_URL_OR_DOC)" || (echo "BTC_FEE_TIER_SOURCE_URL_OR_DOC is required" >&2; exit 2)
	@test -n "$(BTC_FEE_TIER_CAPTURED_AT)" || (echo "BTC_FEE_TIER_CAPTURED_AT is required" >&2; exit 2)
	$(PYTHON) scripts/import_btc_fee_tier_overlay.py \
		--maker-fee-bps "$(BTC_FEE_TIER_MAKER_BPS)" \
		--taker-fee-bps "$(BTC_FEE_TIER_TAKER_BPS)" \
		--source "$(BTC_FEE_TIER_SOURCE)" \
		--source-url-or-doc "$(BTC_FEE_TIER_SOURCE_URL_OR_DOC)" \
		--captured-at "$(BTC_FEE_TIER_CAPTURED_AT)" \
		--overlay-output "$(BTC_FEE_TIER_OVERLAY)" \
		--report-output "$(BTC_FEE_TIER_DRY_RUN_REPORT)" \
		--dry-run

apply-btc-fee-tier-overlay-import:
	@test -n "$(BTC_FEE_TIER_MAKER_BPS)" || (echo "BTC_FEE_TIER_MAKER_BPS is required" >&2; exit 2)
	@test -n "$(BTC_FEE_TIER_TAKER_BPS)" || (echo "BTC_FEE_TIER_TAKER_BPS is required" >&2; exit 2)
	@test -n "$(BTC_FEE_TIER_SOURCE)" || (echo "BTC_FEE_TIER_SOURCE is required" >&2; exit 2)
	@test -n "$(BTC_FEE_TIER_SOURCE_URL_OR_DOC)" || (echo "BTC_FEE_TIER_SOURCE_URL_OR_DOC is required" >&2; exit 2)
	@test -n "$(BTC_FEE_TIER_CAPTURED_AT)" || (echo "BTC_FEE_TIER_CAPTURED_AT is required" >&2; exit 2)
	$(PYTHON) scripts/import_btc_fee_tier_overlay.py \
		--maker-fee-bps "$(BTC_FEE_TIER_MAKER_BPS)" \
		--taker-fee-bps "$(BTC_FEE_TIER_TAKER_BPS)" \
		--source "$(BTC_FEE_TIER_SOURCE)" \
		--source-url-or-doc "$(BTC_FEE_TIER_SOURCE_URL_OR_DOC)" \
		--captured-at "$(BTC_FEE_TIER_CAPTURED_AT)" \
		--overlay-output "$(BTC_FEE_TIER_OVERLAY)" \
		--report-output "$(BTC_FEE_TIER_IMPORT_REPORT)"
	$(MAKE) rebuild-btc-paper-readiness-chain
	$(MAKE) validate-btc-evidence

dry-run-btc-paper-gate-manual-inputs:
	@test -n "$(EXCHANGE_INFO_RAW)" || (echo "EXCHANGE_INFO_RAW is required" >&2; exit 2)
	@test -n "$(FUNDING_INFO_RAW)" || (echo "FUNDING_INFO_RAW is required" >&2; exit 2)
	@test -n "$(EXCHANGE_INFO_HTTP_STATUS)" || (echo "EXCHANGE_INFO_HTTP_STATUS is required" >&2; exit 2)
	@test -n "$(FUNDING_INFO_HTTP_STATUS)" || (echo "FUNDING_INFO_HTTP_STATUS is required" >&2; exit 2)
	@test -n "$(BTC_MANUAL_METADATA_CAPTURED_AT)" || (echo "BTC_MANUAL_METADATA_CAPTURED_AT is required" >&2; exit 2)
	@test -n "$(BTC_FEE_TIER_MAKER_BPS)" || (echo "BTC_FEE_TIER_MAKER_BPS is required" >&2; exit 2)
	@test -n "$(BTC_FEE_TIER_TAKER_BPS)" || (echo "BTC_FEE_TIER_TAKER_BPS is required" >&2; exit 2)
	@test -n "$(BTC_FEE_TIER_CAPTURED_AT)" || (echo "BTC_FEE_TIER_CAPTURED_AT is required" >&2; exit 2)
	$(MAKE) dry-run-btc-manual-metadata-import
	$(MAKE) dry-run-btc-fee-tier-overlay-import

apply-btc-paper-gate-manual-inputs:
	@test -n "$(EXCHANGE_INFO_RAW)" || (echo "EXCHANGE_INFO_RAW is required" >&2; exit 2)
	@test -n "$(FUNDING_INFO_RAW)" || (echo "FUNDING_INFO_RAW is required" >&2; exit 2)
	@test -n "$(EXCHANGE_INFO_HTTP_STATUS)" || (echo "EXCHANGE_INFO_HTTP_STATUS is required" >&2; exit 2)
	@test -n "$(FUNDING_INFO_HTTP_STATUS)" || (echo "FUNDING_INFO_HTTP_STATUS is required" >&2; exit 2)
	@test -n "$(BTC_MANUAL_METADATA_CAPTURED_AT)" || (echo "BTC_MANUAL_METADATA_CAPTURED_AT is required" >&2; exit 2)
	@test -n "$(BTC_FEE_TIER_MAKER_BPS)" || (echo "BTC_FEE_TIER_MAKER_BPS is required" >&2; exit 2)
	@test -n "$(BTC_FEE_TIER_TAKER_BPS)" || (echo "BTC_FEE_TIER_TAKER_BPS is required" >&2; exit 2)
	@test -n "$(BTC_FEE_TIER_CAPTURED_AT)" || (echo "BTC_FEE_TIER_CAPTURED_AT is required" >&2; exit 2)
	$(MAKE) dry-run-btc-manual-metadata-import
	$(MAKE) dry-run-btc-fee-tier-overlay-import
	$(MAKE) apply-btc-manual-metadata-import
	$(MAKE) apply-btc-fee-tier-overlay-import

apply-and-validate-btc-paper-gate-manual-inputs:
	$(MAKE) apply-btc-paper-gate-manual-inputs
	$(MAKE) validate-btc-evidence
	$(MAKE) check-btc-paper-validation-readiness

validate-candidate-gate:
	$(PYTHON) -m pytest tests/contracts/test_event_ledger_required.py tests/contracts/test_no_signal_equity_promotion.py tests/contracts/test_paper_live_locked.py tests/contracts/test_global_research_registry_schema.py -q

validate-no-production-data-hardening:
	$(PYTHON) scripts/build_us_equity_portfolio_fixture_event_ledger_report.py
	$(PYTHON) scripts/build_us_equity_portfolio_canonical_report.py
	$(PYTHON) scripts/build_global_research_registry.py
	$(PYTHON) scripts/check_artifact_lineage_health.py
	$(PYTHON) -m pytest tests/contracts/test_us_equity_portfolio_fixture_event_ledger.py tests/contracts/test_us_equity_portfolio_ledger_required.py tests/contracts/test_no_lookahead_factor_pipeline.py tests/contracts/test_no_lookahead_walk_forward.py tests/contracts/test_no_lookahead_portfolio_rebalance.py tests/contracts/test_risk_budget_contract.py tests/contracts/test_kill_switch_fail_closed.py tests/contracts/test_no_broker_import_in_evidence_builders.py tests/contracts/test_artifact_lineage_health_check.py tests/contracts/test_registry_failure_explanations.py tests/contracts/test_btc_audit_only_boundaries.py -q

ci-local: test test-integration frontend-build
	@echo "CI local passed"
