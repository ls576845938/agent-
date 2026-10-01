import {expect, test, type Page} from '@playwright/test';

const HEAD = '04e5647dbddd62a0e2b1676096b20ee8396a647e';
const API_PATH = '/api/research/cn-equity/domain-read-model';
const HARNESS_PATH = '/src/workspaces/cn/e2e-harness.html';

const SAFETY = {
  broker_access_allowed: false,
  live_allowed: false,
  order_endpoint_allowed: false,
  paper_allowed: false,
  paper_queue_allowed: false,
  private_endpoint_allowed: false,
  promotion_allowed: false,
  qmt_sdk_allowed: false,
  real_order_allowed: false,
  withdraw_allowed: false,
};

const LAYER_IDS = [
  'data',
  'market_rules',
  'backtest',
  'oms',
  'replay',
  'qmt',
] as const;

function layer(layerId: (typeof LAYER_IDS)[number], blocker: string) {
  return {
    status: 'blocked',
    readiness_class: 'quality_checked',
    source_event: `integrated-cn-v3-${layerId}-goal9-batch-01`,
    source_path: `.agent/handoffs/cn/${layerId}.json`,
    source_sha256: layerId.charCodeAt(0).toString(16).padStart(2, '0').repeat(32),
    deliverable_commit: layerId.charCodeAt(0).toString(16).slice(-1).repeat(40),
    gate_impact: 'blocks_gate',
    promotion_eligible: false,
    blockers: [blocker],
    classifications: [`${layerId}_fixture_or_external_evidence_only`],
  };
}

function currentHeadPayload() {
  const blockerByLayer = {
    data: 'cn_dataready_current_main_manifest_missing',
    market_rules: 'board_lot_rule_missing',
    backtest: 'real_data_backtest_evidence_not_produced',
    oms: 'cn_oms_offline_fixture_only',
    replay: 'cn_replay_injected_history_only',
    qmt: 'cn_broker_capability_unproven',
  } as const;
  const blockers = LAYER_IDS.map(layerId => ({
    code: blockerByLayer[layerId],
    owner: layerId === 'data' || layerId === 'market_rules'
      ? 'data_steward'
      : 'a_share_developer',
    next_action: `resolve_${blockerByLayer[layerId]}`,
    layer: layerId,
    detail: `${layerId} evidence remains externally blocked and fail-closed.`,
  }));
  return {
    schema_version: 'cn_equity_operator_read_model_v1',
    domain: 'cn_equity',
    owner: 'a_share_developer',
    code_commit: HEAD,
    source_head: HEAD,
    generated_at_utc: '2026-07-24T15:00:00Z',
    input_sha256: 'a'.repeat(64),
    generation_hash: 'b'.repeat(64),
    data_version: 'cn-current-main-blocked-v1',
    status: 'blocked',
    decision: 'fail_closed',
    readiness_class: 'quality_checked',
    promotion_evidence_ready: false,
    paper_ready: false,
    live_ready: false,
    current_stage: 'blocked_read_only',
    layers: Object.fromEntries(
      LAYER_IDS.map(layerId => [
        layerId,
        layer(layerId, blockerByLayer[layerId]),
      ]),
    ),
    evidence: [],
    blockers,
    blocker_count: blockers.length,
    gate: {
      decision: 'blocked_fail_closed',
      owner: 'data_steward',
      next_action: 'publish_current_main_dataready_and_formal_market_rules',
      first_blocker: 'cn_dataready_current_main_manifest_missing',
    },
    safety: SAFETY,
    api_contract: {
      method: 'GET',
      path: API_PATH,
      cache_control: 'no-store',
      read_only: true,
      side_effects: false,
      builder_triggered: false,
      order_path_registered: false,
    },
  };
}

type CapturedRequest = {
  method: string;
  pathname: string;
  cacheControl: string | undefined;
};

async function routeCN(
  page: Page,
  captured: CapturedRequest[],
  options: {
    status?: number;
    payload?: unknown;
    omitNoStoreHeader?: boolean;
  } = {},
) {
  await page.route('**/api/**', async route => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    captured.push({
      method: request.method(),
      pathname,
      cacheControl: request.headers()['cache-control'],
    });
    if (pathname !== API_PATH || request.method() !== 'GET') {
      await route.fulfill({status: 418, json: {detail: 'unexpected_request'}});
      return;
    }
    await route.fulfill({
      status: options.status ?? 200,
      headers: options.omitNoStoreHeader
        ? {}
        : {'Cache-Control': 'no-store'},
      json: options.payload ?? currentHeadPayload(),
    });
  });
}

test('CN workspace exposes current-HEAD blockers with every trading capability locked', async ({page}) => {
  const captured: CapturedRequest[] = [];
  await routeCN(page, captured);
  await page.goto(HARNESS_PATH);

  await expect(page.getByRole('heading', {name: 'A 股证据工作台'})).toBeVisible();
  await expect(page.getByTestId('cn-fail-closed-banner')).toContainText(
    'FAIL-CLOSED · READ ONLY',
  );
  await expect(page.getByText(HEAD.slice(0, 12), {exact: false}).first()).toBeVisible();
  await expect(page.getByText('CURRENT_HEAD', {exact: true})).toBeVisible();
  await expect(page.getByTestId('cn-paper-lock')).toContainText('LOCKED');
  await expect(page.getByTestId('cn-live-lock')).toContainText('LOCKED');

  for (const layerId of LAYER_IDS) {
    await expect(page.getByTestId(`cn-layer-${layerId}`)).toContainText(
      '阻塞',
    );
  }
  await expect(page.getByText('board_lot_rule_missing').first()).toBeVisible();
  await expect(
    page.getByText('cn_broker_capability_unproven').first(),
  ).toBeVisible();

  const safetyFlags = page.getByTestId('cn-safety-flag');
  await expect(safetyFlags).toHaveCount(13);
  for (let index = 0; index < 13; index += 1) {
    await expect(safetyFlags.nth(index)).toContainText('false');
  }
  await expect(page.getByText(/PROMOTION READY/i)).toHaveCount(0);

  expect(captured.length).toBeGreaterThan(0);
  expect(captured.every(item => item.method === 'GET')).toBe(true);
  expect(captured.every(item => item.pathname === API_PATH)).toBe(true);
  expect(captured.every(item => item.cacheControl === 'no-store')).toBe(true);
  if (process.env.CN_VISUAL_DESKTOP_PATH) {
    await page.screenshot({
      path: process.env.CN_VISUAL_DESKTOP_PATH,
      fullPage: true,
    });
  }
});

