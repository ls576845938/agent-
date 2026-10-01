import {useEffect, useRef, useState} from 'react';
import {
  addEdge,
  Background,
  BaseEdge,
  EdgeLabelRenderer,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState,
} from '@xyflow/react';
import type {
  Connection,
  Edge,
  EdgeChange,
  EdgeMouseHandler,
  EdgeProps,
  Node,
  NodeChange,
  NodeMouseHandler,
  NodeProps,
  OnNodeDrag,
  ReactFlowInstance,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {btcPanoramaNodeCount, btcSystemPanorama} from './btcPanoramaData';
import {
  applyBtcPanoramaBaselineGeometry,
  arrangeBtcPanorama,
  routeBtcPanoramaEdges,
  usesSimplifiedPanoramaRouting,
} from './btcPanoramaLayout';
import type {EdgeRoute} from './btcPanoramaLayout';
import {
  BTC_PANORAMA_DRAFT_SCHEMA,
  BTC_PANORAMA_MAX_DRAFT_BYTES,
  parseBtcPanoramaDraft,
} from './btcPanoramaDraft';
import type {
  BtcPanoramaStoredDraft,
  BtcPanoramaStoredEdge,
  BtcPanoramaStoredNode,
} from './btcPanoramaDraft';
import './btc-system-panorama.css';

const STORAGE_KEY = 'quantstation:architecture:btc-panorama-draft:v1';
const HISTORY_LIMIT = 50;
const EDGE_COLOR = '#91a9c2';
const EDGE_LABEL_COLOR = '#dbeafe';
const EDGE_LABEL_BACKGROUND = '#111c2a';
const EDGE_LABEL_BORDER = '#3a526d';

type PanoramaNodeData = {
  kind: 'group' | 'node';
  title: string;
  detail: string;
  original: boolean;
};
type PanoramaNode = Node<PanoramaNodeData>;
type PanoramaEdgeData = {original: boolean; dashed: boolean; bidirectional: boolean; route?: EdgeRoute};
type PanoramaEdge = Edge<PanoramaEdgeData>;
type Snapshot = {nodes: PanoramaNode[]; edges: PanoramaEdge[]};

const clone = <T,>(value: T): T => structuredClone(value);
const edgeStyle = (dashed: boolean) => ({
  stroke: EDGE_COLOR,
  strokeWidth: 2,
  strokeDasharray: dashed ? '8 7' : undefined,
});

function createInitialNodes(): PanoramaNode[] {
  return btcSystemPanorama.groups.flatMap(group => {
    const groupId = `group-${group.id}`;
    const frame: PanoramaNode = {
      id: groupId,
      type: 'panoramaGroup',
      position: {x: group.x, y: group.y},
      style: {width: group.width, height: group.height},
      data: {kind: 'group', title: group.title, detail: '', original: true},
    };
    const children: PanoramaNode[] = group.nodes.map(node => ({
      id: node.id,
      type: 'panoramaNode',
      parentId: groupId,
      extent: 'parent',
      position: {x: node.x - group.x, y: node.y - group.y},
      style: {width: node.width, height: node.height},
      data: {kind: 'node', title: node.title, detail: node.detail, original: true},
    }));
    return [frame, ...children];
  });
}

function createInitialEdges(): PanoramaEdge[] {
  return btcSystemPanorama.edges.map(edge => ({
    id: edge.id,
    source: edge.from,
    target: edge.to,
    type: 'panoramaEdge',
    label: edge.label ?? '',
    markerEnd: {type: MarkerType.ArrowClosed, color: EDGE_COLOR},
    markerStart: edge.both ? {type: MarkerType.ArrowClosed, color: EDGE_COLOR} : undefined,
    style: edgeStyle(edge.style === 'dashed'),
    labelStyle: {fill: EDGE_LABEL_COLOR, fontWeight: 650, fontSize: 13},
    labelBgStyle: {fill: EDGE_LABEL_BACKGROUND, stroke: EDGE_LABEL_BORDER},
    labelBgPadding: [7, 4],
    labelBgBorderRadius: 12,
    data: {original: true, dashed: edge.style === 'dashed', bidirectional: Boolean(edge.both)},
  }));
}

const BASELINE_NODES = applyBtcPanoramaBaselineGeometry(createInitialNodes());
const baselineEdgeSources = createInitialEdges();
const baselineRoutes = routeBtcPanoramaEdges(BASELINE_NODES, baselineEdgeSources);
const BASELINE_EDGES = baselineEdgeSources.map(edge => ({
  ...edge,
  data: {...edge.data!, route: baselineRoutes.get(edge.id)},
}));
const REQUIRED_GROUP_IDS = BASELINE_NODES
  .filter(node => node.data.kind === 'group')
  .map(node => node.id);

function PanoramaRoutedEdge({id, data, label, markerEnd, markerStart, selected, style, sourceX, sourceY, targetX, targetY}: EdgeProps<PanoramaEdge>) {
  const points = data?.route?.points ?? [{x: sourceX, y: sourceY}, {x: targetX, y: targetY}];
  const path = points.map((point, index) => `${index ? 'L' : 'M'} ${point.x} ${point.y}`).join(' ');
  const labelX = data?.route?.labelX;
  const labelY = data?.route?.labelY;
  return <>
    <BaseEdge id={id} path={path} markerEnd={markerEnd} markerStart={markerStart}
      style={style} interactionWidth={24} />
    {label && labelX != null && labelY != null ? <EdgeLabelRenderer>
      <div className={`btc-panorama-edge-label ${selected ? 'is-selected' : ''}`}
        style={{transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`}}
        aria-hidden="true">{String(label)}</div>
    </EdgeLabelRenderer> : null}
  </>;
}

function PanoramaGroupNode({data, selected}: NodeProps<PanoramaNode>) {
  return <div className={`btc-flow-group ${selected ? 'is-selected' : ''}`} data-panorama-group>
    <strong>{data.title}</strong>
  </div>;
}

function PanoramaArchitectureNode({data, selected}: NodeProps<PanoramaNode>) {
  return <div className={`btc-flow-node ${selected ? 'is-selected' : ''}`} data-panorama-node>
    <Handle type="target" position={Position.Left} id="target-left" />
    <Handle type="target" position={Position.Top} id="target-top" />
    <strong>{data.title}</strong><span>{data.detail}</span>
    <Handle type="source" position={Position.Right} id="source-right" />
    <Handle type="source" position={Position.Bottom} id="source-bottom" />
  </div>;
}

const nodeTypes = {panoramaGroup: PanoramaGroupNode, panoramaNode: PanoramaArchitectureNode};
const edgeTypes = {panoramaEdge: PanoramaRoutedEdge};

const withRoutes = (nodes: PanoramaNode[], edges: PanoramaEdge[]) => {
  const routes = routeBtcPanoramaEdges(nodes, edges);
  return edges.map(edge => ({...edge, type: 'panoramaEdge', data: {...edge.data!, route: routes.get(edge.id)}}));
};

const routeSubsetSafely = (nodes: PanoramaNode[], edges: PanoramaEdge[], edgeIds: Set<string>) => {
  const subset = edges.filter(edge => edgeIds.has(edge.id));
  let simplified = false;
  let routes: Map<string, EdgeRoute>;
  try {
    routes = routeBtcPanoramaEdges(nodes, subset);
  } catch {
    simplified = true;
    routes = routeBtcPanoramaEdges(nodes, subset, {forceSimplified: true});
  }
  return {
    simplified,
    edges: edges.map(edge => routes.has(edge.id)
      ? {...edge, type: 'panoramaEdge', data: {...edge.data!, route: routes.get(edge.id)}}
      : edge),
  };
};

const hydrateNodes = (nodes: BtcPanoramaStoredNode[]): PanoramaNode[] => nodes.map(node => ({
  ...node,
  ...(node.data.kind === 'node' ? {expandParent: true} : {}),
}));

const hydrateEdges = (edges: BtcPanoramaStoredEdge[]): PanoramaEdge[] => edges.map(edge => ({
  ...edge,
  type: 'panoramaEdge',
  markerEnd: {type: MarkerType.ArrowClosed, color: EDGE_COLOR},
  markerStart: edge.data.bidirectional ? {type: MarkerType.ArrowClosed, color: EDGE_COLOR} : undefined,
  style: edgeStyle(edge.data.dashed),
  labelStyle: {fill: EDGE_LABEL_COLOR, fontWeight: 650, fontSize: 13},
  labelBgStyle: {fill: EDGE_LABEL_BACKGROUND, stroke: EDGE_LABEL_BORDER},
  labelBgPadding: [7, 4],
  labelBgBorderRadius: 12,
}));

const storeNodes = (nodes: PanoramaNode[]): BtcPanoramaStoredNode[] => nodes.map(node => ({
  id: node.id,
  type: node.data.kind === 'group' ? 'panoramaGroup' : 'panoramaNode',
  ...(node.data.kind === 'node' ? {parentId: node.parentId, extent: 'parent' as const} : {}),
  position: {x: node.position.x, y: node.position.y},
  style: {width: Number(node.style?.width), height: Number(node.style?.height)},
  data: {...node.data},
}));

const storeEdges = (edges: PanoramaEdge[]): BtcPanoramaStoredEdge[] => edges.map(edge => ({
  id: edge.id,
  source: edge.source,
  target: edge.target,
  label: String(edge.label ?? ''),
  data: {
    original: edge.data?.original ?? false,
    dashed: edge.data?.dashed ?? false,
    bidirectional: edge.data?.bidirectional ?? false,
  },
}));

export function BtcSystemPanorama() {
  const [nodes, setNodes, onNodesChangeBase] = useNodesState<PanoramaNode>(clone(BASELINE_NODES));
  const [edges, setEdges, onEdgesChangeBase] = useEdgesState<PanoramaEdge>(clone(BASELINE_EDGES));
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [linkSource, setLinkSource] = useState(BASELINE_NODES.find(node => node.data.kind === 'node')?.id ?? '');
  const [linkTarget, setLinkTarget] = useState(BASELINE_NODES.filter(node => node.data.kind === 'node')[1]?.id ?? '');
  const [zoom, setZoom] = useState(1);
  const [draftDirty, setDraftDirty] = useState(false);
  const [layoutBusy, setLayoutBusy] = useState(true);
  const [status, setStatus] = useState('原始核验版本，尚未读取本机草稿。');
  const [undoStack, setUndoStack] = useState<Snapshot[]>([]);
  const [redoStack, setRedoStack] = useState<Snapshot[]>([]);
  const flowRef = useRef<ReactFlowInstance<PanoramaNode, PanoramaEdge> | null>(null);
  const dragSnapshotRef = useRef<Snapshot | null>(null);
  const layoutRequestRef = useRef(0);

  const fitPanoramaAfterRender = async (duration: number) => {
    await new Promise<void>(resolve => window.requestAnimationFrame(() => resolve()));
    await flowRef.current?.fitView({padding: 0.06, duration});
  };

  const snapshot = (): Snapshot => ({nodes: clone(nodes), edges: clone(edges)});
  const checkpoint = (value = snapshot()) => {
    setUndoStack(previous => [...previous, value].slice(-HISTORY_LIMIT));
    setRedoStack([]);
  };
  const markChanged = (message = '个人草稿已修改，尚未保存、未经代码核验。') => {
    layoutRequestRef.current += 1;
    setLayoutBusy(false);
    setDraftDirty(true);
    setStatus(message);
  };

  useEffect(() => {
    let active = true;
    const applyBaseline = (message: string) => {
      layoutRequestRef.current += 1;
      setNodes(clone(BASELINE_NODES));
      setEdges(clone(BASELINE_EDGES));
      setStatus(message);
      setLayoutBusy(false);
      window.requestAnimationFrame(() => {
        if (active) flowRef.current?.fitView({padding: 0.06, duration: 0});
      });
    };
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (!raw) {
        applyBaseline('当前显示原始核验版本；暂无本机个人草稿。');
      } else {
        const draft = parseBtcPanoramaDraft(raw, btcSystemPanorama.sourceHead, REQUIRED_GROUP_IDS);
        const draftNodes = hydrateNodes(draft.nodes);
        const draftEdges = hydrateEdges(draft.edges);
        setNodes(draftNodes);
        setLayoutBusy(false);
        try {
          setEdges(withRoutes(draftNodes, draftEdges));
          setStatus(usesSimplifiedPanoramaRouting(draftNodes, draftEdges)
            ? `已读取大型个人草稿（${draft.savedAt}），位置保持原样；当前使用简化直角路由，可显式重新整理布局。`
            : `已读取本机个人草稿（${draft.savedAt}），位置保持原样；可显式重新整理布局。`);
        } catch (error) {
          setEdges(draftEdges);
          setStatus(`已读取本机个人草稿（${draft.savedAt}），位置保持原样；连线路由需重新整理。${error instanceof Error ? error.message : ''}`);
        }
      }
    } catch (error) {
      applyBaseline(`本机草稿无法读取；已安全回到原始核验版本。${error instanceof Error ? error.message : ''}`);
    }
    return () => {
      active = false;
      layoutRequestRef.current += 1;
    };
  }, [setEdges, setNodes]);

  const selectedNode = nodes.find(node => node.id === selectedNodeId) ?? null;
  const selectedEdge = edges.find(edge => edge.id === selectedEdgeId) ?? null;
  const editableNodes = nodes.filter(node => node.data.kind === 'node');

  const onNodesChange = (changes: NodeChange<PanoramaNode>[]) => onNodesChangeBase(changes);
  const onEdgesChange = (changes: EdgeChange<PanoramaEdge>[]) => onEdgesChangeBase(changes);
  const selectNode = (node: PanoramaNode) => {
    setSelectedNodeId(node.id);
    setSelectedEdgeId(null);
  };
  const selectEdge = (edge: PanoramaEdge) => {
    setSelectedNodeId(null);
    setSelectedEdgeId(edge.id);
  };
  const clearSelection = () => {
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
  };
  const handleNodeClick: NodeMouseHandler<PanoramaNode> = (_event, node) => selectNode(node);
  const handleEdgeClick: EdgeMouseHandler<PanoramaEdge> = (_event, edge) => selectEdge(edge);
  const handleSelectionChange = ({edges: selectedEdges}: {edges: PanoramaEdge[]}) => {
    if (selectedEdges.length) selectEdge(selectedEdges[0]);
  };
  const handleNodeDragStart: OnNodeDrag<PanoramaNode> = (_event, node) => {
    if (layoutBusy) {
      dragSnapshotRef.current = null;
      return;
    }
    layoutRequestRef.current += 1;
    setLayoutBusy(false);
    selectNode(node);
    dragSnapshotRef.current = snapshot();
  };
  const handleNodeDragStop: OnNodeDrag<PanoramaNode> = (_event, movedNode) => {
    if (layoutBusy) {
      dragSnapshotRef.current = null;
      return;
    }
    if (dragSnapshotRef.current) checkpoint(dragSnapshotRef.current);
    dragSnapshotRef.current = null;
    const nextNodes = nodes.map(node => node.id === movedNode.id ? {...node, position: {...movedNode.position}} : node);
    const incident = new Set(edges.filter(edge => edge.source === movedNode.id || edge.target === movedNode.id).map(edge => edge.id));
    const routed = routeSubsetSafely(nextNodes, edges, incident);
    setEdges(routed.edges);
    markChanged(routed.simplified
      ? '节点位置已调整；相邻连线已回退为简化直角路径，可用“重新整理布局”优化。'
      : '节点位置已调整，连线路径已刷新；尚未保存、未经代码核验。');
  };
  const isValidConnection = (connection: Connection | PanoramaEdge) => {
    const source = nodes.find(node => node.id === connection.source);
    const target = nodes.find(node => node.id === connection.target);
    return !layoutBusy && Boolean(source && target && source.data.kind === 'node' && target.data.kind === 'node' && source.id !== target.id);
  };
  const onConnect = (connection: Connection) => {
    if (layoutBusy || !isValidConnection(connection)) return;
    checkpoint();
    const newEdge: PanoramaEdge = {
      ...connection,
      id: `draft-edge-${Date.now()}`,
      label: '新连线',
      markerEnd: {type: MarkerType.ArrowClosed, color: EDGE_COLOR},
      style: edgeStyle(false),
      labelStyle: {fill: EDGE_LABEL_COLOR, fontWeight: 650, fontSize: 13},
      labelBgStyle: {fill: EDGE_LABEL_BACKGROUND, stroke: EDGE_LABEL_BORDER},
      labelBgPadding: [7, 4],
      labelBgBorderRadius: 12,
      data: {original: false, dashed: false, bidirectional: false},
    };
    const nextEdges = addEdge(newEdge, edges);
    const routed = routeSubsetSafely(nodes, nextEdges, new Set([newEdge.id]));
    setEdges(routed.edges);
    markChanged(routed.simplified
      ? '新连线已保留并使用简化直角路径；可用“重新整理布局”优化。'
      : undefined);
  };

  const updateNode = (field: 'title' | 'detail', value: string) => {
    if (!selectedNodeId) return;
    setNodes((current: PanoramaNode[]) => current.map((node: PanoramaNode) => node.id === selectedNodeId
      ? {...node, data: {...node.data, [field]: value.slice(0, field === 'title' ? 500 : 4_000)}} : node));
    markChanged();
  };
  const updateEdge = (field: 'label' | 'dashed', value: string | boolean) => {
    if (!selectedEdgeId) return;
    setEdges((current: PanoramaEdge[]) => {
      const updated = current.map((edge: PanoramaEdge) => {
        if (edge.id !== selectedEdgeId) return edge;
        if (field === 'label') return {...edge, label: String(value).slice(0, 1_000)};
        return {
          ...edge,
          style: edgeStyle(Boolean(value)),
          data: {...edge.data!, dashed: Boolean(value)},
        };
      });
      return field === 'label'
        ? routeSubsetSafely(nodes, updated, new Set([selectedEdgeId])).edges
        : updated;
    });
    markChanged();
  };

  const addNode = () => {
    const selectedGroup = selectedNode?.data.kind === 'group' ? selectedNode.id : selectedNode?.parentId;
    const parentId = selectedGroup ?? nodes.find(node => node.data.kind === 'group')?.id;
    if (!parentId) return;
    const siblings = nodes.filter(node => node.parentId === parentId);
    const parent = nodes.find(node => node.id === parentId);
    const nextX = Math.max(34, ...siblings.map(node => node.position.x + Number(node.style?.width ?? 340))) + 46;
    const id = `draft-node-${Date.now()}`;
    checkpoint();
    const draftNode: PanoramaNode = {
      id,
      type: 'panoramaNode',
      parentId,
      extent: 'parent',
      expandParent: true,
      position: {x: nextX, y: 74},
      style: {width: 340, height: 120},
      data: {kind: 'node', title: '新节点', detail: '个人草稿，未经代码核验。', original: false},
    };
    const nextNodes = [
      ...nodes.map((node: PanoramaNode) => node.id === parentId
        ? {...node, selected: false, style: {...node.style, width: Math.max(Number(parent?.style?.width ?? 0), nextX + 374)}}
        : {...node, selected: false}),
      {...draftNode, selected: true},
    ];
    setNodes(nextNodes);
    setEdges((currentEdges: PanoramaEdge[]) => currentEdges.map(edge => ({...edge, selected: false})));
    setSelectedNodeId(id);
    setSelectedEdgeId(null);
    markChanged();
  };
  const deleteSelection = () => {
    if (selectedNode?.data.kind === 'group') {
      setStatus('原始 A–I 职责分区不在本轮编辑范围；可删除其中节点或恢复原始版本。');
      return;
    }
    if (!selectedNodeId && !selectedEdgeId) return;
    checkpoint();
    if (selectedNodeId) {
      const nextNodes = nodes.filter((node: PanoramaNode) => node.id !== selectedNodeId);
      setNodes(nextNodes);
      setEdges((currentEdges: PanoramaEdge[]) => currentEdges.filter(edge => edge.source !== selectedNodeId && edge.target !== selectedNodeId));
    } else if (selectedEdgeId) setEdges((current: PanoramaEdge[]) => current.filter((edge: PanoramaEdge) => edge.id !== selectedEdgeId));
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
    markChanged();
  };
  const addLinkFromSelectors = () => {
    if (!linkSource || !linkTarget || linkSource === linkTarget) {
      setStatus('请选择两个不同的节点作为起点和终点。');
      return;
    }
    onConnect({source: linkSource, target: linkTarget, sourceHandle: null, targetHandle: null});
  };

  const undo = () => {
    const previous = undoStack.at(-1);
    if (!previous) return;
    setRedoStack(stack => [...stack, snapshot()].slice(-HISTORY_LIMIT));
    setUndoStack(stack => stack.slice(0, -1));
    setNodes(clone(previous.nodes));
    setEdges(clone(previous.edges));
    markChanged('已撤销上一次草稿编辑；尚未保存。');
  };
  const redo = () => {
    const next = redoStack.at(-1);
    if (!next) return;
    setUndoStack(stack => [...stack, snapshot()].slice(-HISTORY_LIMIT));
    setRedoStack(stack => stack.slice(0, -1));
    setNodes(clone(next.nodes));
    setEdges(clone(next.edges));
    markChanged('已重做草稿编辑；尚未保存。');
  };
  const applyArranged = async (sourceNodes: PanoramaNode[], sourceEdges: PanoramaEdge[], message: string) => {
    const request = ++layoutRequestRef.current;
    setLayoutBusy(true);
    setStatus('正在重新整理分层布局；不会自动保存本机草稿。');
    try {
      const arranged = await arrangeBtcPanorama(clone(sourceNodes), clone(sourceEdges));
      if (request !== layoutRequestRef.current) return;
      setNodes(arranged.nodes);
      setEdges(sourceEdges.map(edge => ({...edge, type: 'panoramaEdge', data: {...edge.data!, route: arranged.routes.get(edge.id)}})));
      setDraftDirty(true);
      await fitPanoramaAfterRender(250);
      if (request !== layoutRequestRef.current) return;
      setLayoutBusy(false);
      setStatus(message);
    } catch (error) {
      if (request !== layoutRequestRef.current) return;
      setLayoutBusy(false);
      setStatus(`重新整理失败，已保留原画布。${error instanceof Error ? error.message : ''}`);
    }
  };
  const rearrangeDraft = () => {
    if (!window.confirm('重新整理当前画布？节点与连线内容会保留，位置变化可撤销且不会自动保存。')) return;
    checkpoint();
    void applyArranged(nodes, edges, '已重新整理画布；点击“保存本机草稿”后刷新才生效，仍可撤销。');
  };
  const restoreBaseline = () => {
    if (!window.confirm('恢复 5542a542 原始核验版本？当前草稿会保留在撤销栈中，且不会立即覆盖 localStorage。')) return;
    checkpoint();
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
    const request = ++layoutRequestRef.current;
    setLayoutBusy(true);
    setStatus('正在恢复原始核验版本；不会自动保存本机草稿。');
    setNodes(clone(BASELINE_NODES));
    setEdges(clone(BASELINE_EDGES));
    setDraftDirty(true);
    void fitPanoramaAfterRender(0).then(() => {
      if (request !== layoutRequestRef.current) return;
      setLayoutBusy(false);
      setStatus('已恢复到画布；点击“保存本机草稿”后刷新才生效，仍可撤销。');
    }).catch(error => {
      if (request !== layoutRequestRef.current) return;
      setLayoutBusy(false);
      setStatus(`恢复视图失败，已保留原始核验内容。${error instanceof Error ? error.message : ''}`);
    });
  };

  const buildDraft = (): BtcPanoramaStoredDraft => ({
    schemaVersion: BTC_PANORAMA_DRAFT_SCHEMA,
    sourceHead: btcSystemPanorama.sourceHead,
    savedAt: new Date().toISOString(),
    verification: 'personal_unverified_draft',
    nodes: storeNodes(nodes),
    edges: storeEdges(edges),
  });
  const saveDraft = () => {
    try {
      const raw = JSON.stringify(buildDraft());
      if (raw.length > BTC_PANORAMA_MAX_DRAFT_BYTES) throw new Error('草稿超过 1 MB 限制');
      window.localStorage.setItem(STORAGE_KEY, raw);
      setDraftDirty(false);
      setStatus('本机个人草稿已保存；仍未经代码核验，不覆盖原始来源。');
    } catch (error) {
      setStatus(`保存失败，本机草稿未更新。${error instanceof Error ? error.message : ''}`);
    }
  };
  const exportDraft = () => {
    try {
      const blob = new Blob([JSON.stringify(buildDraft(), null, 2)], {type: 'application/json'});
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `btc-system-panorama-draft-${new Date().toISOString().slice(0, 10)}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
      setStatus('已导出个人草稿 JSON；文件仍是未经代码核验的文档草稿。');
    } catch (error) {
      setStatus(`导出失败。${error instanceof Error ? error.message : ''}`);
    }
  };

  return <section className="btc-panorama-panel" aria-label="BTC 系统完整架构图">
    <header className="btc-panorama-toolbar">
      <div>
        <p className="atlas-kicker">BTC SYSTEM PANORAMA / EDITABLE PERSONAL DRAFT</p>
        <h2>BTC 系统全景</h2>
      </div>
      <div className="btc-panorama-controls" role="group" aria-label="BTC 全景图缩放与草稿操作">
        <button type="button" disabled={layoutBusy} aria-label="缩小全景图" onClick={() => flowRef.current?.zoomOut({duration: 180})}>−</button>
        <output aria-label="BTC 全景图当前缩放比例">{Math.round(zoom * 100)}%</output>
        <button type="button" disabled={layoutBusy} aria-label="放大全景图" onClick={() => flowRef.current?.zoomIn({duration: 180})}>＋</button>
        <button type="button" disabled={layoutBusy} onClick={() => flowRef.current?.fitView({padding: 0.06, duration: 250})}>适应画布</button>
        <button type="button" disabled={layoutBusy} onClick={() => flowRef.current?.setViewport({x: 0, y: 0, zoom: 1}, {duration: 250})}>恢复 100%</button>
        <button type="button" disabled={layoutBusy || !undoStack.length} onClick={undo}>撤销</button>
        <button type="button" disabled={layoutBusy || !redoStack.length} onClick={redo}>重做</button>
        <button type="button" disabled={layoutBusy} onClick={rearrangeDraft}>重新整理布局</button>
        <button type="button" disabled={layoutBusy} onClick={saveDraft}>保存本机草稿</button>
        <button type="button" disabled={layoutBusy} onClick={exportDraft}>导出 JSON</button>
        <button type="button" disabled={layoutBusy} className="is-restore" onClick={restoreBaseline}>恢复原始版本</button>
      </div>
    </header>
    <p className={`btc-panorama-status ${draftDirty ? 'is-dirty' : ''}`} role="status">{status}</p>
    <div className="btc-panorama-editor">
      <div className="btc-panorama-viewport" data-testid="btc-panorama-viewport" aria-label="可编辑的 BTC 系统全景画布">
        <ReactFlow<PanoramaNode, PanoramaEdge>
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={handleNodeClick}
          onEdgeClick={handleEdgeClick}
          onSelectionChange={handleSelectionChange}
          onPaneClick={clearSelection}
          onConnect={onConnect}
          isValidConnection={isValidConnection}
          onInit={(instance: ReactFlowInstance<PanoramaNode, PanoramaEdge>) => {flowRef.current = instance;}}
          onMoveEnd={(_event: MouseEvent | TouchEvent | null, viewport: {zoom: number}) => setZoom(viewport.zoom)}
          onNodeDragStart={handleNodeDragStart}
          onNodeDragStop={handleNodeDragStop}
          fitView fitViewOptions={{padding: 0.06}}
          minZoom={0.12} maxZoom={1.6}
          deleteKeyCode={null}
          nodesConnectable={!layoutBusy}
          nodesDraggable={!layoutBusy}
          elementsSelectable={!layoutBusy}
          edgesReconnectable={false}
          panOnDrag={!layoutBusy}
          panOnScroll={!layoutBusy}
          selectionOnDrag={!layoutBusy}
          zoomOnScroll={!layoutBusy}
          zoomOnPinch={!layoutBusy}
          zoomOnDoubleClick={!layoutBusy}
          zoomActivationKeyCode={layoutBusy ? null : undefined}>
          <Background color="#26374a" gap={28} size={1} />
          <MiniMap pannable={!layoutBusy} zoomable={!layoutBusy} maskColor="rgba(4, 8, 14, .72)"
            nodeColor={(node: PanoramaNode) => node.data.kind === 'group' ? '#182a3d' : '#2d4863'} />
        </ReactFlow>
      </div>
      <aside className="btc-panorama-inspector" aria-label="BTC 全景图编辑面板" aria-busy={layoutBusy}>
        <fieldset className="btc-panorama-inspector-fields" disabled={layoutBusy}>
        <section>
          <h3>节点编辑</h3>
          {selectedNode ? <>
            <label>标题<input value={selectedNode.data.title} maxLength={500}
              onFocus={() => checkpoint()} onChange={(event: {target: {value: string}}) => updateNode('title', event.target.value)} /></label>
            {selectedNode.data.kind === 'node' ? <label>说明<textarea value={selectedNode.data.detail} maxLength={4_000} rows={5}
              onFocus={() => checkpoint()} onChange={(event: {target: {value: string}}) => updateNode('detail', event.target.value)} /></label> : null}
            <small>{selectedNode.data.original ? '原始快照节点；编辑后仅属于个人草稿。' : '个人草稿新增节点。'}</small>
          </> : <p>点击节点后编辑纯文本；可直接拖动节点。</p>}
          <div className="btc-panorama-inspector-actions">
            <button type="button" onClick={addNode}>在当前分区新增节点</button>
            <button type="button" disabled={!selectedNodeId && !selectedEdgeId} onClick={deleteSelection}>删除选中节点 / 连线</button>
          </div>
        </section>
        <section>
          <h3>连线编辑</h3>
          {selectedEdge ? <>
            <label>连线文案<input value={String(selectedEdge.label ?? '')} maxLength={1_000}
              onFocus={() => checkpoint()} onChange={(event: {target: {value: string}}) => updateEdge('label', event.target.value)} /></label>
            <label>线型<select value={selectedEdge.data?.dashed ? 'dashed' : 'solid'}
              onFocus={() => checkpoint()} onChange={(event: {target: {value: string}}) => updateEdge('dashed', event.target.value === 'dashed')}>
              <option value="solid">实线：已实现关系</option><option value="dashed">虚线：旁路 / 限定 / 未启用</option>
            </select></label>
          </> : null}
          <label>起点<select value={linkSource} onChange={(event: {target: {value: string}}) => setLinkSource(event.target.value)}>
            {editableNodes.map(node => <option key={node.id} value={node.id}>{node.data.title}</option>)}
          </select></label>
          <label>终点<select value={linkTarget} onChange={(event: {target: {value: string}}) => setLinkTarget(event.target.value)}>
            {editableNodes.map(node => <option key={node.id} value={node.id}>{node.data.title}</option>)}
          </select></label>
          <button type="button" onClick={addLinkFromSelectors}>新增连线</button>
        </section>
        <section className="btc-panorama-legend" aria-label="BTC 全景图图例">
          <span><i className="is-solid" />实现调用 / 数据关系</span>
          <span><i className="is-dashed" />旁路 / 限定 / 尚未启用</span>
          <span>{btcSystemPanorama.groups.length} 分区 · 原始 {btcPanoramaNodeCount} 节点 · {btcSystemPanorama.edges.length} 连线</span>
        </section>
        </fieldset>
      </aside>
    </div>
  </section>;
}
