import {expect, test, type Page, type Route} from '@playwright/test';

import {mockBtcTradingPage} from './btc-trading-fixtures';

const BTC_CONSOLE_WIDTH_KEY = 'quantstation.btc.demo-console-width.v1';
const BTC_STRATEGY_TESTER_HEIGHT_KEY = 'quantstation.btc.strategy-tester-height.v1';

test('BTC Demo startup gates remain waiting while heavy research reports load', async ({page}) => {
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname === '/api/health') {
      return route.fulfill({json: {status: 'ok', service: 'quantstation', data_source_default: 'sqlite', fastapi_available: true}});
    }
    if (pathname === '/api/strategies') return route.fulfill({json: []});
    if (pathname === '/api/research/btc/demo-paper/catalog') {
      await new Promise((resolve) => setTimeout(resolve, 500));
      return route.fulfill({json: catalogFixture()});
    }
    if (pathname === '/api/research/btc/demo-paper/status') {
      await new Promise((resolve) => setTimeout(resolve, 500));
      return route.fulfill({json: runtimeFixture('stopped')});
    }
    if (pathname === '/api/research/btc/demo-paper/klines') {
      await new Promise((resolve) => setTimeout(resolve, 500));
      return route.fulfill({json: klineFixture()});
    }
    if (pathname === '/api/research/btc/demo-paper/market-view') return route.fulfill({json: marketViewFixture()});
    await new Promise((resolve) => setTimeout(resolve, 5_000));
    if (pathname.endsWith('/report')) return route.fulfill({json: canonicalReportFixture()});
    return route.fulfill({json: canonicalSummaryFixture()});
  });

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const gates = page.getByTestId('btc-demo-start-gates');
  await expect(gates).toContainText('WAITING');
  await expect(gates).not.toContainText('BLOCKED');
  await expect(gates).toContainText('正在读取冻结策略目录');
  await expect(page.getByTestId('btc-promotion-observation-gates')).toContainText('WAITING');
  await expect(page.getByTestId('btc-promotion-observation-gates')).not.toContainText('PASS');
  await expect(gates).toContainText('freshness 合同通过', {timeout: 2_000});
  await expect(gates).not.toContainText('BLOCKED');
  await expect(page.getByTestId('btc-demo-console')).not.toContainText('Demo 启动阻塞');
});

test('stale chart history is informational and does not block a clean Demo start precheck', async ({page}) => {
  const posted: Record<string, unknown>[] = [];
  await installStartGateFixture(page, runtimeFixture('stopped'), {
    ...klineFixture(),
    source_kind: 'local_sqlite_binance_spot_completed_1h',
    strategy_signal_compatible: false,
    freshness_status: 'stale',
  }, posted);

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const console = page.getByTestId('btc-demo-console');
  const startButton = console.getByRole('button', {name: '重新预检并启动'});
  await expect(console).toContainText('图表 freshness 未通过');
  await expect(console).toContainText('仅影响图表与回测，不影响 Demo 启动');
  await expect(console).not.toContainText('Demo 启动阻塞');
  await expect(startButton).toBeDisabled();
  await expect(console.getByTestId('btc-demo-confirmation-readiness')).toContainText('还需 7 项确认');
  for (const checkbox of await console.locator('input[type="checkbox"]').all()) await checkbox.check();
  await console.getByPlaceholder('BTC DEMO').fill('BTC DEMO ');
  await expect(startButton).toBeDisabled();
  await expect(console.getByTestId('btc-demo-confirmation-readiness')).toContainText('还需 1 项确认');
  expect(posted).toEqual([]);
  await console.getByPlaceholder('BTC DEMO').fill('BTC DEMO');
  await expect(startButton).toBeEnabled();
  await startButton.click();
  await expect.poll(() => posted.length).toBe(1);
});

test('first stopped runtime_not_started state opens the existing authoritative start once', async ({page}) => {
  const posted: Record<string, unknown>[] = [];
  await installStartGateFixture(page, firstStartRuntimeFixture(), klineFixture(), posted);

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const console = page.getByTestId('btc-demo-console');
  const startButton = console.getByRole('button', {name: '重新预检并启动'});
  await expect(console.getByTestId('btc-demo-operator-control')).toContainText('服务重启后需要重新预检');
  await expect(console.getByTestId('btc-demo-operator-control')).toContainText('仅阻止 Demo 启动');
  await expect(startButton).toBeDisabled();
  await expect(console.getByTestId('btc-demo-confirmation-readiness')).toContainText('还需 7 项确认');
  expect(posted).toEqual([]);
  for (const checkbox of await console.locator('input[type="checkbox"]').all()) await checkbox.check();
  await console.getByPlaceholder('BTC DEMO').fill('BTC DEMO');
  await expect(startButton).toBeEnabled();
  await startButton.click();

  await expect.poll(() => posted.length).toBe(1);
  expect(posted[0]).toMatchObject({confirmation_text: 'BTC DEMO'});
});

test('durable 202 start projects one persisted operation and polls GET-only', async ({page}) => {
  const posted: Record<string, unknown>[] = [];
  const initial = firstStartRuntimeFixture();
  const queued = JSON.parse(JSON.stringify(initial)) as Record<string, unknown>;
  const operation = {
    schema_version: 'btc_demo_start_operation_v1',
    operation_id: 'op-durable-01',
    attempt_id: 'attempt-durable-01',
    idempotency_key: 'idem-durable-01',
    request_fingerprint: 'f'.repeat(64),
    state: 'running',
    phase: 'account_positions_orders_oco',
    revision: 4,
    started_at_utc: '2026-08-22T00:00:00Z',
    updated_at_utc: '2026-08-22T00:00:01Z',
    deadline_utc: '2026-08-22T00:05:00Z',
    source_head: 'b786d73aef26515f9939b8fee6966a7f7a961fa9',
    owner: {pid: 1234, nonce: 'nonce-durable-01', create_time_utc: '2026-08-22T00:00:00Z'},
    worker_generation: 0,
    incident: {category: 'none', code: ''},
    blockers: [],
    terminal_error: '',
    post_counts: {orders: 0, cancels: 0, dead_man: 0},
  };
  queued.start_operation = operation;
  (queued.runtime as Record<string, unknown>).start_operation = operation;
  (queued.operator_control as Record<string, unknown>).start_operation = operation;
  (queued.operator_control as Record<string, unknown>).lifecycle = 'starting_preflight';
  const running = runtimeFixture('running');
  const headers: string[] = [];
  await installStartGateFixture(
    page,
    initial,
    klineFixture(),
    posted,
    '',
    0,
    {
      schema_version: 'btc_demo_start_operation_v1',
      accepted: true,
      operation_id: operation.operation_id,
      attempt_id: operation.attempt_id,
      state: operation.state,
      phase: operation.phase,
      revision: operation.revision,
      status_url: '/api/research/btc/demo-paper/status',
      start_operation: operation,
    },
    0,
    [initial, queued, running as unknown as Record<string, unknown>],
    202,
  );
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().includes('/api/research/btc/demo-paper/start')) {
      headers.push(request.headers()['idempotency-key'] ?? '');
    }
  });

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});
  const console = page.getByTestId('btc-demo-console');
  for (const checkbox of await console.locator('input[type="checkbox"]').all()) await checkbox.check();
  await console.getByPlaceholder('BTC DEMO').fill('BTC DEMO');
  await console.getByRole('button', {name: '重新预检并启动'}).click();

  await expect.poll(() => posted.length).toBe(1);
  await expect.poll(() => headers.length).toBe(1);
  expect(headers[0]).toBeTruthy();
  await expect(console).toContainText('未重发 /start');
  await expect(console.getByTestId('btc-demo-operator-control')).toContainText('策略运行中');
});

test('raw frozen reason cannot override the backend operator action contract', async ({page}) => {
  const posted: Record<string, unknown>[] = [];
  const status = firstStartRuntimeFixture();
  (status.risk_control as Record<string, unknown>).reason = 'okx_demo_previous_cancel_only_state_restored';
  await installStartGateFixture(page, status, klineFixture(), posted);

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const console = page.getByTestId('btc-demo-console');
  const startButton = console.getByRole('button', {name: '重新预检并启动'});
  await expect(console.getByTestId('btc-demo-operator-control')).toContainText('服务重启后需要重新预检');
  for (const checkbox of await console.locator('input[type="checkbox"]').all()) await checkbox.check();
  await console.getByPlaceholder('BTC DEMO').fill('BTC DEMO');
  await expect(startButton).toBeEnabled();
  await startButton.click();
  await expect.poll(() => posted.length).toBe(1);
});

test('missing backend operator contract stays fail-closed without frontend inference', async ({page}) => {
  const posted: Record<string, unknown>[] = [];
  const status = runtimeFixture('stopped') as unknown as Record<string, unknown>;
  delete status.operator_control;
  await installStartGateFixture(page, status, klineFixture(), posted);

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const console = page.getByTestId('btc-demo-console');
  await expect(console.getByTestId('btc-demo-operator-control')).toContainText('后端统一运行控制契约不可用');
  await expect(console.getByTestId('btc-demo-start-blocker')).toContainText('前端不会自行推导启动权限');
  for (const checkbox of await console.locator('input[type="checkbox"]').all()) await checkbox.check();
  await console.getByPlaceholder('BTC DEMO').fill('BTC DEMO');
  await expect(console.getByRole('button', {name: '等待后端控制契约'})).toBeDisabled();
  expect(posted).toEqual([]);
});

test('inactive safe-flat blocked runtime offers one authoritative re-preflight start path', async ({page}) => {
  const posted: Record<string, unknown>[] = [];
  await installStartGateFixture(page, recoverableBlockedRuntimeFixture(), klineFixture(), posted);

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const console = page.getByTestId('btc-demo-console');
  const recoveryFlow = page.getByTestId('btc-demo-recovery-flow');
  const recoveryButton = console.getByRole('button', {name: '重新预检并启动'});
  await expect(recoveryFlow).toContainText('1. 账户');
  await expect(recoveryFlow).toContainText('2. 仓位 / 挂单 / OCO');
  await expect(recoveryFlow).toContainText('3. 账本');
  await expect(recoveryFlow).toContainText('4. Private WS');
  await expect(recoveryFlow).toContainText('5. 行情 / Broker Truth');
  await expect(recoveryFlow).toContainText('6. dead-man');
  await expect(console).toContainText('只刷新账户快照与账本，不启动 Private WS，也不解除 cancel-only');
  await expect(recoveryButton).toBeDisabled();

  for (const checkbox of await console.locator('input[type="checkbox"]').all()) await checkbox.check();
  await console.getByPlaceholder('BTC DEMO').fill('BTC DEMO');
  await expect(recoveryButton).toBeEnabled();
  await recoveryButton.click();

  await expect.poll(() => posted.length).toBe(1);
  await expect(console.getByTestId('btc-demo-operator-control')).toContainText('策略运行中');
  await expect(recoveryFlow.getByText('PASS')).toHaveCount(6);
});

test('unclean frozen safe-flat runtime offers only the existing authoritative start preflight', async ({page}) => {
  const posted: Record<string, unknown>[] = [];
  const status = recoverableBlockedRuntimeFixture();
  (status.runtime as Record<string, unknown>).status = 'unclean_restart_fail_closed';
  await installStartGateFixture(page, status, klineFixture(), posted);

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});
  const console = page.getByTestId('btc-demo-console');
  await expect(console.getByTestId('btc-demo-operator-control')).toContainText('服务重启后需要重新预检');
  for (const checkbox of await console.locator('input[type="checkbox"]').all()) await checkbox.check();
  await console.getByPlaceholder('BTC DEMO').fill('BTC DEMO');
  await expect(console.getByRole('button', {name: '重新预检并启动'})).toBeEnabled();
  await console.getByRole('button', {name: '重新预检并启动'}).click();
  await expect.poll(() => posted.length).toBe(1);
  expect(posted[0]).toMatchObject({confirmation_text: 'BTC DEMO'});
});

test('start-blocked runtime with an unavailable old snapshot still exposes authoritative re-preflight', async ({page}) => {
  const posted: Record<string, unknown>[] = [];
  const status = frozenRuntimeFixture();
  (status.runtime as Record<string, unknown>).status = 'start_blocked_fail_closed';
  (status.exchange as Record<string, unknown>).captured_at_utc = '';
  await installStartGateFixture(
    page,
    status,
    klineFixture(),
    posted,
    'okx_demo_authoritative_preflight_required',
  );

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});
  const console = page.getByTestId('btc-demo-console');
  await expect(console.getByTestId('btc-demo-operator-control')).toContainText('账户或订单状态需要人工处理');
  const recoveryButton = console.getByRole('button', {name: '重新核验账户（仅安全时启动）'});
  await expect(recoveryButton).toBeDisabled();
  for (const checkbox of await console.locator('input[type="checkbox"]').all()) await checkbox.check();
  await console.getByPlaceholder('BTC DEMO').fill('BTC DEMO');
  await expect(recoveryButton).toBeEnabled();
  await recoveryButton.click();

  await expect.poll(() => posted.length).toBe(1);
  await expect(page.getByTestId('btc-demo-recovery-failure')).toContainText('重新预检失败');
  await expect(console.getByTestId('btc-demo-operator-control')).toContainText('账户与订单安全');
});

