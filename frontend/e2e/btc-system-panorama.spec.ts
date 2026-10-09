import {expect, test} from '@playwright/test';
import type {Page} from '@playwright/test';

const waitForBaselineLayout = async (page: Page) => {
  const panorama = page.getByLabel('BTC 系统完整架构图');
  await expect(panorama.locator('p.btc-panorama-status[role="status"]')).toContainText('当前显示原始核验版本');
  await expect(page.getByRole('button', {name: '重新整理布局'})).toBeEnabled();
};

const installPanoramaFitFrameGate = async (page: Page) => {
  await page.evaluate(() => {
    type FitFrameGateWindow = Window & {
      __btcPanoramaFitFrameGate?: {
        heldCount: () => number;
        sources: () => string[];
        release: () => void;
      };
    };
    const target = window as FitFrameGateWindow;
    if (target.__btcPanoramaFitFrameGate) throw new Error('BTC panorama fit frame gate already installed');
    const originalRequest = window.requestAnimationFrame;
    const originalCancel = window.cancelAnimationFrame;
    const held = new Map<number, FrameRequestCallback>();
    const sources: string[] = [];
    let nextHeldId = -1;
    window.requestAnimationFrame = callback => {
      const source = new Error('BTC panorama fit frame source').stack ?? '';
      if (source.includes('fitPanoramaAfterRender')) {
        const id = nextHeldId--;
        held.set(id, callback);
        sources.push(source);
        return id;
      }
      return originalRequest.call(window, callback);
    };
    window.cancelAnimationFrame = id => {
      if (!held.delete(id)) originalCancel.call(window, id);
    };
    target.__btcPanoramaFitFrameGate = {
      heldCount: () => held.size,
      sources: () => [...sources],
      release: () => {
        window.requestAnimationFrame = originalRequest;
        window.cancelAnimationFrame = originalCancel;
        const callbacks = [...held.values()];
        held.clear();
        callbacks.forEach(callback => originalRequest.call(window, callback));
      },
    };
  });
};

const waitForPanoramaFitFrame = async (page: Page) => {
  await expect.poll(() => page.evaluate(() => {
    const target = window as Window & {__btcPanoramaFitFrameGate?: {heldCount: () => number}};
    return target.__btcPanoramaFitFrameGate?.heldCount() ?? 0;
  })).toBeGreaterThan(0);
  const sources = await page.evaluate(() => {
    const target = window as Window & {__btcPanoramaFitFrameGate?: {sources: () => string[]}};
    return target.__btcPanoramaFitFrameGate?.sources() ?? [];
  });
  expect(sources.length).toBeGreaterThan(0);
  expect(sources.every(source => source.includes('fitPanoramaAfterRender'))).toBe(true);
};

const releasePanoramaFitFrameGate = async (page: Page) => {
  await page.evaluate(() => {
    const target = window as Window & {__btcPanoramaFitFrameGate?: {release: () => void}};
    target.__btcPanoramaFitFrameGate?.release();
    delete target.__btcPanoramaFitFrameGate;
  });
};

test('deep link opens the complete BTC panorama and browser back restores overview', async ({page}) => {
  await page.goto('/architecture?view=btc-panorama');
  await waitForBaselineLayout(page);
  await expect(page.getByRole('button', {name: 'BTC 系统全景'})).toHaveAttribute('aria-pressed', 'true');
  const panorama = page.getByLabel('BTC 系统完整架构图');
  await expect(panorama).toBeVisible();
  await expect(panorama.locator('[data-panorama-group]')).toHaveCount(9);
  await expect(panorama.locator('[data-panorama-node]')).toHaveCount(37);
  await expect(panorama.locator('.react-flow__edge')).toHaveCount(49);
  await expect(page.locator('.atlas-label')).toHaveText('原始快照只读 · 个人草稿可编辑且未经代码核验');
  await expect(panorama).not.toContainText('原始 A–I 结构及实虚线来自');
  await expect(panorama).not.toContainText('个人编辑草稿不是实时权限或代码验收');
  await expect(panorama).not.toContainText('可从节点右侧 / 下方手柄拖到另一节点');
  await expect(panorama).toContainText('当前部署：research_readonly');
  await expect(panorama).toContainText('离线任务未配置、未启用');
  await page.getByRole('button', {name: '总览思维导图'}).click();
  await expect(page).toHaveURL('/architecture');
  await expect(page.getByLabel('系统总览思维导图')).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL('/architecture?view=btc-panorama');
  await expect(page.getByLabel('BTC 系统完整架构图')).toBeVisible();
});

