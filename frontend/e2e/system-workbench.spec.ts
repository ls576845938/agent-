import {expect, test, type Page} from '@playwright/test';
import {readdirSync, readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import * as ts from 'typescript';

type RouteContract = {
  path: string;
  mode: string;
  symbol: string;
  pipeline: string[];
  crypto?: boolean;
  strategy?: boolean;
};

const routeContracts: RouteContract[] = [
  {
    path: '/architecture',
    mode: 'architecture',
    symbol: 'SOURCE ARCHITECTURE',
    pipeline: ['源码清单', '职责边界', '引用证据', '未读范围'],
  },
  {
    path: '/',
    mode: 'us-equity',
    symbol: 'US ETF RESEARCH',
    pipeline: ['Data', 'Signal', 'Portfolio', 'Risk', 'Backtest', 'Ledger', 'Report'],
  },
  {
    path: '/cn-equity',
    mode: 'cn-equity',
    symbol: 'A-SHARE EVIDENCE',
    pipeline: ['Data / PIT', 'Market Rules', 'Backtest', 'OMS / Ledger', 'Replay', 'QMT Contract'],
  },
  {
    path: '/research',
    mode: 'research',
    symbol: 'RESEARCH REGISTRY',
    pipeline: ['Evidence', 'Candidate', 'Validation', 'Review', 'Decision'],
  },
  {
    path: '/portfolio',
    mode: 'portfolio',
    symbol: 'PORTFOLIO & RISK',
    pipeline: ['Forecast', 'TargetPosition', 'Exposure', 'RiskDecision', 'Rebalance'],
  },
  {
    path: '/crypto',
    mode: 'crypto',
    symbol: 'BTCUSDT.P',
    pipeline: ['BTC-USDT-SWAP', 'Demo only', 'Live locked'],
    crypto: true,
  },
  {
    path: '/live',
    mode: 'execution',
    symbol: '执行安全',
    pipeline: ['风险批准意图', 'OMS', '成交', '账本', '对账'],
  },
  {
    path: '/strategies',
    mode: 'strategies',
    symbol: 'STRATEGY REGISTRY',
    pipeline: ['Strategy', 'Signal', 'Forecast', 'TargetPosition', 'Evidence'],
    strategy: true,
  },
];

const primaryNavigationPaths = [
  '/', '/cn-equity', '/research', '/portfolio', '/crypto', '/live',
  '/strategies', '/strategy-modules', '/architecture',
];

async function mockReadOnlyApis(page: Page) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());

    if (url.pathname === '/api/health') {
      await route.fulfill({
        json: {
          status: 'ok',
          service: 'quantstation',
          data_source_default: 'shared-etf26',
          fastapi_available: true,
          evidence_profile: 'research_readonly',
          read_only: true,
          controls_disabled: true,
        },
      });
      return;
    }

    if (url.pathname === '/api/strategies') {
      await route.fulfill({
        json: [
          {
            id: 'etf_rotation',
            display_name: 'ETF Rotation',
            description: 'Research-only rotation strategy',
            category: 'equity',
            default_weight: 1,
            default_params: {},
          },
        ],
      });
      return;
    }

    if (url.pathname === '/api/portfolio/status') {
      await route.fulfill({
        json: {
          status: 'ok',
          portfolio_count: 1,
          latest_portfolio: {
            portfolio_id: 'portfolio-etf26',
            date: '2026-07-17',
            strategy_weights: {etf_rotation: 1},
            total_capital: 100000,
            expected_return: 0.12,
            expected_volatility: 0.18,
            symbol_exposures: {SPY: 0.4, QQQ: 0.35, TLT: 0.25},
          },
        },
      });
      return;
    }

    if (url.pathname === '/api/us/paper/status') {
      await route.fulfill({
        json: {
          equity: 100000,
          cash: 100000,
          buying_power: 100000,
          positions: 0,
          kill_switch_triggered: false,
          kill_switch_reason: null,
          days_traded: 0,
          healthy: true,
          last_reconciliation_passed: null,
        },
      });
      return;
    }

    if (url.pathname === '/api/us/paper/daily-results') {
      await route.fulfill({json: []});
      return;
    }

    await route.fulfill({
      status: 503,
      json: {error: 'Intentional fail-closed contract fixture'},
    });
  });
}