test('market view is public-only, visual-only, and keeps an in-progress minute bar out of strategy readiness', async ({page}) => {
  await installStartGateFixture(page, runtimeFixture('stopped'), klineFixture(), []);

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});
  await page.getByRole('button', {name: '市场 K 线'}).click();
  const chartTimeframes = page.locator('.tv-timeframes');
  for (const label of ['1 分钟', '5 分钟', '15 分钟', '1 小时', '4 小时', '1 天', '1 周', '1 月']) {
    await expect(chartTimeframes.getByRole('button', {name: label, exact: true})).toBeVisible();
  }
  await expect(chartTimeframes.getByRole('button', {name: '1 分钟', exact: true})).toHaveClass(/active/);
  const globalToolbar = page.locator('.tv-global-toolbar');
  await globalToolbar.getByRole('button', {name: '1 分钟', exact: true}).click();
  const timeframeMenu = page.getByTestId('btc-timeframe-menu');
  for (const label of ['1 分钟', '5 分钟', '15 分钟', '1 小时', '4 小时', '1 天', '1 周', '1 月']) {
    const escapedLabel = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    await expect(timeframeMenu.getByRole('button', {name: new RegExp(`^${escapedLabel}(?:\\s|$)`)})).toBeVisible();
  }
  await expect(page.getByTestId('btc-chart-context')).not.toBeVisible();
  await expect(page.locator('.tv-chart-source')).toContainText('OKX public');
  await expect(page.locator('.tv-chart-source')).toContainText('in-progress bar');
  await expect(page.locator('.tv-chart-foot')).toContainText('Public only=PASS');
  await expect(page.locator('.tv-chart-foot')).toContainText('策略兼容=false');
  await expect(page.locator('.tv-chart-legend')).toContainText('策略指标不可用');
  await expect(page.locator('.tv-chart-legend')).not.toContainText('Donchian');
  await expect(page.getByTestId('btc-demo-console')).toContainText('completed 1h 信号');
  await expect(page.getByTestId('btc-demo-console')).toContainText('等待权威账本投影');
});

test('market view keeps one in-flight refresh and preserves last-good candles on failure', async ({page}) => {
  let marketRequests = 0;
  let inFlight = 0;
  let maxInFlight = 0;
  await installStartGateFixture(page, runtimeFixture('stopped'), klineFixture(), []);
  await page.route('**/api/research/btc/demo-paper/market-view**', async (route) => {
    marketRequests += 1;
    inFlight += 1;
    maxInFlight = Math.max(maxInFlight, inFlight);
    try {
      if (marketRequests === 1) {
        await new Promise((resolve) => setTimeout(resolve, 250));
        return route.fulfill({json: marketViewFixture()});
      }
      return route.fulfill({status: 503, json: {detail: 'temporary public market unavailable'}});
    } finally {
      inFlight -= 1;
    }
  });

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});
  await page.getByRole('button', {name: '市场 K 线'}).click();
  await expect(page.getByTestId('btc-market-summary')).toContainText('62,031.0');
  await expect.poll(() => marketRequests, {timeout: 7_000}).toBe(2);
  await expect.poll(() => maxInFlight).toBe(1);
  await expect(page.getByTestId('btc-market-summary')).toContainText('62,031.0');
  await expect(page.locator('.tv-chart-source')).toContainText('stale');
});

test('public-only local EventSource updates the unfinished bar and five-level depth without an OKX browser connection', async ({page}) => {
  await page.addInitScript(() => {
    class LocalMarketEventSource {
      private listeners = new Map<string, Array<(event: MessageEvent<string>) => void>>();
      onerror: ((event: Event) => void) | null = null;

      constructor(url: string) {
        if (url !== '/api/research/btc/demo-paper/market-stream') throw new Error(`unexpected_stream_url:${url}`);
        const publish = (tradeId: string, price: string, minute: number, status = 'live') => {
          const timestamp = Date.UTC(2026, 6, 14, 2, minute, 1);
          const event = new MessageEvent('market', {data: JSON.stringify({
            schema_version: 'btc_okx_public_market_stream_v1',
            instrument_id: 'BTC-USDT-SWAP',
            public_only: true,
            display_only: true,
            persisted: false,
            strategy_signal_compatible: false,
            private_endpoint_accessed: false,
            order_endpoint_accessed: false,
            status,
            last_error_code: '',
            last_update_ms: timestamp,
            subscriber_count: 1,
            trade: {trade_id: tradeId, price, size: '0.02', side: 'buy', timestamp_ms: timestamp},
            depth: {
              bids: [['62043', '2', '1'], ['62042', '3', '1'], ['62041', '4', '1'], ['62040', '5', '1'], ['62039', '6', '1']].map(([price, size, count]) => ({price, size, count})),
              asks: [['62045', '2', '1'], ['62046', '3', '1'], ['62047', '4', '1'], ['62048', '5', '1'], ['62049', '6', '1']].map(([price, size, count]) => ({price, size, count})),
              spread: '2', top5_imbalance: 0.5, timestamp_ms: timestamp, sequence: 7,
            },
          })});
          this.listeners.get('market')?.forEach((listener) => listener(event));
        };
        // Replayed trade id arrives with new books/status snapshots; it must
        // never be merged twice. The distinct id still advances immediately.
        window.setTimeout(() => publish('public-trade-001', '62044', 2), 0);
        window.setTimeout(() => publish('public-trade-001', '63000', 3, 'reconnecting'), 60);
        window.setTimeout(() => publish('public-trade-002', '62048', 4), 120);
      }

      addEventListener(type: string, listener: (event: MessageEvent<string>) => void) {
        this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
      }

      removeEventListener(type: string, listener: (event: MessageEvent<string>) => void) {
        this.listeners.set(type, (this.listeners.get(type) ?? []).filter((item) => item !== listener));
      }

      close() {}
    }
    Object.defineProperty(window, 'EventSource', {configurable: true, value: LocalMarketEventSource});
  });
  await installStartGateFixture(page, runtimeFixture('stopped'), klineFixture(), []);

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});
  await page.getByRole('button', {name: '市场 K 线'}).click();

  const depth = page.getByTestId('btc-public-depth');
  await expect(depth).toContainText('Order Book');
  await expect(depth).toContainText('Price');
  await expect(depth).toContainText('Amount');
  await expect(depth).toContainText('Total');
  await expect(depth).toContainText('LIVE');
  await expect(depth).toContainText('62,043.0');
  await expect(depth).toContainText('62,045.0');
  await expect(depth).toContainText('Spread 2');
  await expect(depth).toContainText('买 50.0%');
  await expect(depth).toContainText('卖 50.0%');
  await expect(page.locator('.tv-quote-pair')).toContainText('62,043.0');
  await expect(page.locator('.tv-quote-pair')).toContainText('62,045.0');
  await expect(page.locator('.tv-chart-foot')).toContainText('62,048.0');
  await expect(page.locator('.tv-chart-foot')).not.toContainText('63000');
  await expect(page.getByTestId('btc-market-summary')).toContainText('实时 forming bar');
  await expect(page.getByTestId('btc-market-summary')).toContainText('62,048.0');
  await expect(page.locator('.tv-chart-source')).toContainText('4 / 4 bars');
  await expect(page.locator('.tv-chart-legend')).not.toContainText('Donchian');
});

test('stale public WS depth visibly falls back to keyless OKX REST books5', async ({page}) => {
  await page.addInitScript(() => {
    class StaleDepthEventSource {
      private listeners = new Map<string, Array<(event: MessageEvent<string>) => void>>();
      onerror: ((event: Event) => void) | null = null;

      constructor(url: string) {
        if (url !== '/api/research/btc/demo-paper/market-stream') throw new Error(`unexpected_stream_url:${url}`);
        window.setTimeout(() => {
          const timestamp = Date.UTC(2026, 6, 14, 2, 1, 1);
          const event = new MessageEvent('market', {data: JSON.stringify({
            schema_version: 'btc_okx_public_market_stream_v1', instrument_id: 'BTC-USDT-SWAP',
            public_only: true, display_only: true, persisted: false, strategy_signal_compatible: false,
            private_endpoint_accessed: false, order_endpoint_accessed: false, status: 'stale',
            last_error_code: 'btc_okx_public_display_socket_disconnected', last_update_ms: timestamp,
            subscriber_count: 1, trade: null, depth: null,
          })});
          this.listeners.get('market')?.forEach((listener) => listener(event));
        }, 20);
      }

      addEventListener(type: string, listener: (event: MessageEvent<string>) => void) { this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]); }
      removeEventListener(type: string, listener: (event: MessageEvent<string>) => void) { this.listeners.set(type, (this.listeners.get(type) ?? []).filter((item) => item !== listener)); }
      close() {}
    }
    Object.defineProperty(window, 'EventSource', {configurable: true, value: StaleDepthEventSource});
  });
  await installStartGateFixture(page, runtimeFixture('stopped'), klineFixture(), []);
  await page.route('**/api/research/btc/demo-paper/market-view**', (route) => {
    const market = marketViewFixture() as Record<string, unknown>;
    market.depth_source = 'okx_public_rest_books5';
    market.depth = {
      source: 'okx_public_rest_books5', instrument_id: 'BTC-USDT-SWAP',
      bids: ['62043', '62042', '62041', '62040', '62039'].map((price, index) => ({price, size: String(index + 2), count: '3'})),
      asks: ['62045', '62046', '62047', '62048', '62049'].map((price, index) => ({price, size: String(index + 2), count: '4'})),
      spread: '2', top5_imbalance: 0.5, timestamp_ms: Date.UTC(2026, 6, 14, 2, 1, 1), sequence: 8,
    };
    return route.fulfill({json: market});
  });

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});
  await page.getByRole('button', {name: '市场 K 线'}).click();

  const depth = page.getByTestId('btc-public-depth');
  await expect(depth).toContainText('REST 2s FALLBACK');
  await expect(depth).toContainText('62,043.0');
  await expect(depth).toContainText('62,045.0');
  await expect(depth).toContainText('public-only');
});

test('late strategy history cannot replace an explicit market view while consecutive public trades update visual OHLCV', async ({page}) => {
  await page.addInitScript(() => {
    class SameMinuteEventSource {
      private listeners = new Map<string, Array<(event: MessageEvent<string>) => void>>();
      onerror: ((event: Event) => void) | null = null;

      constructor(url: string) {
        if (url !== '/api/research/btc/demo-paper/market-stream') throw new Error(`unexpected_stream_url:${url}`);
        const timestamp = Date.UTC(2026, 6, 14, 2, 2, 1);
        const publish = (tradeId: string, price: string, size: string, offset: number) => {
          window.setTimeout(() => {
            const event = new MessageEvent('market', {data: JSON.stringify({
              schema_version: 'btc_okx_public_market_stream_v1', instrument_id: 'BTC-USDT-SWAP',
              public_only: true, display_only: true, persisted: false, strategy_signal_compatible: false,
              private_endpoint_accessed: false, order_endpoint_accessed: false, status: 'live',
              last_error_code: '', last_update_ms: timestamp + offset, subscriber_count: 1,
              trade: {trade_id: tradeId, price, size, side: 'buy', timestamp_ms: timestamp + offset},
              depth: {
                bids: [['62009', '2', '1'], ['62008', '3', '1'], ['62007', '4', '1'], ['62006', '5', '1'], ['62005', '6', '1']].map(([price, size, count]) => ({price, size, count})),
                asks: [['62011', '2', '1'], ['62012', '3', '1'], ['62013', '4', '1'], ['62014', '5', '1'], ['62015', '6', '1']].map(([price, size, count]) => ({price, size, count})),
                spread: '2', top5_imbalance: 0.6, timestamp_ms: timestamp + offset, sequence: 10 + offset,
              },
            })});
            this.listeners.get('market')?.forEach((listener) => listener(event));
          }, offset);
        };
        publish('public-minute-001', '62020', '0.02', 0);
        publish('public-minute-002', '62060', '0.03', 30);
        publish('public-minute-003', '62010', '0.04', 60);
      }

      addEventListener(type: string, listener: (event: MessageEvent<string>) => void) { this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]); }
      removeEventListener(type: string, listener: (event: MessageEvent<string>) => void) { this.listeners.set(type, (this.listeners.get(type) ?? []).filter((item) => item !== listener)); }
      close() {}
    }
    Object.defineProperty(window, 'EventSource', {configurable: true, value: SameMinuteEventSource});
  });
  await installStartGateFixture(page, runtimeFixture('stopped'), klineFixture(), [], '', 150);

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});
  await page.getByRole('button', {name: '市场 K 线'}).click();
  const ohlc = page.locator('.tv-ohlc-strip');
  await expect(ohlc).toContainText('开 62,020.0');
  await expect(ohlc).toContainText('高 62,060.0');
  await expect(ohlc).toContainText('低 62,010.0');
  await expect(ohlc).toContainText('收 62,010.0');
  await expect(ohlc).toContainText('量 0.09');
  await expect(page.getByTestId('btc-public-depth-mid')).toContainText('62,010.0');
  await expect(page.locator('.tv-chart-source')).toContainText('OKX public');
  await expect(page.locator('.tv-chart-legend')).toContainText('策略指标不可用');
  await expect(page.locator('.tv-chart-legend')).not.toContainText('Donchian');
});

