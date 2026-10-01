import type {Page} from '@playwright/test';
import {execFileSync} from 'node:child_process';

export type BtcTradingMockOptions = {
  signalReady?: boolean;
  canonicalFreshness?: string;
  runtimeStatus?: string;
  runtimeBlockers?: string[];
  catalogError?: string;
  catalogFailuresBeforeSuccess?: number;
  statusError?: string;
  klinesError?: string;
  initialEquity?: string;
  reconciledEquity?: string;
  domainReadModelError?: string;
  domainReadModelUnsafe?: boolean;
  domainReadModelHead?: string;
  domainReadModelSyntheticSafetyKeys?: boolean;
  domainReadModelInvalidRequiredBlockers?: boolean;
  domainReadModelRequiredBlockerContract?: 'legacy' | 'quality' | 'current-head-rebuild';
  domainReadModelRequiredBlockerTamper?:
    | 'missing'
    | 'extra'
    | 'reordered'
    | 'sha'
    | 'count'
    | 'preserved'
    | 'payload';
  domainReadModelInvalidGateDecision?: boolean;
  historyIdentityMismatch?: boolean;
  bootstrapDelayMs?: number;
  catalogDelayMs?: number;
  statusDelayMs?: number;
  klinesDelayMs?: number;
};

export type BtcTradingMockState = {
  runtimeStatus: string;
  reconciled: boolean;
  calls: Array<{pathname: string; payload: Record<string, unknown>}>;
  requests: Array<{method: string; pathname: string}>;
};

export async function mockBtcTradingPage(page: Page, options: BtcTradingMockOptions = {}): Promise<BtcTradingMockState> {
  const state: BtcTradingMockState = {
    runtimeStatus: options.runtimeStatus ?? 'stopped',
    reconciled: false,
    calls: [],
    requests: [],
  };
  let catalogAttempts = 0;
  let marketTickerSequence = 0;
  const delayBootstrap = async (endpointDelayMs?: number) => {
    const delayMs = endpointDelayMs ?? options.bootstrapDelayMs;
    if (delayMs) {
      await new Promise((resolve) => setTimeout(resolve, delayMs));
    }
  };
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    const method = request.method();
    state.requests.push({method, pathname});

    if (method === 'GET' && pathname === '/api/health') {
      return route.fulfill({json: {status: 'ok', service: 'quantstation', data_source_default: 'sqlite', fastapi_available: true}});
    }
    if (method === 'GET' && pathname === '/api/strategies') return route.fulfill({json: []});
    if (method === 'GET' && pathname === '/api/research/btc/domain-read-model') {
      if (options.domainReadModelError) {
        return route.fulfill({
          status: 503,
          json: {detail: options.domainReadModelError},
        });
      }
      return route.fulfill({
        headers: {'Cache-Control': 'no-store'},
        json: domainReadModelFixture(options),
      });
    }
    if (method === 'GET' && pathname === '/api/research/btc/demo-paper/catalog') {
      await delayBootstrap(options.catalogDelayMs);
      catalogAttempts += 1;
      if (catalogAttempts <= (options.catalogFailuresBeforeSuccess ?? 0)) {
        return route.fulfill({
          status: 503,
          json: {detail: 'catalog temporarily unavailable'},
        });
      }
      if (options.catalogError) return route.fulfill({status: 503, json: {detail: options.catalogError}});
      return route.fulfill({json: catalogFixture()});
    }
    if (method === 'GET' && pathname === '/api/research/btc/demo-paper/status') {
      await delayBootstrap(options.statusDelayMs);
      if (options.statusError) return route.fulfill({status: 503, json: {detail: options.statusError}});
      return route.fulfill({json: runtimeFixture(state.runtimeStatus, options, state.reconciled)});
    }
    if (method === 'GET' && pathname === '/api/research/btc/demo-paper/private-readonly-observation') {
      return route.fulfill({json: privateReadonlyObservationFixture()});
    }
    if (method === 'GET' && pathname === '/api/research/btc/demo-paper/klines') {
      await delayBootstrap(options.klinesDelayMs);
      if (options.klinesError) return route.fulfill({status: 503, json: {detail: options.klinesError}});
      return route.fulfill({json: klineFixture(options.signalReady ?? true)});
    }
    if (method === 'GET' && pathname === '/api/research/btc/demo-paper/market-view') {
      await delayBootstrap(options.klinesDelayMs);
      if (options.klinesError) return route.fulfill({status: 503, json: {detail: options.klinesError}});
      const timeframe = new URL(request.url()).searchParams.get('timeframe') ?? '1m';
      return route.fulfill({json: publicMarketViewFixture(timeframe)});
    }
    if (method === 'GET' && pathname === '/api/research/btc/demo-paper/market-ticker') {
      marketTickerSequence += 1;
      const timestampMs = Date.UTC(2026, 6, 14, 15, 0, marketTickerSequence * 2);
      const last = String(62032 + marketTickerSequence);
      return route.fulfill({json: {
        schema_version: 'okx_public_market_ticker_v1',
        source_kind: 'okx_public_market_ticker_v1',
        instrument_id: 'BTC-USDT-SWAP',
        read_only: true,
        public_only: true,
        private_endpoint_used: false,
        order_endpoint_used: false,
        strategy_signal_compatible: false,
        captured_at_ms: timestampMs,
        cache_age_ms: 0,
        stale: false,
        last_error_code: '',
        sequence: marketTickerSequence,
        ticker: {bid: String(Number(last) - 1), ask: String(Number(last) + 1), last, timestamp_ms: timestampMs},
      }});
    }
    if (method === 'GET' && pathname === '/api/research/btc/strategy-history/catalog') {
      return route.fulfill({json: strategyHistoryCatalogFixture()});
    }
    if (method === 'GET' && pathname === '/api/research/btc/strategy-registry') {
      return route.fulfill({json: strategyRegistryFixture()});
    }
    if (method === 'GET' && pathname === '/api/research/strategy-history/catalog') {
      return route.fulfill({json: unifiedStrategyHistoryCatalogFixture()});
    }
    if (method === 'GET' && pathname.startsWith('/api/research/btc/strategy-history/')) {
      const parts = pathname.split('/').filter(Boolean);
      const strategyId = decodeURIComponent(parts[4] ?? '');
      const candidateId = decodeURIComponent(parts[5] ?? '');
      const known = catalogFixture().strategies.some(
        (item) => item.strategy_id === strategyId && item.candidate_id === candidateId,
      );
      if (!known) return route.fulfill({status: 404, json: {detail: 'unknown candidate'}});
      const payload = strategyHistoryFixture(strategyId, candidateId);
      if (options.historyIdentityMismatch) {
        payload.candidate_id = 'mismatched-candidate';
      }
      return route.fulfill({json: payload});
    }
    if (method === 'GET' && pathname === '/api/research/btc/canonical-backtest/latest') {
      return route.fulfill({json: canonicalFixture(options.canonicalFreshness ?? 'pass')});
    }
    if (method === 'GET' && pathname === '/api/research/btc/canonical-backtest/latest/report') {
      return route.fulfill({json: canonicalReportFixture(options.canonicalFreshness ?? 'pass', false)});
    }
    if (method === 'GET' && pathname === '/api/research/btc/okx-native-backtest/latest') {
      return route.fulfill({json: nativeCanonicalFixture(options.canonicalFreshness ?? 'pass')});
    }
    if (method === 'GET' && pathname === '/api/research/btc/okx-native-backtest/latest/report') {
      return route.fulfill({json: canonicalReportFixture(options.canonicalFreshness ?? 'pass', true)});
    }
    if (method === 'POST' && (pathname === '/api/backtests/crypto-event' || pathname === '/api/research/btc/okx-native-backtest/run')) {
      state.calls.push({pathname, payload: request.postDataJSON() as Record<string, unknown>});
      return route.fulfill({json: backtestRunFixture()});
    }
    if (method === 'GET' && pathname === '/api/runs/run-test-001/chart') return route.fulfill({json: backtestChartFixture()});
    if (method === 'POST' && pathname.startsWith('/api/research/btc/demo-paper/')) {
      const payload = request.postDataJSON() as Record<string, unknown>;
      state.calls.push({pathname, payload});
      if (pathname.endsWith('/start')) state.runtimeStatus = 'running';
      if (pathname.endsWith('/stop')) state.runtimeStatus = 'stopped';
      if (pathname.endsWith('/cancel-only')) state.runtimeStatus = 'cancel_only';
      if (pathname.endsWith('/reconcile')) state.reconciled = true;
      return route.fulfill({json: runtimeFixture(state.runtimeStatus, options, state.reconciled)});
    }
    return route.fulfill({status: 404, json: {detail: 'fixture unavailable'}});
  });
  return state;
}