test('App registers the CN route as GET-only and fail-closed', async ({page}) => {
  const captured: CapturedRequest[] = [];
  await page.route('**/api/**', async route => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    captured.push({
      method: request.method(),
      pathname,
      cacheControl: request.headers()['cache-control'],
    });
    if (pathname === API_PATH) {
      await route.fulfill({
        headers: {'Cache-Control': 'no-store'},
        json: currentHeadPayload(),
      });
      return;
    }
    if (pathname === '/api/health') {
      await route.fulfill({
        json: {
          status: 'ok',
          service: 'test',
          data_source_default: 'none',
          fastapi_available: true,
        },
      });
      return;
    }
    if (pathname === '/api/strategies') {
      await route.fulfill({json: []});
      return;
    }
    await route.fulfill({status: 418, json: {detail: 'unexpected_request'}});
  });

  await page.goto('/cn-equity');

  await expect(page.getByRole('heading', {name: 'A 股证据工作台'})).toBeVisible();
  await expect(page.getByRole('link', {name: /A 股量化/})).toHaveClass(/active/);
  await expect(page.getByTestId('cn-paper-lock')).toContainText('LOCKED');
  await expect(page.getByTestId('cn-live-lock')).toContainText('LOCKED');
  expect(captured.some(item => item.pathname === API_PATH)).toBe(true);
  expect(captured.every(item => item.method === 'GET')).toBe(true);
});

test('CN workspace maps an unavailable API to BACKEND_UNAVAILABLE and remains fail-closed', async ({page}) => {
  const captured: CapturedRequest[] = [];
  await routeCN(page, captured, {
    status: 503,
    payload: {
      schema_version: 'cn_equity_operator_read_model_error_v1',
      domain: 'cn_equity',
      status: 'blocked',
      decision: 'fail_closed',
      readiness_class: 'quality_checked',
      blockers: [{
        code: 'cn_read_model_metadata_missing',
        owner: 'a_share_developer',
        next_action: 'materialize_current_head',
      }],
      safety: SAFETY,
    },
  });
  await page.goto(HARNESS_PATH);

  await expect(page.getByTestId('cn-fail-closed-banner')).toContainText(
    'BACKEND_UNAVAILABLE · FAIL-CLOSED',
  );
  await expect(page.getByTestId('cn-blocker-list')).toContainText(
    'cn_read_model_metadata_missing',
  );
  await expect(page.getByTestId('cn-paper-lock')).toContainText('LOCKED');
  await expect(page.getByTestId('cn-live-lock')).toContainText('LOCKED');
  await expect(page.getByTestId('cn-safety-flag')).toHaveCount(13);
  expect(captured.every(item => item.method === 'GET')).toBe(true);
});

test('CN workspace rejects a true safety flag and does not echo unsafe state', async ({page}) => {
  const unsafe = currentHeadPayload();
  unsafe.safety = {...SAFETY, paper_allowed: true};
  await routeCN(page, [], {payload: unsafe});
  await page.goto(HARNESS_PATH);

  await expect(page.getByTestId('cn-fail-closed-banner')).toContainText(
    'CONTRACT_INVALID · FAIL-CLOSED',
  );
  await expect(page.getByTestId('cn-blocker-list')).toContainText(
    'CONTRACT_INVALID',
  );
  const safetyFlags = page.getByTestId('cn-safety-flag');
  await expect(safetyFlags).toHaveCount(13);
  await expect(safetyFlags.filter({hasText: 'true'})).toHaveCount(0);
});

test('CN workspace rejects a cacheable API response', async ({page}) => {
  await routeCN(page, [], {omitNoStoreHeader: true});
  await page.goto(HARNESS_PATH);

  await expect(page.getByTestId('cn-fail-closed-banner')).toContainText(
    'CONTRACT_INVALID · FAIL-CLOSED',
  );
  await expect(page.getByTestId('cn-blocker-list')).toContainText(
    'CN_API_NO_STORE_HEADER_MISSING',
  );
  await expect(page.getByTestId('cn-paper-lock')).toContainText('LOCKED');
  await expect(page.getByTestId('cn-live-lock')).toContainText('LOCKED');
});

test('CN blocked workspace has no horizontal overflow on desktop or mobile', async ({page}) => {
  await routeCN(page, []);
  for (const viewport of [
    {width: 1366, height: 768},
    {width: 390, height: 844},
  ]) {
    await page.setViewportSize(viewport);
    await page.goto(HARNESS_PATH);
    await expect(page.getByRole('heading', {name: 'A 股证据工作台'})).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    );
    expect(overflow).toBe(false);
    if (viewport.width === 390 && process.env.CN_VISUAL_MOBILE_PATH) {
      await page.screenshot({
        path: process.env.CN_VISUAL_MOBILE_PATH,
        fullPage: true,
      });
    }
  }
});