test('a public trade in a new UTC month appends one visual-only 1M candle', async ({page}) => {
  await page.addInitScript(() => {
    class CalendarMarketEventSource {
      private listeners = new Map<string, Array<(event: MessageEvent<string>) => void>>();
      onerror: ((event: Event) => void) | null = null;

      constructor(url: string) {
        if (url !== '/api/research/btc/demo-paper/market-stream') throw new Error(`unexpected_stream_url:${url}`);
        window.setTimeout(() => {
          const timestamp = Date.UTC(2026, 7, 1, 0, 0, 1);
          const event = new MessageEvent('market', {data: JSON.stringify({
            schema_version: 'btc_okx_public_market_stream_v1', instrument_id: 'BTC-USDT-SWAP',
            public_only: true, display_only: true, persisted: false, strategy_signal_compatible: false,
            private_endpoint_accessed: false, order_endpoint_accessed: false, status: 'live',
            last_error_code: '', last_update_ms: timestamp, subscriber_count: 1,
            trade: {trade_id: 'public-trade-calendar-001', price: '62055', size: '0.03', side: 'buy', timestamp_ms: timestamp},
            depth: null,
          })});
          this.listeners.get('market')?.forEach((listener) => listener(event));
        }, 400);
        window.setTimeout(() => {
          const event = new MessageEvent('market', {data: JSON.stringify({
            schema_version: 'btc_okx_public_market_stream_v1', instrument_id: 'BTC-USDT-SWAP',
            public_only: true, display_only: true, persisted: false, strategy_signal_compatible: false,
            private_endpoint_accessed: false, order_endpoint_accessed: false, status: 'live',
            last_error_code: '', last_update_ms: Date.UTC(2026, 6, 1, 0, 0, 1), subscriber_count: 1,
            trade: {trade_id: 'public-trade-calendar-old', price: '60000', size: '0.03', side: 'sell', timestamp_ms: Date.UTC(2026, 6, 1, 0, 0, 1)},
            depth: null,
          })});
          this.listeners.get('market')?.forEach((listener) => listener(event));
        }, 440);
      }

      addEventListener(type: string, listener: (event: MessageEvent<string>) => void) {
        this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
      }

      removeEventListener(type: string, listener: (event: MessageEvent<string>) => void) {
        this.listeners.set(type, (this.listeners.get(type) ?? []).filter((item) => item !== listener));
      }

      close() {}
    }
    Object.defineProperty(window, 'EventSource', {configurable: true, value: CalendarMarketEventSource});
  });
  await installStartGateFixture(page, runtimeFixture('stopped'), klineFixture(), []);

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});
  await page.getByRole('button', {name: '市场 K 线'}).click();
  await page.locator('.tv-timeframes').getByRole('button', {name: '1 月', exact: true}).click();

  await expect(page.locator('.tv-chart-source')).toContainText('3 / 3 bars');
  await page.waitForTimeout(500);
  await expect(page.locator('.tv-chart-foot')).toContainText('62,055.0');
  await expect(page.locator('.tv-chart-foot')).not.toContainText('60000');
});

test('market fill-marker summary exposes only unique fills aligned to the selected minute candles', async ({page}) => {
  const status = runtimeFixture('running') as unknown as Record<string, any>;
  const market = marketViewFixture();
  const timestampMs = market.candles[0].open_time_ms + 30_000;
  const buyFill = {
    fill_id: 'demo-buy-fill-1m-001',
    order_id: 'demo-fill-order-001',
    client_order_id: 'btc-demo-fill-001',
    instrument_id: 'BTC-USDT-SWAP',
    side: 'buy',
    position_side: 'long',
    price: '62002',
    size: '0.01',
    fee: '-0.0031',
    fee_currency: 'USDT',
    pnl: '0',
    execution_type: 'taker',
    timestamp_ms: timestampMs,
  };
  status.exchange.fills = [buyFill, {...buyFill}];
  status.exchange.orders = [
    {...buyFill, state: 'filled', order_type: 'ioc', filled_size: '0.01', created_at_ms: timestampMs, updated_at_ms: timestampMs},
    {order_id: 'demo-pending-order-001', client_order_id: 'btc-demo-pending-001', instrument_id: 'BTC-USDT-SWAP', side: 'buy', position_side: 'long', order_type: 'limit', state: 'live', price: '62000', average_price: '', size: '0.01', filled_size: '0', fee: '0', pnl: '0', created_at_ms: timestampMs, updated_at_ms: timestampMs},
    {order_id: 'demo-canceled-order-001', client_order_id: 'btc-demo-canceled-001', instrument_id: 'BTC-USDT-SWAP', side: 'sell', position_side: 'long', order_type: 'limit', state: 'canceled', price: '62040', average_price: '', size: '0.01', filled_size: '0', fee: '0', pnl: '0', created_at_ms: timestampMs, updated_at_ms: timestampMs},
  ];
  await installStartGateFixture(page, status, klineFixture(), []);
  await page.route('**/api/research/btc/demo-paper/market-view', (route) => route.fulfill({json: market}));

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});
  await page.locator('.tv-timeframes').getByRole('button', {name: '1 分钟', exact: true}).click();
  await page.getByRole('button', {name: '市场 K 线'}).click();

  const summary = page.getByTestId('trading-chart-marker-summary');
  await expect(summary).toHaveAttribute('data-marker-count', '1');
  await expect(summary).toHaveAttribute('data-marker-labels', /^Demo run · BUY FILL 0\.01(?:\s|$)/);
  await expect(summary).toHaveAttribute('aria-label', /^成交标记摘要：Demo run · BUY FILL 0\.01(?:\s|$)/);
  await expect(summary).not.toHaveAttribute('data-marker-labels', /pending|canceled/i);
});

test('realized net PnL renders only an explicit reconciled ledger projection', async ({page}) => {
  const status = runtimeFixture('running');
  Object.assign(status.ledger_reconciliation, {
    authoritative_realized_net_pnl: '12.3456',
    authoritative_realized_net_pnl_provenance: 'ledger_cash_and_fills_reconciled_v1',
  });
  await installStartGateFixture(page, status, klineFixture(), []);

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});
  await expect(page.getByTestId('btc-demo-console')).toContainText('12.3456 USDT');
});

test('untrusted realised PnL provenance stays unavailable despite a numeric value', async ({page}) => {
  const status = runtimeFixture('running');
  Object.assign(status.ledger_reconciliation, {
    authoritative_realized_net_pnl: '12.3456',
    authoritative_realized_net_pnl_provenance: 'untrusted',
  });
  await installStartGateFixture(page, status, klineFixture(), []);

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});
  await expect(page.getByTestId('btc-demo-console')).toContainText('等待权威账本投影');
  await expect(page.getByTestId('btc-demo-console')).not.toContainText('12.3456 USDT');
});

test('start POST timeout polls bounded authoritative status to running without resubmitting', async ({page}) => {
  let statusReads = 0;
  await installStartGateFixture(page, runtimeFixture('stopped'), klineFixture(), []);
  await page.addInitScript(() => {
    const originalFetch = window.fetch.bind(window);
    const originalSetTimeout = window.setTimeout.bind(window);
    let startAttempts = 0;
    const timeoutCallbacks: Array<() => void> = [];
    const pollCallbacks: Array<() => void> = [];
    window.setTimeout = ((handler: TimerHandler, timeout?: number, ...args: unknown[]) => {
      if (timeout === 20_000 && typeof handler === 'function') {
        timeoutCallbacks.push(() => handler(...args));
        return 1 as unknown as number;
      }
      if (timeout === 5_000 && typeof handler === 'function') {
        pollCallbacks.push(() => handler(...args));
        return 2 as unknown as number;
      }
      return originalSetTimeout(handler, timeout, ...args);
    }) as typeof window.setTimeout;
    window.fetch = (input, init) => {
      const url = typeof input === 'string' ? input : input instanceof Request ? input.url : input.url;
      if ((init?.method ?? 'GET') === 'POST' && url.includes('/api/research/btc/demo-paper/start')) {
        startAttempts += 1;
        return new Promise((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new DOMException('timed out', 'AbortError')), {once: true});
        });
      }
      return originalFetch(input, init);
    };
    Object.defineProperty(window, '__btcStartAttempts', {value: () => startAttempts});
    Object.defineProperty(window, '__btcFireLastTimeout', {value: () => timeoutCallbacks.at(-1)?.()});
    Object.defineProperty(window, '__btcPollWaitCount', {value: () => pollCallbacks.length});
    Object.defineProperty(window, '__btcFireNextPoll', {value: () => pollCallbacks.shift()?.()});
  });
  await page.route('**/api/research/btc/demo-paper/status', async (route) => {
    statusReads += 1;
    await route.fulfill({json: runtimeFixture(statusReads >= 3 ? 'running' : 'stopped')});
  });

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});
  const console = page.getByTestId('btc-demo-console');
  for (const checkbox of await console.locator('input[type="checkbox"]').all()) await checkbox.check();
  await console.getByPlaceholder('BTC DEMO').fill('BTC DEMO');
  await console.getByRole('button', {name: '重新预检并启动'}).click();

  await expect.poll(() => page.evaluate(() => (window as unknown as {__btcStartAttempts: () => number}).__btcStartAttempts())).toBe(1);
  await page.evaluate(() => (window as unknown as {__btcFireLastTimeout: () => void}).__btcFireLastTimeout());
  await expect.poll(() => page.evaluate(() => (window as unknown as {__btcStartAttempts: () => number}).__btcStartAttempts())).toBe(1);
  await expect.poll(() => page.evaluate(() => (window as unknown as {__btcPollWaitCount: () => number}).__btcPollWaitCount())).toBeGreaterThan(0);
  await page.evaluate(() => (window as unknown as {__btcFireNextPoll: () => void}).__btcFireNextPoll());
  await expect.poll(() => page.evaluate(() => (window as unknown as {__btcPollWaitCount: () => number}).__btcPollWaitCount())).toBe(0);
  await expect(console).toContainText('已通过权威状态确认 runtime 正在运行');
  await expect(console).toContainText('未重发 /start');
  await expect(console.getByTestId('btc-demo-operator-control')).toContainText('策略运行中');
  await expect.poll(() => page.evaluate(() => (window as unknown as {__btcStartAttempts: () => number}).__btcStartAttempts())).toBe(1);
});

test('start POST timeout converges to precise authoritative blocked status without resubmitting', async ({page}) => {
  let statusReads = 0;
  const initial = recoverableBlockedRuntimeFixture();
  const startup = recoverableBlockedRuntimeFixture();
  Object.assign(startup.runtime as Record<string, unknown>, {
    status: 'startup_reconciling',
    active: true,
    opening_allowed: false,
    cancel_only: true,
    last_error: '',
    blockers: [],
  });
  startup.operator_control = operatorControlFixture(
    'starting',
    'preflight_progress',
    'private_ws_startup_probe_local_disconnect',
  );
  const blocked = recoverableBlockedRuntimeFixture();
  Object.assign(blocked.runtime as Record<string, unknown>, {
    status: 'start_blocked_fail_closed',
    last_error: 'okx_demo_private_ws_startup_reconnect_probe_failed',
    blockers: ['okx_demo_private_ws_startup_reconnect_probe_failed'],
  });
  blocked.operator_control = operatorControlFixture(
    'stopped',
    'network_transport',
    'okx_demo_private_ws_startup_reconnect_probe_failed',
  );
  await installStartGateFixture(page, initial, klineFixture(), []);
  await page.addInitScript(() => {
    const originalFetch = window.fetch.bind(window);
    const originalSetTimeout = window.setTimeout.bind(window);
    let startAttempts = 0;
    const timeoutCallbacks: Array<() => void> = [];
    const pollCallbacks: Array<() => void> = [];
    window.setTimeout = ((handler: TimerHandler, timeout?: number, ...args: unknown[]) => {
      if (timeout === 20_000 && typeof handler === 'function') {
        timeoutCallbacks.push(() => handler(...args));
        return 1 as unknown as number;
      }
      if (timeout === 5_000 && typeof handler === 'function') {
        pollCallbacks.push(() => handler(...args));
        return 2 as unknown as number;
      }
      return originalSetTimeout(handler, timeout, ...args);
    }) as typeof window.setTimeout;
    window.fetch = (input, init) => {
      const url = typeof input === 'string' ? input : input instanceof Request ? input.url : input.url;
      if ((init?.method ?? 'GET') === 'POST' && url.includes('/api/research/btc/demo-paper/start')) {
        startAttempts += 1;
        return new Promise((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new DOMException('timed out', 'AbortError')), {once: true});
        });
      }
      return originalFetch(input, init);
    };
    Object.defineProperty(window, '__btcStartAttempts', {value: () => startAttempts});
    Object.defineProperty(window, '__btcFireLastTimeout', {value: () => timeoutCallbacks.at(-1)?.()});
    Object.defineProperty(window, '__btcPollWaitCount', {value: () => pollCallbacks.length});
    Object.defineProperty(window, '__btcFireNextPoll', {value: () => pollCallbacks.shift()?.()});
  });
  await page.route('**/api/research/btc/demo-paper/status', async (route) => {
    statusReads += 1;
    await route.fulfill({json: statusReads === 1 ? initial : statusReads === 2 ? startup : blocked});
  });

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});
  const console = page.getByTestId('btc-demo-console');
  for (const checkbox of await console.locator('input[type="checkbox"]').all()) await checkbox.check();
  await console.getByPlaceholder('BTC DEMO').fill('BTC DEMO');
  await console.getByRole('button', {name: '重新预检并启动'}).click();
  await expect.poll(() => page.evaluate(() => (window as unknown as {__btcStartAttempts: () => number}).__btcStartAttempts())).toBe(1);
  await page.evaluate(() => (window as unknown as {__btcFireLastTimeout: () => void}).__btcFireLastTimeout());
  await expect.poll(() => page.evaluate(() => (window as unknown as {__btcPollWaitCount: () => number}).__btcPollWaitCount())).toBeGreaterThan(0);
  await page.evaluate(() => (window as unknown as {__btcFireNextPoll: () => void}).__btcFireNextPoll());
  await expect.poll(() => page.evaluate(() => (window as unknown as {__btcPollWaitCount: () => number}).__btcPollWaitCount())).toBe(0);

  await expect(page.getByTestId('btc-demo-recovery-failure')).toContainText('lifecycle=stopped_needs_preflight');
  await expect(page.getByTestId('btc-demo-recovery-failure')).toContainText('incident=network_transport');
  await expect(page.getByTestId('btc-demo-recovery-failure')).toContainText('okx_demo_private_ws_startup_reconnect_probe_failed');
  await expect(page.getByTestId('btc-demo-recovery-failure')).toContainText('未重发 /start');
  await expect(console).toContainText('继续保持 cancel-only');
  await expect.poll(() => page.evaluate(() => (window as unknown as {__btcStartAttempts: () => number}).__btcStartAttempts())).toBe(1);
});