async function expectTerminalRegions(page: Page, route: RouteContract) {
  await expect(page.getByLabel('主导航')).toBeVisible();

  if (route.strategy) {
    const workbench = page.getByTestId('strategy-workbench');
    await expect(workbench).toBeVisible();
    await expect(workbench.locator('.strategy-workbench-commandbar')).toBeVisible();
    await expect(workbench.getByLabel('策略目录', {exact: true})).toBeVisible();
    await expect(workbench.getByLabel('策略代码与本机研究草稿')).toBeVisible();
    await expect(workbench.getByLabel('回测绩效')).toBeVisible();
    await expect(workbench.getByLabel('策略证据与记录')).toBeVisible();
    await expect(workbench.getByRole('separator')).toHaveCount(3);
    const navBox = await page.locator('.app-sidebar').boundingBox();
    expect(navBox?.width).toBeLessThanOrEqual(190);
    return;
  }

  const toolbar = route.crypto
    ? page.locator('.crypto-tv-shell > .tv-global-toolbar')
    : page.getByTestId('terminal-global-toolbar');
  const rail = route.crypto ? page.locator('.crypto-tv-shell .tv-drawing-rail') : null;
  const canvas = route.crypto
    ? page.locator('.crypto-tv-shell .tv-chart-panel')
    : page.getByTestId('terminal-main-canvas');
  const console = route.crypto
    ? page.locator('.crypto-tv-shell .tv-demo-console')
    : page.getByTestId('terminal-inspector');
  const dock = route.crypto
    ? page.locator('.crypto-tv-shell .tv-bottom-dock')
    : page.getByTestId('terminal-bottom-dock');

  for (const region of [toolbar, canvas, dock]) {
    await expect(region).toBeVisible();
  }
  if (rail) await expect(rail).toBeVisible();
  else await expect(page.locator('.system-workbench .tv-drawing-rail')).toHaveCount(0);
  if (route.crypto) await expect(console).toBeVisible();
  else await expect(console).toHaveCount(0);

  const toolbarBox = await toolbar.boundingBox();
  expect(toolbarBox?.height).toBeGreaterThanOrEqual(42);
  expect(toolbarBox?.height).toBeLessThanOrEqual(50);

  const navBox = await page.locator('.app-sidebar').boundingBox();
  expect(navBox?.width).toBeLessThanOrEqual(190);
}

test.beforeEach(async ({page}) => {
  await mockReadOnlyApis(page);
});

test('frontend exposes a visible version fingerprint and runtime identity endpoint', async ({page, request}) => {
  const response = await page.goto('/', {waitUntil: 'domcontentloaded'});
  expect(response?.status()).toBe(200);

  const runtimeResponse = await request.get('/__frontend_identity');
  expect(runtimeResponse.ok()).toBe(true);
  const runtime = await runtimeResponse.json();
  expect(runtime.schema_version).toBe('quant_frontend_runtime_identity_v1');
  expect(runtime.release_id).toBe('quantstation-full-tradingview-main-v1');
  expect(runtime.fingerprint).toMatch(/^[0-9a-f]{64}$/);
  expect(runtime.source_head).toMatch(/^[0-9a-f]{40}$/);

  const fingerprint = page.getByTestId('frontend-version-fingerprint');
  await expect(fingerprint).toContainText(runtime.fingerprint.slice(0, 12));
  await expect(fingerprint).toHaveAttribute('data-canonical', String(runtime.canonical));
  expect(await page.locator('meta[name="quant-frontend-fingerprint"]').getAttribute('content')).toBe(runtime.fingerprint);
  expect(await page.locator('meta[name="quant-frontend-source-head"]').getAttribute('content')).toBe(runtime.source_head);
});

test('seven routes return 200 and expose the six-region terminal structure', async ({page}) => {
  test.setTimeout(180_000);

  for (const route of routeContracts) {
    const response = await page.goto(route.path, {waitUntil: 'domcontentloaded'});
    expect(response?.status(), `${route.path} must return 200`).toBe(200);
    await expectTerminalRegions(page, route);

    if (route.crypto) {
      await expect(page.locator('.app-shell')).toHaveClass(/crypto-app-shell/);
      await expect(page.getByTestId('crypto-workspace')).toBeVisible();
    } else if (!route.strategy) {
      await expect(page.locator('.app-shell')).toHaveClass(/non-crypto-workbench-shell/);
      await expect(page.locator('.system-workbench')).toHaveAttribute('data-terminal-mode', route.mode);
    }
  }
});

