import { test, expect } from '@playwright/test';

test('Research page shows unified Qlib and PyPortfolioOpt state cards', async ({ page }) => {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const {pathname} = url;
    const method = route.request().method();

    if (method === 'GET' && pathname === '/api/health') {
      await route.fulfill({json: {status: 'ok', service: 'quantstation', data_source_default: 'sqlite', fastapi_available: true}});
      return;
    }

    if (method === 'GET' && pathname === '/api/strategies') {
      await route.fulfill({json: [{id: 'trend_macd', display_name: 'Trend MACD', description: 'BTC event-driven trend', category: 'crypto', default_weight: 1, default_params: {}}]});
      return;
    }

    if (method === 'GET' && pathname === '/api/tasks') {
      await route.fulfill({json: []});
      return;
    }

    if (method === 'GET' && pathname === '/api/research/experiments') {
      await route.fulfill({json: []});
      return;
    }

    if (method === 'GET' && pathname === '/api/research/candidates') {
      await route.fulfill({json: []});
      return;
    }

    if (method === 'GET' && pathname === '/api/research/features') {
      await route.fulfill({json: []});
      return;
    }

    if (method === 'GET' && pathname === '/api/research/factors') {
      await route.fulfill({json: []});
      return;
    }

    if (method === 'GET' && pathname === '/api/research/strategy-manifests') {
      await route.fulfill({json: []});
      return;
    }

    if (method === 'GET' && pathname === '/api/research/paper-review/pending') {
      await route.fulfill({json: []});
      return;
    }

    if (method === 'GET' && pathname === '/api/research/evidence-registry') {
      await route.fulfill({json: {registry_integrity_status: 'PASS'}});
      return;
    }

    if (method === 'GET' && pathname === '/api/integrations/qlib/runs') {
      await route.fulfill({
        json: {
          status: 'PASS',
          latest_run_id: 'qlib-001',
          runs: [
            {
              run_id: 'qlib-001',
              workflow_status: 'PASS',
              dataset_status: 'READY',
              manifest_status: 'READY',
              score_rows: 128,
              symbols: ['AAPL', 'MSFT'],
            },
          ],
        },
      });
      return;
    }

    if (method === 'GET' && pathname === '/api/integrations/portfolio/runs') {
      await route.fulfill({
        json: {
          status: 'PASS',
          latest_run_id: 'portfolio-001',
          runs: [
            {
              portfolio_run_id: 'portfolio-001',
              status: 'READY_FOR_BACKTEST_ENTRY',
              optimizer: 'max_sharpe',
              fallback_used: false,
              latest_weight_sum: 1,
              has_target_positions: true,
              source_score_run_id: 'qlib-001',
            },
          ],
        },
      });
      return;
    }

    if (method === 'POST' && pathname === '/api/tasks/integrations/qlib/run-workflow') {
      await route.fulfill({
        json: {
          task_id: 'task-qlib-workflow',
          kind: 'qlib_workflow',
          label: 'Qlib workflow latest',
          status: 'queued',
          stage: 'run_workflow',
          progress: 30,
          message: 'running qlib workflow',
          request: {},
          result: null,
          blockers: [],
          created_at: '2026-05-12T00:00:00Z',
        },
      });
      return;
    }

    if (method === 'POST' && pathname === '/api/tasks/integrations/portfolio/optimize-weights') {
      await route.fulfill({
        json: {
          task_id: 'task-pypfopt-optimize',
          kind: 'portfolio_optimize_weights',
          label: 'PyPortfolioOpt optimize qlib-001',
          status: 'queued',
          stage: 'optimize_weights',
          progress: 40,
          message: 'optimizing portfolio weights',
          request: {},
          result: null,
          blockers: [],
          created_at: '2026-05-12T00:00:00Z',
        },
      });
      return;
    }

    if (method === 'GET' && pathname === '/api/tasks/task-qlib-workflow') {
      await route.fulfill({
        json: {
          task_id: 'task-qlib-workflow',
          kind: 'qlib_workflow',
          label: 'Qlib workflow latest',
          status: 'completed',
          stage: 'completed',
          progress: 100,
          message: 'qlib workflow completed',
          request: {},
          result: {status: 'completed', run_id: 'qlib-001', research_only: true, live_enabled: false},
          blockers: [],
          created_at: '2026-05-12T00:00:00Z',
          completed_at: '2026-05-12T00:00:05Z',
        },
      });
      return;
    }

    if (method === 'GET' && pathname === '/api/tasks/task-pypfopt-optimize') {
      await route.fulfill({
        json: {
          task_id: 'task-pypfopt-optimize',
          kind: 'portfolio_optimize_weights',
          label: 'PyPortfolioOpt optimize qlib-001',
          status: 'completed',
          stage: 'completed',
          progress: 100,
          message: 'portfolio optimization completed',
          request: {},
          result: {status: 'completed', portfolio_run_id: 'portfolio-001', latest_weight_sum: 1, research_only: true, live_enabled: false},
          blockers: [],
          created_at: '2026-05-12T00:00:00Z',
          completed_at: '2026-05-12T00:00:05Z',
        },
      });
      return;
    }

    if (method === 'GET' && pathname === '/api/system/overview') {
      await route.fulfill({
        json: {
          status: 'ok',
          stage: 'research',
          mode: 'paper',
          data_root: 'data',
          health: {service: 'quantstation', data_source_default: 'sqlite', fastapi_available: true},
          registry: {integrity: 'PASS', path: 'data/research/evidence_registry.json'},
          paper_validation: {state: 'PASS', days_completed: 20, days_required: 20},
          minute_data_quality: {status: 'PASS', evaluated_symbols: ['AAPL'], bar_sizes: ['1d']},
          data_coverage: {status: 'PASS', coverage_pct: 100, min_coverage_pct: 95},
          paper_review: {status: 'BLOCKED', entry_allowed: false, manual_review_pending: true, summary: 'Waiting on fresh paper evidence', manifest_path: 'reports/review/manifest.json', evidence_pack_path: 'reports/review/evidence-pack.json'},
          broker_credentials: {credentials_present: true, endpoint_kind: 'paper', base_url_valid: true},
          execution: {live_state: 'frozen', live_block_reason: 'live frozen until review'},
          small_account: {suggested_max_daily_notional: 5000, suggested_max_daily_order_count: 5},
          integrations: {
            dependencies: {qlib: true, pypfopt: true},
            qlib: {status: 'PASS', latest_run_id: 'qlib-001', latest_run: {run_id: 'qlib-001', workflow_status: 'PASS'}},
            portfolio: {status: 'PASS', latest_run_id: 'portfolio-001', latest_run: {portfolio_run_id: 'portfolio-001', status: 'READY_FOR_BACKTEST_ENTRY'}},
          },
          next_actions: [],
        },
      });
      return;
    }

    await route.fulfill({status: 404, json: {error: `Unhandled mock for ${method} ${pathname}`}});
  });

  await page.goto('/research');
  await expect(page.locator('h2')).toContainText('研究台');
  await page.waitForSelector('[data-testid="research-content"]', {timeout: 10000});
  await expect(page.locator('[data-testid="module-state-qlib"]')).toContainText('PASS');
  await expect(page.locator('[data-testid="module-state-pypfopt"]')).toContainText('PASS');
  await page.getByRole('button', {name: 'Qlib组合'}).click();
  await page.locator('[data-testid="module-state-qlib"]').getByRole('button', {name: '运行 workflow'}).click();
  await page.getByRole('button', {name: '优化 target weights'}).click();
  await expect(page.locator('.task-queue-panel')).toContainText('Qlib / PyPortfolioOpt tasks');
  await expect(page.locator('.task-queue-panel')).toContainText('COMPLETED');
  await expect(page.locator('.task-queue-panel')).toContainText('portfolio-001');
});

test('Portfolio page loads and shows summary', async ({ page }) => {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const {pathname} = url;
    const method = route.request().method();

    if (method === 'GET' && pathname === '/api/health') {
      await route.fulfill({json: {status: 'ok', service: 'quantstation', data_source_default: 'sqlite', fastapi_available: true}});
      return;
    }

    if (method === 'GET' && pathname === '/api/strategies') {
      await route.fulfill({json: []});
      return;
    }

    if (method === 'GET' && pathname === '/api/portfolio/status') {
      await route.fulfill({
        json: {
          status: 'ok',
          portfolio_count: 1,
          latest_portfolio: {
            portfolio_id: 'pf-001',
            date: '2026-05-11T00:00:00Z',
            strategy_weights: {trend_macd: 1},
            total_capital: 100000,
            expected_return: 0.12,
            expected_volatility: 0.18,
            symbol_exposures: {AAPL: 0.4, MSFT: 0.6},
          },
        },
      });
      return;
    }

    await route.fulfill({status: 404, json: {error: `Unhandled mock for ${method} ${pathname}`}});
  });
  await page.goto('/portfolio');
  await expect(page.getByRole('heading', {name: '投资组合监控'})).toBeVisible();
  await expect(page.locator('body')).toContainText('pf-001');
});