test('failed authoritative re-preflight names the failed stage and remains cancel-only', async ({page}) => {
  const posted: Record<string, unknown>[] = [];
  await installStartGateFixture(
    page,
    recoverableBlockedRuntimeFixture(),
    klineFixture(),
    posted,
    'okx_demo_private_ws_startup_reconnect_probe_failed',
  );

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const console = page.getByTestId('btc-demo-console');
  for (const checkbox of await console.locator('input[type="checkbox"]').all()) await checkbox.check();
  await console.getByPlaceholder('BTC DEMO').fill('BTC DEMO');
  await console.getByRole('button', {name: '重新预检并启动'}).click();

  await expect.poll(() => posted.length).toBe(1);
  await expect(page.getByTestId('btc-demo-recovery-failure')).toContainText('Private WS');
  await expect(page.getByTestId('btc-demo-recovery-failure')).toContainText('继续保持 cancel-only');
  await expect(console).toContainText('okx_demo_private_ws_startup_reconnect_probe_failed');
});

test('start keeps backend READY and WAITING stages visible while the authority is running', async ({page}) => {
  const posted: Record<string, unknown>[] = [];
  const starting = runtimeFixture('stopped') as unknown as Record<string, unknown>;
  const startingRuntime = starting.runtime as Record<string, unknown>;
  startingRuntime.status = 'startup_reconciling';
  startingRuntime.last_error = '';
  startingRuntime.blockers = [];
  starting.operator_control = operatorControlFixture('starting', 'preflight_progress');

  await page.addInitScript(() => {
    const originalSetTimeout = window.setTimeout.bind(window);
    const pollCallbacks: Array<() => void> = [];
    window.setTimeout = ((handler: TimerHandler, timeout?: number, ...args: unknown[]) => {
      if (timeout === 5_000 && typeof handler === 'function') {
        pollCallbacks.push(() => handler(...args));
        return 1 as unknown as number;
      }
      return originalSetTimeout(handler, timeout, ...args);
    }) as typeof window.setTimeout;
    Object.defineProperty(window, '__btcFireNextPoll', {value: () => pollCallbacks.shift()?.()});
  });
  await installStartGateFixture(page, recoverableBlockedRuntimeFixture(), klineFixture(), posted, '', 0, starting);

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});
  const console = page.getByTestId('btc-demo-console');
  for (const checkbox of await console.locator('input[type="checkbox"]').all()) await checkbox.check();
  await console.getByPlaceholder('BTC DEMO').fill('BTC DEMO');
  await console.getByRole('button', {name: '重新预检并启动'}).click();

  await expect.poll(() => posted.length).toBe(1);
  const recoveryFlow = page.getByTestId('btc-demo-recovery-flow');
  await expect(console.getByRole('button', {name: '正在执行权威预检…'})).toBeDisabled();
  await expect(recoveryFlow.getByText('PASS')).toHaveCount(3);
  await expect(recoveryFlow.getByText('WAITING')).toHaveCount(3);
  await expect(recoveryFlow).toContainText('1. 账户');
  await expect(recoveryFlow).toContainText('4. Private WS');
});

test('start 400 releases the busy action immediately while status GET remains diagnostic-only', async ({page}) => {
  const posted: Record<string, unknown>[] = [];
  await installStartGateFixture(
    page,
    recoverableBlockedRuntimeFixture(),
    klineFixture(),
    posted,
    'okx_demo_dead_man_heartbeat_rejected:50001',
    0,
    undefined,
    1_000,
  );

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});
  const console = page.getByTestId('btc-demo-console');
  const recoveryButton = console.getByRole('button', {name: '重新预检并启动'});
  for (const checkbox of await console.locator('input[type="checkbox"]').all()) await checkbox.check();
  await console.getByPlaceholder('BTC DEMO').fill('BTC DEMO');
  await recoveryButton.click();

  await expect.poll(() => posted.length).toBe(1);
  await expect(recoveryButton).toBeEnabled({timeout: 500});
  await expect(page.getByTestId('btc-demo-recovery-failure')).toContainText(
    'POST /api/research/btc/demo-paper/start: 400 · okx_demo_dead_man_heartbeat_rejected:50001',
  );
  await expect(console).toContainText('继续保持 cancel-only');
});

test('account-risk contract exposes authoritative account recheck without direct start', async ({page}) => {
  const posted: Record<string, unknown>[] = [];
  await installStartGateFixture(page, frozenRuntimeFixture(), {
    ...klineFixture(),
    source_kind: 'local_sqlite_binance_spot_completed_1h',
    strategy_signal_compatible: false,
    freshness_status: 'stale',
  }, posted, 'okx_demo_nonflat_position_has_no_verified_protection');

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const console = page.getByTestId('btc-demo-console');
  const control = page.getByTestId('btc-demo-operator-control');
  await expect(control).toContainText('账户或订单状态需要人工处理');
  await expect(control).toContainText('账户与订单安全');
  for (const checkbox of await console.locator('input[type="checkbox"]').all()) await checkbox.check();
  await console.getByPlaceholder('BTC DEMO').fill('BTC DEMO');
  const recoveryButton = console.getByRole('button', {name: '重新核验账户（仅安全时启动）'});
  await expect(recoveryButton).toBeEnabled();
  await recoveryButton.click();
  await expect.poll(() => posted.length).toBe(1);
  await expect(page.getByTestId('btc-demo-recovery-failure')).toContainText('仓位 / 挂单 / OCO');
  await expect(console).toContainText('继续保持 cancel-only');
});

test('BTC Demo status failure is visible and keeps polling without fabricating progress', async ({page}) => {
  const mock = await mockBtcTradingPage(page, {statusError: 'demo status temporarily unavailable'});

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const observationProgress = page.getByTestId('btc-demo-observation-progress');
  await expect(observationProgress).toHaveJSProperty('open', false);
  await expect(observationProgress.locator('summary')).toContainText('— / 25');
  await expect(observationProgress.getByRole('progressbar')).not.toBeVisible();
  await observationProgress.locator('summary').click();
  await expect(observationProgress).toHaveJSProperty('open', true);
  await expect(observationProgress).toContainText('Demo 状态接口不可用，未计入当前小时');
  await expect(page.getByTestId('btc-demo-status-error')).toContainText('Demo 状态接口不可用，未计入当前小时');
  await expect(observationProgress.getByRole('progressbar')).toHaveAttribute(
    'aria-valuetext',
    '状态接口不可用，未计入当前小时',
  );
  await expect.poll(
    () => mock.requests.filter((request) => request.pathname === '/api/research/btc/demo-paper/status').length,
    {timeout: 12_000},
  ).toBeGreaterThan(1);
  expect(mock.requests.filter((request) => request.method === 'POST')).toEqual([]);
});

test('runtime URLError is localized while remaining fail-closed without extra POST', async ({page}) => {
  const posted: Record<string, unknown>[] = [];
  const status = recoverableBlockedRuntimeFixture();
  const runtime = status.runtime as Record<string, unknown>;
  runtime.last_error = 'URLError';
  runtime.blockers = ['URLError'];
  status.operator_control = operatorControlFixture('stopped', 'network_transport', 'URLError');
  await installStartGateFixture(page, status, klineFixture(), posted);

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const console = page.getByTestId('btc-demo-console');
  await expect(console.getByTestId('btc-demo-operator-control')).toContainText('OKX Demo 网络链路不可用');
  await expect(console.getByTestId('btc-demo-operator-control')).toContainText('仅阻止 Demo 启动');
  await expect(console).toContainText('诊断：URLError');
  await expect(console).not.toContainText('runtime 最近错误：URLError');
  expect(posted).toEqual([]);
});

test('historical transport diagnostics stay history before a fresh start attempt', async ({page}) => {
  const posted: Record<string, unknown>[] = [];
  const status = firstStartRuntimeFixture();
  const runtime = status.runtime as Record<string, unknown>;
  const privateWs = status.private_ws as Record<string, unknown>;
  const incident = (status.operator_control as Record<string, unknown>).incident as Record<string, unknown>;
  runtime.last_error = 'URLError: previous attempt connection reset';
  runtime.blockers = ['URLError: previous attempt connection reset'];
  privateWs.status = 'not_started';
  privateWs.blockers = ['URLError: previous attempt connection reset'];
  incident.category = 'service_restart';
  incident.current_attempt = false;
  incident.reason_codes = ['URLError: previous attempt connection reset'];
  await installStartGateFixture(page, status, klineFixture(), posted);

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const console = page.getByTestId('btc-demo-console');
  await expect(console.getByTestId('btc-demo-operator-control')).toContainText('服务重启后需要重新预检');
  await expect(console.getByTestId('btc-demo-operator-control')).not.toContainText('OKX Demo 网络链路不可用');
  await expect(console.getByTestId('btc-runtime-health')).toContainText('历史错误');
  expect(posted).toEqual([]);
});

test('intentional private WS startup disconnect stays in reconnect verification until probe terminates', async ({page}) => {
  const posted: Record<string, unknown>[] = [];
  const status = recoverableBlockedRuntimeFixture();
  const runtime = status.runtime as Record<string, unknown>;
  const privateWs = status.private_ws as Record<string, unknown>;
  runtime.status = 'starting';
  runtime.last_error = 'private_ws_startup_probe_local_disconnect';
  runtime.blockers = ['private_ws_startup_probe_local_disconnect'];
  privateWs.status = 'starting';
  privateWs.blockers = ['private_ws_startup_probe_local_disconnect'];
  status.operator_control = operatorControlFixture(
    'starting',
    'preflight_progress',
    'private_ws_startup_probe_local_disconnect',
  );
  await installStartGateFixture(page, status, klineFixture(), posted);

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const console = page.getByTestId('btc-demo-console');
  await expect(console.getByTestId('btc-demo-operator-control')).toContainText('正在验证 Private WS 断线重连');
  await expect(console.getByTestId('btc-demo-operator-control')).toContainText('不是网络事故');
  await expect(console).toContainText('private_ws_startup_probe_local_disconnect');
  await expect(console).not.toContainText('OKX Demo 网络连接失败；保持 cancel-only');
  expect(posted).toEqual([]);
});

test('historical observation evidence is collapsed and separated from the current runtime count', async ({page}) => {
  await installStartGateFixture(page, runtimeFixture('running'), klineFixture(), []);

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const observationEvidence = page.getByTestId('btc-demo-observation-progress');
  await expect(observationEvidence.locator('summary')).toContainText('历史观察证据（不作为当前 Demo 启动门槛）');
  await expect(observationEvidence.locator('summary')).toContainText('当前 runtime 状态接口计数：13 / 25');
  await expect(observationEvidence).toHaveJSProperty('open', false);
  await expect(observationEvidence.getByText('Receipt 数')).not.toBeVisible();
  await observationEvidence.locator('summary').click();
  await expect(observationEvidence).toHaveJSProperty('open', true);
  await expect(observationEvidence).toContainText('当前 runtime 计数与外部不可变封存证据相互独立');
  await expect(observationEvidence).toContainText('Receipt 数19');
  await expect(observationEvidence.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '13');
});

