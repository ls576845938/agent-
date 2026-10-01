import ELK from 'elkjs/lib/elk.bundled.js';

export type LayoutNodeLike = {
  id: string;
  parentId?: string;
  position: {x: number; y: number};
  style?: {width?: number | string; height?: number | string};
  data: {kind: 'group' | 'node'};
};

export type LayoutEdgeLike = {
  id: string;
  source: string;
  target: string;
  label?: unknown;
};

export type RoutePoint = {x: number; y: number};
export type EdgeRoute = {points: RoutePoint[]; labelX?: number; labelY?: number};

type Rect = {id: string; left: number; top: number; right: number; bottom: number};
type PlacedNode = LayoutNodeLike & {width: number; height: number; absoluteX: number; absoluteY: number};

const GROUP_POSITIONS: Record<string, [number, number]> = {
  'group-data': [1300, 60],
  'group-research': [1120, 850],
  'group-market': [60, 900],
  'group-delivery': [1810, 850],
  'group-decision': [1200, 1810],
  'group-authority': [2700, 1720],
  'group-environment': [2600, 2700],
  'group-ledger': [1370, 3060],
  'group-evidence': [60, 2200],
};

// The immutable 37-node baseline is checked in so opening the page does not run
// nine ELK jobs. ELK remains the explicit, undoable "rearrange" operation.
const BASELINE_GEOMETRY: Record<string, readonly [number, number, number, number]> = {
  'group-data': [1300, 60, 568, 722],
  'okx-history': [69, 374, 430, 130],
  dataset: [34, 558, 500, 130],
  'public-market': [34, 74, 430, 130],
  'account-facts': [34, 224, 430, 130],
  'group-research': [1120, 850, 568, 790],
  'factor-ast': [69, 74, 430, 130],
  'alpha-factory': [69, 258, 430, 130],
  'qlib-training': [69, 442, 430, 130],
  'sealed-research': [34, 626, 500, 130],
  'group-market': [60, 900, 1044, 572],
  'market-m1': [34, 74, 430, 130],
  'market-v2': [105.66666666666666, 224, 430, 130],
  'market-diagnostics': [34, 408, 430, 130],
  'market-entry-policy': [510, 408, 500, 130],
  'group-delivery': [1810, 850, 1044, 606],
  'package-validation': [34, 74, 500, 130],
  registration: [34, 258, 500, 130],
  'offline-job': [140.66666666666666, 442, 430, 130],
  'offline-disabled': [580, 258, 430, 130],
  'group-decision': [1200, 1810, 1180, 606],
  donchian: [34, 74, 340, 130],
  'donchian-policy': [34, 258, 340, 130],
  'legacy-qlib': [420, 74, 340, 130],
  'registered-inference': [806, 74, 340, 130],
  'candidate-policy': [476.6666666666667, 258, 340, 130],
  target: [90.66666666666667, 442, 340, 130],
  'group-authority': [2700, 1720, 568, 790],
  risk: [34, 74, 500, 130],
  guardian: [69, 258, 430, 130],
  oms: [69, 442, 430, 130],
  dispatcher: [56.5, 626, 455, 130],
  'group-environment': [2600, 2700, 1001, 606],
  offline: [418.6666666666667, 74, 500, 130],
  demo: [61, 258, 430, 130],
  protection: [537, 258, 430, 130],
  events: [36, 442, 480, 130],
  'group-ledger': [1370, 3060, 1114, 422],
  'ledger-uow': [117.33333333333334, 74, 500, 130],
  recovery: [580, 258, 500, 130],
  economics: [34, 258, 500, 130],
  'group-evidence': [60, 2200, 1044, 681],
  trace: [34, 74, 500, 155],
  readonly: [34, 283, 500, 155],
  frontend: [140.66666666666666, 492, 430, 155],
  'readonly-boundary': [580, 283, 430, 155],
};

const GROUP_PADDING = {top: 74, left: 34, bottom: 34, right: 34};
const NODE_CLEARANCE = 12;
const LABEL_HEIGHT = 30;
const DETAILED_ROUTER_NODE_LIMIT = 80;
const DETAILED_ROUTER_EDGE_LIMIT = 120;

