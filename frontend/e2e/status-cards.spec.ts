import {test, expect} from '@playwright/test';

test('Home page shows unified US equity, paper review, and live freeze cards', async ({page}) => {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const {pathname} = url;
    const method = route.request().method();

    if (method === 'GET' && pathname === '/api/health') {
      await route.fulfill({json: {status: 'ok', service: 'quantstation', data_source_default: 'sqlite', fastapi_available: true}});
      return;
    }

    if (method === 'GET' && pathname === '/api/strategies') {
      await route.fulfill({
        json: [
          {id: 'trend_macd', display_name: 'Trend MACD', description: 'US equity trend', category: 'equity', default_weight: 1, default_params: {}},
        ],
      });
      return;
    }

    if (method === 'GET' && pathname === '/api/system/overview') {
      await route.fulfill({
        json: {
          status: 'ok',
          stage: 'pre-live',
          mode: 'paper',
          data_root: 'data',
          health: {service: 'quantstation', data_source_default: 'sqlite', fastapi_available: true},
          registry: {integrity: 'PASS', path: 'data/research/evidence_registry.json'},
          paper_validation: {state: 'PASS', days_completed: 14, days_required: 20},
          minute_data_quality: {status: 'PASS', evaluated_symbols: ['AAPL'], bar_sizes: ['1d']},
          data_coverage: {status: 'PASS', coverage_pct: 100, min_coverage_pct: 95},
          paper_review: {
            status: 'BLOCKED',
            entry_allowed: false,
            manual_review_pending: true,
            summary: 'Paper evidence missing fresh review',
            manifest_path: 'reports/review/manifest.json',
            evidence_pack_path: 'reports/review/evidence-pack.json',
            review_path: 'reports/review/review.json',
          },
          broker_credentials: {credentials_present: true, endpoint_kind: 'paper', base_url_valid: true},
          execution: {
            live_state: 'frozen',
            live_block_reason: 'live frozen until paper review passes',
            paper_network_submit_confirmation: false,
          },
          small_account: {suggested_max_daily_notional: 5000, suggested_max_daily_order_count: 5},
          integrations: {
            dependencies: {qlib: true, pypfopt: true},
            qlib: {status: 'PASS', latest_run_id: 'qlib-001', latest_run: {run_id: 'qlib-001', workflow_status: 'PASS'}},
            portfolio: {status: 'PASS', latest_run_id: 'portfolio-001', latest_run: {portfolio_run_id: 'portfolio-001', status: 'READY_FOR_BACKTEST_ENTRY'}},
          },
          pit_data_intake: {
            status: 'production_pit_data_intake_blocked',
            current_blocking_stage: 'incoming_drop_readiness',
            next_action: {
              stage_id: 'incoming_drop_readiness',
              description: 'Place the six licensed CSV files under data/external/us_equity_lineage/incoming/manual_vendor_drop, then run readiness again.',
              first_blocker: 'source_dir_missing',
            },
            stages: [
              {stage_id: 'manual_vendor_drop_package', status: 'pass'},
              {stage_id: 'incoming_drop_readiness', status: 'blocked'},
            ],
            blockers: ['source_dir_missing'],
            operator_actions: [
              {
                label: '复查投放目录',
                intent: 'Validate required licensed CSV files under data/external/us_equity_lineage/incoming/manual_vendor_drop.',
                command: 'python scripts/build_us_equity_incoming_drop_readiness_report.py',
                blocked_until: 'incoming_drop_readiness_pass',
              },
            ],
          },
          development_plan_audit: {
            status: 'development_plan_blocked_by_production_pit_data',
            decision: 'continue_building_production_line_do_not_unlock_live',
            summary: {phase_count: 11, complete_count: 6, blocked_count: 4, observing_count: 1},
            phase_checks: [
              {
                phase_id: 'phase_1_data_lineage_hardening',
                title: '数据链路硬化与 PIT 生产数据包',
                status: 'blocked_external_data',
                blockers: ['production_bundle_missing', 'explicit_bundle_selection_missing'],
                blocked_count: 2,
              },
              {
                phase_id: 'phase_3_forward_observation_evaluation',
                title: 'Forward observation 30/60/90 日评估',
                status: 'observing',
                blockers: [],
                blocked_count: 0,
              },
            ],
          },
          live_readiness: {
            status: 'live_readiness_blocked',
            decision: 'do_not_start_live_trading',
            strategy_id: 'us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x',
            account_capital_usd: 10000,
            max_live_principal_usd: 0,
            live_order_allowed: false,
            paper_simulation_unlocked_by_this_report: false,
            blockers: [
              'us_equity_live_readiness_strategy_validation_gate_not_passed',
              'us_equity_live_readiness_forward_observation_less_than_30_days',
            ],
            gate_checks: {strategy_validation_gate_passed: false},
          },
          strategy_validation_gate: {
            status: 'blocked_data_quality',
            decision: 'do_not_claim_strategy_validated_until_data_quality_gate_passes',
            strategy_id: 'us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x',
            candidate_variant: 'min_adv_10m_to_shv + vol_target_20pct_cap1.5x',
            allowed_next_action: 'fix_blockers',
            forward_observation_allowed: true,
            paper_ready: false,
            live_ready: false,
            blockers: ['us_etf_strategy_validation_data_coverage_and_quality_failed'],
            checks: [
              {
                check_id: 'data_coverage_and_quality',
                passed: false,
                matched_data_quality_blockers: ['point_in_time_universe_not_confirmed'],
              },
              {check_id: 'walk_forward', passed: true, fold_count: 6},
            ],
          },
          forward_observation: {
            status: 'forward_observing',
            decision: 'continue_observing',
            daily_health_status: 'daily_health_pass',
            daily_health_decision: 'continue_forward_observation',
            observation_days: 1,
            minimum_complete_days: 30,
            latest_observation_date: '2026-06-23',
            blockers: [],
            metrics: {simulated_fill_count: 3},
          },
          manual_review_packet: {
            status: 'manual_review_pending',
            decision: 'human_review_required',
            blockers: [
              'us_equity_manual_review_strategy_validation_not_passed',
              'us_equity_manual_review_forward_observation_not_complete',
            ],
            evidence_checklist: [
              {check_id: 'strategy_validation_gate_passed', passed: false},
              {check_id: 'forward_ledger_recalculation_passed', passed: true},
            ],
            signoff_requirements: [
              {signoff_id: 'strategy_research_review', required: true, recorded: false},
            ],
          },
          paper_simulation_readiness: {
            status: 'paper_simulation_blocked',
            decision: 'do_not_start_paper_simulation',
            strategy_id: 'us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x',
            paper_ledger_root: 'data/paper_ledger/us_equity_etf_rotation_v1',
            paper_runner_allowed: false,
            required_runner_contract: {
              independent_ledger_root: 'data/paper_ledger/us_equity_etf_rotation_v1',
              must_not_reuse_forward_observation_ledger: true,
              order_endpoint_allowed: false,
              real_order_submitted: false,
            },
            manual_review_evidence: {
              forward_data_gate_no_blocked_runs: true,
              forward_data_gate_blocked_count: 0,
            },
            blockers: [
              'us_equity_paper_readiness_manual_review_not_ready',
              'us_equity_paper_readiness_strategy_validation_not_passed',
              'us_equity_paper_readiness_production_pit_intake_not_ready',
            ],
            unsafe_flags: [],
            source_reports: {
              production_pit_intake_status: 'artifacts/us_equity_data_lineage/latest/us_equity_pit_data_intake_status_report.json',
            },
            guardrails: {paper_simulation_allowed: false, live_order_allowed: false},
          },
          small_account_execution_preflight: {
            status: 'pass_observation_only',
            strategy_id: 'us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x',
            candidate_variant: 'min_adv_10m_to_shv',
            timestamp: '2026-06-23',
            account_equity: 10000,
            annual_financing_rate: 0.055,
            slippage_bps: 10,
            min_trade_amount_usd: 25,
            latest_target: {gross_exposure: 0.978, symbols: ['DBMF', 'SHV', 'USO']},
            scenario_count: 2,
            passed_scenario_count: 2,
            scenarios: [
              {
                scenario_id: 'one_x_cash_only',
                gross_cap: 1,
                effective_gross: 0.978,
                allow_margin: false,
                passes_preflight: true,
                fractional_cash_after_orders: 210.32,
                whole_cash_after_orders: 234.15,
              },
              {
                scenario_id: 'research_cap_1_5x',
                gross_cap: 1.5,
                effective_gross: 0.978,
                allow_margin: true,
                passes_preflight: true,
                fractional_cash_after_orders: 210.32,
                whole_cash_after_orders: 234.15,
              },
            ],
            blockers: [],
            guardrails: {live_order_allowed: false, research_cap_1_5x_not_live_default: true},
          },
          data_lineage_governance: {
            status: 'research_reconciled_promotion_blocked',
            reconciliation_status: 'research_reconciled_promotion_blocked',
            remediation_status: 'remediation_required',
            macro_release_lag_status: 'research_lag_only_release_calendar_missing',
            selected_price_source: 'tiingo_eod_adjusted',
            selected_price_root: 'data/external/us_equity_eod/tiingo/kline',
            lineage_maturity: 'research_only',
            remediation_task_count: 5,
            macro_source: 'FRED',
            accepted_evidence_for_promotion: false,
            blockers: ['fred_release_calendar_missing', 'point_in_time_universe_not_confirmed'],
            remediation_groups: [
              {group_id: 'point_in_time_universe', status: 'blocked', blocker_count: 1},
              {group_id: 'corporate_actions', status: 'blocked', blocker_count: 1},
            ],
          },
          production_data_acquisition: {
            status: 'production_data_acquisition_required',
            acquisition_status: 'production_data_acquisition_required',
            candidate_evidence_status: 'candidate_evidence_ready_for_manual_bundle_build',
            candidate_evidence_decision: 'use_as_manual_bundle_build_input_only_do_not_promote',
            intake_packet_status: 'intake_packet_ready_for_data_vendor_drop',
            intake_packet_decision: 'prepare_external_pit_bundle_drop_do_not_unlock_trading',
            manual_package_status: 'manual_vendor_drop_package_ready',
            incoming_drop_dir: 'data/external/us_equity_lineage/incoming/manual_vendor_drop',
            default_bundle_id: 'manual_vendor_bundle_v1',
            acceptable_provider_ids: ['crsp', 'sharadar', 'norgate', 'local_csv'],
            missing_contract_groups: ['pit_universe', 'survivorship', 'corporate_actions'],
            required_table_count: 6,
            field_count: 51,
            required_tables: [
              {table: 'universe_membership_events', filename: 'universe_membership_events.csv', field_count: 3},
              {table: 'delisted_symbols', filename: 'delisted_symbols.csv', field_count: 3},
            ],
            operator_steps: [
              {
                step_id: 'prepare_incoming_drop',
                command: 'Place the six licensed CSV files in data/external/us_equity_lineage/incoming/manual_vendor_drop',
                expected_result: 'incoming drop contains licensed CSV files',
              },
              {
                step_id: 'run_importer',
                command:
                  'python scripts/import_us_equity_local_csv_production_bundle.py --source-dir data/external/us_equity_lineage/incoming/manual_vendor_drop --bundle-id manual_vendor_bundle_v1',
                expected_result: 'bundle created',
              },
            ],
            blockers: ['production_bundle_missing'],
          },
          production_bundle_gate: {
            status: 'production_bundle_gate_blocked',
            current_blocking_stage: 'incoming_drop_readiness',
            stages: [
              {
                stage_id: 'incoming_drop_readiness',
                status: 'incoming_drop_blocked',
                blockers: ['source_dir_missing'],
                summary: {source_dir: 'data/external/us_equity_lineage/incoming/manual_vendor_drop'},
              },
              {
                stage_id: 'local_csv_import',
                status: 'production_bundle_import_blocked',
                blockers: ['source_dir_missing'],
                summary: {bundle_id: 'manual_vendor_bundle_v1'},
              },
              {
                stage_id: 'production_bundle_activation',
                status: 'activation_blocked',
                blockers: ['candidate_bundle_manifest_missing'],
                summary: {candidate_bundle_id: 'manual_vendor_bundle_v1'},
              },
            ],
            operator_actions: [
              {
                stage_id: 'incoming_drop_readiness',
                label: 'check_incoming_drop_readiness',
                command: 'python scripts/build_us_equity_incoming_drop_readiness_report.py',
                blocked_until: 'incoming_drop_ready_for_import',
              },
              {
                stage_id: 'local_csv_import',
                label: 'import_local_csv_production_bundle',
                command:
                  'python scripts/import_us_equity_local_csv_production_bundle.py --source-dir data/external/us_equity_lineage/incoming/manual_vendor_drop --bundle-id manual_vendor_bundle_v1 --promotion-clean-allowed',
                blocked_until: 'production_bundle_imported',
              },
              {
                stage_id: 'production_bundle_activation',
                label: 'build_activation_report',
                command:
                  'python scripts/build_us_equity_production_bundle_activation_report.py --bundle-id manual_vendor_bundle_v1 --license-reviewed',
                blocked_until: 'activation_ready_for_manual_config_apply',
              },
            ],
            blockers: ['source_dir_missing', 'candidate_bundle_manifest_missing'],
            guardrails: {live_order_allowed: false, paper_simulation_allowed: false},
          },
          standard_report_schema_audit: {
            status: 'schema_audit_pass',
            decision: 'standard_schema_ready_for_manual_review',
            strategy_id: 'us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x',
            candidate_variant: 'min_adv_10m_to_shv + vol_target_20pct_cap1.5x',
            required_fields: ['strategy_id', 'metrics', 'benchmarks'],
            coverage_summary: {
              required_field_count: 3,
              passed_field_count: 3,
              missing_input_count: 0,
              unsafe_flag_count: 0,
            },
            field_checks: [
              {field_id: 'strategy_id', passed: true},
              {field_id: 'metrics', passed: true},
              {field_id: 'benchmarks', passed: true},
            ],
            blockers: [],
          },
          monitoring_rules: {
            status: 'monitoring_rules_defined',
            strategy_id: 'us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x',
            monitor_count: 18,
            required_before_paper_or_live: true,
            minimum_required_before_paper: ['structured_daily_run_report', 'data_staleness_stop'],
            rule_sections: ['data_monitors', 'retirement_rules'],
            blockers: [],
          },
          replay_readiness: {
            status: 'replay_readiness_pass',
            decision: 'replay_inputs_available_for_manual_audit',
            latest_observation: {timestamp: '2026-06-23', fill_count: 3},
            checks: [
              {check_id: 'fixed_replay_contract', passed: true},
              {check_id: 'unsafe_flags', passed: true},
            ],
            blockers: [],
          },
          strategy_registry: {
            status: 'present',
            strategy_count: 2,
            primary_strategy_id: 'us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x',
            primary_stage: 'forward_observation',
            primary_status: 'forward_observation_only',
            registered_families: ['us_etf_macro_momentum_rotation', 'dual_momentum'],
            stage_counts: {forward_observation: 1, strategy_hypothesis_registration: 1},
            status_counts: {forward_observation_only: 1, hypothesis_registered_only: 1},
            blockers: [],
            audit: {
              status: 'pass',
              strategy_count: 2,
              primary_candidate_count: 1,
              formal_candidate_count: 1,
              missing_required_families: [],
              required_families: ['us_etf_macro_momentum_rotation', 'dual_momentum'],
              blockers: [],
              warnings: [],
            },
            strategies: [
              {
                strategy_id: 'us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x',
                family: 'us_etf_macro_momentum_rotation',
                status: 'forward_observation_only',
                current_stage: 'forward_observation',
                primary_candidate: true,
                paper_ready: false,
                live_ready: false,
              },
              {
                strategy_id: 'us_equity_dual_momentum_research_placeholder',
                family: 'dual_momentum',
                status: 'hypothesis_registered_only',
                current_stage: 'strategy_hypothesis_registration',
                primary_candidate: false,
                paper_ready: false,
                live_ready: false,
              },
            ],
            policy: {live_order_allowed: false},
          },
          daily_production_line: {
            status: 'PASS',
            decision: 'continue_forward_observation_and_keep_paper_live_locked',
            generated_at: '2026-06-26T01:55:51Z',
            pipeline: 'us_equity_daily_production_line',
            step_count: 2,
            passed_step_count: 2,
            failed_step_count: 0,
            expected_external_blocker: {
              production_pit_data_required: true,
              production_line_status: 'production_line_blocked_before_paper_or_live',
              development_plan_status: 'development_plan_blocked_by_production_pit_data',
            },
            forward_observation: {
              daily_health_status: 'daily_health_pass',
              observation_days: 1,
              minimum_complete_days: 30,
            },
            forward_data_gate: {
              status: 'pass',
              checks: [
                {check_id: 'data_freshness', status: 'pass', passed: true, first_blocker: ''},
                {check_id: 'kline_quality', status: 'warn', passed: true, first_blocker: ''},
                {check_id: 'fred_preflight', status: 'fred_macro_preflight_warn', passed: true, first_blocker: ''},
              ],
              blockers: [],
            },
            steps: [
              {step_id: 'etf_kline_quality_daily', status: 'warn', passed: true, first_blocker: ''},
              {
                step_id: 'strategy_production_line',
                status: 'production_line_blocked_before_paper_or_live',
                passed: true,
                first_blocker: '',
              },
            ],
            blockers: [],
            unsafe_flags: [],
            guardrails: {live_order_allowed: false},
          },
          next_actions: ['Review paper evidence before live approval.'],
        },
      });
      return;
    }

    if (method === 'GET' && pathname === '/api/us/paper/status') {
      await route.fulfill({
        json: {
          equity: 100000,
          cash: 50000,
          buying_power: 50000,
          positions: 0,
          kill_switch_triggered: true,
          kill_switch_reason: 'live frozen until paper review passes',
          days_traded: 14,
          healthy: true,
          last_reconciliation_passed: true,
        },
      });
      return;
    }

    if (method === 'GET' && pathname === '/api/us/paper/daily-results') {
      await route.fulfill({json: []});
      return;
    }

    await route.fulfill({status: 404, json: {error: `Unhandled mock for ${method} ${pathname}`}});
  });

  await page.goto('/');
  await expect(page.locator('[data-testid="module-state-us-equity"]')).toContainText('BLOCKED');
  await expect(page.locator('[data-testid="module-state-paper-review"]')).toContainText('BLOCKED');
  await expect(page.locator('[data-testid="module-state-live-freeze"]')).toContainText('PASS');
  await expect(page.locator('[data-testid="us-equity-pit-intake-card"]')).toContainText('incoming_drop_readiness');
  await expect(page.locator('[data-testid="us-equity-pit-intake-card"]')).toContainText('source_dir_missing');
  await expect(page.locator('[data-testid="us-equity-pit-operator-actions"]')).toContainText('build_us_equity_incoming_drop_readiness_report.py');
  await expect(page.locator('[data-testid="us-equity-pit-operator-actions"]')).toContainText('data/external/us_equity_lineage/incoming/manual_vendor_drop');
  await expect(page.locator('[data-testid="us-equity-data-lineage-governance"]')).toContainText('research_reconciled_promotion_blocked');
  await expect(page.locator('[data-testid="us-equity-data-lineage-governance"]')).toContainText('tiingo_eod_adjusted');
  await expect(page.locator('[data-testid="us-equity-data-lineage-governance"]')).toContainText('fred_release_calendar_missing');
  await expect(page.locator('[data-testid="us-equity-production-data-acquisition"]')).toContainText('production_data_acquisition_required');
  await expect(page.locator('[data-testid="us-equity-production-data-acquisition"]')).toContainText('manual_vendor_bundle_v1');
  await expect(page.locator('[data-testid="us-equity-production-data-acquisition"]')).toContainText('local_csv');
  await expect(page.locator('[data-testid="us-equity-production-data-acquisition"]')).toContainText('universe_membership_events.csv');
  await expect(page.locator('[data-testid="us-equity-production-data-acquisition"]')).toContainText('production_bundle_missing');
  await expect(page.locator('[data-testid="us-equity-production-bundle-gate"]')).toContainText('production_bundle_gate_blocked');
  await expect(page.locator('[data-testid="us-equity-production-bundle-gate"]')).toContainText('incoming_drop_readiness');
  await expect(page.locator('[data-testid="us-equity-production-bundle-gate"]')).toContainText('local_csv_import');
  await expect(page.locator('[data-testid="us-equity-production-bundle-gate"]')).toContainText('activation_blocked');
  await expect(page.locator('[data-testid="us-equity-production-bundle-gate"]')).toContainText('source_dir_missing');
  await expect(page.locator('[data-testid="us-equity-production-bundle-gate"]')).toContainText('build_us_equity_incoming_drop_readiness_report.py');
  await expect(page.locator('[data-testid="us-equity-production-bundle-gate"]')).toContainText('import_us_equity_local_csv_production_bundle.py');
  await expect(page.locator('[data-testid="us-equity-production-bundle-gate"]')).toContainText('build_us_equity_production_bundle_activation_report.py');
  await expect(page.locator('[data-testid="us-equity-development-plan-audit"]')).toContainText('development_plan_blocked_by_production_pit_data');
  await expect(page.locator('[data-testid="us-equity-development-plan-audit"]')).toContainText('数据链路硬化与 PIT 生产数据包');
  await expect(page.locator('[data-testid="us-equity-development-plan-audit"]')).toContainText('production_bundle_missing');
  await expect(page.locator('[data-testid="us-equity-daily-production-line"]')).toContainText('continue_forward_observation_and_keep_paper_live_locked');
  await expect(page.locator('[data-testid="us-equity-daily-production-line"]')).toContainText('steps 2/2');
  await expect(page.locator('[data-testid="us-equity-daily-production-line"]')).toContainText('production_line_blocked_before_paper_or_live');
  await expect(page.locator('[data-testid="us-equity-daily-production-line"]')).toContainText('data gate pass');
  await expect(page.locator('[data-testid="us-equity-daily-production-line"]')).toContainText('data_freshness');
  await expect(page.locator('[data-testid="us-equity-daily-production-line"]')).toContainText('fred_preflight');
  await expect(page.locator('[data-testid="us-equity-strategy-registry-summary"]')).toContainText('us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x');
  await expect(page.locator('[data-testid="us-equity-strategy-registry-summary"]')).toContainText('forward_observation');
  await expect(page.locator('[data-testid="us-equity-strategy-registry-summary"]')).toContainText('hypothesis_registered_only');
  await expect(page.locator('[data-testid="us-equity-strategy-registry-summary"]')).toContainText('audit pass');
  await expect(page.locator('[data-testid="us-equity-strategy-registry-summary"]')).toContainText('formal 1');
  await expect(page.locator('[data-testid="module-state-live-freeze"]')).toContainText('live_readiness_blocked');
  await expect(page.locator('[data-testid="us-equity-live-readiness-summary"]')).toContainText('do_not_start_live_trading');
  await expect(page.locator('[data-testid="us-equity-live-readiness-summary"]')).toContainText('us_equity_live_readiness_strategy_validation_gate_not_passed');
  await expect(page.locator('[data-testid="us-equity-strategy-validation-gate"]')).toContainText('blocked_data_quality');
  await expect(page.locator('[data-testid="us-equity-strategy-validation-gate"]')).toContainText('us_etf_strategy_validation_data_coverage_and_quality_failed');
  await expect(page.locator('[data-testid="us-equity-strategy-validation-gate"]')).toContainText('point_in_time_universe_not_confirmed');
  await expect(page.locator('[data-testid="us-equity-forward-observation-summary"]')).toContainText('forward_observing');
  await expect(page.locator('[data-testid="us-equity-forward-observation-summary"]')).toContainText('1/30');
  await expect(page.locator('[data-testid="us-equity-manual-review-packet"]')).toContainText('manual_review_pending');
  await expect(page.locator('[data-testid="us-equity-manual-review-packet"]')).toContainText('us_equity_manual_review_strategy_validation_not_passed');
  await expect(page.locator('[data-testid="us-equity-small-account-preflight"]')).toContainText('pass_observation_only');
  await expect(page.locator('[data-testid="us-equity-small-account-preflight"]')).toContainText('账户 $10,000');
  await expect(page.locator('[data-testid="us-equity-small-account-preflight"]')).toContainText('场景 2/2');
  await expect(page.locator('[data-testid="us-equity-small-account-preflight"]')).toContainText('research_cap_1_5x');
  await expect(page.locator('[data-testid="us-equity-paper-simulation-readiness"]')).toContainText('paper_simulation_blocked');
  await expect(page.locator('[data-testid="us-equity-paper-simulation-readiness"]')).toContainText('runner locked');
  await expect(page.locator('[data-testid="us-equity-paper-simulation-readiness"]')).toContainText('us_equity_paper_readiness_strategy_validation_not_passed');
  await expect(page.locator('[data-testid="us-equity-paper-simulation-readiness"]')).toContainText('us_equity_paper_readiness_production_pit_intake_not_ready');
  await expect(page.locator('[data-testid="us-equity-paper-simulation-readiness"]')).toContainText('forward data gate clean');
  await expect(page.locator('[data-testid="us-equity-paper-simulation-readiness"]')).toContainText('PIT artifacts/us_equity_data_lineage/latest/us_equity_pit_data_intake_status_report.json');
  await expect(page.locator('[data-testid="us-equity-standard-schema-audit"]')).toContainText('schema_audit_pass');
  await expect(page.locator('[data-testid="us-equity-standard-schema-audit"]')).toContainText('3/3');
  await expect(page.locator('[data-testid="us-equity-standard-schema-audit"]')).toContainText('benchmarks');
  await expect(page.locator('[data-testid="us-equity-monitoring-rules"]')).toContainText('monitoring_rules_defined');
  await expect(page.locator('[data-testid="us-equity-monitoring-rules"]')).toContainText('structured_daily_run_report');
  await expect(page.locator('[data-testid="us-equity-replay-readiness"]')).toContainText('replay_readiness_pass');
  await expect(page.locator('[data-testid="us-equity-replay-readiness"]')).toContainText('fills 3');
  await expect(page.locator('body')).not.toHaveCSS('background-color', 'rgb(0, 0, 0)');
});