test('running status refreshes confirmed OKX chart on decision-bar change and every 60 seconds', async ({page}) => {
  await page.clock.install();
  let statusCalls = 0;
  let klineCalls = 0;
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    const method = request.method();
    if (method === 'GET' && pathname === '/api/health') {
      return route.fulfill({json: {status: 'ok', service: 'quantstation', data_source_default: 'sqlite', fastapi_available: true}});
    }
    if (method === 'GET' && pathname === '/api/strategies') return route.fulfill({json: []});
    if (method === 'GET' && pathname === '/api/research/btc/demo-paper/catalog') return route.fulfill({json: catalogFixture()});
    if (method === 'GET' && pathname === '/api/research/btc/demo-paper/status') {
      statusCalls += 1;
      const status = runtimeFixture('running') as unknown as Record<string, any>;
      status.strategy = strategyFixture(
        'long_short_donchian_top5_okx_native',
        'btc_ls_okx_native_001',
        'Long/Short Donchian Top5 · OKX Native',
        true,
        '',
      );
      status.signal = {
        direction: statusCalls > 1 ? 'long' : 'flat',
        target_contracts: statusCalls > 1 ? '0.01' : '0',
        decision_bar_close_utc: statusCalls > 1
          ? '2026-08-16T11:00:00Z'
          : '2026-08-16T10:00:00Z',
      };
      status.runtime.last_heartbeat_utc = '2026-08-16T11:00:05Z';
      return route.fulfill({json: status});
    }
    if (method === 'GET' && pathname === '/api/research/btc/demo-paper/klines') {
      klineCalls += 1;
      return route.fulfill({json: {
        ...klineFixture(),
        source_kind: 'okx_runtime_confirmed_completed_swap_1h',
        freshness_status: 'pass',
        sample_end: '2026-08-16T11:00:00Z',
      }});
    }
    if (method === 'GET' && pathname.startsWith('/api/research/btc/strategy-source/')) {
      const parts = pathname.split('/').filter(Boolean);
      const strategyId = decodeURIComponent(parts[4] ?? '');
      const candidateId = decodeURIComponent(parts[5] ?? '');
      const content = 'def signal(bar):\n    return "controlled-canonical"\n';
      return route.fulfill({json: {
        strategy_id: strategyId,
        candidate_id: candidateId,
        source_ref: 'registry://btc/okx-native/canonical.py',
        content_sha256: 'a'.repeat(64),
        content,
        sections: [{symbol: 'signal', source_ref: 'canonical.signal'}],
        canonical_signal_available: true,
      }});
    }
    if (method === 'GET' && pathname === '/api/research/btc/strategy-versions') {
      const content = 'def signal(bar):\n    return "controlled-canonical"\n';
      return route.fulfill({json: {
        versions: [{
          version_id: 'swv-demo-001',
          source_sha256: 'a'.repeat(64),
          source_content: content,
          execution: {runnable: true, canonical_source_match: true, blocker: ''},
        }],
      }});
    }
    if (method === 'GET' && pathname === '/api/research/btc/demo-paper/market-view') return route.fulfill({json: marketViewFixture()});
    if (method === 'GET' && pathname === '/api/research/btc/domain-read-model') {
      return route.fulfill({json: {status: 'blocked', freshness: 'current_head', safety: {}}});
    }
    if (method === 'GET' && pathname.includes('/strategy-history/')) {
      return route.fulfill({json: {strategy_id: 'long_short_donchian_top5_okx_native', candidate_id: 'btc_ls_okx_native_001', selected_run_id: '', history_runs: [], canonical: canonicalSummaryFixture(), canonical_report: null}});
    }
    return route.fulfill({json: canonicalSummaryFixture()});
  });

  await page.goto('/crypto?strategy_id=long_short_donchian_top5&candidate_id=btc_ls_tf_stable_001', {waitUntil: 'domcontentloaded'});

  const runtimeStrip = page.getByTestId('btc-runtime-visibility');
  const provenanceStrip = page.getByTestId('btc-provenance-strip');
  await expect(runtimeStrip).toContainText('运行中');
  await expect(runtimeStrip).toContainText('多空唐奇安突破 Top5（OKX 原生）');
  await expect(provenanceStrip).toContainText('OKX runtime · latest completed 1h · confirmed');
  await expect(provenanceStrip).not.toContainText('Binance');
  await expect.poll(() => klineCalls).toBe(1);

  await page.clock.fastForward(5_000);
  await expect.poll(() => klineCalls).toBe(2);
  await expect(runtimeStrip).toContainText('long');
  const expectedDecisionBarLabel = new Date('2026-08-16T11:00:00Z')
    .toLocaleString('zh-CN', {hour12: false});
  await expect(runtimeStrip).toContainText(expectedDecisionBarLabel);

  const beforeMinuteRefresh = klineCalls;
  await page.clock.fastForward(60_000);
  await expect.poll(() => klineCalls).toBe(beforeMinuteRefresh + 1);
  expect(statusCalls).toBeGreaterThan(1);
});

test('BTC Demo console controls the mock runtime and exposes reconciled evidence', async ({page}) => {
  let runtimeState: 'stopped' | 'running' | 'cancel_only' = 'stopped';
  let startPayload: Record<string, unknown> | null = null;
  let stopPayload: Record<string, unknown> | null = null;
  let reconcilePayload: Record<string, unknown> | null = null;
  let cancelOnlyPayload: Record<string, unknown> | null = null;

  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    const method = request.method();

    if (method === 'GET' && pathname === '/api/health') {
      return route.fulfill({json: {status: 'ok', service: 'quantstation', data_source_default: 'sqlite', fastapi_available: true}});
    }
    if (method === 'GET' && pathname === '/api/strategies') return route.fulfill({json: []});
    if (method === 'GET' && pathname === '/api/research/btc/demo-paper/catalog') return route.fulfill({json: catalogFixture()});
    if (method === 'GET' && pathname === '/api/research/btc/demo-paper/status') return route.fulfill({json: runtimeFixture(runtimeState)});
    if (method === 'GET' && pathname === '/api/research/btc/demo-paper/klines') return route.fulfill({json: klineFixture()});
    if (method === 'GET' && pathname === '/api/research/btc/demo-paper/market-view') return route.fulfill({json: marketViewFixture()});
    if (method === 'GET' && pathname.startsWith('/api/research/btc/strategy-history/')) {
      const parts = pathname.split('/').filter(Boolean);
      const strategyId = decodeURIComponent(parts[4] ?? '');
      const candidateId = decodeURIComponent(parts[5] ?? '');
      const canonical = canonicalSummaryFixture() as Record<string, unknown>;
      const identity = canonical.strategy_identity as Record<string, unknown>;
      canonical.strategy_identity = {...identity, strategy_id: strategyId, candidate_id: candidateId};
      canonical.promotion_readiness_blockers = ['promotion_artifact_unavailable'];
      return route.fulfill({json: {
        strategy_id: strategyId,
        candidate_id: candidateId,
        selected_run_id: '',
        history_runs: [],
        canonical,
        canonical_report: canonicalReportFixture(),
      }});
    }
    if (method === 'GET' && pathname === '/api/research/btc/canonical-backtest/latest') return route.fulfill({json: canonicalSummaryFixture()});
    if (method === 'GET' && pathname === '/api/research/btc/canonical-backtest/latest/report') return route.fulfill({json: canonicalReportFixture()});
    if (method === 'POST' && pathname === '/api/research/btc/demo-paper/start') {
      startPayload = request.postDataJSON() as Record<string, unknown>;
      runtimeState = 'running';
      return route.fulfill({json: runtimeFixture(runtimeState)});
    }
    if (method === 'POST' && pathname === '/api/research/btc/demo-paper/stop') {
      stopPayload = request.postDataJSON() as Record<string, unknown>;
      runtimeState = 'stopped';
      return route.fulfill({json: runtimeFixture(runtimeState)});
    }
    if (method === 'POST' && pathname === '/api/research/btc/demo-paper/reconcile') {
      reconcilePayload = request.postDataJSON() as Record<string, unknown>;
      return route.fulfill({json: runtimeFixture(runtimeState)});
    }
    if (method === 'POST' && pathname === '/api/research/btc/demo-paper/cancel-only') {
      cancelOnlyPayload = request.postDataJSON() as Record<string, unknown>;
      runtimeState = 'cancel_only';
      return route.fulfill({json: runtimeFixture(runtimeState)});
    }
    return route.fulfill({status: 404, json: {detail: 'fixture unavailable'}});
  });

  await page.goto('/crypto?strategy_id=long_short_donchian_top5&candidate_id=btc_ls_tf_stable_001', {waitUntil: 'domcontentloaded'});

  const console = page.locator('[data-testid="btc-demo-console"]');
  await expect(console).toContainText('OKX 模拟盘');
  await expect(page.locator('[data-testid="btc-trading-chart"] canvas').first()).toBeVisible();
  await expect(page.getByRole('button', {name: /高收益唐奇安/})).toBeDisabled();
  await expect(page.getByRole('button', {name: /高强度进攻分仓/})).toBeDisabled();
  await expect(console).toContainText('0.01 张');
  await expect(console).toContainText('≤ 10 USDT');
  await expect(page.getByTestId('btc-provenance-strip')).toContainText('OKX runtime · latest completed 1h · confirmed');
  await expect(page.getByTestId('btc-provenance-strip')).not.toContainText('Binance');
  await expect(page.getByTestId('btc-provenance-strip')).toContainText('OKX · BTC-USDT-SWAP · Demo');
  await expect(page.getByTestId('btc-report-freshness')).toContainText('历史 canonical 证据');
  await expect(page.getByTestId('btc-strategy-tester')).toContainText('2026-07-09 — 2026-07-14');
  await page.getByRole('button', {name: '业绩表现'}).click();
  await expect(page.locator('.tv-report-table')).toContainText('100,000.00 USDT');
  await page.getByRole('button', {name: 'Canonical 成交'}).click();
  await expect(page.getByTestId('btc-chart-context')).toContainText('2 / 2 个事件落在当前 K 线窗口');
  await expect(page.locator('.tv-chart-foot')).toContainText('Canonical 2');
  // A browsing deep link is history-only.  It cannot silently replace the
  // catalog-approved Demo start candidate.
  await expect(console.getByRole('combobox')).toHaveValue('btc_ls_okx_native_001');
  await console.locator('.tv-strategy-lines button').filter({hasText: 'OKX 原生'}).first().click();
  await expect(console.getByRole('combobox')).toHaveValue('btc_ls_okx_native_001');
  await console.locator('.tv-strategy-lines button').filter({hasText: '多空唐奇安突破 Top5'}).first().click();
  await expect(console.getByRole('combobox')).toHaveValue('btc_ls_tf_stable_001');
  await expect(page).toHaveURL(/candidate_id=btc_ls_tf_stable_001/);
  await expect(page.getByTestId('btc-runtime-health')).toContainText('私有 WS / gapfill');
  await expect(page.getByTestId('btc-runtime-health')).toContainText('Promotion 待验证');
  await expect(page.getByTestId('btc-demo-start-gates')).toContainText('Demo 启动条件');
  await expect(page.getByTestId('btc-demo-start-gates')).toContainText('completed 1h 信号');
  await expect(page.getByTestId('btc-demo-start-gates')).not.toContainText('私有 WS');
  await expect(page.getByTestId('btc-promotion-observation-gates')).toContainText('未来 Promotion 条件');
  await expect(page.getByTestId('btc-promotion-observation-gates')).toContainText('不阻止 Demo 启动');
  await expect(page.getByTestId('btc-promotion-observation-gates')).toContainText('WAITING');

  const startButton = console.getByRole('button', {name: '重新预检并启动'});
  await expect(startButton).toBeDisabled();
  for (const checkbox of await console.locator('input[type="checkbox"]').all()) await checkbox.check();
  await console.getByPlaceholder('BTC DEMO').fill('BTC DEMO');
  await expect(startButton).toBeEnabled();
  await startButton.click();

  await expect(console.getByTestId('btc-demo-operator-control')).toContainText('策略运行中');
  const observationProgress = page.getByTestId('btc-demo-observation-progress');
  await expect(observationProgress).toHaveJSProperty('open', false);
  await expect(observationProgress.locator('summary')).toContainText('13 / 25');
  await expect(observationProgress.getByRole('progressbar')).not.toBeVisible();
  await observationProgress.locator('summary').click();
  await expect(observationProgress).toHaveJSProperty('open', true);
  await expect(observationProgress).toContainText('还需 12 个完整小时');
  await expect(observationProgress).toContainText('正在累计完整小时');
  await expect(observationProgress).toContainText('跨重启累计有效 UTC 小时；不替代连续观察门槛');
  await expect(observationProgress).toContainText('Receipt 数19');
  await expect(observationProgress).toContainText('当前 runtime 计数与外部不可变封存证据相互独立');
  await expect(observationProgress).toContainText('累计观察 blockerbtc_okx_native:25_hour_demo_observation_window_incomplete');
  await expect(observationProgress).toContainText('订单 / 成交1 / 1');
  await expect(observationProgress).toContainText('Funding bills1');
  await expect(observationProgress).toContainText('Private WSconnected');
  await expect(observationProgress).toContainText('WS listeneralive');
  await expect(observationProgress).toContainText('Ledger reconciliationreconciled');
  await expect(observationProgress.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '13');
  await expect(observationProgress.getByRole('progressbar')).toHaveAttribute('aria-valuetext', '13 / 25 个累计有效小时');
  await expect.poll(() => startPayload).not.toBeNull();
  expect(startPayload).toEqual({
    authorization_ticket: 'BTC-OKX-DEMO-PAPER-01',
    strategy_id: 'long_short_donchian_top5',
    candidate_id: 'btc_ls_tf_stable_001',
    strategy_version: 'btc_long_short_top5_v1',
    instrument_id: 'BTC-USDT-SWAP',
    margin_mode: 'isolated',
    order_contracts: 0.01,
    max_net_contracts: 0.01,
    max_notional_usdt: 10,
    confirmation_text: 'BTC DEMO',
    confirm_demo_only: true,
    confirm_automatic_orders: true,
    confirm_risk_limits: true,
    confirm_cancel_only_on_error: true,
    confirm_dedicated_demo_account: true,
    dead_man_tag: 'btcP0Demo',
    server_side_protection_policy: {
      policy_id: 'btc_demo_p0_exchange_guard',
      version: '1',
      policy_sha256: '28e04b92827f23d0c06579056094b3d48db5fb905d38eaa6ec67aa727e550465',
      sl_distance_bps: '100',
      tp_distance_bps: '200',
      trigger: 'mark',
    },
  });
  await expect(console).toContainText('专用 Demo 账户');
  await expect(console).toContainText('P0 服务端保护');
  await expect(console).toContainText('不会解锁实盘');
  await expect(page.getByTestId('btc-demo-authority-bar')).toContainText('LONG 0.01 张');
  await expect(console.getByTestId('btc-demo-stop-and-flatten')).toBeVisible();

  await console.getByRole('button', {name: '刷新账户对账'}).click();
  await expect.poll(() => reconcilePayload).toEqual({confirmation_text: 'BTC DEMO'});

  await page.getByRole('button', {name: /订单 1/}).click();
  await expect(page.locator('.tv-data-table')).toContainText('btc-demo-client-001');
  await page.getByRole('button', {name: /成交 1/}).click();
  await expect(page.locator('.tv-data-table')).toContainText('demo-fill-001');
  await page.getByRole('button', {name: /仓位 1/}).click();
  await expect(page.locator('.tv-data-table')).toContainText('long');
  await page.getByRole('button', {name: '费用与资金费'}).click();
  await expect(page.locator('.tv-cost-grid')).toContainText('Funding 样本');
  await expect(page.locator('.tv-cost-grid')).toContainText('1');
  await expect(page.locator('.tv-cost-workbench')).toContainText('Depth → fill mapping');
  await expect(page.locator('.tv-cost-workbench')).toContainText('BLOCKED');
  await page.getByRole('button', {name: '审计'}).click();
  await expect(page.locator('.tv-audit-workbench')).toContainText('Append-only 本地审计');
  await expect(page.locator('.tv-audit-workbench')).toContainText('已记录并对账 fill demo-fill-001；不代表 depth/slippage mapping 已验证。');

  page.once('dialog', (dialog) => dialog.accept());
  await console.getByRole('button', {name: '停止策略（保留仓位）'}).click();
  await expect(console).toContainText('stopped');
  await expect.poll(() => stopPayload).toEqual({confirmation_text: 'BTC DEMO'});

  page.once('dialog', (dialog) => dialog.accept());
  await console.getByRole('button', {name: '紧急 Cancel-only'}).click();
  await expect(console).toContainText('仅禁止新增风险');
  await expect(console).toContainText('Cancel-only');
  await expect(observationProgress).toContainText('0 / 25');
  await expect(observationProgress).toContainText('还需 25 个完整小时');
  await expect(observationProgress).toContainText('累计已停止，当前小时不计入');
  await expect(observationProgress).toContainText('worker no');
  await expect(observationProgress).toContainText(/Runtime blocker[\s\S]*OKX Demo 网络连接失败；保持 cancel-only[\s\S]*诊断：okx_demo_private_ws/);
  await expect(observationProgress.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '0');
  await expect.poll(() => cancelOnlyPayload).toEqual({confirmation_text: 'CANCEL ONLY'});
  await expect(page.locator('.tv-research-disclaimer')).toContainText('不表示 paper/live ready');
});