test('seven routes keep readable navigation and common controls without restoring wide US margins', async ({page}) => {
  test.setTimeout(180_000);
  for (const route of routeContracts) {
    await page.goto(route.path, {waitUntil: 'domcontentloaded'});
    await expectTerminalRegions(page, route);
    const primaryNav = await page.locator('.app-sidebar :is(a, button, strong, span)').evaluateAll((elements) => {
      const visible = elements.filter((element) => element.getBoundingClientRect().width > 0 && element.getBoundingClientRect().height > 0);
      return {count: visible.length, minimum: Math.min(...visible.map((element) => Number.parseFloat(getComputedStyle(element).fontSize)))};
    });
    expect(primaryNav.count, `${route.path} sidebar primary labels`).toBeGreaterThan(0);
    expect(primaryNav.minimum, `${route.path} sidebar primary font`).toBeGreaterThanOrEqual(16);

    const navigationLinks = page.getByRole('navigation', {name: '主导航'}).getByRole('link');
    await expect(navigationLinks).toHaveCount(primaryNavigationPaths.length);
    expect(await navigationLinks.evaluateAll(elements => elements.map(element => element.getAttribute('href'))))
      .toEqual(primaryNavigationPaths);
    expect(
      await navigationLinks.evaluateAll(elements => elements.every(element => Boolean(element.getAttribute('title')?.includes(' · ')))),
      `${route.path} sidebar links expose primary labels and accessible descriptions`,
    ).toBe(true);

    const commonControls = page.locator('.workspace-content :is(button, input, select, textarea, a[href], summary, [role="button"], [role="tab"], [role="treeitem"])');
    const controlMetrics = () => commonControls.evaluateAll((elements) => {
      const visible = elements.filter((element) => element.getBoundingClientRect().width > 0 && element.getBoundingClientRect().height > 0);
      return {count: visible.length, minimum: Math.min(...visible.map((element) => Number.parseFloat(getComputedStyle(element).fontSize)))};
    });
    await expect.poll(async () => (await controlMetrics()).count, {message: `${route.path} common readable controls`}).toBeGreaterThan(0);
    await expect.poll(async () => (await controlMetrics()).minimum, {message: `${route.path} common control font`}).toBeGreaterThanOrEqual(14);
  }

  await page.goto('/', {waitUntil: 'domcontentloaded'});
  const geometry = await page.locator('.workspace-content').evaluate((workspace) => {
    const dashboard = workspace.querySelector<HTMLElement>('.us-equity-workbench');
    if (!dashboard) return null;
    const workspaceBox = workspace.getBoundingClientRect();
    const dashboardBox = dashboard.getBoundingClientRect();
    return {workspaceWidth: workspaceBox.width, dashboardWidth: dashboardBox.width, leftGap: dashboardBox.left - workspaceBox.left};
  });
  expect(geometry).not.toBeNull();
  expect(Math.abs((geometry?.workspaceWidth ?? 0) - (geometry?.dashboardWidth ?? 0))).toBeLessThanOrEqual(2);
  expect(Math.abs(geometry?.leftGap ?? 999)).toBeLessThanOrEqual(1);
});

