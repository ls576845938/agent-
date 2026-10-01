export type USEquityDomainLayer = {
  status: string;
  freshness: 'current_head' | 'blocked';
  readiness_class: string;
  evidence_id: string;
  artifact_path: string;
  artifact_sha256: string;
  manifest_path: string;
  manifest_sha256: string;
  integration_commit: string;
};

export type USEquityDomainBlocker = {
  code: string;
  source: string;
  root_cause: string;
  owner: string;
  next_action: string;
};

export type USEquityDomainReadModel = {
  schema_version: 'us_equity_domain_read_model_v1';
  domain: 'us_equity';
  source_head: string;
  generated_at_utc: string;
  freshness: 'current_head' | 'blocked';
  status: 'blocked' | 'current_read_only';
  current_stage: string;
  readiness_class: string;
  gate_decision: string;
  promotion_evidence_ready: false;
  paper_ready: false;
  live_ready: false;
  layers: Record<string, USEquityDomainLayer>;
  blockers: USEquityDomainBlocker[];
  gate: {
    first_blocker: string;
    root_cause: string;
    owner: string;
    next_action: string;
  };
  safety: Record<string, false>;
  api_contract: {
    method: 'GET';
    path: '/api/research/us-equity/domain-read-model';
    cache_control: 'no-store';
    read_only: true;
    side_effects: false;
  };
  artifact_identity_sha256: string;
};

export async function fetchUSEquityDomainReadModel(
  request: typeof fetch = fetch,
): Promise<USEquityDomainReadModel> {
  const response = await request('/api/research/us-equity/domain-read-model', {
    method: 'GET',
    cache: 'no-store',
    headers: {'Cache-Control': 'no-store'},
  });
  if (!response.ok) {
    throw new Error(`us_equity_domain_read_model_http_${response.status}`);
  }
  return response.json() as Promise<USEquityDomainReadModel>;
}

export function blockedUSEquityDomainReadModel(
  code: string,
): USEquityDomainReadModel {
  return {
    schema_version: 'us_equity_domain_read_model_v1',
    domain: 'us_equity',
    source_head: '',
    generated_at_utc: '',
    freshness: 'blocked',
    status: 'blocked',
    current_stage: 'research_only_fail_closed',
    readiness_class: 'quality_checked',
    gate_decision: 'blocked_do_not_promote_or_start_paper',
    promotion_evidence_ready: false,
    paper_ready: false,
    live_ready: false,
    layers: {},
    blockers: [
      {
        code,
        source: 'frontend',
        root_cause: 'The current-HEAD operator projection is unavailable.',
        owner: 'integrator',
        next_action: 'Wire the US GET router and rebuild the current-HEAD read model.',
      },
    ],
    gate: {
      first_blocker: code,
      root_cause: 'The current-HEAD operator projection is unavailable.',
      owner: 'integrator',
      next_action: 'Wire the US GET router and rebuild the current-HEAD read model.',
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
    artifact_identity_sha256: '',
  };
}