test('stop and flatten is a separate confirmed action with no frontend quantity', async ({page}) => {
  let flattenPayload: Record<string, unknown> | null = null;
  const postPaths: string[] = [];
  page.on('request', (request) => {
    if (request.method() === 'POST') postPaths.push(new URL(request.url()).pathname);
  });
  await installStartGateFixture(page, runtimeFixture('running'), klineFixture(), []);
  await page.route('**/api/research/btc/demo-paper/stop-and-flatten', async (route) => {
    flattenPayload = route.request().postDataJSON() as Record<string, unknown>;
    return route.fulfill({json: runtimeFixture('stopped')});
  });

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const console = page.getByTestId('btc-demo-console');
  await expect(console.getByRole('button', {name: '停止策略（保留仓位）'})).toBeVisible();
  await console.getByTestId('btc-demo-stop-and-flatten').click();
  const confirmation = page.getByTestId('btc-demo-flatten-confirm');
  await expect(confirmation).toContainText('当前待平仓位：LONG 0.01 张');
  const confirmButton = confirmation.getByRole('button', {name: '确认停止并平仓'});
  await expect(confirmButton).toBeDisabled();
  await confirmation.locator('input').fill('STOP AND FLATTEN');
  await expect(confirmButton).toBeEnabled();
  await confirmButton.click();

  await expect.poll(() => flattenPayload).toEqual({confirmation_text: 'STOP AND FLATTEN'});
  expect(postPaths).toEqual(['/api/research/btc/demo-paper/stop-and-flatten']);
  await expect(console).toContainText('stopped');
});

test('BTC Demo console separator supports pointer, keyboard, reset, persistence, and narrow stacking without writes', async ({page}) => {
  const mock = await mockBtcTradingPage(page);
  await page.setViewportSize({width: 1440, height: 900});
  await page.addInitScript((storageKey) => localStorage.setItem(storageKey, 'not-a-number'), BTC_CONSOLE_WIDTH_KEY);
  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const separator = page.getByTestId('btc-demo-console-separator');
  await expect(separator).toBeVisible();
  await expect(separator).toHaveAttribute('role', 'separator');
  await expect(separator).toHaveAttribute('aria-orientation', 'vertical');
  await expect(separator).toHaveAttribute('aria-valuemin', '320');
  await expect(separator).toHaveAttribute('aria-valuemax', /\d+/);
  const initialWidth = Number(await separator.getAttribute('aria-valuenow'));
  expect(initialWidth).toBeGreaterThanOrEqual(320);

  await separator.focus();
  await page.keyboard.press('ArrowRight');
  await expect.poll(async () => Number(await separator.getAttribute('aria-valuenow'))).toBe(initialWidth + 16);
  await expect.poll(() => page.evaluate((storageKey) => localStorage.getItem(storageKey), BTC_CONSOLE_WIDTH_KEY)).toBe(String(initialWidth + 16));

  const beforeDrag = await separator.boundingBox();
  if (!beforeDrag) throw new Error('separator bounding box unavailable');
  await page.mouse.move(beforeDrag.x + beforeDrag.width / 2, beforeDrag.y + 30);
  await page.mouse.down();
  await page.mouse.move(beforeDrag.x + beforeDrag.width / 2 - 64, beforeDrag.y + 30);
  await page.mouse.up();
  const pointerWidth = Number(await separator.getAttribute('aria-valuenow'));
  expect(pointerWidth).not.toBe(initialWidth + 16);
  await expect.poll(() => page.evaluate((storageKey) => localStorage.getItem(storageKey), BTC_CONSOLE_WIDTH_KEY)).toBe(String(pointerWidth));

  await separator.dblclick();
  await expect(separator).toHaveAttribute('aria-valuenow', String(initialWidth));
  await page.reload({waitUntil: 'domcontentloaded'});
  await expect(page.getByTestId('btc-demo-console-separator')).toHaveAttribute('aria-valuenow', String(initialWidth));

  const chartBox = await page.getByTestId('btc-trading-chart').boundingBox();
  expect(chartBox?.width).toBeGreaterThanOrEqual(560);
  const mainChartBox = await page.locator('.crypto-tv-shell .tv-chart-panel').boundingBox();
  const testerBox = await page.getByTestId('btc-strategy-tester').boundingBox();
  const wideConsoleBox = await page.getByTestId('btc-demo-console').boundingBox();
  expect(mainChartBox).not.toBeNull();
  expect(testerBox).not.toBeNull();
  expect(wideConsoleBox).not.toBeNull();
  expect((testerBox?.right ?? 0)).toBeLessThanOrEqual((wideConsoleBox?.left ?? Number.POSITIVE_INFINITY) + 1);
  expect(Math.abs((testerBox?.left ?? 0) - (mainChartBox?.left ?? 0))).toBeLessThanOrEqual(2);
  expect(Math.abs((testerBox?.width ?? 0) - (mainChartBox?.width ?? 0))).toBeLessThanOrEqual(2);
  expect(mock.requests.filter((item) => item.method === 'POST')).toEqual([]);

  await page.setViewportSize({width: 900, height: 900});
  await expect(page.getByTestId('btc-demo-console-separator')).toBeHidden();
  const consoleBox = await page.getByTestId('btc-demo-console').boundingBox();
  const narrowChartBox = await page.getByTestId('btc-trading-chart').boundingBox();
  expect(consoleBox?.y).toBeGreaterThan(narrowChartBox?.y ?? 0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)).toBe(false);
  expect(mock.requests.filter((item) => item.method === 'POST')).toEqual([]);
});

test('BTC strategy tester separator supports pointer, keyboard, reset, persistence, and only appears for the tester', async ({page}) => {
  const mock = await mockBtcTradingPage(page);
  await page.setViewportSize({width: 1440, height: 1080});
  await page.addInitScript((storageKey) => localStorage.setItem(storageKey, 'not-a-number'), BTC_STRATEGY_TESTER_HEIGHT_KEY);
  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const separator = page.getByTestId('btc-strategy-tester-separator');
  await expect(separator).toBeVisible();
  await expect(separator).toHaveAttribute('role', 'separator');
  await expect(separator).toHaveAttribute('aria-orientation', 'horizontal');
  await expect(separator).toHaveAttribute('aria-valuemin', '280');
  await expect(separator).toHaveAttribute('aria-valuemax', /\d+/);
  await expect(separator).toHaveAttribute('aria-valuenow', '420');

  await separator.focus();
  await page.keyboard.press('ArrowUp');
  await expect(separator).toHaveAttribute('aria-valuenow', '436');
  await expect.poll(() => page.evaluate((key) => localStorage.getItem(key), BTC_STRATEGY_TESTER_HEIGHT_KEY)).toBe('436');

  const beforeDrag = await separator.boundingBox();
  if (!beforeDrag) throw new Error('strategy tester separator bounding box unavailable');
  await page.mouse.move(beforeDrag.x + 40, beforeDrag.y + beforeDrag.height / 2);
  await page.mouse.down();
  await page.mouse.move(beforeDrag.x + 40, beforeDrag.y - 48);
  await page.mouse.up();
  const draggedHeight = Number(await separator.getAttribute('aria-valuenow'));
  expect(draggedHeight).toBeGreaterThan(436);
  await expect.poll(() => page.evaluate((key) => localStorage.getItem(key), BTC_STRATEGY_TESTER_HEIGHT_KEY)).toBe(String(draggedHeight));

  await separator.dblclick();
  await expect(separator).toHaveAttribute('aria-valuenow', '420');
  await page.reload({waitUntil: 'domcontentloaded'});
  await expect(page.getByTestId('btc-strategy-tester-separator')).toHaveAttribute('aria-valuenow', '420');

  await page.getByRole('button', {name: /订单/}).click();
  await expect(page.getByTestId('btc-strategy-tester-separator')).toHaveCount(0);
  await page.getByRole('button', {name: '策略测试器'}).click();
  await expect(page.getByTestId('btc-strategy-tester-separator')).toBeVisible();

  await page.setViewportSize({width: 900, height: 1080});
  await expect(page.getByTestId('btc-strategy-tester-separator')).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)).toBe(false);
  expect(mock.requests.filter((item) => item.method === 'POST')).toEqual([]);
});

async function installStartGateFixture(
  page: Page,
  status: Record<string, unknown>,
  klines: Record<string, unknown>,
  posted: Record<string, unknown>[],
  startFailure = '',
  historyResponseDelayMs = 0,
  startResponse: Record<string, unknown> | undefined = undefined,
  statusResponseDelayMs = 0,
  statusSequence: Record<string, unknown>[] = [],
  startResponseStatus = 200,
) {
  let startRejected = false;
  let statusReads = 0;
  await page.route('**/api/**', async (route: Route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    const method = request.method();
    if (method === 'GET' && pathname === '/api/health') {
      return route.fulfill({json: {status: 'ok', service: 'quantstation', data_source_default: 'sqlite', fastapi_available: true}});
    }
    if (method === 'GET' && pathname === '/api/strategies') return route.fulfill({json: []});
    if (method === 'GET' && pathname === '/api/research/btc/demo-paper/catalog') return route.fulfill({json: catalogFixture()});
    if (method === 'GET' && pathname === '/api/research/btc/demo-paper/status') {
      if (startRejected && statusResponseDelayMs) await new Promise((resolve) => setTimeout(resolve, statusResponseDelayMs));
      const sequenceStatus = statusSequence.length
        ? statusSequence[Math.min(statusReads, statusSequence.length - 1)]
        : status;
      statusReads += 1;
      return route.fulfill({json: startRejected && startFailure ? rejectedStartStatusFixture(sequenceStatus, startFailure) : sequenceStatus});
    }
    if (method === 'GET' && pathname === '/api/research/btc/demo-paper/klines') return route.fulfill({json: klines});
    if (method === 'GET' && pathname === '/api/research/btc/demo-paper/market-view') return route.fulfill({json: marketViewFixture()});
    if (method === 'GET' && pathname === '/api/research/btc/domain-read-model') return route.fulfill({json: {status: 'blocked', freshness: 'current_head', safety: {}}});
    if (method === 'GET' && pathname.startsWith('/api/research/btc/strategy-history/')) {
      if (historyResponseDelayMs) await new Promise((resolve) => setTimeout(resolve, historyResponseDelayMs));
      const parts = pathname.split('/').filter(Boolean);
      const strategyId = decodeURIComponent(parts[4] ?? '');
      const candidateId = decodeURIComponent(parts[5] ?? '');
      const canonical = canonicalSummaryFixture() as Record<string, unknown>;
      const identity = canonical.strategy_identity as Record<string, unknown>;
      canonical.strategy_identity = {...identity, strategy_id: strategyId, candidate_id: candidateId};
      canonical.promotion_readiness_blockers = ['promotion_artifact_unavailable'];
      return route.fulfill({json: {
        strategy_id: strategyId,
        candidate_id: candidateId,
        selected_run_id: '',
        history_runs: [],
        canonical,
        canonical_report: null,
      }});
    }
    if (method === 'GET' && pathname.includes('/canonical-backtest/latest')) return route.fulfill({json: canonicalSummaryFixture()});
    if (method === 'GET' && pathname.includes('/okx-native-backtest/latest')) return route.fulfill({json: canonicalSummaryFixture()});
    if (method === 'POST' && pathname === '/api/research/btc/demo-paper/start') {
      posted.push(request.postDataJSON() as Record<string, unknown>);
      if (startFailure) {
        startRejected = true;
        return route.fulfill({status: 400, json: {detail: startFailure}});
      }
      return route.fulfill({status: startResponseStatus, json: startResponse ?? runtimeFixture('running')});
    }
    if (method === 'POST' && pathname.startsWith('/api/research/btc/demo-paper/')) return route.fulfill({json: status});
    return route.fulfill({status: 404, json: {detail: 'fixture unavailable'}});
  });
}