test('non-crypto evidence docks stay compact and flush to the viewport when first opened', async ({page}) => {
  test.setTimeout(180_000);
  await page.setViewportSize({width: 1440, height: 900});
  for (const path of ['/', '/cn-equity', '/research', '/portfolio', '/live', '/strategies', '/architecture']) {
    await page.goto(path, {waitUntil: 'domcontentloaded'});
    const dock = path === '/strategies'
      ? page.locator('.strategy-workbench-dock')
      : page.locator('.system-workbench .tv-bottom-dock');
    const collapsedDock = path === '/strategies'
      ? page.locator('.strategy-workbench-dock.is-collapsed')
      : page.locator('.system-workbench .tv-bottom-dock.dock-collapsed');
    await expect(collapsedDock).toHaveCount(1);
    const geometry = await collapsedDock.evaluate((element) => {
      const box = element.getBoundingClientRect();
      return {
        height: box.height,
        bottom: box.bottom,
        viewport: window.innerHeight,
        content: element.querySelector('.tv-dock-content, .strategy-workbench-dock-body'),
      };
    });
    expect(geometry.height, `${path} collapsed dock height`).toBeLessThanOrEqual(50);
    expect(geometry.bottom, `${path} collapsed dock must reach viewport bottom`).toBeGreaterThanOrEqual(geometry.viewport - 1);
    expect(geometry.content, `${path} collapsed dock must not mount content`).toBeNull();

    if (path === '/strategies') {
      await dock.getByRole('button', {name: '展开底部信息栏'}).click();
      await expect(page.locator('.strategy-workbench-dock-body')).toBeVisible();
      await page.getByRole('button', {name: '折叠底部信息栏'}).click();
      await expect(page.locator('.strategy-workbench-dock-body')).toHaveCount(0);
    } else {
      await dock.locator('.tv-bottom-tabs button').first().click();
      await expect(dock.locator('.tv-dock-content')).toBeVisible();
      await dock.locator('.tv-bottom-tabs button').first().click();
      await expect(dock.locator('.tv-dock-content')).toHaveCount(0);
    }
  }
});

test('each route keeps its own domain pipeline and does not leak another terminal identity', async ({page}) => {
  test.setTimeout(180_000);
  const symbols = routeContracts.filter(route => !route.strategy).map(route => route.symbol);

  for (const route of routeContracts) {
    await page.goto(route.path, {waitUntil: 'domcontentloaded'});
    if (route.strategy) {
      const workbench = page.getByTestId('strategy-workbench');
      await expect(workbench.locator('.strategy-workbench-commandbar')).toContainText('策略工作台');
      await expect(workbench.getByLabel('策略目录', {exact: true})).toContainText('策略 / 回测目录');
      await expect(workbench.getByLabel('策略代码与本机研究草稿')).toContainText('策略代码 / 本机研究草稿');
      await expect(workbench.getByLabel('回测绩效')).toContainText('分析 / 真实回测数据');
      continue;
    }
    const terminal = route.crypto
      ? page.getByTestId('crypto-workspace')
      : page.locator('.system-workbench');

    if (!route.crypto) await expect(terminal).toHaveAttribute('data-terminal-mode', route.mode);
    const identityRegion = route.crypto ? terminal.locator('.tv-global-toolbar') : page.getByTestId('terminal-global-toolbar');
    await expect(identityRegion).toContainText(route.symbol);
    if (route.crypto) {
      for (const step of route.pipeline) await expect(terminal).toContainText(step);
    } else {
      const pipelineButton = page.getByTestId('terminal-global-toolbar').locator('[aria-controls="terminal-pipeline-menu"]');
      await pipelineButton.click();
      const pipelineMenu = page.getByTestId('terminal-pipeline-menu');
      for (const step of route.pipeline) await expect(pipelineMenu).toContainText(step);
      await page.getByRole('button', {name: '关闭领域处理链菜单'}).click();
    }
    for (const otherSymbol of symbols.filter(symbol => symbol !== route.symbol)) {
      await expect(identityRegion).not.toContainText(otherSymbol);
    }
  }
});

