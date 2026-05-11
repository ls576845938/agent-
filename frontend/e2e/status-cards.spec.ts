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
  await expect(page.locator('body')).not.toHaveCSS('background-color', 'rgb(0, 0, 0)');
});