function rejectedStartStatusFixture(
  base: Record<string, unknown>,
  reason: string,
): Record<string, unknown> {
  const status = JSON.parse(JSON.stringify(base)) as Record<string, unknown>;
  const runtime = status.runtime as Record<string, unknown>;
  const privateWs = status.private_ws as Record<string, unknown>;
  const baseControl = status.operator_control as Record<string, any> | undefined;
  const networkFailure = /private_ws|urlerror|disconnect|connection|timeout|tls|dns/i.test(reason);
  const accountFailure = /nonflat|position|pending|protection|ledger_mismatch/i.test(reason)
    || baseControl?.incident?.category === 'account_risk';
  runtime.status = 'start_blocked_fail_closed';
  runtime.active = false;
  runtime.opening_allowed = false;
  runtime.cancel_only = true;
  runtime.last_error = reason;
  runtime.blockers = [reason];
  if (networkFailure) {
    privateWs.status = 'blocked';
    privateWs.connected = false;
    privateWs.listener_alive = false;
    privateWs.opening_allowed_after_reconciliation = false;
    privateWs.blockers = [reason];
  }
  status.operator_control = operatorControlFixture(
    'stopped',
    networkFailure ? 'network_transport' : accountFailure ? 'account_risk' : 'runtime_fault',
    reason,
  );
  return status;
}

function recoverableBlockedRuntimeFixture(): Record<string, unknown> {
  const status = runtimeFixture('stopped') as unknown as Record<string, unknown>;
  const runtime = status.runtime as Record<string, unknown>;
  const ledger = status.ledger_reconciliation as Record<string, unknown>;
  const privateWs = status.private_ws as Record<string, unknown>;
  runtime.status = 'blocked_fail_closed';
  runtime.active = false;
  runtime.opening_allowed = false;
  runtime.cancel_only = true;
  runtime.worker_alive = false;
  runtime.last_error = 'okx_demo_previous_cancel_only_state_restored';
  runtime.blockers = [
    'okx_demo_private_ws_reconciled_full_reconciliation_pending',
    'okx_demo_previous_cancel_only_state_restored',
  ];
  ledger.status = 'reconciled';
  ledger.current_state_exchange_snapshot_match = true;
  ledger.funding_cashflow_reconciled = true;
  ledger.position_count = 0;
  ledger.pending_order_count = 0;
  privateWs.status = 'not_started';
  privateWs.connected = false;
  privateWs.listener_alive = false;
  privateWs.opening_allowed_after_reconciliation = false;
  privateWs.blockers = ['okx_demo_private_ws_reconciled_full_reconciliation_pending'];
  status.risk_control = {
    mode: 'FROZEN_UNKNOWN',
    reason: 'okx_demo_previous_cancel_only_state_restored',
    write_path_trusted: false,
    dead_man: {
      armed: false,
      heartbeat_thread_alive: false,
      watchdog_renews_dead_man: false,
      last_error: '',
    },
  };
  status.operator_control = operatorControlFixture(
    'stopped',
    'service_restart',
    'okx_demo_previous_cancel_only_state_restored',
  );
  return status;
}

function firstStartRuntimeFixture(): Record<string, unknown> {
  const status = runtimeFixture('stopped') as unknown as Record<string, unknown>;
  const runtime = status.runtime as Record<string, unknown>;
  const ledger = status.ledger_reconciliation as Record<string, unknown>;
  const privateWs = status.private_ws as Record<string, unknown>;
  runtime.status = 'stopped';
  runtime.active = false;
  runtime.opening_allowed = false;
  runtime.cancel_only = false;
  runtime.worker_alive = false;
  runtime.last_error = '';
  runtime.blockers = [];
  ledger.status = 'reconciled';
  ledger.current_state_exchange_snapshot_match = true;
  ledger.funding_cashflow_reconciled = true;
  ledger.position_count = 0;
  ledger.pending_order_count = 0;
  privateWs.status = 'not_started';
  privateWs.connected = false;
  privateWs.listener_alive = false;
  privateWs.opening_allowed_after_reconciliation = false;
  privateWs.blockers = [];
  status.risk_control = {
    mode: 'FROZEN_UNKNOWN',
    reason: 'runtime_not_started',
    write_path_trusted: false,
    dead_man: {
      armed: false,
      heartbeat_thread_alive: false,
      watchdog_renews_dead_man: false,
      last_error: '',
    },
  };
  status.operator_control = operatorControlFixture(
    'stopped',
    'service_restart',
    'runtime_not_started',
  );
  return status;
}

function frozenRuntimeFixture(): Record<string, unknown> {
  const status = runtimeFixture('stopped') as unknown as Record<string, unknown>;
  const runtime = status.runtime as Record<string, unknown>;
  const exchange = status.exchange as Record<string, unknown>;
  runtime.status = 'blocked_fail_closed';
  runtime.last_error = 'okx_demo_nonflat_position_has_no_verified_protection';
  runtime.blockers = ['okx_demo_nonflat_position_has_no_verified_protection'];
  exchange.positions = [{
    instrument_id: 'BTC-USDT-SWAP',
    position_side: 'long',
    margin_mode: 'isolated',
    contracts: '0.01',
    average_price: '62000',
    mark_price: '62032',
    liquidation_price: '31000',
    unrealized_pnl: '0.32',
    realized_pnl: '0',
    leverage: '3',
    updated_at_ms: '1783994400000',
  }];
  exchange.pending_algo_orders = [{
    algo_id: 'demo-oco-001',
    algo_client_order_id: 'btc-demo-oco-001',
    instrument_id: 'BTC-USDT-SWAP',
    position_side: 'long',
    size: '0.01',
    order_type: 'oco',
    state: 'live',
  }];
  status.risk_control = {
    mode: 'FROZEN_UNKNOWN',
    reason: 'okx_demo_nonflat_position_has_no_verified_protection',
  };
  status.operator_control = operatorControlFixture(
    'stopped',
    'account_risk',
    'okx_demo_nonflat_position_has_no_verified_protection',
  );
  return status;
}

function catalogFixture() {
  return {
    schema_version: 'btc_demo_strategy_catalog_v1',
    environment: 'OKX Demo',
    instrument_id: 'BTC-USDT-SWAP',
    authorization_ticket: 'BTC-OKX-DEMO-PAPER-01',
    confirmation_text: 'BTC DEMO',
    default_strategy_id: 'long_short_donchian_top5_okx_native',
    default_candidate_id: 'btc_ls_okx_native_001',
    default_reason: 'OKX Native frozen identity is the Demo default',
    strategies: [
      strategyFixture('long_short_donchian_top5', 'btc_ls_tf_stable_001', 'Long/Short Donchian Top5', true, ''),
      strategyFixture('long_short_donchian_top5_okx_native', 'btc_ls_okx_native_001', 'Long/Short Donchian Top5 · OKX Native', true, ''),
      strategyFixture('btc_high_yield_v2', 'identity-high-yield', 'High-Yield', false, 'identity_only_no_demo_execution_ledger'),
      strategyFixture('btc_high_octane_v1', 'identity-high-octane', 'High-Octane', false, 'identity_only_no_demo_execution_ledger'),
    ],
    safety: {live_order_allowed: false, real_money_allowed: false, transfer_allowed: false, withdraw_allowed: false, permission_upgrade_allowed: false},
  };
}

function strategyFixture(strategyId: string, candidateId: string, displayName: string, selectable: boolean, blocker: string) {
  return {
    strategy_id: strategyId,
    candidate_id: candidateId,
    strategy_version: strategyId === 'long_short_donchian_top5' ? 'btc_long_short_top5_v1' : strategyId === 'long_short_donchian_top5_okx_native' ? 'btc_long_short_top5_okx_native_v1' : 'identity_v1',
    params_hash: 'a'.repeat(64),
    display_name: displayName,
    timeframe: '1h',
    direction_policy: 'long_short',
    adapter_fidelity: selectable ? 'exact_frozen_identity' : 'identity_only',
    promotion_eligibility: 'gated',
    canonical_signal_available: selectable,
    demo_selectable: selectable,
    demo_blocker: blocker,
  };
}

function runtimeFixture(state: 'stopped' | 'running' | 'cancel_only') {
  const active = state !== 'stopped';
  const running = state === 'running';
  const hasPosition = state !== 'stopped';
  return {
    schema_version: 'btc_okx_demo_paper_runtime_status_v1',
    runtime_version: 'okx_demo_paper_runtime_v1',
    environment: 'OKX Demo',
    instrument_id: 'BTC-USDT-SWAP',
    runtime: {
      run_id: active ? 'btc-demo-run-001' : '',
      status: state,
      active,
      worker_alive: running,
      opening_allowed: running,
      cancel_only: state === 'cancel_only',
      started_at_utc: active ? '2026-07-14T01:00:00Z' : '',
      stopped_at_utc: active ? '' : '2026-07-14T02:00:00Z',
      last_heartbeat_utc: '2026-07-14T02:00:00Z',
      last_reconciled_at_utc: '2026-07-14T02:00:00Z',
      last_processed_bar_close_utc: '2026-07-14T01:00:00Z',
      last_error: '',
      blockers: state === 'cancel_only' ? ['okx_demo_private_ws:disconnected'] : [],
      orders_submitted: 1,
      fills_observed: 1,
      authorization_ticket: 'BTC-OKX-DEMO-PAPER-01',
    },
    private_ws: {
      status: running ? 'connected' : 'disconnected',
      connected: running,
      listener_alive: running,
      opening_allowed_after_reconciliation: running,
      reconnect_rest_reconciled: running,
      blockers: state === 'cancel_only' ? ['btc_okx_demo_private_ws:disconnected'] : [],
      promotion_evidence_ready: false,
    },
    observation: {
      observation_receipt_count: running ? 19 : state === 'cancel_only' ? 4 : 0,
      consecutive_hours: running ? 13 : 0,
      window_complete: false,
      ledger_hash: running ? 'e'.repeat(64) : '',
      last_receipt_sha256: running ? 'f'.repeat(64) : '',
      last_observation_hour_utc: running ? '2026-07-14T01:00:00Z' : '',
      blockers: ['btc_okx_native:25_hour_demo_observation_window_incomplete'],
      promotion_evidence_ready: false,
    },
    ledger_reconciliation: {
      status: 'reconciled',
      current_state_exchange_snapshot_match: running,
      funding_cashflow_reconciled: running,
      order_count: hasPosition ? 1 : 0,
      pending_order_count: 0,
      fill_count: hasPosition ? 1 : 0,
      position_count: hasPosition ? 1 : 0,
      funding_bill_count: hasPosition ? 1 : 0,
      funding_cashflow: hasPosition ? '-0.0012' : '0',
      last_funding_ledger_hash: running ? 'a'.repeat(64) : '',
      fixture: false,
      promotion_evidence_ready: false,
    },
    strategy: strategyFixture('long_short_donchian_top5', 'btc_ls_tf_stable_001', 'Long/Short Donchian Top5', true, ''),
    limits: {margin_mode: 'isolated', order_contracts: '0.01', max_net_contracts: '0.01', max_notional_usdt: '10'},
    signal: {direction: hasPosition ? 'long' : 'flat', target_contracts: hasPosition ? '0.01' : '0'},
    exchange: {
      captured_at_utc: '2026-07-14T02:00:00Z',
      account: {account_level: '2', position_mode: 'long_short_mode', permissions: ['read', 'trade'], withdraw_permission_present: false},
      balance: {equity_usdt: '1000.50', available_usdt: '992.50', unrealized_pnl_usdt: '0.32', timestamp_ms: '1783994400000'},
      positions: hasPosition ? [{instrument_id: 'BTC-USDT-SWAP', position_side: 'long', margin_mode: 'isolated', contracts: '0.01', average_price: '62000', mark_price: '62032', liquidation_price: '31000', unrealized_pnl: '0.32', realized_pnl: '0', leverage: '1', updated_at_ms: '1783994400000'}] : [],
      pending_orders: [],
      orders: hasPosition ? [{order_id: 'demo-order-001', client_order_id: 'btc-demo-client-001', instrument_id: 'BTC-USDT-SWAP', side: 'buy', position_side: 'long', order_type: 'ioc', state: 'filled', price: '62010', average_price: '62002', size: '0.01', filled_size: '0.01', fee: '-0.0031', pnl: '0', created_at_ms: '1783990800000', updated_at_ms: '1783990800000'}] : [],
      fills: hasPosition ? [{fill_id: 'demo-fill-001', order_id: 'demo-order-001', client_order_id: 'btc-demo-client-001', instrument_id: 'BTC-USDT-SWAP', side: 'buy', position_side: 'long', price: '62002', size: '0.01', fee: '-0.0031', fee_currency: 'USDT', pnl: '0', execution_type: 'taker', timestamp_ms: '1783990800000'}] : [],
      bills: hasPosition ? [{bill_id: 'demo-funding-001', instrument_id: 'BTC-USDT-SWAP', currency: 'USDT', type: '8', sub_type: '173', balance_change: '-0.0012', fee: '0', pnl: '-0.0012', timestamp_ms: '1783994400000'}] : [],
      fee_schedule: {level: 'Lv1', maker_rate: '0.0002', taker_rate: '0.0005', rule_type: '0', timestamp_ms: '1783994400000'},
      funding: {funding_rate: '0.0001', next_funding_rate: '0.00012', funding_time_ms: '1783994400000', next_funding_time_ms: '1784023200000'},
      ticker: {bid: '62031', ask: '62033', last: '62032', timestamp_ms: '1783994400000'},
      mark: {mark_price: '62032', timestamp_ms: '1783994400000'},
    },
    audit: [],
    events: hasPosition ? [
      {event_id: 'event-001', timestamp_utc: '2026-07-14T02:00:00Z', event_type: 'fill_reconciled', payload: {fill_id: 'demo-fill-001'}},
    ] : [],
    safety: {live_order_allowed: false, real_money_allowed: false, transfer_allowed: false, withdraw_allowed: false, permission_upgrade_allowed: false},
    operator_control: operatorControlFixture(state),
    risk_control: {
      mode: running ? 'RUNNING' : state === 'cancel_only' ? 'FROZEN_UNKNOWN' : 'STOPPED',
      reason: running ? 'startup_complete' : '',
      write_path_trusted: running,
      dead_man: {
        armed: running,
        heartbeat_thread_alive: running,
        watchdog_renews_dead_man: running,
        last_error: '',
      },
    },
  };
}