const numberStyle = (value: number | string | undefined, fallback: number) => {
  const result = Number(value);
  return Number.isFinite(result) && result > 0 ? result : fallback;
};

export function applyBtcPanoramaBaselineGeometry<TNode extends LayoutNodeLike>(nodes: readonly TNode[]) {
  return nodes.map(node => {
    const geometry = BASELINE_GEOMETRY[node.id];
    if (!geometry) throw new Error(`missing BTC panorama baseline geometry: ${node.id}`);
    return {
      ...node,
      position: {x: geometry[0], y: geometry[1]},
      style: {...node.style, width: geometry[2], height: geometry[3]},
    };
  }) as TNode[];
}

const compact = (points: RoutePoint[]) => points.filter((point, index) => {
  if (index > 0 && point.x === points[index - 1].x && point.y === points[index - 1].y) return false;
  if (index === 0 || index === points.length - 1) return true;
  const previous = points[index - 1];
  const next = points[index + 1];
  return !((previous.x === point.x && point.x === next.x) || (previous.y === point.y && point.y === next.y));
});

const intersectsRect = (a: RoutePoint, b: RoutePoint, rect: Rect) => {
  if (a.x === b.x) {
    const low = Math.min(a.y, b.y);
    const high = Math.max(a.y, b.y);
    return a.x > rect.left && a.x < rect.right && high > rect.top && low < rect.bottom;
  }
  const low = Math.min(a.x, b.x);
  const high = Math.max(a.x, b.x);
  return a.y > rect.top && a.y < rect.bottom && high > rect.left && low < rect.right;
};

const overlaps = (left: Rect, right: Rect) => left.right > right.left && left.left < right.right
  && left.bottom > right.top && left.top < right.bottom;

const edgeKey = (a: RoutePoint, b: RoutePoint) => a.x === b.x
  ? `v:${a.x}:${Math.min(a.y, b.y)}:${Math.max(a.y, b.y)}`
  : `h:${a.y}:${Math.min(a.x, b.x)}:${Math.max(a.x, b.x)}`;

function placedNodes(nodes: readonly LayoutNodeLike[]) {
  const groups = new Map(nodes.filter(node => node.data.kind === 'group').map(node => [node.id, node]));
  return nodes.filter(node => node.data.kind === 'node').map(node => {
    const parent = node.parentId ? groups.get(node.parentId) : undefined;
    return {
      ...node,
      width: numberStyle(node.style?.width, 360),
      height: numberStyle(node.style?.height, 130),
      absoluteX: node.position.x + (parent?.position.x ?? 0),
      absoluteY: node.position.y + (parent?.position.y ?? 0),
    };
  });
}

function obstacles(nodes: readonly LayoutNodeLike[]) {
  const ordinary = placedNodes(nodes);
  const nodeRects: Rect[] = ordinary.map(node => ({
    id: node.id,
    left: node.absoluteX - NODE_CLEARANCE,
    top: node.absoluteY - NODE_CLEARANCE,
    right: node.absoluteX + node.width + NODE_CLEARANCE,
    bottom: node.absoluteY + node.height + NODE_CLEARANCE,
  }));
  const titleRects: Rect[] = nodes.filter(node => node.data.kind === 'group').map(node => ({
    id: `${node.id}:title`,
    left: node.position.x + 8,
    top: node.position.y + 8,
    right: node.position.x + numberStyle(node.style?.width, 400) - 8,
    bottom: node.position.y + 58,
  }));
  return {ordinary, nodeRects, titleRects};
}

function chooseAnchors(source: PlacedNode, target: PlacedNode) {
  const sourceCenter = {x: source.absoluteX + source.width / 2, y: source.absoluteY + source.height / 2};
  const targetCenter = {x: target.absoluteX + target.width / 2, y: target.absoluteY + target.height / 2};
  if (targetCenter.y > sourceCenter.y + 80) {
    return {
      start: {x: sourceCenter.x, y: source.absoluteY + source.height},
      end: {x: targetCenter.x, y: target.absoluteY},
    };
  }
  return {
    start: {x: source.absoluteX + source.width, y: sourceCenter.y},
    end: {x: target.absoluteX, y: targetCenter.y},
  };
}