test('all routes keep fail-closed and locked permissions visible', async ({page}) => {
  test.setTimeout(180_000);

  for (const route of routeContracts) {
    await page.goto(route.path, {waitUntil: 'domcontentloaded'});
    if (route.strategy) {
      const workbench = page.getByTestId('strategy-workbench');
      await expect(workbench.locator('.strategy-workbench-safety')).toHaveText('RESEARCH ONLY · ORDER / PAPER / LIVE = FALSE');
      const safetyTab = workbench.getByRole('tab', {name: '安全与证据'});
      await safetyTab.click();
      await expect(safetyTab).toHaveAttribute('aria-selected', 'true');
      await expect(workbench.locator('.strategy-workbench-dock-body')).toContainText('research-only · paper/live/order/private=false');
      continue;
    }
    const terminal = route.crypto
      ? page.getByTestId('crypto-workspace')
      : page.locator('.system-workbench');

    await expect(terminal).toContainText(/locked|LOCKED|fail-closed|实盘能力始终关闭|交易锁定|已锁定/);
    if (route.crypto) {
      await expect(terminal).toContainText('Live locked');
      await expect(terminal).toContainText('实盘能力始终关闭');
    } else {
      await expect(terminal.locator('.tv-chart-foot')).toContainText(route.path === '/live' ? '实盘订单：FALSE' : 'LIVE ORDER: FALSE');
    }
  }

  await page.goto('/cn-equity');
  await expect(page.getByTestId('cn-paper-lock')).toContainText('LOCKED');
  await expect(page.getByTestId('cn-live-lock')).toContainText('LOCKED');
  await expect(page.getByTestId('cn-fail-closed-banner')).toContainText('FAIL-CLOSED');

  await page.goto('/portfolio');
  const portfolioWorkspace = page.getByTestId('workspace-portfolio');
  await expect(portfolioWorkspace).not.toContainText('PORTFOLIO READY');
  await expect(portfolioWorkspace).not.toContainText('STATE LOADED');
  await expect(portfolioWorkspace).toContainText('组合运行读取失败');
  await expect(portfolioWorkspace).toContainText('不能判断是否存在版本');
  await expect(portfolioWorkspace).toContainText('失败不代表零记录');
  const portfolioFacts = portfolioWorkspace.locator('.research-data-facts > div');
  await expect(portfolioFacts.filter({hasText: '可读取组合版本'}).locator('strong')).toHaveText('未知');
  await expect(portfolioFacts.filter({hasText: '执行权限'}).locator('strong')).toHaveText('未授予');
  const legacySnapshot = portfolioWorkspace.locator('details.research-intro-card').filter({hasText: '旧目标快照（独立来源，不作为当前组合结果）'});
  await legacySnapshot.locator('summary').click();
  await expect(legacySnapshot).toContainText('快照编号：portfolio-etf26');
  await expect(legacySnapshot).toContainText('再平衡尚未接入受控提交；当前快照只用于查看。');
  await expect(legacySnapshot.getByRole('button', {name: /再平衡/})).toHaveCount(0);

  await page.goto('/live');
  const executionTerminal = page.locator('.system-workbench');
  await expect(executionTerminal).toContainText('IBKR 运行时状态不可用');
  await expect(executionTerminal).toContainText('实盘就绪');
  await expect(executionTerminal).toContainText('只读消费 IBKR runtime-status API');
  await expect(executionTerminal).not.toContainText('NEW ORDERS BLOCKED');
  await expect(executionTerminal).not.toContainText('RUNTIME STATUS UNAVAILABLE');
  await expect(executionTerminal).toContainText('Paper / Live 已锁定');
  await expect(executionTerminal).toContainText('私有 / 订单');
  await expect(executionTerminal.locator('.tv-chart-foot')).toContainText('实盘订单：FALSE');
});

test('terminal dock, US workflow tabs, portfolio tabs and strategy filters remain interactive', async ({page}) => {
  test.setTimeout(120_000);
  await page.goto('/');

  await expect(page.getByTestId('terminal-inspector')).toHaveCount(0);
  await expect(page.getByTestId('terminal-bottom-dock').locator('.tv-dock-content')).toHaveCount(0);

  await page.locator('.tv-global-toolbar').getByRole('button', {name: '证据', exact: true}).click();
  await expect(page.getByTestId('terminal-inspector')).toContainText('证据链');
  await page.getByRole('button', {name: '层级合同'}).click();
  await expect(page.getByRole('button', {name: '层级合同'})).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByTestId('terminal-bottom-dock')).toContainText('TargetPosition');
  await page.getByRole('button', {name: '层级合同'}).click();
  await expect(page.getByRole('button', {name: '层级合同'})).toHaveAttribute('aria-expanded', 'false');
  await expect(page.getByTestId('terminal-bottom-dock').locator('.tv-dock-content')).toHaveCount(0);

  const usTabs = page.locator('.workbench-tabs .workbench-tab');
  await expect(usTabs).toHaveCount(5);
  await usTabs.nth(1).click();
  await expect(usTabs.nth(1)).toHaveClass(/active/);

  await page.goto('/portfolio');
  const portfolioTabs = page.getByRole('tablist', {name: '投资组合工作流'});
  const portfolioLabels = ['来源与版本', '权重优化', '组合模拟', '风险与证据'];
  await expect(portfolioTabs.getByRole('tab')).toHaveCount(portfolioLabels.length);
  for (const label of portfolioLabels) {
    const tab = portfolioTabs.getByRole('tab', {name: label});
    await tab.click();
    await expect(tab).toHaveAttribute('aria-selected', 'true');
  }

  await page.goto('/strategies');
  const strategyWorkbench = page.getByTestId('strategy-workbench');
  const search = page.getByTestId('strategy-workbench-tree-search');
  await search.fill('no-match');
  await expect(strategyWorkbench.getByRole('treeitem')).toHaveCount(0);
  await expect(strategyWorkbench).toContainText('没有匹配的策略目录项');
  await search.fill('etf_rotation');
  const etf = page.getByTestId('strategy-tree-registry-etf_rotation');
  await etf.click();
  await expect(etf).toHaveAttribute('aria-selected', 'true');
  await expect(strategyWorkbench.getByLabel('策略代码与本机研究草稿')).toContainText('registry:etf_rotation');
});