export function privateReadonlyObservationFixture() {
  const head = currentGitHead();
  return {
    schema_version: 'btc_private_readonly_observation_projection_v1',
    status: 'observing',
    freshness: 'current',
    source_head: head,
    current_head: head,
    head_match: true,
    runner_active: true,
    gate_eligible: false,
    run_id: 'btc-private-readonly-fixture',
    phase: 'observing',
    started_at_utc: '2026-09-02T00:00:00Z',
    eligible_since_utc: '2026-09-02T00:00:00Z',
    last_observed_at_utc: '2026-09-02T00:29:30Z',
    progress: {
      required_hours: 25,
      completed_hours: 0,
      current_hour_fraction: 0.5,
      progress_hours: 0.5,
      remaining_hours: 24.5,
      receipt_count: 0,
      last_receipt_hour_utc: '',
      complete: false,
    },
    private_ws: {connected: true, listener_alive: true, reconciled: true},
    reconciliation: {
      rest_snapshot_observed: true,
      snapshot_reconciled: true,
      funding_reconciled: true,
    },
    blockers: [],
    gap_flags: [],
    safety_flags: {
      promotion: false,
      paper: false,
      live: false,
      private: false,
      order: false,
      real_order: false,
      transfer: false,
      withdraw: false,
    },
  };
}

export function domainReadModelFixture(options: BtcTradingMockOptions = {}) {
  const safety = Object.fromEntries((options.domainReadModelSyntheticSafetyKeys
    ? Array.from({length: 49}, (_, index) => `safety_${index + 1}`)
    : BTC_SAFETY_KEYS
  ).map(key => [key, false]));
  const unsafe = options.domainReadModelUnsafe === true;
  const contract = options.domainReadModelRequiredBlockerContract === 'quality'
    ? BTC_QUALITY_L2_REQUIRED_BLOCKER_CONTRACT
    : options.domainReadModelRequiredBlockerContract === 'current-head-rebuild'
      ? BTC_CURRENT_HEAD_REBUILD_REQUIRED_BLOCKER_CONTRACT
      : BTC_LEGACY_REQUIRED_BLOCKER_CONTRACT;
  const tamper = options.domainReadModelRequiredBlockerTamper
    ?? (options.domainReadModelInvalidRequiredBlockers ? 'reordered' : undefined);
  const requiredBlockers = [...contract.requiredBlockers];
  let requiredBlockersSha256 = contract.sha256;
  let requiredBlockerCount = contract.requiredBlockers.length;
  let requiredBlockersPreserved = true;
  if (tamper === 'missing') requiredBlockers.pop();
  if (tamper === 'extra') requiredBlockers.push('unexpected_required_blocker');
  if (tamper === 'reordered') {
    [requiredBlockers[0], requiredBlockers[1]] = [
      requiredBlockers[1],
      requiredBlockers[0],
    ];
  }
  if (tamper === 'sha') requiredBlockersSha256 = '0'.repeat(64);
  if (tamper === 'count') requiredBlockerCount += 1;
  if (tamper === 'preserved') requiredBlockersPreserved = false;
  const blockerCount = contract === BTC_QUALITY_L2_REQUIRED_BLOCKER_CONTRACT
    ? 183
    : contract === BTC_CURRENT_HEAD_REBUILD_REQUIRED_BLOCKER_CONTRACT
      ? 10
      : 184;
  const requiredCodes = contract.requiredBlockers.map(requiredBlockerCode);
  const blockerCodes = Array.from({length: blockerCount}, (_, index) => (
    index < requiredCodes.length
      ? requiredCodes[index]
      : `current_head_blocker_${index.toString().padStart(3, '0')}`
  ));
  if (tamper === 'payload') {
    blockerCodes[0] = 'required_blocker_payload_mismatch';
  }
  const blockers = blockerCodes.map((code) => ({
    code,
    category: 'engineering',
    owner: 'btc_developer',
    next_executable_action: `resolve_engineering_blocker:${code}`,
  }));
  return {
    schema_version: 'btc_domain_read_model_v1',
    domain: 'btc',
    source_head: options.domainReadModelHead ?? currentGitHead(),
    code_commit: options.domainReadModelHead ?? currentGitHead(),
    generated_at_utc: '2026-07-27T14:00:00Z',
    freshness: 'current_head',
    status: 'blocked',
    current_stage: 'pending_next_stage_gate',
    decision: 'blocked_fail_closed_no_paper_no_live',
    gate_decision: options.domainReadModelInvalidGateDecision
      ? 'blocked'
      : 'blocked_fail_closed_no_paper_no_live',
    readiness_class: 'quality_checked',
    promotion_evidence_ready: unsafe,
    paper_ready: false,
    live_ready: false,
    blockers,
    blocker_count: blockerCount,
    required_blocker_count: requiredBlockerCount,
    required_blockers_sha256: requiredBlockersSha256,
    required_blockers_preserved: requiredBlockersPreserved,
    required_blockers: requiredBlockers,
    safety,
  };
}