test('zoom, fit and reset controls change the panorama canvas without business requests', async ({page}) => {
  const sideEffects: string[] = [];
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    const businessApiSideEffect = path.startsWith('/api/')
      && /candidate-offline\/jobs|start|resume|stop|register|review|bind/.test(path);
    if (request.method() !== 'GET' || businessApiSideEffect) {
      sideEffects.push(`${request.method()} ${path}`);
    }
  });
  await page.goto('/architecture?view=btc-panorama');
  await waitForBaselineLayout(page);
  const output = page.getByLabel('BTC 全景图当前缩放比例');
  await page.getByRole('button', {name: '恢复 100%'}).click();
  await expect(output).toHaveText('100%');
  await page.getByRole('button', {name: '放大全景图'}).click();
  await expect.poll(async () => Number.parseInt(await output.textContent() ?? '', 10)).toBeGreaterThan(100);
  await page.getByRole('button', {name: '缩小全景图'}).click();
  await expect.poll(async () => Number.parseInt(await output.textContent() ?? '', 10)).toBeLessThanOrEqual(100);
  await page.getByRole('button', {name: '适应画布'}).click();
  await expect.poll(async () => Number.parseInt(await output.textContent() ?? '', 10)).toBeLessThanOrEqual(100);
  expect(sideEffects).toEqual([]);
});

test('personal edits save locally, survive refresh, restore baseline and remain undoable', async ({page}) => {
  await page.goto('/architecture?view=btc-panorama');
  const panorama = page.getByLabel('BTC 系统完整架构图');
  await expect(panorama.locator('p.btc-panorama-status[role="status"]')).toContainText('当前显示原始核验版本');
  const historyNode = panorama.locator('[data-panorama-node]').filter({hasText: 'OKX 历史行情、资金费'});
  await historyNode.scrollIntoViewIfNeeded();
  const beforeMove = await historyNode.boundingBox();
  if (!beforeMove) throw new Error('history node has no bounding box');
  await page.mouse.move(beforeMove.x + beforeMove.width / 2, beforeMove.y + beforeMove.height / 2);
  await page.mouse.down();
  await page.mouse.move(beforeMove.x + beforeMove.width / 2 + 70, beforeMove.y + beforeMove.height / 2 + 35, {steps: 6});
  await page.mouse.up();
  const afterMove = await historyNode.boundingBox();
  if (!afterMove) throw new Error('moved history node has no bounding box');
  expect(Math.abs(afterMove.x - beforeMove.x) + Math.abs(afterMove.y - beforeMove.y)).toBeGreaterThan(30);
  await historyNode.click();
  await page.getByLabel('标题').fill('OKX 历史行情与资金费（个人草稿）');
  await page.getByRole('button', {name: '保存本机草稿'}).click();
  await expect(panorama.locator('p.btc-panorama-status[role="status"]')).toContainText('本机个人草稿已保存');
  await page.reload({waitUntil: 'domcontentloaded'});
  await expect(panorama).toContainText('OKX 历史行情与资金费（个人草稿）');
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', {name: '恢复原始版本'}).click();
  await expect(panorama).toContainText('OKX 历史行情、资金费');
  await expect(panorama.locator('p.btc-panorama-status[role="status"]')).toContainText('点击“保存本机草稿”后刷新才生效');
  await page.reload({waitUntil: 'domcontentloaded'});
  await expect(panorama).toContainText('OKX 历史行情与资金费（个人草稿）');
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', {name: '恢复原始版本'}).click();
  await page.getByRole('button', {name: '撤销'}).click();
  await expect(panorama).toContainText('OKX 历史行情与资金费（个人草稿）');
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', {name: '恢复原始版本'}).click();
  await page.getByRole('button', {name: '保存本机草稿'}).click();
  await page.reload({waitUntil: 'domcontentloaded'});
  await expect(panorama).toContainText('OKX 历史行情、资金费');
  await expect(panorama).not.toContainText('OKX 历史行情与资金费（个人草稿）');
});

