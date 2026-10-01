export const BTC_PANORAMA_DRAFT_SCHEMA = 'btc_panorama_personal_draft_v1';
export const BTC_PANORAMA_MAX_DRAFT_BYTES = 1_000_000;
export const BTC_PANORAMA_MAX_NODES = 300;
export const BTC_PANORAMA_MAX_EDGES = 1_000;

const MAX_ABS_COORDINATE = 100_000;
const MAX_DIMENSION = 10_000;

export type BtcPanoramaStoredNode = {
  id: string;
  type: 'panoramaGroup' | 'panoramaNode';
  parentId?: string;
  extent?: 'parent';
  position: {x: number; y: number};
  style: {width: number; height: number};
  data: {
    kind: 'group' | 'node';
    title: string;
    detail: string;
    original: boolean;
  };
};

export type BtcPanoramaStoredEdge = {
  id: string;
  source: string;
  target: string;
  label: string;
  data: {
    original: boolean;
    dashed: boolean;
    bidirectional: boolean;
  };
};

export type BtcPanoramaStoredDraft = {
  schemaVersion: typeof BTC_PANORAMA_DRAFT_SCHEMA;
  sourceHead: string;
  savedAt: string;
  verification: 'personal_unverified_draft';
  nodes: BtcPanoramaStoredNode[];
  edges: BtcPanoramaStoredEdge[];
};

type UnknownRecord = Record<string, unknown>;

const isRecord = (value: unknown): value is UnknownRecord =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const boundedFinite = (value: unknown, maxAbsolute: number) =>
  typeof value === 'number' && Number.isFinite(value) && Math.abs(value) <= maxAbsolute;

const validDimension = (value: unknown) =>
  typeof value === 'number' && Number.isFinite(value) && value >= 40 && value <= MAX_DIMENSION;

const validIdentifier = (value: unknown) =>
  typeof value === 'string' && value.length > 0 && value.length <= 120;

function invalid(message: string): never {
  throw new Error(message);
}

export function parseBtcPanoramaDraft(
  raw: string,
  expectedSourceHead: string,
  requiredGroupIds: readonly string[],
): BtcPanoramaStoredDraft {
  if (raw.length > BTC_PANORAMA_MAX_DRAFT_BYTES) invalid('本机草稿超过 1 MB 限制');
  const value: unknown = JSON.parse(raw);
  if (!isRecord(value)
    || value.schemaVersion !== BTC_PANORAMA_DRAFT_SCHEMA
    || value.sourceHead !== expectedSourceHead
    || value.verification !== 'personal_unverified_draft') {
    invalid('草稿版本、来源或核验类型不匹配');
  }
  if (typeof value.savedAt !== 'string' || value.savedAt.length > 64
    || !Number.isFinite(Date.parse(value.savedAt))) {
    invalid('草稿保存时间不合法');
  }
  if (!Array.isArray(value.nodes) || !Array.isArray(value.edges)
    || value.nodes.length > BTC_PANORAMA_MAX_NODES
    || value.edges.length > BTC_PANORAMA_MAX_EDGES) {
    invalid('草稿节点或连线数量不合法');
  }

  const requiredGroups = new Set(requiredGroupIds);
  if (requiredGroups.size !== requiredGroupIds.length || requiredGroups.size === 0) {
    invalid('原始职责分区定义不合法');
  }
  const ids = new Set<string>();
  const ordinaryNodeIds = new Set<string>();
  const seenGroups = new Set<string>();
  const nodes: BtcPanoramaStoredNode[] = [];

  for (const item of value.nodes) {
    if (!isRecord(item) || !validIdentifier(item.id) || ids.has(item.id as string)
      || !isRecord(item.position)
      || !boundedFinite(item.position.x, MAX_ABS_COORDINATE)
      || !boundedFinite(item.position.y, MAX_ABS_COORDINATE)
      || !isRecord(item.style)
      || !validDimension(item.style.width) || !validDimension(item.style.height)
      || !isRecord(item.data)
      || (item.data.kind !== 'group' && item.data.kind !== 'node')
      || typeof item.data.title !== 'string' || item.data.title.length > 500
      || typeof item.data.detail !== 'string' || item.data.detail.length > 4_000
      || typeof item.data.original !== 'boolean') {
      invalid('草稿包含无效节点');
    }
    const id = item.id as string;
    const isGroup = item.data.kind === 'group';
    if (isGroup) {
      if (item.type !== 'panoramaGroup' || !requiredGroups.has(id)
        || item.parentId !== undefined || item.extent !== undefined || seenGroups.has(id)) {
        invalid('草稿职责分区类型或标识不合法');
      }
      seenGroups.add(id);
    } else {
      if (item.type !== 'panoramaNode' || typeof item.parentId !== 'string'
        || !requiredGroups.has(item.parentId) || item.extent !== 'parent') {
        invalid('草稿业务节点类型或分区引用不合法');
      }
      ordinaryNodeIds.add(id);
    }
    ids.add(id);
    nodes.push({
      id,
      type: item.type as 'panoramaGroup' | 'panoramaNode',
      ...(isGroup ? {} : {parentId: item.parentId as string, extent: 'parent' as const}),
      position: {x: item.position.x as number, y: item.position.y as number},
      style: {width: item.style.width as number, height: item.style.height as number},
      data: {
        kind: item.data.kind,
        title: item.data.title,
        detail: item.data.detail,
        original: item.data.original,
      },
    });
  }
  if (seenGroups.size !== requiredGroups.size
    || [...requiredGroups].some(groupId => !seenGroups.has(groupId))) {
    invalid('草稿缺少原始 A-I 职责分区');
  }

  const edgeIds = new Set<string>();
  const edges: BtcPanoramaStoredEdge[] = [];
  for (const item of value.edges) {
    if (!isRecord(item) || !validIdentifier(item.id) || edgeIds.has(item.id as string)
      || typeof item.source !== 'string' || typeof item.target !== 'string'
      || item.source === item.target
      || !ordinaryNodeIds.has(item.source) || !ordinaryNodeIds.has(item.target)
      || typeof item.label !== 'string' || item.label.length > 1_000
      || !isRecord(item.data)
      || typeof item.data.original !== 'boolean'
      || typeof item.data.dashed !== 'boolean'
      || typeof item.data.bidirectional !== 'boolean') {
      invalid('草稿包含无效连线');
    }
    const id = item.id as string;
    edgeIds.add(id);
    edges.push({
      id,
      source: item.source,
      target: item.target,
      label: item.label,
      data: {
        original: item.data.original,
        dashed: item.data.dashed,
        bidirectional: item.data.bidirectional,
      },
    });
  }

  return {
    schemaVersion: BTC_PANORAMA_DRAFT_SCHEMA,
    sourceHead: expectedSourceHead,
    savedAt: value.savedAt,
    verification: 'personal_unverified_draft',
    nodes,
    edges,
  };
}
