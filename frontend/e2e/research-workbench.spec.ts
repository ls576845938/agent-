import { test, expect, type Page } from '@playwright/test';

// UI contract fixtures only: these tests do not prove training, backtest or promotion success.
async function mockResearch(page: Page, failed = false) {
  const writes: string[] = [];
  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() !== 'GET') {
      writes.push(path);
      await route.fulfill({status: 403, json: {detail: 'UI QA forbids writes'}});
      return;
    }
    if (failed && path === '/api/research/experiments') {
      await route.fulfill({status: 503, json: {detail: 'fixture unavailable'}});
    } else if (path === '/api/health') {
      await route.fulfill({json: {status: 'ok', service: 'quantstation'}});
    } else if (path === '/api/integrations/qlib/runs') {
      await route.fulfill({json: {runs: [], dependencies: {qlib: false, lightgbm: false}}});
    } else if (path === '/api/integrations/portfolio/runs') {
      await route.fulfill({json: {runs: [], dependencies: {pypfopt: false}}});
    } else if (path === '/api/system/overview') {
      await route.fulfill({json: {stage: 'RESEARCH_ONLY', registry: {integrity: 'PASS'}, paper_enabled: false, live_enabled: false}});
    } else if (/experiments|candidates|features|factors|strategy-manifests|pending|tasks$|strategies$/.test(path)) {
      await route.fulfill({json: []});
    } else {
      await route.fulfill({json: {}});
    }
  });
  return writes;
}

test('saved previous version: four stages expose all research views without automatic writes', async ({page}) => {
  const writes = await mockResearch(page);
  await page.goto('/research?layout=previous');
  const stages = page.getByRole('tablist', {name: '研究阶段'});
  await expect(stages.getByRole('tab')).toHaveCount(4);
  await expect(page.getByRole('tabpanel')).toContainText('先确认数据，再开始实验');
  await expect(page.getByRole('region', {name: '研究状态总览'})).toContainText('独立门禁 · 未解锁');
  for (const [stage, views] of [
    ['数据与特征', ['数据准备', '因子评估与快照']],
    ['实验与回测', ['新建实验', '实验记录与报告']],
    ['候选与证据', ['候选证据', '数据与门禁检查']],
    ['组合与复核', ['Qlib 与组合工具', '组合模拟与人工复核']],
  ] as const) {
    await stages.getByRole('tab', {name: new RegExp(stage)}).click();
    for (const view of views) {
      const tab = page.getByRole('tab', {name: view, exact: true});
      await tab.click();
      await expect(tab).toHaveAttribute('aria-selected', 'true');
      await expect(page.getByRole('tabpanel')).toBeVisible();
    }
  }
  expect(writes).toEqual([]);
});

test('saved previous version: failed reads remain unknown, not an empty successful experiment list', async ({page}) => {
  await mockResearch(page, true);
  await page.goto('/research?layout=previous');
  const overview = page.getByRole('region', {name: '研究状态总览'});
  await expect(overview).toContainText('部分状态读取失败');
  await expect(overview.locator('.research-health')).toContainText('未知');
  await expect(overview).not.toContainText('0 / 0 完成');
});

test('saved previous version: shared context follows stage changes and rejects invalid dates', async ({page}) => {
  const writes = await mockResearch(page);
  await page.goto('/research?layout=previous');
  await page.getByRole('button', {name: '编辑上下文'}).click();
  await page.getByLabel('研究标的', {exact:true}).fill('SPY,QQQ');
  await page.getByLabel('研究开始', {exact:true}).fill('2025-01-01');
  await page.getByLabel('研究结束', {exact:true}).fill('2024-12-31');
  await page.getByRole('tab', {name: /实验与回测/}).click();
  await expect(page.getByLabel('策略 ID', {exact:true})).toHaveValue('trend_momentum');
  await expect(page.getByRole('textbox', {name: /^params JSON/})).toHaveValue('{"lookback_bars": 20}');
  await expect(page.getByRole('button', {name: '运行研究闭环', exact:true})).toBeDisabled();
  await page.getByLabel('研究结束', {exact:true}).fill('2025-12-31');
  await expect(page.getByRole('button', {name: '运行研究闭环', exact:true})).toBeEnabled();
  await page.getByRole('tab', {name: /数据与特征/}).click();
  await page.getByRole('tab', {name: '因子评估与快照', exact:true}).click();
  await expect(page.getByRole('tabpanel')).toContainText('SPY,QQQ');
  await page.getByLabel('研究标的', {exact:true}).fill('');
  await expect(page.getByRole('button', {name: '计算预览', exact:true})).toBeDisabled();
  await expect(page.getByRole('button', {name: '构建特征快照', exact:true})).toBeDisabled();
  expect(writes).toEqual([]);
});