const BTC_LEGACY_REQUIRED_BLOCKERS = [
  'btc_okx_websocket_client_dependency_missing',
  'real_timestamp_aligned_l2_missing',
  'btc_okx_l2_sequence_continuity_unverified',
  'l2_lt_30_natural_days',
  'btc_open_interest_history_not_verified_diagnostic_partial',
  'btc_okx_server_time_offset_exceeds_threshold',
  'manifest_data_schema_mismatch',
  'manifest_quality_status_not_pass',
  'l2_manifest_attestation_readiness_mismatch',
  'runtime_pointer_immutable_snapshot_not_published',
  'runtime_pointer_data_steward_attestation_required',
  'not_promotion_evidence',
  'owner:btc_operations btc_next_stage:real_funding_cashflow_evidence_missing',
  'owner:btc_operations btc_next_stage:real_private_ws_reconciliation_evidence_missing',
  'owner:btc_observation btc_next_stage:real_non_flat_fill_evidence_missing',
  'owner:btc_observation btc_next_stage:natural_observation_window_30_60d_incomplete',
  'owner:architect/manual_reviewer btc_next_stage:manual_promotion_approval_missing',
] as const;

const BTC_QUALITY_L2_REQUIRED_BLOCKERS = [
  'btc_okx_l2_history_below_30_natural_days',
  'btc_execution_latency_model_missing',
  'btc_queue_model_missing',
  'btc_okx_l2_natural_execution_observation_missing',
  'btc_okx_l2_two_sided_coverage_incomplete',
  'btc_private_ws_evidence_missing',
  'btc_real_funding_nonflat_fill_evidence_missing',
  'btc_paper_live_manual_approval_missing',
  'btc_open_interest_history_not_verified_diagnostic_partial',
  'not_promotion_evidence',
  'owner:btc_operations btc_next_stage:real_funding_cashflow_evidence_missing',
  'owner:btc_operations btc_next_stage:real_private_ws_reconciliation_evidence_missing',
  'owner:btc_observation btc_next_stage:real_non_flat_fill_evidence_missing',
  'owner:btc_observation btc_next_stage:natural_observation_window_30_60d_incomplete',
  'owner:architect/manual_reviewer btc_next_stage:manual_promotion_approval_missing',
  'btc_next_stage:ledger_positions_cash_pnl_receipts_missing',
  'btc_next_stage:replay_observe_only_offline_no_paper_queue',
] as const;

const BTC_CURRENT_HEAD_REBUILD_REQUIRED_BLOCKERS = [
  'btc_okx_native:promotion_evidence_current_head_rebuild_required',
  'btc_okx_native:historical_timestamp_aligned_depth_fill_mapping_missing',
  'btc_okx_native:active_strategy_family_dependency_scope_missing',
  'btc_okx_native:effective_sample_regime_coverage_prereg_evidence_incomplete',
  'btc_okx_native:active_criteria_pointer_lineage_mismatch',
  'btc_okx_native:natural_strategy_runtime_non_flat_fill_sample_missing',
  'btc_okx_native:funding_cashflow_not_observed_in_demo_runtime',
  'btc_okx_native:private_ws_runtime_reconciliation_observation_incomplete',
  'btc_okx_native:25_hour_demo_observation_window_incomplete',
  'btc_okx_native:manual_promotion_approval_missing',
] as const;

const BTC_LEGACY_REQUIRED_BLOCKER_CONTRACT = {
  requiredBlockers: BTC_LEGACY_REQUIRED_BLOCKERS,
  sha256: 'd7e66f764b4f1c0a5ed19eed267d519ae662b3a3d09f125cdea649e1f2f8dd4f',
} as const;

const BTC_QUALITY_L2_REQUIRED_BLOCKER_CONTRACT = {
  requiredBlockers: BTC_QUALITY_L2_REQUIRED_BLOCKERS,
  sha256: 'f0e1ce43e7927f505d44ea2b1918bac3335868ec80681f1641e140c655dd7e36',
} as const;

const BTC_CURRENT_HEAD_REBUILD_REQUIRED_BLOCKER_CONTRACT = {
  requiredBlockers: BTC_CURRENT_HEAD_REBUILD_REQUIRED_BLOCKERS,
  sha256: 'cc0d8cbd8ff93afeab933d1b87bed493f667177aa1c9b1fdbe38a42a07ec65fa',
} as const;

function requiredBlockerCode(value: string): string {
  return value.startsWith('owner:') && value.includes(' ')
    ? value.slice(value.indexOf(' ') + 1)
    : value;
}

