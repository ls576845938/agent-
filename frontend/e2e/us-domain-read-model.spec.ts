import {expect, test} from '@playwright/test';


test('US operator evidence is read-only, fail-closed, and separated from legacy research controls', async ({page}) => {
  const requestedMethods: string[] = [];
  await page.route('**/api/**', async route => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    requestedMethods.push(`${request.method()} ${pathname}`);
    if (pathname === '/api/health') {
      await route.fulfill({
        json: {
          status: 'ok',
          service: 'quantstation',
          data_source_default: 'sqlite',
          fastapi_available: true,
        },
      });
      return;
    }
    if (pathname === '/api/strategies') {
      await route.fulfill({
        json: [
          {
            id: 'us_etf_complete_return_fixed_signal_v1',
            display_name: 'Frozen ETF26 Candidate',
            description: 'Research-only frozen candidate',
            category: 'equity',
            default_weight: 1,
            default_params: {},
          },
        ],
      });
      return;
    }
    if (pathname === '/api/research/us-equity/domain-read-model') {
      await route.fulfill({
        headers: {'Cache-Control': 'no-store'},
        json: {
          schema_version: 'us_equity_domain_read_model_v1',
          domain: 'us_equity',
          source_head: 'a'.repeat(40),
          generated_at_utc: '2026-07-24T13:30:00Z',
          freshness: 'current_head',
          status: 'blocked',
          current_stage: 'blocked_external_data',
          readiness_class: 'quality_checked',
          gate_decision: 'blocked_do_not_promote_or_start_paper',
          promotion_evidence_ready: false,
          paper_ready: false,
          live_ready: false,
          layers: {
            data: {
              status: 'missing',
              freshness: 'current_head',
              readiness_class: 'research_ready',
              evidence_id: 'g06',
              artifact_path: 'docs/handoffs/g06/report.json',
              artifact_sha256: '1'.repeat(64),
              manifest_path: '.agent/data_manifests/us.json',
              manifest_sha256: '2'.repeat(64),
              integration_commit: '3'.repeat(40),
            },
            backtest: {
              status: 'complete_research_only_blocked',
              freshness: 'current_head',
              readiness_class: 'backtest_ready',
              evidence_id: 'g07',
              artifact_path: 'docs/handoffs/g07/report.json',
              artifact_sha256: '4'.repeat(64),
              manifest_path: 'docs/handoffs/g07/manifest.json',
              manifest_sha256: '5'.repeat(64),
              integration_commit: '6'.repeat(40),
            },
          },
          blockers: [
            {
              code: 'production_pit_bundle_root_not_supplied',
              source: 'g06',
              root_cause: 'Production PIT is missing.',
              owner: 'data_steward',
              next_action: 'Publish immutable production PIT.',
            },
          ],
          gate: {
            first_blocker: 'production_pit_bundle_root_not_supplied',
            root_cause: 'Production PIT is missing.',
            owner: 'data_steward',
            next_action: 'Publish immutable production PIT.',
          },
          safety: {
            promotion_allowed: false,
            paper_allowed: false,
            live_allowed: false,
            private_endpoint_allowed: false,
            order_endpoint_allowed: false,
            broker_access_allowed: false,
            paper_runner_started: false,
            paper_queue_write_allowed: false,
            real_order_submitted: false,
            withdraw_allowed: false,
            network_used: false,
          },
          api_contract: {
            method: 'GET',
            path: '/api/research/us-equity/domain-read-model',
            cache_control: 'no-store',
            read_only: true,
            side_effects: false,
          },
          artifact_identity_sha256: '7'.repeat(64),
        },
      });
      return;
    }
    await route.fulfill({status: 404, json: {detail: 'not configured'}});
  });

  await page.goto('/');
  await page.locator('.ops-stage-tab').filter({hasText: '04'}).click();
  const view = page.locator('[data-testid="us-equity-domain-read-model"]');
  await expect(view).toContainText('当前 HEAD 运营证据');
  await expect(view).toContainText('blocked_do_not_promote_or_start_paper');
  await expect(view).toContainText('全部 false');
  await expect(view).toContainText('production_pit_bundle_root_not_supplied');
  await expect(page.locator('[data-view-zone="legacy-research-operations"]')).toContainText('历史研究操作台');
  const readModelRequests = requestedMethods.filter(item => item.includes('domain-read-model'));
  expect(readModelRequests.length).toBeGreaterThan(0);
  expect(readModelRequests.every(item => item === 'GET /api/research/us-equity/domain-read-model')).toBe(true);
  expect(requestedMethods.some(item => /POST .*?(sync|backtest|paper|reset)/.test(item))).toBe(false);
});