test('a loaded personal draft keeps its positions until explicit reversible rearrangement', async ({page}) => {
  await page.goto('/architecture?view=btc-panorama');
  const panorama = page.getByLabel('BTC 系统完整架构图');
  await expect(panorama.locator('p.btc-panorama-status[role="status"]')).toContainText('当前显示原始核验版本');
  await page.getByRole('button', {name: '保存本机草稿'}).click();
  const saved = await page.evaluate(() => localStorage.getItem('quantstation:architecture:btc-panorama-draft:v1'));
  await page.reload();
  await expect(panorama.locator('p.btc-panorama-status[role="status"]')).toContainText('位置保持原样');
  expect(await page.evaluate(() => localStorage.getItem('quantstation:architecture:btc-panorama-draft:v1'))).toBe(saved);

  const historyNode = panorama.locator('[data-panorama-node]').filter({hasText: 'OKX 历史行情、资金费'});
  const addNodeButton = page.getByRole('button', {name: '在当前分区新增节点'});
  const flowNode = historyNode.locator('xpath=ancestor::div[contains(@class, "react-flow__node")][1]');
  const arrangedLayoutTargets = panorama.locator(
    '.react-flow__node[data-id="okx-history"], .react-flow__node[data-id="group-data"]',
  );
  const readArrangedLayoutSignature = async () => arrangedLayoutTargets.evaluateAll(elements => {
    if (elements.length !== 2) throw new Error(`expected two arranged layout targets, received ${elements.length}`);
    return elements.map(element => {
      if (!(element instanceof HTMLElement)) throw new Error('arranged layout target is not an HTMLElement');
      const id = element.dataset.id;
      const transform = element.style.transform;
      const computed = getComputedStyle(element);
      const width = Number.parseFloat(computed.width);
      const height = Number.parseFloat(computed.height);
      if (!id || !transform || !Number.isFinite(width) || !Number.isFinite(height)) {
        throw new Error(`arranged layout signature is incomplete for ${id ?? 'unknown target'}`);
      }
      return {id, transform, width, height};
    }).sort((left, right) => left.id.localeCompare(right.id));
  });
  const expectHistoryNodeAt = async (box: {x: number; y: number; width: number; height: number}) => {
    const hit = await page.evaluate(({x, y}) => {
      const node = document.elementFromPoint(x, y)?.closest('[data-panorama-node]');
      return {
        title: node?.querySelector('strong')?.textContent ?? null,
        id: node?.closest('.react-flow__node')?.getAttribute('data-id') ?? null,
      };
    }, {x: box.x + box.width / 2, y: box.y + box.height / 2});
    expect(hit).toEqual({title: 'OKX 历史行情、资金费', id: 'okx-history'});
  };

  await installPanoramaFitFrameGate(page);
  try {
    page.once('dialog', dialog => dialog.accept());
    await page.getByRole('button', {name: '重新整理布局'}).click();
    await waitForPanoramaFitFrame(page);
    await expect(addNodeButton).toBeDisabled();
    await expect(panorama.locator('p.btc-panorama-status[role="status"]')).toContainText('正在重新整理分层布局');
  } finally {
    await releasePanoramaFitFrameGate(page);
  }
  await expect(panorama.locator('p.btc-panorama-status[role="status"]')).toContainText('点击“保存本机草稿”后刷新才生效');
  await expect(addNodeButton).toBeEnabled();
  const firstArrangedLayoutSignature = await readArrangedLayoutSignature();
  expect(await page.evaluate(() => localStorage.getItem('quantstation:architecture:btc-panorama-draft:v1'))).toBe(saved);
  await expect(page.getByRole('button', {name: '撤销'})).toBeEnabled();
  await page.getByRole('button', {name: '撤销'}).click();
  await expect(panorama.locator('p.btc-panorama-status[role="status"]')).toContainText('已撤销');

  await installPanoramaFitFrameGate(page);
  try {
    page.once('dialog', dialog => dialog.accept());
    await page.getByRole('button', {name: '重新整理布局'}).click();
    await waitForPanoramaFitFrame(page);
    await expect(addNodeButton).toBeDisabled();
    await expect(panorama.locator('p.btc-panorama-status[role="status"]')).toContainText('正在重新整理分层布局');
    await expect(flowNode).not.toHaveClass(/draggable/);
    await expect.poll(readArrangedLayoutSignature).toEqual(firstArrangedLayoutSignature);
    await historyNode.scrollIntoViewIfNeeded();
    const beforeBusyBox = await historyNode.boundingBox();
    if (!beforeBusyBox) throw new Error('history node has no bounding box before layout busy check');
    await expectHistoryNodeAt(beforeBusyBox);
    await page.mouse.move(beforeBusyBox.x + beforeBusyBox.width / 2, beforeBusyBox.y + beforeBusyBox.height / 2);
    await page.mouse.down();
    await page.mouse.move(beforeBusyBox.x + beforeBusyBox.width / 2 + 45, beforeBusyBox.y + beforeBusyBox.height / 2 + 25, {steps: 4});
    await page.mouse.up();
    const afterBusyBox = await historyNode.boundingBox();
    if (!afterBusyBox) throw new Error('history node has no bounding box after layout busy check');
    expect(Math.abs(afterBusyBox.x - beforeBusyBox.x) + Math.abs(afterBusyBox.y - beforeBusyBox.y)).toBeLessThan(2);
  } finally {
    await releasePanoramaFitFrameGate(page);
  }
  await expect(panorama.locator('p.btc-panorama-status[role="status"]')).toContainText('已重新整理画布');
  await expect(addNodeButton).toBeEnabled();
  await expect(flowNode).toHaveClass(/draggable/);

  await historyNode.scrollIntoViewIfNeeded();
  const readyBox = await historyNode.boundingBox();
  if (!readyBox) throw new Error('history node has no bounding box after layout becomes ready');
  await expectHistoryNodeAt(readyBox);
  await page.mouse.move(readyBox.x + readyBox.width / 2, readyBox.y + readyBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(readyBox.x + readyBox.width / 2 + 45, readyBox.y + readyBox.height / 2 + 25, {steps: 4});
  await page.mouse.up();
  await expect(panorama.locator('p.btc-panorama-status[role="status"]')).toContainText('节点位置已调整');
  const movedBox = await historyNode.boundingBox();
  if (!movedBox) throw new Error('history node has no bounding box after ready drag');
  expect(Math.abs(movedBox.x - readyBox.x) + Math.abs(movedBox.y - readyBox.y)).toBeGreaterThan(20);
  await page.waitForTimeout(1_600);
  await expect(panorama.locator('p.btc-panorama-status[role="status"]')).toContainText('节点位置已调整');
  const stableBox = await historyNode.boundingBox();
  if (!stableBox) throw new Error('history node has no bounding box after drag stability check');
  expect(Math.abs(stableBox.x - movedBox.x) + Math.abs(stableBox.y - movedBox.y)).toBeLessThan(2);
});

test('node and edge CRUD plus JSON export work inside the personal draft only', async ({page}) => {
  await page.goto('/architecture?view=btc-panorama');
  await waitForBaselineLayout(page);
  const panorama = page.getByLabel('BTC 系统完整架构图');
  await page.getByRole('button', {name: '在当前分区新增节点'}).click();
  await expect(panorama.locator('[data-panorama-node]')).toHaveCount(38);
  await page.getByRole('button', {name: '删除选中节点 / 连线'}).click();
  await expect(panorama.locator('[data-panorama-node]')).toHaveCount(37);

  const selectors = page.getByLabel('BTC 全景图编辑面板').locator('select');
  await selectors.nth(0).selectOption('okx-history');
  await selectors.nth(1).selectOption('public-market');
  await page.getByRole('button', {name: '新增连线'}).click();
  await expect(panorama.locator('.react-flow__edge')).toHaveCount(50);
  const draftEdge = panorama.locator('.react-flow__edge[data-id^="draft-edge-"]');
  const routeBeforeStyleChange = await draftEdge.locator('.react-flow__edge-path').getAttribute('d');
  await draftEdge.focus();
  await expect(draftEdge).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByLabel('线型')).toBeEnabled();
  await page.getByLabel('线型').selectOption('dashed');
  await expect(draftEdge.locator('.react-flow__edge-path')).toHaveAttribute('d', routeBeforeStyleChange ?? '');
  const dashSegments = await draftEdge.locator('.react-flow__edge-path').evaluate(element =>
    (getComputedStyle(element).strokeDasharray.match(/\d+(?:\.\d+)?/g) ?? []).map(Number));
  expect(dashSegments).toEqual([8, 7]);
  await page.getByRole('button', {name: '删除选中节点 / 连线'}).click();
  await expect(panorama.locator('.react-flow__edge')).toHaveCount(49);

  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', {name: '导出 JSON'}).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^btc-system-panorama-draft-\d{4}-\d{2}-\d{2}\.json$/);
});