const BTC_SAFETY_KEYS = [
  'api_key_permission_reviewed',
  'approval_granted',
  'broker_access_allowed',
  'broker_calls_used',
  'broker_endpoint_accessed',
  'broker_endpoint_allowed',
  'broker_or_order_allowed',
  'credential_permissions_verified',
  'demo_allowed',
  'demo_order_submitted',
  'demo_trading_enabled',
  'live_allowed',
  'paper_allowed',
  'live_enabled',
  'live_order_allowed',
  'live_ready',
  'live_unlock_allowed',
  'manual_approval_recorded',
  'micro_live_allowed',
  'network_accessed',
  'oms_access_allowed',
  'order_endpoint_accessed',
  'order_endpoint_allowed',
  'order_endpoint_used',
  'order_submission_allowed',
  'paper_candidate_allowed',
  'paper_candidate_created',
  'paper_execution_authorized',
  'paper_order_intake_allowed',
  'paper_order_submitted',
  'paper_or_live_unlock_allowed',
  'paper_queue_write_allowed',
  'paper_queue_write_enabled',
  'paper_ready',
  'paper_start_allowed',
  'permission_evidence_ready',
  'permission_granted',
  'position_increase_allowed',
  'private_endpoint_accessed',
  'private_endpoint_allowed',
  'private_endpoint_used',
  'promotion_allowed',
  'promotion_evidence_ready',
  'real_order_submitted',
  'real_orders_enabled',
  'secret_access_allowed',
  'secrets_read',
  'strategy_skeleton_generated',
  'withdraw_allowed',
] as const;

function currentGitHead(): string {
  return execFileSync('git', ['rev-parse', 'HEAD'], {
    cwd: '..',
    encoding: 'utf8',
  }).trim();
}

export function catalogFixture() {
  return {
    schema_version: 'btc_demo_strategy_catalog_v1',
    environment: 'OKX Demo',
    instrument_id: 'BTC-USDT-SWAP',
    authorization_ticket: 'BTC-OKX-DEMO-PAPER-01',
    confirmation_text: 'BTC DEMO',
    default_strategy_id: 'long_short_donchian_top5_okx_native',
    default_candidate_id: 'okx_native_btc_ls_tf_stable_001',
    default_reason: 'okx_native_current_evidence_passed',
    strategies: [
      strategyFixture('long_short_donchian_top5_okx_native', 'okx_native_btc_ls_tf_stable_001', 'Long/Short Donchian Top5 · OKX Native', true, ''),
      strategyFixture('long_short_donchian_top5_okx_native', 'okx_native_btc_ls_tf_stable_002', 'Long/Short Donchian Top5 · OKX Native', true, ''),
      strategyFixture('long_short_donchian_top5', 'btc_ls_tf_stable_001', 'Long/Short Donchian Top5', true, ''),
      strategyFixture('long_short_donchian_top5', 'btc_ls_tf_stable_002', 'Long/Short Donchian Top5', true, ''),
      strategyFixture('btc_high_yield_v2', 'identity-high-yield', 'High-Yield Donchian v2', false, 'identity_only_no_demo_execution_ledger'),
      strategyFixture('btc_high_octane_v1', 'identity-high-octane', 'High-Octane Attack Sleeve v2', false, 'identity_only_no_demo_execution_ledger'),
    ],
    safety: {live_order_allowed: false, real_money_allowed: false, transfer_allowed: false, withdraw_allowed: false, permission_upgrade_allowed: false},
  };
}

export function strategyHistoryCatalogFixture() {
  const candidates = catalogFixture().strategies
    .filter((item) => item.strategy_id === 'long_short_donchian_top5' || item.strategy_id === 'long_short_donchian_top5_okx_native')
    .map((item) => ({
      strategy_id: item.strategy_id,
      candidate_id: item.candidate_id,
      source_candidate_id: item.candidate_id.replace(/^okx_native_/, ''),
      variant_id: item.candidate_id,
      display_name: item.display_name,
      relationship: item.strategy_id.endsWith('_okx_native') ? 'same_formula_historical_research_baseline' : 'exact_candidate_historical_research_report',
      relationship_label: item.strategy_id.endsWith('_okx_native') ? '同公式历史研究基线（非 OKX-native 原生回测）' : '历史研究回测',
      research_status: 'research_only',
      annual_return_pct: 36.25,
      total_return_pct: 116.22,
      max_drawdown_pct: -11.46,
      report_sha256: '9'.repeat(64),
      generated_at_utc: '2026-06-29T01:02:03Z',
      history_runs: strategyHistoryFixture(item.strategy_id, item.candidate_id).history_runs,
      history_run_count: 1,
    }));
  return {
    schema_version: 'btc_strategy_history_api_v1',
    status: 'complete_research_only',
    decision: 'history_catalog_read_only_no_paper_no_live',
    candidates,
    safety: {paper_queue_write_allowed: false, live_unlock_allowed: false, broker_or_order_allowed: false},
  };
}

export function strategyRegistryFixture() {
  return {
    schema_version: 'btc_strategy_registry_api_v1',
    status: 'complete_research_only',
    decision: 'btc_strategy_registry_identity_catalog_no_auto_paper_no_live',
    default_strategy_id: 'long_short_donchian_top5',
    default_candidate_id: 'btc_ls_tf_stable_001',
    specs: catalogFixture().strategies.map((strategy) => ({
      ...strategy,
      instrument: strategy.signal_instrument,
      venue: strategy.signal_data_venue,
      strategy_callable: 'fixture.read_only',
      params: {},
      backtest_execution: {supported: strategy.demo_selectable, endpoint: '/api/backtests/fixture'},
      promotion_credit_eligible: false,
      promotion_credit_allowed: false,
    })),
    paper_queue_write_allowed: false,
    live_unlock_allowed: false,
    broker_or_order_allowed: false,
  };
}