test('saved previous version: keyboard navigation, dry-run distinction and reversible legacy layout', async ({page}) => {
  // Both rollback links load a complete document through the canonical main guard.
  test.setTimeout(60000);
  const writes = await mockResearch(page);
  await page.goto('/research?layout=previous');
  const first = page.getByRole('tablist', {name: '研究阶段'}).getByRole('tab').first();
  await first.focus();
  await page.keyboard.press('End');
  await expect(page.getByRole('tab', {name: /组合与复核/})).toBeFocused();
  await expect(page.getByLabel('仅检查配置（dry-run，不训练模型、不算运行成功）')).toBeChecked();
  await page.getByRole('link', {name: '切回原版'}).click();
  await expect(page).toHaveURL(/layout=legacy/);
  await expect(page.getByTestId('research-content')).toBeVisible({timeout:15000});
  await expect(page.getByTestId('module-state-qlib')).toBeVisible({timeout:15000});
  await page.getByRole('link', {name: '返回新版研究台'}).click();
  await expect(page.getByRole('tablist', {name: '研究工作区'})).toBeVisible({timeout:15000});
  expect(writes).toEqual([]);
});

test('saved previous version: integration refresh failure remains unknown in dependency and run panels', async ({page}) => {
  const writes = await mockResearch(page);
  await page.goto('/research?layout=previous');
  await page.getByRole('tab', {name: /组合与复核/}).click();
  const dependencies = page.getByTestId('research-dependencies');
  await expect(dependencies).toContainText('缺失');
  await page.route('**/api/integrations/**/runs**', route => route.fulfill({status: 503, json: {detail: 'fixture unavailable'}}));
  await page.getByRole('button', {name: '刷新集成', exact:true}).click();
  await expect(page.getByRole('region', {name: '研究状态总览'})).toContainText('部分状态读取失败');
  await expect(dependencies).toContainText('未知');
  await expect(dependencies).not.toContainText('缺失');
  await expect(page.getByRole('tabpanel')).toContainText('Qlib 状态读取失败，运行记录未知。');
  await expect(page.getByRole('tabpanel')).toContainText('组合工具读取失败，运行记录未知。');
  expect(writes).toEqual([]);
});

test('saved previous version: Qlib shows the actual root and blocks actions until the changed root is read', async ({page}) => {
  const writes = await mockResearch(page);
  await page.goto('/research?layout=previous');
  await page.locator('.research-source-details summary').click();
  await page.locator('.research-source-details input').fill('data/research-workbench-qa');
  await page.getByRole('tab', {name: /组合与复核/}).click();
  await expect(page.getByRole('tabpanel')).toContainText('实际数据目录：data/research-workbench-qa');
  await expect(page.getByRole('button', {name: '构建数据集', exact:true})).toBeDisabled();
  await expect(page.getByRole('button', {name: '运行工作流', exact:true})).toBeDisabled();
  await page.getByRole('tab', {name: /数据与特征/}).click();
  await page.locator('.research-source-details summary').click();
  await page.getByRole('button', {name: '读取此目录', exact:true}).click();
  await page.getByRole('tab', {name: /组合与复核/}).click();
  await expect(page.getByRole('button', {name: '构建数据集', exact:true})).toBeEnabled();
  expect(writes).toEqual([]);
});

test('saved previous version: compact desktop viewport has no horizontal overflow', async ({page}) => {
  await page.setViewportSize({width: 1131, height: 975});
  await mockResearch(page);
  await page.goto('/research?layout=previous');
  await expect(page.getByRole('tablist', {name: '研究阶段'})).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole('tab', {name: /组合与复核/}).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('saved previous version: root changes block an otherwise ready risk backtest and registry rebuild', async ({page}) => {
  const writes = await mockResearch(page);
  await page.route('**/api/integrations/portfolio/runs**', route => route.fulfill({json: {
    runs: [{portfolio_run_id: 'ui-only-ready', has_target_positions: true, status: 'completed'}],
    dependencies: {pypfopt: true},
  }}));
  await page.goto('/research?layout=previous');
  await page.getByRole('tab', {name: /组合与复核/}).click();
  const backtest = page.getByRole('button', {name: '运行风险回测流水线', exact:true});
  await expect(backtest).toBeEnabled();
  await page.getByRole('tab', {name: /数据与特征/}).click();
  await page.locator('.research-source-details summary').click();
  await page.locator('.research-source-details input').fill('data/unread-ui-fixture');
  await page.getByRole('tab', {name: /组合与复核/}).click();
  await expect(backtest).toBeDisabled();
  await expect(page.getByRole('button', {name: '优化目标权重', exact:true})).toBeDisabled();
  await page.getByRole('tab', {name: /实验与回测/}).click();
  await expect(page.getByRole('button', {name: '重建证据注册表', exact:true})).toBeDisabled();
  expect(writes).toEqual([]);
});