test('a damaged local draft fails safely to the immutable baseline', async ({page}) => {
  await page.goto('/architecture?view=btc-panorama');
  await waitForBaselineLayout(page);
  const panorama = page.getByLabel('BTC 系统完整架构图');
  await page.evaluate(() => localStorage.setItem('quantstation:architecture:btc-panorama-draft:v1', '{broken'));
  await page.reload();
  await expect(panorama.locator('p.btc-panorama-status[role="status"]')).toContainText('本机草稿无法读取');
  await expect(panorama).toContainText('OKX 历史行情、资金费');
  await expect(panorama.locator('[data-panorama-node]')).toHaveCount(37);
});

test('a structurally invalid draft with duplicate identities is rejected', async ({page}) => {
  await page.goto('/architecture?view=btc-panorama');
  await waitForBaselineLayout(page);
  const panorama = page.getByLabel('BTC 系统完整架构图');
  await page.getByRole('button', {name: '保存本机草稿'}).click();
  await page.evaluate(() => {
    const key = 'quantstation:architecture:btc-panorama-draft:v1';
    const draft = JSON.parse(localStorage.getItem(key) ?? '{}');
    draft.edges.push({...draft.edges[0]});
    localStorage.setItem(key, JSON.stringify(draft));
  });
  await page.reload();
  await expect(panorama.locator('p.btc-panorama-status[role="status"]')).toContainText('本机草稿无法读取');
  await expect(panorama.locator('.react-flow__edge')).toHaveCount(49);
});

