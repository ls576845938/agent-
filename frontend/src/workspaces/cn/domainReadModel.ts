export const CN_DOMAIN_READ_MODEL_PATH =
  '/api/research/cn-equity/domain-read-model' as const;

export const CN_LAYER_IDS = [
  'data',
  'market_rules',
  'backtest',
  'oms',
  'replay',
  'qmt',
] as const;

export const CN_SAFETY_FLAG_KEYS = [
  'broker_access_allowed',
  'live_allowed',
  'order_endpoint_allowed',
  'paper_allowed',
  'paper_queue_allowed',
  'private_endpoint_allowed',
  'promotion_allowed',
  'qmt_sdk_allowed',
  'real_order_allowed',
  'withdraw_allowed',
] as const;

export const CN_WORKSPACE_INVARIANT_FLAGS = [
  'demo_allowed',
  'network_allowed',
  'secret_access_allowed',
] as const;

export type CNLayerId = (typeof CN_LAYER_IDS)[number];
export type CNSafetyFlagKey = (typeof CN_SAFETY_FLAG_KEYS)[number];
export type CNWorkspaceInvariantFlag =
  (typeof CN_WORKSPACE_INVARIANT_FLAGS)[number];

export type CNOperatorLayer = {
  status: 'blocked' | 'quality_checked';
  readiness_class:
    | 'quality_checked'
    | 'research_ready'
    | 'backtest_ready'
    | 'promotion_evidence_ready';
  source_event: string;
  source_path: string;
  source_sha256: string;
  deliverable_commit: string;
  gate_impact: 'none' | 'evidence_only' | 'requires_gate_rebuild' | 'blocks_gate';
  promotion_eligible: false;
  blockers: string[];
  classifications: string[];
};

export type CNOperatorBlocker = {
  code: string;
  owner: string;
  next_action: string;
  layer: CNLayerId | 'gate';
  detail: string;
};

export type CNOperatorReadModel = {
  schema_version: 'cn_equity_operator_read_model_v1';
  domain: 'cn_equity';
  owner: 'a_share_developer';
  code_commit: string;
  source_head: string;
  generated_at_utc: string;
  input_sha256: string;
  generation_hash: string;
  data_version: string;
  status: 'blocked' | 'current_read_only';
  decision: 'fail_closed' | 'read_only_review';
  readiness_class: 'quality_checked';
  promotion_evidence_ready: false;
  paper_ready: false;
  live_ready: false;
  current_stage: 'blocked_read_only' | 'manual_review';
  layers: Record<CNLayerId, CNOperatorLayer>;
  blockers: CNOperatorBlocker[];
  blocker_count: number;
  gate: {
    decision: 'blocked_fail_closed' | 'manual_review_required';
    owner: string;
    next_action: string;
    first_blocker: string;
  };
  safety: Record<CNSafetyFlagKey, false> & Record<string, false>;
  api_contract: {
    method: 'GET';
    path: typeof CN_DOMAIN_READ_MODEL_PATH;
    cache_control: 'no-store';
    read_only: true;
    side_effects: false;
    builder_triggered: false;
    order_path_registered: false;
  };
};

export type CNWorkspaceSafetyFlag = {
  key: CNSafetyFlagKey | CNWorkspaceInvariantFlag;
  value: false;
  source: 'current_head_read_model' | 'workspace_invariant';
};

export type CNWorkspaceReadModel = {
  availability: 'CURRENT_HEAD_API' | 'BACKEND_UNAVAILABLE' | 'CONTRACT_INVALID';
  availability_detail: string;
  freshness: 'CURRENT_HEAD' | 'BACKEND_UNAVAILABLE' | 'CONTRACT_INVALID';
  fail_closed: true;
  model: CNOperatorReadModel | null;
  code_commit: string;
  generated_at_utc: string;
  status: 'blocked' | 'current_read_only';
  decision: 'fail_closed' | 'read_only_review';
  current_stage: string;
  readiness_class: 'quality_checked';
  layers: Record<CNLayerId, CNOperatorLayer>;
  blockers: CNOperatorBlocker[];
  gate: {
    decision: string;
    owner: string;
    next_action: string;
    first_blocker: string;
  };
  safety_flags: CNWorkspaceSafetyFlag[];
  input_sha256: string;
  generation_hash: string;
};