function routeOne(
  source: PlacedNode,
  target: PlacedNode,
  allRects: readonly Rect[],
  occupied: Map<string, number>,
) {
  const {start, end} = chooseAnchors(source, target);
  const activeRects = allRects.filter(rect => rect.id !== source.id && rect.id !== target.id);
  const minimumX = Math.min(18, start.x - 50, end.x - 50, ...activeRects.map(rect => rect.left - 20));
  const maximumX = Math.max(3730, start.x + 50, end.x + 50, ...activeRects.map(rect => rect.right + 20));
  const minimumY = Math.min(18, start.y - 50, end.y - 50, ...activeRects.map(rect => rect.top - 20));
  const maximumY = Math.max(3540, start.y + 50, end.y + 50, ...activeRects.map(rect => rect.bottom + 20));
  const xs = [...new Set([minimumX, maximumX, start.x, end.x, ...activeRects.flatMap(rect => [rect.left, rect.right])])].sort((a, b) => a - b);
  const ys = [...new Set([minimumY, maximumY, start.y, end.y, ...activeRects.flatMap(rect => [rect.top, rect.bottom])])].sort((a, b) => a - b);
  const xIndex = new Map(xs.map((value, index) => [value, index]));
  const yIndex = new Map(ys.map((value, index) => [value, index]));
  const startKey = `${xIndex.get(start.x)},${yIndex.get(start.y)},s`;
  type QueueItem = {x: number; y: number; direction: 'h' | 'v' | 's'; cost: number; priority: number; key: string};
  const queue: QueueItem[] = [];
  const pushQueue = (item: QueueItem) => {
    queue.push(item);
    let index = queue.length - 1;
    while (index > 0) {
      const parent = Math.floor((index - 1) / 2);
      if (queue[parent].priority <= item.priority) break;
      queue[index] = queue[parent];
      index = parent;
    }
    queue[index] = item;
  };
  const popQueue = () => {
    const first = queue[0];
    const last = queue.pop();
    if (!queue.length || !last) return first;
    let index = 0;
    while (true) {
      const left = index * 2 + 1;
      const right = left + 1;
      if (left >= queue.length) break;
      const child = right < queue.length && queue[right].priority < queue[left].priority ? right : left;
      if (queue[child].priority >= last.priority) break;
      queue[index] = queue[child];
      index = child;
    }
    queue[index] = last;
    return first;
  };
  pushQueue({x: xIndex.get(start.x)!, y: yIndex.get(start.y)!, direction: 's', cost: 0, priority: 0, key: startKey});
  const distance = new Map([[startKey, 0]]);
  const previous = new Map<string, string>();
  let finalKey: string | undefined;

  while (queue.length) {
    const current = popQueue()!;
    if (current.cost !== distance.get(current.key)) continue;
    if (xs[current.x] === end.x && ys[current.y] === end.y) {
      finalKey = current.key;
      break;
    }
    const candidates = [
      [current.x - 1, current.y, 'h'], [current.x + 1, current.y, 'h'],
      [current.x, current.y - 1, 'v'], [current.x, current.y + 1, 'v'],
    ] as const;
    for (const [nextX, nextY, direction] of candidates) {
      if (nextX < 0 || nextY < 0 || nextX >= xs.length || nextY >= ys.length) continue;
      const a = {x: xs[current.x], y: ys[current.y]};
      const b = {x: xs[nextX], y: ys[nextY]};
      if (activeRects.some(rect => intersectsRect(a, b, rect))) continue;
      const segmentLength = Math.abs(a.x - b.x) + Math.abs(a.y - b.y);
      const turn = current.direction !== 's' && current.direction !== direction ? 75 : 0;
      const congestion = (occupied.get(edgeKey(a, b)) ?? 0) * 95;
      const cost = current.cost + segmentLength + turn + congestion;
      const key = `${nextX},${nextY},${direction}`;
      if (cost >= (distance.get(key) ?? Number.POSITIVE_INFINITY)) continue;
      distance.set(key, cost);
      previous.set(key, current.key);
      const heuristic = Math.abs(xs[nextX] - end.x) + Math.abs(ys[nextY] - end.y);
      pushQueue({x: nextX, y: nextY, direction, cost, priority: cost + heuristic, key});
    }
  }
  if (!finalKey) throw new Error(`无法为 ${source.id} → ${target.id} 找到避障正交路径`);
  const reverse: RoutePoint[] = [];
  let cursor: string | undefined = finalKey;
  while (cursor) {
    const [xi, yi] = cursor.split(',').map(Number);
    reverse.push({x: xs[xi], y: ys[yi]});
    cursor = previous.get(cursor);
  }
  const points = compact(reverse.reverse());
  for (let index = 1; index < points.length; index += 1) {
    const key = edgeKey(points[index - 1], points[index]);
    occupied.set(key, (occupied.get(key) ?? 0) + 1);
  }
  return points;
}