test('markup remains plain text and local storage write failures stay fail-closed', async ({page}) => {
  await page.goto('/architecture?view=btc-panorama');
  await waitForBaselineLayout(page);
  const panorama = page.getByLabel('BTC 系统完整架构图');
  const historyNode = panorama.locator('[data-panorama-node]').filter({hasText: 'OKX 历史行情、资金费'});
  await historyNode.click();
  await page.getByLabel('标题').fill('<img src=x onerror="globalThis.__btcPanoramaInjected=true">');
  await expect(panorama).toContainText('<img src=x onerror="globalThis.__btcPanoramaInjected=true">');
  await expect(panorama.locator('img[src="x"]')).toHaveCount(0);
  expect(await page.evaluate(() => (globalThis as {__btcPanoramaInjected?: boolean}).__btcPanoramaInjected)).toBeUndefined();

  await page.evaluate(() => {
    Object.defineProperty(Storage.prototype, 'setItem', {
      configurable: true,
      value: () => { throw new DOMException('quota blocked', 'QuotaExceededError'); },
    });
  });
  await page.getByRole('button', {name: '保存本机草稿'}).click();
  await expect(panorama.locator('p.btc-panorama-status[role="status"]')).toContainText('保存失败，本机草稿未更新');
});

for (const width of [390, 1131, 1440]) {
  test(`BTC panorama stays page-contained and pannable at ${width}px`, async ({page}) => {
    await page.setViewportSize({width, height: 975});
    await page.goto('/architecture?view=btc-panorama');
    await waitForBaselineLayout(page);
    await expect(page.getByTestId('btc-panorama-viewport')).toBeVisible();
    const geometry = await page.evaluate(() => ({
      pageOverflow: document.documentElement.scrollWidth > window.innerWidth + 2,
      panePresent: Boolean(document.querySelector('[data-testid="btc-panorama-viewport"] .react-flow__pane')),
      minimapPresent: Boolean(document.querySelector('[data-testid="btc-panorama-viewport"] .react-flow__minimap')),
    }));
    expect(geometry.pageOverflow).toBe(false);
    expect(geometry.panePresent).toBe(true);
    expect(geometry.minimapPresent).toBe(true);
  });
}
