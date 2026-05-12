import {test, expect} from '@playwright/test';

test('Crypto workspace exposes sqlite coverage, resampling, and blockers', async ({page}) => {
  const syncCalls: string[] = [];
  const resampleCalls: string[] = [];

  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const {pathname, searchParams} = url;
    const method = route.request().method();

    if (method === 'GET' && pathname === '/api/health') {
      await route.fulfill({json: {status: 'ok', service: 'quantstation', data_source_default: 'sqlite', fastapi_available: true}});
      return;
    }

    if (method === 'GET' && pathname === '/api/strategies') {
      await route.fulfill({
        json: [
          {id: 'trend_macd', display_name: 'Trend MACD', description: 'BTC event-driven trend', category: 'crypto', default_weight: 1, default_params: {}},
        ],
      });
      return;
    }

    if (method === 'GET' && pathname === '/api/tasks') {
      await route.fulfill({json: []});
      return;
    }

    if (method === 'GET' && pathname === '/api/data/database') {
      await route.fulfill({
        json: {
          db_path: 'data/market_data.sqlite',
          exists: true,
          initialized: true,
          table_count: 3,
          coverage: [
            {exchange: 'binance_spot', symbol: 'BTCUSDT', interval: '1m', rows: 1200, start: '2026-05-01T00:00:00Z', end: '2026-05-02T00:00:00Z', updated_at: '2026-05-02T00:00:00Z'},
            {exchange: 'binance_spot', symbol: 'BTCUSDT', interval: '5m', rows: 240, start: '2026-05-01T00:00:00Z', end: '2026-05-02T00:00:00Z', updated_at: '2026-05-02T00:00:00Z'},
          ],
        },
      });
      return;
    }

    if (method === 'GET' && pathname === '/api/data/klines') {
      await route.fulfill({
        json: {
          db_path: 'data/market_data.sqlite',
          rows: [
            {exchange: 'binance_spot', symbol: searchParams.get('symbol') ?? 'BTCUSDT', interval: searchParams.get('interval') ?? '1m', time: '2026-05-02T00:00:00Z', open_time_ms: 1, open: 100, high: 110, low: 95, close: 105, volume: 12.4, quote_volume: 1300, trade_count: 88},
          ],
        },
      });
      return;
    }

    if (method === 'GET' && pathname === '/api/data/sync-runs') {
      await route.fulfill({
        json: [
          {run_id: 'sync-1', status: 'completed', db_path: 'data/market_data.sqlite', exchange: 'binance_spot', symbol: 'BTCUSDT', interval: '1m', start: '2026-05-01T00:00:00Z', end: '2026-05-02T00:00:00Z', rows_received: 1200, rows_written: 1200, requests: 2},
        ],
      });
      return;
    }

    if (method === 'GET' && pathname === '/api/data/scheduler') {
      await route.fulfill({json: {running: false, interval_seconds: 86400, symbol: 'BTCUSDT', interval: '1m', db_path: 'data/market_data.sqlite'}});
      return;
    }

    if (method === 'POST' && pathname === '/api/data/sync') {
      const payload = await route.request().postDataJSON();
      syncCalls.push(String(payload.interval));
      await route.fulfill({
        json: {
          run_id: `sync-${syncCalls.length}`,
          status: 'completed',
          db_path: 'data/market_data.sqlite',
          exchange: 'binance_spot',
          symbol: 'BTCUSDT',
          interval: String(payload.interval),
          start: '2026-05-01T00:00:00Z',
          end: '2026-05-02T00:00:00Z',
          rows_received: 1200,
          rows_written: 1200,
          requests: 2,
        },
      });
      return;
    }

    if (method === 'POST' && pathname === '/api/data/resample') {
      const payload = await route.request().postDataJSON();
      resampleCalls.push(String(payload.target_interval));
      await route.fulfill({
        json: {
          status: 'completed',
          db_path: 'data/market_data.sqlite',
          exchange: 'binance_spot',
          symbol: 'BTCUSDT',
          source_interval: String(payload.source_interval),
          target_interval: String(payload.target_interval),
          start: '2026-05-01T00:00:00Z',
          end: '2026-05-02T00:00:00Z',
          source_rows: 1200,
          expected_source_rows: 1200,
          rows_written: 240,
          coverage_pct: 100,
          quality_score: 99,
          manifest_path: 'manifests/btc-resample.json',
          data_version: 'btc-resample-v1',
          fingerprint: 'resample-demo',
          quality_summary: {},
        },
      });
      return;
    }

    if (method === 'POST' && pathname === '/api/data/quality') {
      await route.fulfill({
        json: {
          status: 'FAIL',
          selected_priority: 'data_quality',
          framework: [],
          source: 'sqlite',
          actual_source: 'sqlite',
          symbol: 'BTCUSDT',
          interval: '1h',
          row_count: 120,
          raw_row_count: 120,
          expected_rows: 240,
          coverage_pct: 50,
          missing_bars: 120,
          duplicate_timestamps: 0,
          cleaning_loss_rows: 0,
          invalid_ohlc: 1,
          non_positive_prices: 0,
          non_positive_volume: 0,
          large_price_jumps: 0,
          volume_anomalies: 0,
          max_gap_bars: 4,
          max_price_jump_pct: 0,
          quality_score: 40,
          is_usable: false,
          fingerprint: 'demo',
          data_version: 'btc-demo',
          issues: [
            {severity: 'high', code: 'missing_bars', message: 'coverage below threshold'},
            {severity: 'medium', code: 'invalid_ohlc', message: 'bad candle'},
          ],
        },
      });
      return;
    }

    if (method === 'POST' && pathname === '/api/tasks/crypto/closure') {
      await route.fulfill({
        json: {
          task_id: 'task-crypto-closure',
          kind: 'crypto_closure',
          label: 'BTC production closure BTCUSDT 1h',
          status: 'queued',
          stage: 'running',
          progress: 5,
          message: 'BTC production closure task queued',
          request: {},
          result: null,
          blockers: [],
          created_at: '2026-05-12T00:00:00Z',
        },
      });
      return;
    }

    if (method === 'GET' && pathname === '/api/tasks/task-crypto-closure') {
      await route.fulfill({
        json: {
          task_id: 'task-crypto-closure',
          kind: 'crypto_closure',
          label: 'BTC production closure BTCUSDT 1h',
          status: 'completed',
          stage: 'completed',
          progress: 100,
          message: 'BTC production closure completed',
          request: {},
          result: {
            status: 'completed',
            decision: 'fail',
            next_stage: 'blocked',
            blockers: ['coverage below threshold'],
            recommendations: ['BTC closure completed but blocked.'],
            symbol: 'BTCUSDT',
            target_intervals: ['5m', '15m', '1h', '4h', '1d'],
            data_integrity: {status: 'pass'},
            candidate_screen: {
              candidate_count: 2,
              selected_candidate: {rank: 1, strategy_id: 'trend_macd', parameters: {}, score: 1.4, validation: {sharpe_ratio: 1.4, max_drawdown_pct: -6.2}},
            },
            selected_candidate: {rank: 1, strategy_id: 'trend_macd', parameters: {}, score: 1.4, validation: {sharpe_ratio: 1.4, max_drawdown_pct: -6.2}},
            event_backtest: {summary: {sharpe_ratio: 1.4, total_return_pct: 5.6, trade_count: 3}},
            cost_stress: {survival_rate_pct: 88, ledger_consistency_pct: 100},
            walk_forward: {stability: {fold_pass_rate_pct: 75, ledger_consistency_pct: 100}},
            promotion_gate: {decision: 'fail', next_stage: 'blocked', gates: [{name: 'data_quality', status: 'fail', message: 'coverage below threshold'}]},
          },
          blockers: ['coverage below threshold'],
          created_at: '2026-05-12T00:00:00Z',
          completed_at: '2026-05-12T00:00:05Z',
        },
      });
      return;
    }

    if (method === 'POST' && pathname === '/api/tasks/research/promotion-gate') {
      await route.fulfill({
        json: {
          task_id: 'task-promotion-gate',
          kind: 'promotion_gate',
          label: 'promotion gate BTCUSDT single',
          status: 'queued',
          stage: 'running',
          progress: 5,
          message: 'promotion gate task queued',
          request: {},
          result: null,
          blockers: [],
          created_at: '2026-05-12T00:00:00Z',
        },
      });
      return;
    }

    if (method === 'GET' && pathname === '/api/tasks/task-promotion-gate') {
      await route.fulfill({
        json: {
          task_id: 'task-promotion-gate',
          kind: 'promotion_gate',
          label: 'promotion gate BTCUSDT single',
          status: 'completed',
          stage: 'completed',
          progress: 100,
          message: 'promotion gate completed',
          request: {},
          result: {
            status: 'FAIL',
            selected_priority: 'promotion_gate',
            framework: [],
            decision: 'fail',
            next_stage: 'research_ready',
            manifest_id: 'manifest-123',
            manifest_path: 'manifests/manifest-123.json',
            strategy_version: 'btc-v1',
            experiment_record: {experiment_name: 'btc_event_driven', data_version: 'btc-demo'},
            data_quality: {},
            backtest_summary: {
              total_return_pct: 0,
              annual_return_pct: 0,
              annual_volatility_pct: 0,
              sharpe_ratio: 0.4,
              sortino_ratio: 0.5,
              max_drawdown_pct: -9.1,
              calmar_ratio: 0.1,
              win_rate_pct: 42,
              profit_factor: 0.8,
              trade_count: 3,
            },
            gates: [
              {name: 'data_quality', status: 'fail', message: 'coverage below threshold', metrics: {}, threshold: 'coverage >= 95%'},
              {name: 'walk_forward', status: 'warn', message: 'insufficient oos robustness', metrics: {}, threshold: 'pass_rate >= 60%'},
            ],
            recommendations: ['Fill SQLite gaps before promotion.'],
          },
          blockers: ['coverage below threshold'],
          created_at: '2026-05-12T00:00:00Z',
          completed_at: '2026-05-12T00:00:05Z',
        },
      });
      return;
    }

    if (method === 'POST' && pathname === '/api/research/promotion-gate') {
      await route.fulfill({
        json: {
          status: 'FAIL',
          selected_priority: 'promotion_gate',
          framework: [],
          decision: 'fail',
          next_stage: 'research_ready',
          manifest_id: 'manifest-123',
          manifest_path: 'manifests/manifest-123.json',
          strategy_version: 'btc-v1',
          experiment_record: {experiment_name: 'btc_event_driven', data_version: 'btc-demo'},
          data_quality: {},
          backtest_summary: {
            total_return_pct: 0,
            annual_return_pct: 0,
            annual_volatility_pct: 0,
            sharpe_ratio: 0.4,
            sortino_ratio: 0.5,
            max_drawdown_pct: -9.1,
            calmar_ratio: 0.1,
            win_rate_pct: 42,
            profit_factor: 0.8,
            trade_count: 3,
          },
          gates: [
            {name: 'data_quality', status: 'fail', message: 'coverage below threshold', metrics: {}, threshold: 'coverage >= 95%'},
            {name: 'walk_forward', status: 'warn', message: 'insufficient oos robustness', metrics: {}, threshold: 'pass_rate >= 60%'},
          ],
          recommendations: ['Fill SQLite gaps before promotion.'],
        },
      });
      return;
    }

    if (method === 'POST' && pathname === '/api/crypto/research/closure') {
      await route.fulfill({
        json: {
          status: 'completed',
          selected_priority: 'BTC closure',
          symbol: 'BTCUSDT',
          source: 'sqlite',
          interval: '1h',
          target_intervals: ['5m', '15m', '1h', '4h', '1d'],
          data_integrity: {status: 'pass', blockers: [], resample_results: [], quality_results: []},
          candidate_screen: {
            status: 'completed',
            candidate_count: 2,
            candidates: [
              {rank: 1, strategy_id: 'trend_macd', parameters: {}, score: 1.4, validation: {sharpe_ratio: 1.4, max_drawdown_pct: -6.2}},
              {rank: 2, strategy_id: 'donchian_breakout', parameters: {channel_window: 20}, score: 0.9, validation: {sharpe_ratio: 0.9, max_drawdown_pct: -8.1}},
            ],
            selected_candidate: {rank: 1, strategy_id: 'trend_macd', parameters: {}, score: 1.4, validation: {sharpe_ratio: 1.4, max_drawdown_pct: -6.2}},
            errors: [],
            blockers: [],
          },
          selected_candidate: {rank: 1, strategy_id: 'trend_macd', parameters: {}, score: 1.4, validation: {sharpe_ratio: 1.4, max_drawdown_pct: -6.2}},
          event_backtest: {
            status: 'completed',
            mode: 'crypto_event',
            summary: {
              total_return_pct: 5.6,
              annual_return_pct: 30,
              annual_volatility_pct: 18,
              sharpe_ratio: 1.4,
              sortino_ratio: 1.8,
              max_drawdown_pct: -6.2,
              calmar_ratio: 2,
              win_rate_pct: 52,
              profit_factor: 1.1,
              trade_count: 24,
            },
            diagnostics: {pnl_source: 'ledger_fills'},
          },
          cost_stress: {engine: 'event_driven', survival_rate_pct: 50, ledger_consistency_pct: 100},
          walk_forward: {status: 'completed', stability: {fold_pass_rate_pct: 50, pass_rate_pct: 50, ledger_consistency_pct: 100}, windows: [], regimes: [], recommendations: []},
          promotion_gate: {
            status: 'completed',
            selected_priority: 'gate',
            framework: [],
            decision: 'fail',
            next_stage: 'blocked',
            manifest_id: 'manifest-closure',
            manifest_path: 'reports/research_gates/manifest-closure.json',
            strategy_version: 'btc-closure-v1',
            experiment_record: {experiment_name: 'btc_closure'},
            data_quality: {},
            backtest_summary: {sharpe_ratio: 1.4, max_drawdown_pct: -6.2},
            gates: [{name: 'cost_stress', status: 'fail', message: 'survival too low', metrics: {}, threshold: ''}],
            recommendations: ['Keep paper disabled.'],
          },
          decision: 'fail',
          next_stage: 'blocked',
          blockers: ['cost_stress survival_rate 50% < 60%', 'promotion_gate decision=fail next_stage=blocked'],
          recommendations: ['BTC closure completed but blocked.'],
        },
      });
      return;
    }

    if (method === 'POST' && pathname === '/api/backtests/crypto-event') {
      await route.fulfill({
        json: {
          run_id: 'run-1',
          mode: 'crypto_event',
          status: 'completed',
          created_at: '2026-05-11T00:00:00Z',
          completed_at: '2026-05-11T00:01:00Z',
          summary: {
            total_return_pct: 12.3,
            annual_return_pct: 45.6,
            annual_volatility_pct: 18.2,
            sharpe_ratio: 1.8,
            sortino_ratio: 2.4,
            max_drawdown_pct: -7.2,
            calmar_ratio: 6.3,
            win_rate_pct: 54,
            profit_factor: 1.22,
            trade_count: 18,
          },
          latest_weights: [],
          strategy_details: [],
          diagnostics: {},
        },
      });
      return;
    }

    if (method === 'GET' && pathname === '/api/runs/run-1/chart') {
      await route.fulfill({
        json: {
          candles: [{time: 1, open: 1, high: 2, low: 0.5, close: 1.5}],
          markers: [],
          equity: [{time: 1, value: 100000}],
          drawdown: [{time: 1, value: 0}],
          exposure: [{time: 1, value: 0}],
          net_units: [{time: 1, value: 0}],
          turnover: [{time: 1, value: 0}],
          leverage: [{time: 1, value: 1}],
        },
      });
      return;
    }

    await route.fulfill({status: 404, json: {error: `Unhandled mock for ${method} ${pathname}`}});
  });

  await page.goto('/crypto');
  await expect(page.getByRole('heading', {name: '事件驱动回测'})).toBeVisible();
  await expect(page.locator('[data-testid="crypto-sqlite-coverage"]')).toContainText('1m');
  await expect(page.locator('[data-testid="crypto-sqlite-coverage"]')).toContainText('触发 1m -> 5m 重采样');

  await page.getByRole('button', {name: '1m→1d 重采样链'}).click();
  await expect(page.locator('[data-testid="crypto-data-panel"]')).toContainText('重采样链完成');
  await expect.poll(() => syncCalls).toHaveLength(1);
  await expect.poll(() => resampleCalls).toHaveLength(5);

  await page.getByRole('button', {name: '数据质量'}).click();
  await expect(page.locator('[data-testid="crypto-data-quality"]')).toContainText('阻断');

  await page.getByRole('button', {name: '研究准入门'}).click();
  await expect(page.locator('[data-testid="crypto-promotion-blockers"]')).toContainText('coverage below threshold');
  await expect(page.locator('[data-testid="crypto-blockers"]')).toContainText('promotion');

  await page.locator('[data-testid="module-state-btc"]').getByRole('button', {name: '启动 BTC production closure'}).click();
  await expect(page.locator('[data-testid="module-state-btc"]')).toContainText('任务进度');
  await expect(page.locator('[data-testid="module-state-btc"]')).toContainText('任务阶段');
  await expect(page.locator('.task-queue-panel')).toContainText('BTC production closure 任务');
  await expect(page.locator('.task-queue-panel')).toContainText('COMPLETED');
  await expect(page.locator('.task-queue-panel')).toContainText('100%');
  await expect(page.locator('.task-queue-panel')).toContainText('Decision FAIL');
  await expect(page.locator('.task-queue-panel')).toContainText('Candidate trend_macd');
  await expect(page.locator('.task-queue-panel')).toContainText('coverage below threshold');
});