function placeLabel(label: string, points: readonly RoutePoint[], blocked: readonly Rect[]) {
  const width = Math.min(430, Math.max(120, [...label].length * 14 + 24));
  const candidates = points.slice(1).map((point, index) => {
    const previous = points[index];
    return {
      a: previous,
      b: point,
      length: Math.abs(previous.x - point.x) + Math.abs(previous.y - point.y),
    };
  }).sort((left, right) => right.length - left.length);
  for (const candidate of candidates) {
    for (const fraction of [0.5, 0.25, 0.75]) {
      for (const offset of [0, -26, 26, -48, 48]) {
        const horizontal = candidate.a.y === candidate.b.y;
        const x = candidate.a.x + (candidate.b.x - candidate.a.x) * fraction + (horizontal ? 0 : offset);
        const y = candidate.a.y + (candidate.b.y - candidate.a.y) * fraction + (horizontal ? offset : 0);
        const rect = {id: 'label', left: x - width / 2, right: x + width / 2, top: y - LABEL_HEIGHT / 2, bottom: y + LABEL_HEIGHT / 2};
        if (!blocked.some(obstacle => overlaps(rect, obstacle))) return {labelX: x, labelY: y};
      }
    }
  }
  throw new Error(`连线标签“${label}”没有可用的避障位置`);
}

export function routeBtcPanoramaEdges(
  nodes: readonly LayoutNodeLike[],
  edges: readonly LayoutEdgeLike[],
  options: {forceSimplified?: boolean} = {},
) {
  const {ordinary, nodeRects, titleRects} = obstacles(nodes);
  const byId = new Map(ordinary.map(node => [node.id, node]));
  const blocked = [...nodeRects, ...titleRects];
  const occupied = new Map<string, number>();
  const routes = new Map<string, EdgeRoute>();
  const detailed = !options.forceSimplified && !usesSimplifiedPanoramaRouting(nodes, edges);
  for (const edge of edges) {
    const source = byId.get(edge.source);
    const target = byId.get(edge.target);
    if (!source || !target || source.id === target.id) continue;
    const points = detailed
      ? routeOne(source, target, blocked, occupied)
      : compact([
        chooseAnchors(source, target).start,
        {x: chooseAnchors(source, target).start.x, y: chooseAnchors(source, target).end.y},
        chooseAnchors(source, target).end,
      ]);
    routes.set(edge.id, {
      points,
      ...(edge.label ? detailed
        ? placeLabel(String(edge.label), points, blocked)
        : {labelX: points[Math.floor(points.length / 2)].x, labelY: points[Math.floor(points.length / 2)].y} : {}),
    });
  }
  return routes;
}

