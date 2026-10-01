import {test, expect} from '@playwright/test';

test('research read is single-flight and exposes registry conflict without changing safety', async ({page}) => {
  let evidenceReads = 0;
  const writes: string[] = [];
  const forbidden: string[] = [];
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (request.method() !== 'GET') writes.push(path);
    if (/private|\/orders?(\/|$)/.test(path)) forbidden.push(path);
  });
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/research/evidence-registry') {
      evidenceReads += 1;
      await route.fulfill({json: {
        schema_version: 'evidence_registry_v1',
        registry_status: 'CONFLICT',
        registry_integrity_status: 'CONFLICT',
        registry_path: 'data/research/evidence_registry.json',
        registry_notes: Array.from({length: 57}, (_, index) => `conflict-${index + 1}`),
      }});
      return;
    }
    if (path === '/api/system/overview') {
      await route.fulfill({json: {stage: 'RESEARCH_ONLY', registry: {integrity: 'unknown'}, paper_enabled: false, live_enabled: false}});
      return;
    }
    if (path === '/api/integrations/qlib/runs') {
      await route.fulfill({json: {runs: [], profiles: [], dependencies: {qlib: true, lightgbm: true}}});
      return;
    }
    if (path === '/api/integrations/portfolio/runs') {
      await route.fulfill({json: {runs: [], dependencies: {pypfopt: true}}});
      return;
    }
    if (/experiments|candidates|features|factors|strategy-manifests|pending|\/tasks$/.test(path)) {
      await route.fulfill({json: []});
      return;
    }
    await route.fulfill({json: {}});
  });

  await page.goto('/research?view=research-overview');
  await expect(page.getByRole('region', {name: '研究状态总览'})).toContainText('已返回 · CONFLICT');
  await page.getByText('来源、工具与读取详情').click();
  await expect(page.getByRole('region', {name: '研究状态总览'})).toContainText('CONFLICT · 57 条说明');
  await expect(page.getByRole('region', {name: '研究状态总览'})).toContainText('不代表证据合格或可晋级');
  await expect(page.getByText('仅研究 · 交易锁定', {exact: true})).toBeVisible();
  expect(evidenceReads).toBe(1);
  expect(writes).toEqual([]);
  expect(forbidden).toEqual([]);
});