export function unifiedStrategyHistoryCatalogFixture() {
  return {
    schema_version: 'strategy_history_catalog_v1',
    status: 'complete_research_only',
    records: Array.from({length: 6}, (_, index) => ({
      catalog_key: `us:etf26:trusted-run-${index + 1}`,
      source: 'git_object_report',
      domain: 'us_equity',
      record_kind: 'trusted_backtest_run',
      strategy_id: 'us_etf26_research',
      candidate_id: `etf26-candidate-${index + 1}`,
      experiment_id: 'us-etf26-history',
      run_id: `us-trusted-run-${index + 1}`,
      display_name: `US ETF26 trusted run ${index + 1}`,
      system_category: 'research_display',
      metrics: {cagr_pct: 12 + index, total_return_pct: 30 + index, max_drawdown_pct: -8 - index},
      research_status: 'research_only',
      promotion_status: 'blocked',
      backtest_supported: true,
      paper_allowed: false,
      live_allowed: false,
      report_href: '',
      artifact_path: `artifacts/us/history/run-${index + 1}.json`,
      artifact_sha256: String(index + 1).repeat(64),
      freshness: {status: 'git_object_verified_not_promotion_ready', source: 'current_head_catalog', head: currentGitHead()},
    })),
    coverage: {us: {available: true, trusted_run_count: 6}, cn: {available: false}},
  };
}

function strategyFixture(strategyId: string, candidateId: string, displayName: string, selectable: boolean, blocker: string) {
  const native = strategyId === 'long_short_donchian_top5_okx_native';
  return {
    strategy_id: strategyId,
    candidate_id: candidateId,
    strategy_version: native ? 'btc_long_short_donchian_top5_okx_native@1.0.0' : strategyId === 'long_short_donchian_top5' ? 'btc_long_short_top5_v1' : 'identity_v1',
    params_hash: 'a'.repeat(64),
    display_name: displayName,
    timeframe: '1h',
    direction_policy: 'long_short',
    adapter_fidelity: selectable ? 'exact_frozen_identity' : 'identity_only',
    promotion_eligibility: 'gated',
    canonical_signal_available: selectable,
    demo_selectable: selectable,
    demo_blocker: blocker,
    signal_data_venue: native ? 'OKX' : 'Binance',
    signal_instrument: native ? 'BTC-USDT-SWAP' : 'BTCUSDT',
    execution_venue: 'OKX',
    execution_instrument: 'BTC-USDT-SWAP',
  };
}

function runtimeFixture(status: string, options: BtcTradingMockOptions, reconciled: boolean) {
  const active = status === 'running';
  const equity = reconciled ? options.reconciledEquity ?? options.initialEquity ?? '1000.50' : options.initialEquity ?? '1000.50';
  return {
    schema_version: 'btc_okx_demo_paper_runtime_status_v1',
    runtime_version: 'okx_demo_paper_runtime_v1',
    environment: 'OKX Demo',
    instrument_id: 'BTC-USDT-SWAP',
    runtime: {
      run_id: active ? 'btc-demo-run-001' : '',
      status,
      active,
      opening_allowed: active,
      cancel_only: status === 'cancel_only',
      started_at_utc: active ? '2026-07-14T01:00:00Z' : '',
      stopped_at_utc: active ? '' : '2026-07-14T02:00:00Z',
      last_heartbeat_utc: '2026-07-14T02:00:00Z',
      last_reconciled_at_utc: reconciled ? '2026-07-14T02:05:00Z' : '2026-07-14T02:00:00Z',
      last_processed_bar_close_utc: '2026-07-14T01:00:00Z',
      last_error: '',
      blockers: options.runtimeBlockers ?? [],
      orders_submitted: 1,
      fills_observed: 1,
      authorization_ticket: 'BTC-OKX-DEMO-PAPER-01',
    },
    strategy: strategyFixture('long_short_donchian_top5_okx_native', 'okx_native_btc_ls_tf_stable_001', 'Long/Short Donchian Top5 · OKX Native', true, ''),
    limits: {margin_mode: 'isolated', order_contracts: '0.01', max_net_contracts: '0.01', max_notional_usdt: '10'},
    signal: {direction: 'long', target_contracts: '0.01'},
    exchange: {
      captured_at_utc: '2026-07-14T02:00:00Z',
      account: {account_level: '2', position_mode: 'long_short_mode', permissions: ['read', 'trade'], withdraw_permission_present: false},
      balance: {equity_usdt: equity, available_usdt: '992.50', unrealized_pnl_usdt: '0.32', timestamp_ms: '1783994400000'},
      positions: [{instrument_id: 'BTC-USDT-SWAP', position_side: 'long', margin_mode: 'isolated', contracts: '0.01', average_price: '62000', mark_price: '62032', liquidation_price: '31000', unrealized_pnl: '0.32', realized_pnl: '0', leverage: '1', updated_at_ms: '1783994400000'}],
      pending_orders: [],
      orders: [{order_id: 'demo-order-001', client_order_id: 'btc-demo-client-001', instrument_id: 'BTC-USDT-SWAP', side: 'buy', position_side: 'long', order_type: 'ioc', state: 'filled', price: '62010', average_price: '62002', size: '0.01', filled_size: '0.01', fee: '-0.0031', pnl: '0', created_at_ms: '1783990800000', updated_at_ms: '1783990800000'}],
      fills: [{fill_id: 'demo-fill-001', order_id: 'demo-order-001', client_order_id: 'btc-demo-client-001', instrument_id: 'BTC-USDT-SWAP', side: 'buy', position_side: 'long', price: '62002', size: '0.01', fee: '-0.0031', fee_currency: 'USDT', pnl: '0', execution_type: 'taker', timestamp_ms: '1783990800000'}],
      bills: [{bill_id: 'demo-funding-001', instrument_id: 'BTC-USDT-SWAP', currency: 'USDT', type: '8', sub_type: '173', balance_change: '-0.0012', fee: '0', pnl: '-0.0012', timestamp_ms: '1783994400000'}],
      fee_schedule: {level: 'Lv1', maker_rate: '0.0002', taker_rate: '0.0005', rule_type: '0', timestamp_ms: '1783994400000'},
      funding: {funding_rate: '0.0001', next_funding_rate: '0.00012', funding_time_ms: '1783994400000', next_funding_time_ms: '1784023200000'},
      ticker: {bid: '62031', ask: '62033', last: '62032', timestamp_ms: '1783994400000'},
      mark: {mark_price: '62032', timestamp_ms: '1783994400000'},
    },
    audit: [],
    events: [{event_id: 'event-001', timestamp_utc: '2026-07-14T02:00:00Z', event_type: 'fill_reconciled', payload: {fill_id: 'demo-fill-001'}}],
    safety: {live_order_allowed: false, real_money_allowed: false, transfer_allowed: false, withdraw_allowed: false, permission_upgrade_allowed: false},
  };
}