export function usesSimplifiedPanoramaRouting(nodes: readonly LayoutNodeLike[], edges: readonly LayoutEdgeLike[]) {
  return nodes.filter(node => node.data.kind === 'node').length > DETAILED_ROUTER_NODE_LIMIT
    || edges.length > DETAILED_ROUTER_EDGE_LIMIT;
}

export async function arrangeBtcPanorama<TNode extends LayoutNodeLike, TEdge extends LayoutEdgeLike>(
  nodes: readonly TNode[],
  edges: readonly TEdge[],
) {
  const elk = new ELK();
  const groups = nodes.filter(node => node.data.kind === 'group');
  const arranged = nodes.map(node => ({...node, position: {...node.position}, style: {...node.style}})) as TNode[];
  const byId = new Map(arranged.map(node => [node.id, node]));
  for (const group of groups) {
    const children = arranged.filter(node => node.parentId === group.id);
    const childIds = new Set(children.map(node => node.id));
    const graph = await elk.layout({
      id: group.id,
      layoutOptions: {
        'elk.algorithm': 'layered',
        'elk.direction': 'DOWN',
        'elk.edgeRouting': 'ORTHOGONAL',
        'elk.padding': `[top=${GROUP_PADDING.top},left=${GROUP_PADDING.left},bottom=${GROUP_PADDING.bottom},right=${GROUP_PADDING.right}]`,
        'elk.spacing.nodeNode': '46',
        'elk.spacing.edgeNode': '26',
        'elk.layered.spacing.nodeNodeBetweenLayers': '54',
        'elk.layered.considerModelOrder.strategy': 'NODES_AND_EDGES',
        'elk.layered.cycleBreaking.strategy': 'GREEDY_MODEL_ORDER',
      },
      children: children.map(node => ({
        id: node.id,
        width: numberStyle(node.style?.width, 360),
        height: numberStyle(node.style?.height, 130),
      })),
      edges: edges.filter(edge => childIds.has(edge.source) && childIds.has(edge.target))
        .map(edge => ({id: edge.id, sources: [edge.source], targets: [edge.target]})),
    }) as {width?: number; height?: number; children?: Array<{id: string; x?: number; y?: number}>};
    const position = GROUP_POSITIONS[group.id] ?? [group.position.x, group.position.y];
    const arrangedGroup = byId.get(group.id)!;
    arrangedGroup.position = {x: position[0], y: position[1]};
    arrangedGroup.style = {width: graph.width ?? 480, height: graph.height ?? 420};
    for (const child of graph.children ?? []) {
      const target = byId.get(child.id);
      if (target) target.position = {x: child.x ?? 0, y: child.y ?? 0};
    }
  }
  return {nodes: arranged, routes: routeBtcPanoramaEdges(arranged, edges)};
}

export function inspectBtcPanoramaRoutes(
  nodes: readonly LayoutNodeLike[],
  edges: readonly LayoutEdgeLike[],
  routes: ReadonlyMap<string, EdgeRoute>,
) {
  const {nodeRects, titleRects} = obstacles(nodes);
  const collisions: string[] = [];
  for (const edge of edges) {
    const route = routes.get(edge.id);
    if (!route) {
      collisions.push(`${edge.id}:missing-route`);
      continue;
    }
    const blocked = [...nodeRects.filter(rect => rect.id !== edge.source && rect.id !== edge.target), ...titleRects];
    for (let index = 1; index < route.points.length; index += 1) {
      if (blocked.some(rect => intersectsRect(route.points[index - 1], route.points[index], rect))) {
        collisions.push(`${edge.id}:segment-${index}`);
      }
    }
    if (edge.label && route.labelX != null && route.labelY != null) {
      const width = Math.min(430, Math.max(120, [...String(edge.label)].length * 14 + 24));
      const labelRect = {id: edge.id, left: route.labelX - width / 2, right: route.labelX + width / 2, top: route.labelY - LABEL_HEIGHT / 2, bottom: route.labelY + LABEL_HEIGHT / 2};
      if ([...nodeRects, ...titleRects].some(rect => overlaps(labelRect, rect))) collisions.push(`${edge.id}:label`);
    }
  }
  return collisions;
}