test('safe interaction matrix gives visible accessible feedback on all seven routes', async ({page}) => {
  test.setTimeout(300_000);
  const unsafeRequests: string[] = [];
  page.on('request', request => {
    if (request.url().includes('/api/') && !['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
      unsafeRequests.push(`${request.method()} ${request.url()}`);
    }
  });

  for (const route of routeContracts) {
    await page.goto(route.path, {waitUntil: 'domcontentloaded'});

    if (route.strategy) {
      const workbench = page.getByTestId('strategy-workbench');
      const search = page.getByTestId('strategy-workbench-tree-search');
      await search.fill('etf_rotation');
      const etf = page.getByTestId('strategy-tree-registry-etf_rotation');
      await etf.click();
      await expect(etf).toHaveAttribute('aria-selected', 'true');
      const logsTab = workbench.getByRole('tab', {name: '日志'});
      await logsTab.click();
      await expect(page.getByTestId('strategy-workbench-log-unavailable')).toContainText('不能冒充日志');
      const safetyTab = workbench.getByRole('tab', {name: '安全与证据'});
      await safetyTab.click();
      await expect(safetyTab).toHaveAttribute('aria-selected', 'true');
      const focusCode = workbench.getByRole('button', {name: '聚焦策略代码 / 本机研究草稿'});
      await focusCode.click();
      await expect(workbench).toHaveClass(/is-focused-code/);
      await workbench.getByRole('button', {name: '退出策略代码 / 本机研究草稿聚焦'}).click();
      await expect(workbench).not.toHaveClass(/is-focused-code/);
      continue;
    }

    if (route.crypto) {
      const workspace = page.getByTestId('crypto-workspace');
      const symbolButton = workspace.locator('.tv-symbol-switcher');
      await symbolButton.click();
      await expect(symbolButton).toHaveClass(/active/);
      await expect(page.getByTestId('btc-symbol-menu')).toBeVisible();
      await page.getByTestId('btc-symbol-menu').locator('.tv-popover-head button').click();
      await expect(page.getByTestId('btc-symbol-menu')).toHaveCount(0);

      const auditTab = workspace.locator('.tv-bottom-tabs button').last();
      await auditTab.click();
      await expect(auditTab).toHaveClass(/active/);
      await expect(workspace).toContainText('Live locked');
      continue;
    }

    const terminal = page.locator('.system-workbench');
    const toolbar = page.getByTestId('terminal-global-toolbar');
    const domainButton = toolbar.locator('.tv-symbol-switcher');
    await domainButton.click();
    await expect(domainButton).toHaveAttribute('aria-expanded', 'true');
    await expect(page.getByTestId('terminal-domain-menu')).toBeVisible();
    await page.getByRole('button', {name: '关闭工作域菜单'}).click();
    await expect(domainButton).toHaveAttribute('aria-expanded', 'false');

    const pipelineButton = toolbar.locator('[aria-controls="terminal-pipeline-menu"]');
    await pipelineButton.click();
    await expect(pipelineButton).toHaveAttribute('aria-expanded', 'true');
    await expect(page.getByTestId('terminal-pipeline-menu')).toContainText(route.pipeline[0]);
    await page.getByRole('button', {name: '关闭领域处理链菜单'}).click();

    const consoleButton = toolbar.getByRole('button', {name: '控制台'});
    await expect(consoleButton).toHaveAttribute('aria-expanded', 'false');
    await expect(page.getByTestId('terminal-inspector')).toHaveCount(0);
    await consoleButton.click();
    await expect(consoleButton).toHaveAttribute('aria-expanded', 'true');
    await expect(page.getByTestId('terminal-inspector')).toBeVisible();
    await consoleButton.click();
    await expect(consoleButton).toHaveAttribute('aria-pressed', 'false');
    await expect(page.getByTestId('terminal-inspector')).toHaveCount(0);

    const evidenceButton = toolbar.getByRole('button', {name: '证据', exact: true});
    await evidenceButton.click();
    await expect(evidenceButton).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByTestId('terminal-inspector')).toBeVisible();
    await expect(page.getByTestId('terminal-inspector')).toContainText('证据链');
    await expect(terminal.locator('.terminal-interaction-status')).toContainText('证据链检查器已打开');

    const chartLayout = terminal.locator('.system-tv-layout-switcher').getByRole('button', {name: '画布'});
    await chartLayout.click();
    await expect(chartLayout).toHaveAttribute('aria-pressed', 'true');
    await expect(terminal).toHaveClass(/layout-chart/);
    await expect(terminal.locator('.terminal-interaction-status')).toContainText('画布布局：画布聚焦');

    const splitLayout = terminal.locator('.system-tv-layout-switcher').getByRole('button', {name: '分屏'});
    await splitLayout.click();
    await expect(splitLayout).toHaveAttribute('aria-pressed', 'true');
    await expect(terminal).toHaveClass(/layout-split/);

    const contractsDock = terminal.getByRole('button', {name: '层级合同', exact: true});
    await contractsDock.click();
    await expect(contractsDock).toHaveAttribute('aria-pressed', 'true');
    await expect(terminal.locator('.terminal-interaction-status')).toContainText('证据坞：层级合同');

    const workflowTabs = terminal.locator('.workbench-tabs .workbench-tab');
    if (await workflowTabs.count() > 1) {
      const targetTab = workflowTabs.nth(1);
      const targetLabel = (await targetTab.locator('.workbench-tab-copy strong').textContent())?.trim() ?? '';
      await targetTab.click();
      await expect(targetTab).toHaveAttribute('aria-pressed', 'true');
      await expect(terminal.locator('.workbench-tab-feedback')).toContainText(`当前视图：${targetLabel}`);
    }
  }

  expect(unsafeRequests, 'safe interaction matrix must not issue write requests').toEqual([]);
});