function klineFixture(signalReady: boolean) {
  const rows = candleRows();
  return {
    db_path: signalReady ? '' : 'data/external/btc_perpetual/mark_price_klines_1h.csv',
    read_only: true,
    schema_maintenance_performed: false,
    source_kind: signalReady ? 'okx_native_manifest_verified_completed_swap_1h' : 'canonical_manifest_verified_mark_price_1h',
    source_sha256: signalReady ? '8e3db4e947636550455d88e8d6ff21c362e1f294af6b6c95d86cc0d41f67160d' : '4c4065f547da1ed8cead4e3d1538ea8971e6879c8eefb67cea902dc7db6062fc',
    strategy_signal_compatible: signalReady,
    sample_end: rows.at(-1)?.time ?? '',
    freshness_status: signalReady ? 'pass' : 'stale',
    rows,
  };
}

function publicMarketViewFixture(timeframe: string) {
  const rows = candleRows();
  const timestampMs = rows.at(-1)?.open_time_ms ?? Date.UTC(2026, 6, 14, 0, 0, 0);
  const candles = rows.map((row, index) => ({
    open_time_ms: row.open_time_ms,
    open: row.open,
    high: row.high,
    low: row.low,
    close: row.close,
    volume: row.volume,
    confirmed: index < rows.length - 1,
    in_progress: index === rows.length - 1,
  }));
  const last = String(candles.at(-1)?.close ?? 62_032);
  return {
    schema_version: 'okx_public_market_view_v1',
    source_kind: 'okx_public_market_view_v1',
    instrument_id: 'BTC-USDT-SWAP',
    timeframe,
    read_only: true,
    public_only: true,
    private_endpoint_used: false,
    order_endpoint_used: false,
    strategy_signal_compatible: false,
    persisted_market_rows: false,
    captured_at_ms: timestampMs,
    cache_age_ms: 100,
    stale: false,
    last_error_code: '',
    depth_source: 'okx_public_rest_books5',
    depth_error_code: '',
    ticker: {bid: '62031', ask: '62033', last, timestamp_ms: timestampMs},
    candles,
    depth: {
      source: 'okx_public_rest_books5',
      instrument_id: 'BTC-USDT-SWAP',
      bids: Array.from({length: 5}, (_, index) => ({price: String(62031 - index), size: String(5 + index), count: '1'})),
      asks: Array.from({length: 5}, (_, index) => ({price: String(62033 + index), size: String(4 + index), count: '1'})),
      spread: '2',
      top5_imbalance: 0.56,
      timestamp_ms: timestampMs,
      sequence: 1,
      checksum: null,
    },
  };
}

function canonicalFixture(freshness: string) {
  return {
    status: 'research_only',
    freshness: {status: freshness},
    metrics: {total_return_pct: 36.780278, cagr_pct: 14.19219, max_drawdown_pct: -13.259622, annualized_sharpe: 1.174726, fill_count: 30},
    blockers: ['runtime_non_empty_fill_sample_missing', 'depth_fill_mapping_missing', 'manual_approval_missing'],
  };
}