function operatorControlFixture(
  state: 'stopped' | 'starting' | 'running' | 'cancel_only',
  category: 'none' | 'service_restart' | 'network_transport' | 'preflight_progress' | 'account_risk' | 'runtime_fault' = state === 'cancel_only' ? 'network_transport' : 'none',
  reason = '',
) {
  const starting = state === 'starting';
  const active = state === 'running' || state === 'cancel_only';
  const running = state === 'running';
  const lifecycle = starting
    ? 'starting_preflight'
    : running
    ? 'running'
    : active
      ? 'degraded_no_new_risk'
      : category === 'none'
        ? 'stopped_clean'
        : 'stopped_needs_preflight';
  const incident = {
    none: {severity: 'info', title: '运行控制面正常', summary: '当前没有影响 Demo 运行的故障。', impact_scope: 'none'},
    service_restart: {severity: 'warning', title: '服务重启后需要重新预检', summary: '这不是账户风险；重新完成权威预检后才会恢复新开仓能力。', impact_scope: 'demo_start'},
    network_transport: {severity: 'warning', title: 'OKX Demo 网络链路不可用', summary: '现有风险保持冻结；网络恢复后重新预检，不会盲目重发订单。', impact_scope: 'new_risk_only'},
    preflight_progress: {severity: 'info', title: '正在验证 Private WS 断线重连', summary: '这是权威启动预检步骤，不是网络事故；完成前不会启用新订单能力。', impact_scope: 'demo_start'},
    account_risk: {severity: 'critical', title: '账户或订单状态需要人工处理', summary: '检测到仓位、挂单、保护单或账本不一致；禁止新增风险。', impact_scope: 'account_and_order_safety'},
    runtime_fault: {severity: 'danger', title: 'Demo Runtime 故障', summary: '启动前安全检查未通过，请按故障步骤处理。', impact_scope: 'demo_start'},
  }[category];
  if (category === 'network_transport' && !active) {
    incident.summary = '当前未启用订单能力；网络恢复后重新预检，不会盲目重发订单。';
    incident.impact_scope = 'demo_start';
  }
  const stageState = (key: string): 'ready' | 'waiting' | 'blocked' => {
    if (running) return 'ready';
    if (category === 'network_transport' && ['private_ws', 'broker_truth'].includes(key)) return 'blocked';
    if (category === 'account_risk' && key === 'positions_orders_oco') return 'blocked';
    if (['account', 'positions_orders_oco', 'ledger'].includes(key)) return 'ready';
    return 'waiting';
  };
  const stage = (key: string, label: string) => ({
    key,
    label,
    state: stageState(key),
    detail: stageState(key) === 'ready' ? `${label} 已通过` : stageState(key) === 'blocked' ? `${label} 阻塞` : `等待 ${label}`,
  });
  const lifecycleLabel = {
    starting_preflight: '正在权威预检',
    running: '策略运行中',
    degraded_no_new_risk: '已禁止新增风险',
    stopped_clean: '已干净停止',
    stopped_needs_preflight: '等待重新预检',
  }[lifecycle];
  const safeMode = state === 'cancel_only' ? 'cancel_only' : category === 'none' ? 'normal' : 'frozen_unknown';
  const safeModeLabel = {
    normal: '正常模式',
    cancel_only: 'Cancel-only',
    frozen_unknown: '权威状态待确认',
  }[safeMode];
  const impactLabel = {
    none: '无运行影响',
    demo_start: '仅阻止 Demo 启动',
    new_risk_only: '仅禁止新增风险',
    account_and_order_safety: '账户与订单安全',
  }[incident.impact_scope];
  return {
    schema_version: 'btc_demo_operator_control_v1',
    lifecycle,
    lifecycle_label: lifecycleLabel,
    session_active: active,
    new_risk_allowed: running,
    safe_mode: safeMode,
    safe_mode_label: safeModeLabel,
    incident: {...incident, category, impact_label: impactLabel, reason_codes: reason ? [reason] : []},
    primary_action: starting
      ? {code: 'wait_for_preflight', label: '正在执行权威预检'}
      : active
      ? {code: running ? 'stop_keep_position' : 'inspect_and_stop', label: running ? '停止策略（保留仓位）' : '检查风险并停止'}
      : {code: 'authoritative_preflight_start', label: category === 'account_risk' ? '重新核验账户（仅安全时启动）' : '重新预检并启动'},
    allowed_actions: {
      authoritative_preflight_start: !active && !starting,
      direct_start: false,
      refresh_account_snapshot: true,
      stop_keep_position: active,
      stop_and_flatten: active,
      enter_cancel_only: state !== 'cancel_only',
    },
    preflight_stages: [
      stage('account', '1. 账户'),
      stage('positions_orders_oco', '2. 仓位 / 挂单 / OCO'),
      stage('ledger', '3. 账本'),
      stage('private_ws', '4. Private WS'),
      stage('broker_truth', '5. 行情 / Broker Truth'),
      stage('dead_man', '6. dead-man'),
    ],
    evidence: {
      status: 'incomplete',
      impact_scope: 'promotion_only',
      blocks_demo_start: false,
      reason_codes: ['promotion_evidence_not_ready'],
    },
    raw_state: {
      runtime_status: state,
      risk_mode: running ? 'RUNNING' : state === 'cancel_only' ? 'FROZEN_UNKNOWN' : 'STOPPED',
      risk_reason: reason,
    },
  };
}

function klineFixture() {
  const start = Date.UTC(2026, 6, 9, 0, 0, 0);
  const rows = Array.from({length: 140}, (_, index) => {
    const openTime = start + index * 3_600_000;
    const open = 61_000 + index * 7 + Math.sin(index / 5) * 120;
    const close = open + Math.sin(index / 2) * 70;
    return {
      exchange: 'okx',
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
  return {
    db_path: 'data/market_data.sqlite',
    read_only: true,
    schema_maintenance_performed: false,
    source_kind: 'okx_runtime_confirmed_completed_swap_1h',
    source_sha256: '',
    strategy_signal_compatible: true,
    sample_end: rows.at(-1)?.time ?? '',
    freshness_status: 'pass',
    rows,
  };
}

function marketViewFixture() {
  const start = Date.UTC(2026, 6, 14, 2, 0, 0);
  return {
    schema_version: 'okx_public_market_view_v1',
    source_kind: 'okx_public_market_view_v1',
    instrument_id: 'BTC-USDT-SWAP',
    timeframe: '1m',
    read_only: true,
    public_only: true,
    private_endpoint_used: false,
    order_endpoint_used: false,
    strategy_signal_compatible: false,
    persisted_market_rows: false,
    captured_at_ms: start + 60_000,
    cache_age_ms: 0,
    stale: false,
    last_error_code: '',
    ticker: {bid: '62030', ask: '62031', last: '62030.5', timestamp_ms: start + 60_000},
    candles: [
      {open_time_ms: start, open: 62000, high: 62050, low: 61990, close: 62030, volume: 10, confirmed: true, in_progress: false},
      {open_time_ms: start + 60_000, open: 62030, high: 62035, low: 62020, close: 62031, volume: 2, confirmed: false, in_progress: true},
    ],
  };
}

function canonicalSummaryFixture() {
  return {
    schema_version: 'btc_canonical_backtest_summary_v1',
    status: 'research_only',
    decision: 'historical_evidence_only_fail_closed',
    run_id: 'btc-canonical-run-001',
    strategy_identity: {
      strategy_id: 'long_short_donchian_top5',
      candidate_id: 'btc_ls_tf_stable_001',
      strategy_version: 'btc_long_short_top5_v1',
      params_hash: 'b'.repeat(64),
      signal_data_venue: 'OKX',
      signal_instrument: 'BTC-USDT-SWAP',
      execution_venue: 'OKX',
      execution_instrument: 'BTC-USDT-SWAP',
      timeframe: 'completed_1h_to_4h',
    },
    metrics: {
      initial_equity: 100_000,
      final_equity: 136_780.278391,
      net_pnl: 36_780.278391,
      total_return_pct: 36.780278,
      cagr_pct: 14.19219,
      max_drawdown_pct: -13.259622,
      annualized_sharpe: 1.174726,
      trade_count: 1,
      win_rate_pct: 100,
      profit_factor: 2.8,
      pnl_source: 'ledger_fills',
    },
    cost_components: {commission_cost: 12.4, fixed_slippage_cost: 8.2, market_impact_cost: 3.1, funding_cashflow: -1.7},
    ledger_binding: {pnl_source: 'ledger_fills', ledger_equity_consistent: true, fills_hash: 'c'.repeat(64), ledger_hash: 'd'.repeat(64)},
    artifact_freshness: {
      status: 'fail',
      code_commit: '8a00ca3fe7472eb71e447a6201666b034f8cc2fc',
      current_head: '63001d94600aede6bf7a131bc79b910f1121db52',
      current_head_match: false,
      evidence_pack_path: 'artifacts/btc_canonical_backtest_evidence/runs/btc-canonical-run-001/evidence_pack.json',
    },
    manifest: {path: 'artifacts/btc_canonical_backtest_evidence/runs/btc-canonical-run-001/run_manifest.json'},
    checks: {source_artifacts_present: true, source_no_lookahead_passed: true, source_data_local_and_network_free: true},
    promotion_readiness_blockers: [
      'btc_canonical_backtest:current_head_mismatch',
      'btc_canonical_backtest:depth_fill_mapping_not_verified',
      'btc_canonical_backtest:okx_native_cost_and_funding_validation_missing',
    ],
    safety: safetyFixture(),
  };
}

function canonicalReportFixture() {
  const start = Date.UTC(2026, 6, 9, 0, 0, 0) / 1000;
  const entry = Date.UTC(2026, 6, 10, 4, 0, 0) / 1000;
  const exit = Date.UTC(2026, 6, 11, 6, 0, 0) / 1000;
  const end = Date.UTC(2026, 6, 14, 0, 0, 0) / 1000;
  return {
    schema_version: 'btc_canonical_backtest_report_series_v1',
    status: 'complete_research_only',
    decision: 'canonical_report_read_only_no_paper_no_live',
    run_id: 'btc-canonical-run-001',
    source_run_id: 'btc-canonical-source-001',
    artifact_binding: {
      pointer_code_commit: '8a00ca3fe7472eb71e447a6201666b034f8cc2fc',
      manifest_sha256_verified: true,
      evidence_pack_sha256_verified: true,
      ledger_artifact_sha256_verified: true,
      fills_hash_verified: true,
      ledger_equity_consistent: true,
    },
    series: {
      equity: [{time: start, value: 100_000}, {time: exit, value: 100_250}, {time: end, value: 100_310}],
      drawdown: [{time: start, value: 0}, {time: exit, value: -1.2}, {time: end, value: -0.4}],
      monthly_returns: [{time: end, month: '2026-07', value: 0.31}],
      trades: [{trade_number: 1, direction: 'long', entry_time: entry, exit_time: exit, entry_price: 61_800, exit_price: 62_400, quantity: 0.5, gross_pnl: 300, commission: 48.3, funding_cashflow: -1.7, net_pnl: 250, cumulative_pnl: 250, return_pct: 0.25, duration_bars: 26}],
      costs: [{key: 'commission', label: '手续费', value: 12.4}, {key: 'slippage', label: '滑点', value: 8.2}, {key: 'impact', label: '冲击', value: 3.1}, {key: 'funding', label: 'Funding', value: 1.7}],
    },
    derived_metrics: {trade_count: 1, winning_trade_count: 1, losing_trade_count: 0, win_rate_pct: 100, profit_factor: 2.8, average_trade_pnl: 250, largest_winner: 250, largest_loser: 0, average_duration_bars: 26},
    source_counts: {ledger_snapshot_count: 6, fill_count: 2, closed_trade_count: 1, funding_event_count: 1},
    safety: safetyFixture(),
    blockers: ['btc_canonical_backtest:depth_fill_mapping_not_verified', 'btc_canonical_backtest:okx_native_cost_and_funding_validation_missing'],
  };
}

function safetyFixture() {
  return {
    paper_start_allowed: false,
    paper_queue_write_allowed: false,
    paper_allowed: false,
    paper_order_intake_allowed: false,
    broker_access_allowed: false,
    broker_or_order_allowed: false,
    oms_access_allowed: false,
    private_endpoint_used: false,
    order_endpoint_used: false,
    live_unlock_allowed: false,
    live_order_allowed: false,
    real_order_submitted: false,
  };
}