export class CNReadModelContractError extends Error {
  constructor(public readonly code: string) {
    super(code);
    this.name = 'CNReadModelContractError';
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function requiredRecord(
  value: unknown,
  code: string,
): Record<string, unknown> {
  if (!isRecord(value)) throw new CNReadModelContractError(code);
  return value;
}

function requiredString(value: unknown, code: string): string {
  if (typeof value !== 'string' || value.trim() === '') {
    throw new CNReadModelContractError(code);
  }
  return value;
}

function requiredStringArray(value: unknown, code: string): string[] {
  if (
    !Array.isArray(value)
    || value.some(item => typeof item !== 'string')
  ) {
    throw new CNReadModelContractError(code);
  }
  return value as string[];
}

function assertExact(value: unknown, expected: unknown, code: string): void {
  if (value !== expected) throw new CNReadModelContractError(code);
}

function assertOneOf<T extends string>(
  value: unknown,
  options: readonly T[],
  code: string,
): asserts value is T {
  if (typeof value !== 'string' || !options.includes(value as T)) {
    throw new CNReadModelContractError(code);
  }
}

function assertCommit(value: unknown, code: string): asserts value is string {
  if (typeof value !== 'string' || !/^[0-9a-f]{40}$/.test(value)) {
    throw new CNReadModelContractError(code);
  }
}

function assertSha256(value: unknown, code: string): asserts value is string {
  if (typeof value !== 'string' || !/^[0-9a-f]{64}$/.test(value)) {
    throw new CNReadModelContractError(code);
  }
}

function parseLayer(value: unknown, layerId: CNLayerId): CNOperatorLayer {
  const layer = requiredRecord(value, `CN_LAYER_${layerId.toUpperCase()}_INVALID`);
  assertOneOf(
    layer.status,
    ['blocked', 'quality_checked'] as const,
    `CN_LAYER_${layerId.toUpperCase()}_STATUS_INVALID`,
  );
  assertOneOf(
    layer.readiness_class,
    [
      'quality_checked',
      'research_ready',
      'backtest_ready',
      'promotion_evidence_ready',
    ] as const,
    `CN_LAYER_${layerId.toUpperCase()}_READINESS_INVALID`,
  );
  assertSha256(
    layer.source_sha256,
    `CN_LAYER_${layerId.toUpperCase()}_HASH_INVALID`,
  );
  assertCommit(
    layer.deliverable_commit,
    `CN_LAYER_${layerId.toUpperCase()}_COMMIT_INVALID`,
  );
  assertOneOf(
    layer.gate_impact,
    ['none', 'evidence_only', 'requires_gate_rebuild', 'blocks_gate'] as const,
    `CN_LAYER_${layerId.toUpperCase()}_GATE_IMPACT_INVALID`,
  );
  assertExact(
    layer.promotion_eligible,
    false,
    `CN_LAYER_${layerId.toUpperCase()}_PROMOTION_NOT_FALSE`,
  );
  return {
    status: layer.status,
    readiness_class: layer.readiness_class,
    source_event: requiredString(
      layer.source_event,
      `CN_LAYER_${layerId.toUpperCase()}_EVENT_INVALID`,
    ),
    source_path: requiredString(
      layer.source_path,
      `CN_LAYER_${layerId.toUpperCase()}_PATH_INVALID`,
    ),
    source_sha256: layer.source_sha256,
    deliverable_commit: layer.deliverable_commit,
    gate_impact: layer.gate_impact,
    promotion_eligible: false,
    blockers: requiredStringArray(
      layer.blockers,
      `CN_LAYER_${layerId.toUpperCase()}_BLOCKERS_INVALID`,
    ),
    classifications: requiredStringArray(
      layer.classifications,
      `CN_LAYER_${layerId.toUpperCase()}_CLASSIFICATIONS_INVALID`,
    ),
  };
}

function parseBlocker(value: unknown): CNOperatorBlocker {
  const blocker = requiredRecord(value, 'CN_BLOCKER_INVALID');
  assertOneOf(
    blocker.layer,
    [...CN_LAYER_IDS, 'gate'] as const,
    'CN_BLOCKER_LAYER_INVALID',
  );
  return {
    code: requiredString(blocker.code, 'CN_BLOCKER_CODE_INVALID'),
    owner: requiredString(blocker.owner, 'CN_BLOCKER_OWNER_INVALID'),
    next_action: requiredString(
      blocker.next_action,
      'CN_BLOCKER_NEXT_ACTION_INVALID',
    ),
    layer: blocker.layer,
    detail: requiredString(blocker.detail, 'CN_BLOCKER_DETAIL_INVALID'),
  };
}

function parseSafety(value: unknown): CNOperatorReadModel['safety'] {
  const safety = requiredRecord(value, 'CN_SAFETY_INVALID');
  for (const key of CN_SAFETY_FLAG_KEYS) {
    assertExact(safety[key], false, `CN_SAFETY_${key.toUpperCase()}_NOT_FALSE`);
  }
  if (Object.values(safety).some(flag => flag !== false)) {
    throw new CNReadModelContractError('CN_SAFETY_UNKNOWN_FLAG_NOT_FALSE');
  }
  return safety as CNOperatorReadModel['safety'];
}

function safetyFlags(
  safety: CNOperatorReadModel['safety'] | null,
): CNWorkspaceSafetyFlag[] {
  return [
    ...CN_SAFETY_FLAG_KEYS.map(key => ({
      key,
      value: safety?.[key] === false ? false as const : false as const,
      source: 'current_head_read_model' as const,
    })),
    ...CN_WORKSPACE_INVARIANT_FLAGS.map(key => ({
      key,
      value: false as const,
      source: 'workspace_invariant' as const,
    })),
  ];
}

export function parseCNOperatorReadModel(
  value: unknown,
): CNOperatorReadModel {
  const model = requiredRecord(value, 'CN_READ_MODEL_INVALID');
  assertExact(
    model.schema_version,
    'cn_equity_operator_read_model_v1',
    'CN_SCHEMA_VERSION_INVALID',
  );
  assertExact(model.domain, 'cn_equity', 'CN_DOMAIN_INVALID');
  assertExact(model.owner, 'a_share_developer', 'CN_OWNER_INVALID');
  assertCommit(model.code_commit, 'CN_CODE_COMMIT_INVALID');
  assertCommit(model.source_head, 'CN_SOURCE_HEAD_INVALID');
  assertExact(model.code_commit, model.source_head, 'CN_CURRENT_HEAD_MISMATCH');
  assertSha256(model.input_sha256, 'CN_INPUT_HASH_INVALID');
  assertSha256(model.generation_hash, 'CN_GENERATION_HASH_INVALID');
  assertOneOf(
    model.status,
    ['blocked', 'current_read_only'] as const,
    'CN_STATUS_INVALID',
  );
  assertOneOf(
    model.decision,
    ['fail_closed', 'read_only_review'] as const,
    'CN_DECISION_INVALID',
  );
  assertExact(model.readiness_class, 'quality_checked', 'CN_READINESS_INVALID');
  assertExact(
    model.promotion_evidence_ready,
    false,
    'CN_PROMOTION_EVIDENCE_NOT_FALSE',
  );
  assertExact(model.paper_ready, false, 'CN_PAPER_NOT_FALSE');
  assertExact(model.live_ready, false, 'CN_LIVE_NOT_FALSE');
  assertOneOf(
    model.current_stage,
    ['blocked_read_only', 'manual_review'] as const,
    'CN_STAGE_INVALID',
  );

  const rawLayers = requiredRecord(model.layers, 'CN_LAYERS_INVALID');
  const layers = Object.fromEntries(
    CN_LAYER_IDS.map(layerId => [layerId, parseLayer(rawLayers[layerId], layerId)]),
  ) as Record<CNLayerId, CNOperatorLayer>;

  if (!Array.isArray(model.blockers)) {
    throw new CNReadModelContractError('CN_BLOCKERS_INVALID');
  }
  const blockers = model.blockers.map(parseBlocker);
  if (
    typeof model.blocker_count !== 'number'
    || model.blocker_count !== blockers.length
  ) {
    throw new CNReadModelContractError('CN_BLOCKER_COUNT_MISMATCH');
  }

  const gate = requiredRecord(model.gate, 'CN_GATE_INVALID');
  assertOneOf(
    gate.decision,
    ['blocked_fail_closed', 'manual_review_required'] as const,
    'CN_GATE_DECISION_INVALID',
  );
  const safety = parseSafety(model.safety);
  const api = requiredRecord(model.api_contract, 'CN_API_CONTRACT_INVALID');
  assertExact(api.method, 'GET', 'CN_API_METHOD_INVALID');
  assertExact(api.path, CN_DOMAIN_READ_MODEL_PATH, 'CN_API_PATH_INVALID');
  assertExact(api.cache_control, 'no-store', 'CN_API_CACHE_INVALID');
  assertExact(api.read_only, true, 'CN_API_READ_ONLY_INVALID');
  assertExact(api.side_effects, false, 'CN_API_SIDE_EFFECTS_INVALID');
  assertExact(api.builder_triggered, false, 'CN_API_BUILDER_INVALID');
  assertExact(api.order_path_registered, false, 'CN_API_ORDER_PATH_INVALID');

  return {
    schema_version: 'cn_equity_operator_read_model_v1',
    domain: 'cn_equity',
    owner: 'a_share_developer',
    code_commit: model.code_commit,
    source_head: model.source_head,
    generated_at_utc: requiredString(
      model.generated_at_utc,
      'CN_GENERATED_AT_INVALID',
    ),
    input_sha256: model.input_sha256,
    generation_hash: model.generation_hash,
    data_version: requiredString(model.data_version, 'CN_DATA_VERSION_INVALID'),
    status: model.status,
    decision: model.decision,
    readiness_class: 'quality_checked',
    promotion_evidence_ready: false,
    paper_ready: false,
    live_ready: false,
    current_stage: model.current_stage,
    layers,
    blockers,
    blocker_count: blockers.length,
    gate: {
      decision: gate.decision,
      owner: requiredString(gate.owner, 'CN_GATE_OWNER_INVALID'),
      next_action: requiredString(
        gate.next_action,
        'CN_GATE_NEXT_ACTION_INVALID',
      ),
      first_blocker: typeof gate.first_blocker === 'string'
        ? gate.first_blocker
        : '',
    },
    safety,
    api_contract: {
      method: 'GET',
      path: CN_DOMAIN_READ_MODEL_PATH,
      cache_control: 'no-store',
      read_only: true,
      side_effects: false,
      builder_triggered: false,
      order_path_registered: false,
    },
  };
}

function fallbackLayer(code: string): CNOperatorLayer {
  return {
    status: 'blocked',
    readiness_class: 'quality_checked',
    source_event: 'frontend_fail_closed_fallback',
    source_path: 'unavailable',
    source_sha256: '0'.repeat(64),
    deliverable_commit: '0'.repeat(40),
    gate_impact: 'blocks_gate',
    promotion_eligible: false,
    blockers: [code],
    classifications: ['frontend_fallback_not_evidence'],
  };
}

function fallbackBlocker(
  code: string,
  detail: string,
): CNOperatorBlocker {
  return {
    code,
    owner: 'integrator',
    next_action: 'restore_current_head_cn_read_model_get_contract',
    layer: 'gate',
    detail,
  };
}

export function failClosedCNWorkspaceModel(
  availability: 'BACKEND_UNAVAILABLE' | 'CONTRACT_INVALID',
  detail: string,
  upstreamCodes: string[] = [],
): CNWorkspaceReadModel {
  const blockerCodes = [
    availability,
    ...upstreamCodes.filter(code => code !== availability),
  ];
  const layers = Object.fromEntries(
    CN_LAYER_IDS.map(layerId => [layerId, fallbackLayer(availability)]),
  ) as Record<CNLayerId, CNOperatorLayer>;
  const blockers = blockerCodes.map(code => fallbackBlocker(code, detail));
  return {
    availability,
    availability_detail: detail,
    freshness: availability,
    fail_closed: true,
    model: null,
    code_commit: '',
    generated_at_utc: '',
    status: 'blocked',
    decision: 'fail_closed',
    current_stage: 'blocked_read_only',
    readiness_class: 'quality_checked',
    layers,
    blockers,
    gate: {
      decision: 'blocked_fail_closed',
      owner: 'integrator',
      next_action: 'restore_current_head_cn_read_model_get_contract',
      first_blocker: availability,
    },
    safety_flags: safetyFlags(null),
    input_sha256: '',
    generation_hash: '',
  };
}

export function projectCNWorkspaceModel(
  model: CNOperatorReadModel,
): CNWorkspaceReadModel {
  return {
    availability: 'CURRENT_HEAD_API',
    availability_detail: 'GET no-store · schema validated · zero-write contract',
    freshness: 'CURRENT_HEAD',
    fail_closed: true,
    model,
    code_commit: model.code_commit,
    generated_at_utc: model.generated_at_utc,
    status: model.status,
    decision: model.decision,
    current_stage: model.current_stage,
    readiness_class: model.readiness_class,
    layers: model.layers,
    blockers: model.blockers,
    gate: model.gate,
    safety_flags: safetyFlags(model.safety),
    input_sha256: model.input_sha256,
    generation_hash: model.generation_hash,
  };
}

function responseBlockerCodes(value: unknown): string[] {
  if (!isRecord(value) || !Array.isArray(value.blockers)) return [];
  return value.blockers.flatMap(item => {
    if (typeof item === 'string') return [item];
    if (isRecord(item) && typeof item.code === 'string') return [item.code];
    return [];
  });
}

export async function loadCNWorkspaceReadModel(
  request: typeof fetch = fetch,
): Promise<CNWorkspaceReadModel> {
  try {
    const response = await request(CN_DOMAIN_READ_MODEL_PATH, {
      method: 'GET',
      cache: 'no-store',
      headers: {
        Accept: 'application/json',
        'Cache-Control': 'no-store',
      },
    });
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      return failClosedCNWorkspaceModel(
        response.ok ? 'CONTRACT_INVALID' : 'BACKEND_UNAVAILABLE',
        `HTTP_${response.status}_NON_JSON`,
      );
    }
    if (!response.ok) {
      return failClosedCNWorkspaceModel(
        'BACKEND_UNAVAILABLE',
        `HTTP_${response.status}`,
        responseBlockerCodes(payload),
      );
    }
    if (
      !response.headers.get('cache-control')?.toLowerCase().includes('no-store')
    ) {
      return failClosedCNWorkspaceModel(
        'CONTRACT_INVALID',
        'CN_API_NO_STORE_HEADER_MISSING',
      );
    }
    try {
      return projectCNWorkspaceModel(parseCNOperatorReadModel(payload));
    } catch (error) {
      const detail = error instanceof CNReadModelContractError
        ? error.code
        : 'CN_READ_MODEL_CONTRACT_INVALID';
      return failClosedCNWorkspaceModel('CONTRACT_INVALID', detail);
    }
  } catch (error) {
    const detail = error instanceof Error ? error.message : 'FETCH_FAILED';
    return failClosedCNWorkspaceModel('BACKEND_UNAVAILABLE', detail);
  }
}