export function strategyHistoryFixture(strategyId: string, candidateId: string) {
  const native = strategyId === 'long_short_donchian_top5_okx_native';
  const sourceCandidateId = candidateId.replace(/^okx_native_/, '');
  const relationship = native ? 'same_formula_historical_research_baseline' : 'exact_candidate_historical_research_report';
  const historicalMetrics = {
    annual_return_pct: 36.256276,
    annual_volatility_pct: 16.303337,
    average_exposure: 0.111355,
    average_net_exposure: 0.065568,
    bars_with_exposure: 608,
    calmar_ratio: 3.161356,
    downside_volatility_pct: 30.822374,
    exposure_change_count: 40,
    fee_return_pct: 4,
    final_equity: 54056.72055,
    funding_return_pct: 0.143296,
    long_bar_count: 483,
    max_drawdown_abs_pct: 11.468585,
    max_drawdown_pct: -11.468585,
    profit_factor: 1.441404,
    sharpe_ratio: 1.978442,
    short_bar_count: 125,
    sortino_ratio: 1.046487,
    total_return_pct: 116.226882,
    trading_cost_return_pct: -4,
    turnover: 40,
    winning_exposed_bar_pct: 54.440789,
  };
  const canonical = nativeCanonicalFixture('historical_research_only_not_current_head') as any;
  canonical.strategy_identity.strategy_id = strategyId;
  canonical.strategy_identity.candidate_id = candidateId;
  canonical.strategy_identity.source_candidate_id = sourceCandidateId;
  canonical.status = 'complete_research_only';
  canonical.decision = 'btc_strategy_history_research_only_no_paper_no_live';
  canonical.run_id = 'btc-top5-history-001';
  canonical.metrics = {...historicalMetrics};
  canonical.cost_model = {
    units: 'return_pct',
    trading_cost_return_pct: historicalMetrics.trading_cost_return_pct,
    fee_return_pct: historicalMetrics.fee_return_pct,
    funding_return_pct: historicalMetrics.funding_return_pct,
    cash_cost_components_available: false,
  };
  delete canonical.ledger_binding;
  canonical.artifact_freshness.status = 'historical_research_only_not_current_head';
  canonical.artifact_freshness.current_head_match = false;
  canonical.mapping = {
    relationship,
    relationship_detail: native ? 'same_frozen_formula_different_strategy_and_data_identity' : relationship,
    requested_strategy_id: strategyId,
    requested_candidate_id: candidateId,
    source_candidate_id: sourceCandidateId,
    candidate_identity_match: true,
    is_okx_native_backtest: false,
  };
  const report = canonicalReportFixture('historical_research_only_not_current_head', native) as any;
  report.run_id = 'btc-top5-history-001';
  report.source_run_id = `btc_long_short_top5_review:${sourceCandidateId}`;
  report.series = {equity: [], drawdown: [], monthly_returns: [], trades: [], costs: []};
  report.artifact_binding = {
    pointer_path: 'artifacts/btc_strategy_history/latest_pointer.json',
    pointer_code_commit: '768550e3',
    manifest_sha256_verified: true,
    evidence_pack_sha256_verified: false,
    ledger_artifact_sha256_verified: false,
    fills_hash_verified: false,
    ledger_equity_consistent: false,
  };
  report.derived_metrics = {
    trade_count: 20,
    winning_trade_count: 10,
    profit_factor: 1.97,
  };
  report.source_counts = {
    candidate_review_count: 1,
    annual_segment_count: 1,
    trade_review_count: 1,
  };
  return {
    schema_version: 'btc_strategy_history_api_v1',
    status: 'complete_research_only',
    decision: 'candidate_bound_history_read_only_no_paper_no_live',
    strategy_id: strategyId,
    candidate_id: candidateId,
    source_candidate_id: sourceCandidateId,
    relationship,
    relationship_label: native ? '同公式历史研究基线（Binance spot / simulated perpetual；不是 OKX-native 原生回测）' : '历史研究回测',
    research_status: 'research_only',
    history_runs: [{
      run_id: 'btc-top5-history-001',
      source_run_id: `btc_long_short_top5_review:${sourceCandidateId}`,
      candidate_id: candidateId,
      source_candidate_id: sourceCandidateId,
      generated_at_utc: '2026-06-29T01:02:03Z',
      status: 'complete_research_only',
      relationship,
      label: native ? '同公式历史研究基线' : '历史研究回测',
      report_sha256: '9'.repeat(64),
    }],
    selected_run_id: 'btc-top5-history-001',
    canonical,
    canonical_report: report,
    details: {
      full_metrics: {...historicalMetrics},
      params: {entry_window: 240},
      annual_attribution: {segments: [{year: 2024, passed: true, metrics: {total_return_pct: 37.18, annual_return_pct: 37.08, max_drawdown_pct: -11.46, sharpe_ratio: 1.84}}]},
      confirmation_holdout: {passed: true, metrics: {total_return_pct: 39.70}},
      walk_forward: {pass_rate: 1, folds: [{fold: 1, passed: true}]},
      cost_stress: {scenarios: [{cost_bps: 20, survives: true, metrics: {total_return_pct: 110, max_drawdown_pct: -12}}]},
      market_regime_attribution: {segments: [{regime_label: 'bull_trend', passed: true, metrics: {total_return_pct: 48, max_drawdown_pct: -8, average_exposure: 0.2}}]},
      max_drawdown_attribution: {max_drawdown_pct: -11.46, peak_time: '2024-03-13T19:59:59Z', trough_time: '2024-10-17T19:59:59Z', bar_count: 1309},
      return_concentration: {trade_count: 20, best_trades: [{side: 'long', start: '2024-11-06T07:59:59Z', end: '2024-11-24T15:59:59Z', total_return_pct: 30.02, cost_return_pct: -0.1, bar_count: 111}], worst_trades: []},
      failure_review: {flags: ['top_trade_return_concentration_expected_for_trend_following']},
      forward_observation: {policy: 'future_30d_60d_observe_only_no_paper_no_live'},
      review_design: {clean_pre_selection_holdout: false, holdout_locked_for_this_review: true},
      warnings: ['clean_pre_selection_holdout_false_requires_future_data'],
    },
    source: {
      report_path: `artifacts/btc_strategy_history/runs/${'9'.repeat(64)}/report.json`,
      report_sha256: '9'.repeat(64),
      report_schema_version: 'btc_long_short_top5_review_v1',
      source_code_commit: '768550e3',
      generated_at_utc: '2026-06-29T01:02:03Z',
      data: {exchange: 'binance_spot', symbol: 'BTCUSDT'},
    },
    blockers: ['btc_strategy_history:research_only_no_paper_no_live'],
    safety: {paper_queue_write_allowed: false, paper_allowed: false, live_unlock_allowed: false, broker_or_order_allowed: false},
  };
}

function nativeCanonicalFixture(freshness: string) {
  const fresh = freshness === 'pass';
  return {
    schema_version: 'btc_okx_native_frontend_summary_v1',
    status: fresh ? 'complete_research_only' : 'artifact_stale_fail_closed',
    strategy_identity: {
      strategy_id: 'long_short_donchian_top5_okx_native',
      candidate_id: 'okx_native_btc_ls_tf_stable_001',
      strategy_version: 'btc_long_short_donchian_top5_okx_native@1.0.0',
      params_hash: 'b'.repeat(64),
      signal_data_venue: 'OKX',
      signal_instrument: 'BTC-USDT-SWAP',
      execution_venue: 'OKX',
      execution_instrument: 'BTC-USDT-SWAP',
      timeframe: 'completed_1h_to_4h',
    },
    metrics: {total_return_pct: 12.833824, cagr_pct: 61.471359, max_drawdown_pct: -4.399426, annualized_sharpe: 3.241101, fill_count: 2, initial_equity: 100000, final_equity: 112833.823834, net_pnl: 12833.823834, pnl_source: 'ledger_fills'},
    cost_model: {components: {commission_cost: 88.563069, fixed_slippage_cost: 59.126439, market_impact_cost: 1.124747, funding_cashflow: 113.261484, funding_cost: 0, total_execution_price_cost: 60.251186}},
    ledger_binding: {pnl_source: 'ledger_fills', ledger_equity_consistent: true, replay_consistent: true, fills_hash: 'c'.repeat(64), ledger_hash: 'd'.repeat(64)},
    checks: {source_no_lookahead_passed: true, source_data_local_and_network_free: true, source_artifacts_present: true, cost_components_complete: true},
    blockers: [],
    promotion_readiness_blockers: ['btc_okx_native:historical_timestamp_aligned_depth_fill_mapping_missing', 'btc_okx_native:30_60_day_observation_window_incomplete', 'btc_okx_native:manual_promotion_approval_missing'],
    artifact_freshness: {status: fresh ? 'pass' : 'fail', pointer_present: true, manifest_present: true, manifest_hash_matches: true, source_scope_current: fresh, current_head_match: fresh, dirty_snapshot_match: fresh, code_commit: '0d7c5cfc0fbf', current_head: fresh ? '0d7c5cfc0fbf' : 'new-head', evidence_pack_path: 'artifacts/btc_okx_native_backtest_evidence/runs/run-test-native/evidence_pack.json'},
    manifest: {path: 'artifacts/btc_okx_native_backtest_evidence/runs/run-test-native/manifest.json'},
    run_id: 'run-test-native',
    safety: {paper_start: false, paper_queue_write_allowed: false, broker_runtime_enabled: false, private_endpoint_used: false, order_endpoint_used: false, oms_access_allowed: false, live_unlock_allowed: false, live_order_allowed: false, real_order_submitted: false},
  };
}