test('new experiment navigates to and focuses the existing research form without submitting', async ({page}) => {
  await page.goto('/research', {waitUntil: 'domcontentloaded'});

  const workspace = page.getByRole('tablist', {name: '研究工作区'});
  const experimentStage = workspace.getByRole('tab', {name: '手动实验'});
  await experimentStage.click();
  const experimentViews = page.getByRole('tablist', {name: '手动实验'});
  const recordsTab = experimentViews.getByRole('tab', {name: '实验记录与报告'});
  const cycleTab = experimentViews.getByRole('tab', {name: '新建实验'});
  await recordsTab.click();
  await expect(recordsTab).toHaveAttribute('aria-selected', 'true');

  await page.getByRole('button', {name: '新建实验'}).click();
  await expect(experimentStage).toHaveAttribute('aria-selected', 'true');
  await expect(cycleTab).toHaveAttribute('aria-selected', 'true');
  await expect(recordsTab).toHaveAttribute('aria-selected', 'false');
  await expect(page.locator('#research-experiment-form')).toBeVisible();
  await expect(page.getByLabel('策略 ID')).toBeFocused();
  await expect(page.locator('.research-feedback[role="status"]')).toContainText('尚未创建或提交实验');
});

test('all enabled literal buttons in frontend source have a handler or submit semantics', () => {
  const sourceRoot = resolve(process.cwd(), 'src');
  const sourceFiles: string[] = [];
  const collectSourceFiles = (directory: string) => {
    for (const entry of readdirSync(directory, {withFileTypes: true})) {
      const path = resolve(directory, entry.name);
      if (entry.isDirectory()) collectSourceFiles(path);
      if (entry.isFile() && path.endsWith('.tsx')) sourceFiles.push(path);
    }
  };
  collectSourceFiles(sourceRoot);

  const violations: string[] = [];
  let buttonCount = 0;

  for (const sourceFile of sourceFiles) {
    const source = readFileSync(resolve(process.cwd(), sourceFile), 'utf8');
    const sourceNode = ts.createSourceFile(sourceFile, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    const visit = (node: ts.Node) => {
      if ((ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) && node.tagName.getText(sourceNode) === 'button') {
        buttonCount += 1;
        const attributes = node.attributes.properties.filter(ts.isJsxAttribute);
        const attribute = (name: string) => attributes.find(item => item.name.getText(sourceNode) === name);
        const hasHandler = Boolean(attribute('onClick'));
        const typeAttribute = attribute('type');
        const typeValue = typeAttribute?.initializer && ts.isStringLiteral(typeAttribute.initializer)
          ? typeAttribute.initializer.text
          : typeAttribute?.initializer && ts.isJsxExpression(typeAttribute.initializer)
            && typeAttribute.initializer.expression && ts.isStringLiteral(typeAttribute.initializer.expression)
            ? typeAttribute.initializer.expression.text
            : '';
        const disabledAttribute = attribute('disabled');
        const staticallyDisabled = Boolean(
          disabledAttribute
          && (
            !disabledAttribute.initializer
            || (
              ts.isJsxExpression(disabledAttribute.initializer)
              && disabledAttribute.initializer.expression?.kind === ts.SyntaxKind.TrueKeyword
            )
          ),
        );
        if (!hasHandler && typeValue !== 'submit' && !staticallyDisabled) {
          const position = sourceNode.getLineAndCharacterOfPosition(node.getStart(sourceNode));
          violations.push(`${sourceFile}:${position.line + 1}`);
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(sourceNode);
  }

  expect(buttonCount, 'expected to inspect the complete current frontend button inventory').toBeGreaterThanOrEqual(175);
  expect(violations).toEqual([]);
});

test('all seven terminal routes remain contained at desktop and mobile widths', async ({page}) => {
  test.setTimeout(240_000);

  for (const viewport of [
    {width: 960, height: 900},
    {width: 390, height: 844},
  ]) {
    await page.setViewportSize(viewport);
    for (const route of routeContracts) {
      await page.goto(route.path, {waitUntil: 'domcontentloaded'});
      const hasPageOverflow = await page.evaluate(
        () => document.documentElement.scrollWidth > window.innerWidth + 1,
      );
      expect(hasPageOverflow, `${route.path} overflows at ${viewport.width}px`).toBe(false);
    }
  }
});

test('representative routes keep the readability floor and desktop containment', async ({page}) => {
  test.setTimeout(180_000);

  for (const viewport of [
    {width: 1920, height: 1080},
    {width: 1366, height: 900},
  ]) {
    await page.setViewportSize(viewport);
    for (const path of ['/', '/crypto', '/strategies']) {
      await page.goto(path, {waitUntil: 'domcontentloaded'});
      const result = await page.evaluate(() => {
        const visible = (element: Element) => {
          const style = getComputedStyle(element);
          const rect = element.getBoundingClientRect();
          return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
        };
        const minimum = (selector: string) => Math.min(
          ...Array.from(document.querySelectorAll(`.workspace-content :is(${selector})`))
            .filter((element) => visible(element) && !element.closest('[aria-hidden="true"]'))
            .map((element) => Number.parseFloat(getComputedStyle(element).fontSize)),
        );
        return {
          secondary: minimum('small, .eyebrow, .text-muted, .status-chip'),
          content: minimum('p:not(.eyebrow):not(.text-muted), li, label, button, input, select, textarea, td, th'),
          titles: minimum('h1, h2, h3, h4'),
          brand: Math.min(...Array.from(document.querySelectorAll('.brand-block h1')).filter(visible)
            .map((element) => Number.parseFloat(getComputedStyle(element).fontSize))),
          overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
        };
      });
      expect(result.secondary, `${path} secondary text at ${viewport.width}px`).toBeGreaterThanOrEqual(12);
      expect(result.content, `${path} content text at ${viewport.width}px`).toBeGreaterThanOrEqual(14);
      expect(result.titles, `${path} title text at ${viewport.width}px`).toBeGreaterThanOrEqual(16);
      expect(result.brand, `${path} brand text at ${viewport.width}px`).toBeGreaterThanOrEqual(12);
      expect(result.overflow, `${path} overflows at ${viewport.width}px`).toBe(false);
    }
  }
});