function canonicalReportFixture(freshness: string, native: boolean) {
  const fresh = freshness === 'pass';
  const start = Math.floor(Date.UTC(2026, 3, 14, 8) / 1000);
  return {
    schema_version: native ? 'btc_okx_native_backtest_report_series_v1' : 'btc_canonical_backtest_report_series_v1',
    status: 'complete_research_only',
    decision: 'canonical_report_read_only_no_paper_no_live',
    run_id: native ? 'run-test-native' : 'run-test-historical',
    source_run_id: native ? 'run-test-native' : 'run-test-historical',
    artifact_binding: {manifest_sha256_verified: true, evidence_pack_sha256_verified: true, ledger_artifact_sha256_verified: true, fills_hash_verified: true, ledger_equity_consistent: true},
    series: {
      equity: [{time: start, value: 100000}, {time: start + 86400, value: 104000}, {time: start + 172800, value: native ? 112833.823834 : 136780.278}],
      drawdown: [{time: start, value: 0}, {time: start + 86400, value: -1.2}, {time: start + 172800, value: native ? -4.399426 : -13.259622}],
      monthly_returns: [{month: '2026-04', time: start + 172800, value: native ? 12.833824 : 36.780278}],
      trades: [{trade_number: 1, direction: 'short', entry_time: start + 3600, exit_time: start + 7200, entry_price: 73203.15, exit_price: 63329.59, quantity: 1.29731619, gross_pnl: 12809.13, commission: 88.56, funding_cashflow: 113.26, net_pnl: 12833.823834, cumulative_pnl: 12833.823834, return_pct: 13.52, duration_bars: 260}],
      costs: [{key: 'commission', label: '手续费', value: 88.563069}, {key: 'slippage', label: '固定滑点', value: 59.126439}, {key: 'impact', label: '冲击成本', value: 1.124747}, {key: 'funding', label: 'Funding', value: 0}],
    },
    derived_metrics: {trade_count: 1, winning_trade_count: 1, losing_trade_count: 0, win_rate_pct: 100, profit_factor: 0, average_trade_pnl: 12833.823834, largest_winner: 12833.823834, largest_loser: 0, average_duration_bars: 260},
    source_counts: {ledger_snapshot_count: 3, daily_equity_point_count: 3, fill_count: 2, closed_trade_count: 1, funding_event_count: 33},
    safety: {paper_start_allowed: false, paper_queue_write_allowed: false, broker_access_allowed: false, oms_access_allowed: false, private_endpoint_used: false, order_endpoint_used: false, live_unlock_allowed: false, live_order_allowed: false, real_order_submitted: false},
    blockers: fresh ? ['btc_okx_native:30_60_day_observation_window_incomplete', 'btc_okx_native:manual_promotion_approval_missing'] : ['artifact_stale_fail_closed'],
  };
}

function backtestRunFixture() {
  return {
    run_id: 'run-test-001',
    mode: 'crypto_event',
    status: 'completed',
    created_at: '2026-07-14T02:00:00Z',
    completed_at: '2026-07-14T02:01:00Z',
    summary: {total_return_pct: 12.5, annual_return_pct: 8.2, annual_volatility_pct: 15, sharpe_ratio: 1.4, sortino_ratio: 1.8, max_drawdown_pct: -6.7, calmar_ratio: 1.2, win_rate_pct: 54, profit_factor: 1.35, trade_count: 14},
    latest_weights: [],
    strategy_details: [],
    diagnostics: {pnl_source: 'ledger_fills', ledger_equity_consistent: true, data_version: 'btc-local-fixture', ledger_total_fees: 18.5},
  };
}

function backtestChartFixture() {
  const candles = candleRows().slice(-80).map((row) => ({time: Math.floor(row.open_time_ms / 1000), open: row.open, high: row.high, low: row.low, close: row.close}));
  return {
    candles,
    markers: [{time: candles[20].time, position: 'belowBar', color: '#22c55e', shape: 'arrowUp', text: 'BUY'}],
    equity: candles.map((row, index) => ({time: row.time, value: 10_000 + index * 15})),
    drawdown: candles.map((row, index) => ({time: row.time, value: -Math.abs(Math.sin(index / 8) * 5)})),
    exposure: [],
    net_units: [],
    turnover: [],
    leverage: [],
  };
}

function candleRows() {
  const start = Date.UTC(2026, 6, 8, 0, 0, 0);
  return Array.from({length: 160}, (_, index) => {
    const openTime = start + index * 3_600_000;
    const open = 61_000 + index * 7 + Math.sin(index / 5) * 120;
    const close = open + Math.sin(index / 2) * 70;
    return {
      exchange: 'okx_swap',
      symbol: 'BTC-USDT-SWAP',
      interval: '1h',
      time: new Date(openTime).toISOString(),
      open_time_ms: openTime,
      open,
      high: Math.max(open, close) + 90,
      low: Math.min(open, close) - 85,
      close,
      volume: 100 + index,
      quote_volume: (100 + index) * close,
      trade_count: 1000 + index,
    };
  });
}
