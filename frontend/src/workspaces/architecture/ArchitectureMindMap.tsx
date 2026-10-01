import {useEffect, useMemo, useRef, useState} from 'react';
import {catalog} from './model';
import {architectureMindMap} from './mindmap';
import type {MindMapBranch, MindMapNode} from './mindmap';
import './architecture-mindmap.css';

const MIN_ZOOM = 0.62;
const MAX_ZOOM = 1.28;
const ZOOM_STEP = 0.1;
const ROOT = {x: 610, y: 410, width: 200, height: 100};
const BRANCH = {leftX: 380, rightX: 840, width: 200, height: 90};
const LEAF = {leftXs: [20, 195], rightXs: [1065, 1240], width: 160, height: 56, rowGap: 64};

type Point = {x: number; y: number};
type PositionedNode = {node: MindMapNode; x: number; y: number};

function clampZoom(value: number) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.round(value * 100) / 100));
}

function branchBox(branch: MindMapBranch) {
  return {
    x: branch.side === 'left' ? BRANCH.leftX : BRANCH.rightX,
    y: branch.y - BRANCH.height / 2,
  };
}

function positionedNodes(branch: MindMapBranch): PositionedNode[] {
  const columns = branch.side === 'left' ? LEAF.leftXs : LEAF.rightXs;
  const rows = Math.ceil(branch.nodes.length / 2);
  const startY = branch.y - ((rows - 1) * LEAF.rowGap) / 2 - LEAF.height / 2;
  return branch.nodes.map((node, index) => ({
    node,
    x: columns[index % 2],
    y: startY + Math.floor(index / 2) * LEAF.rowGap,
  }));
}

function curve(from: Point, to: Point) {
  const direction = to.x > from.x ? 1 : -1;
  const bend = Math.max(36, Math.abs(to.x - from.x) * 0.46);
  return `M ${from.x} ${from.y} C ${from.x + bend * direction} ${from.y}, ${to.x - bend * direction} ${to.y}, ${to.x} ${to.y}`;
}

export function ArchitectureMindMap({onSelectModule}: {onSelectModule: (moduleId: string) => void}) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const [zoom, setZoom] = useState(0.72);
  const moduleById = useMemo(() => new Map(catalog.modules.map(module => [module.id, module])), []);
  const setSafeZoom = (next: number) => setZoom(clampZoom(next));
  const fitCanvas = () => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const widthFit = (viewport.clientWidth - 24) / architectureMindMap.canvas.width;
    const heightFit = Math.min(720, Math.max(520, window.innerHeight - 300)) / architectureMindMap.canvas.height;
    setSafeZoom(Math.min(1, widthFit, heightFit));
    viewport.scrollTo({left: 0, top: 0, behavior: 'smooth'});
  };

  useEffect(() => {
    const frame = window.requestAnimationFrame(fitCanvas);
    return () => window.cancelAnimationFrame(frame);
  }, []);

  const resetCanvas = () => {
    setSafeZoom(1);
    viewportRef.current?.scrollTo({left: 0, top: 0, behavior: 'smooth'});
  };

  return <section className="mindmap-panel" aria-label="系统总览思维导图">
    <header className="mindmap-toolbar">
      <div>
        <p className="atlas-kicker">SYSTEM MIND MAP / RESPONSIBILITY OVERVIEW</p>
        <h2>{architectureMindMap.title}</h2>
        <p>从共享平台沿六条职责分支进入源码证据；点击叶节点查看原模块详情与文件清单。</p>
      </div>
      <div className="mindmap-controls" role="group" aria-label="思维导图缩放">
        <button type="button" aria-label="缩小总图" onClick={() => setSafeZoom(zoom - ZOOM_STEP)}>−</button>
        <output aria-label="当前缩放比例">{Math.round(zoom * 100)}%</output>
        <button type="button" aria-label="放大总图" onClick={() => setSafeZoom(zoom + ZOOM_STEP)}>＋</button>
        <button type="button" onClick={fitCanvas}>适应画布</button>
        <button type="button" onClick={resetCanvas}>恢复 100%</button>
      </div>
    </header>
    <div className="mindmap-scope-note" role="note">
      <strong>连线表示职责归属，不等于同一次运行已跑通调用链。</strong>
      <span>源码地图不是运行监控；V0—V3 当前进度见上方交付记录。市场状态 v2 已实现，M2 历史探索没有稳定增量，研究结果不会自动获得交易权限。</span>
    </div>
    <div className="mindmap-viewport" ref={viewportRef} data-testid="architecture-mindmap-viewport" tabIndex={0}
      aria-label="可滚动的系统架构总图">
      <div className="mindmap-stage" style={{
        width: architectureMindMap.canvas.width * zoom,
        height: architectureMindMap.canvas.height * zoom,
      }}>
        <div className="mindmap-canvas" data-testid="architecture-mindmap-canvas" style={{
          width: architectureMindMap.canvas.width,
          height: architectureMindMap.canvas.height,
          transform: `scale(${zoom})`,
        }}>
          <svg className="mindmap-lines" viewBox={`0 0 ${architectureMindMap.canvas.width} ${architectureMindMap.canvas.height}`}
            aria-hidden="true" focusable="false">
            {architectureMindMap.branches.map(branch => {
              const box = branchBox(branch);
              const rootPoint = {x: branch.side === 'left' ? ROOT.x : ROOT.x + ROOT.width, y: ROOT.y + ROOT.height / 2};
              const branchPoint = {x: branch.side === 'left' ? box.x + BRANCH.width : box.x, y: branch.y};
              return <g key={branch.id} style={{color: branch.color}}>
                <path className="mindmap-line mindmap-line--trunk" d={curve(rootPoint, branchPoint)} />
                {positionedNodes(branch).map(({node, x, y}) => {
                  const from = {x: branch.side === 'left' ? box.x : box.x + BRANCH.width, y: branch.y};
                  const to = {x: branch.side === 'left' ? x + LEAF.width : x, y: y + LEAF.height / 2};
                  return <path key={node.id} className={`mindmap-line ${node.status === 'planned' ? 'is-planned' : ''}`}
                    d={curve(from, to)} />;
                })}
              </g>;
            })}
          </svg>
          <div className="mindmap-root" style={{left: ROOT.x, top: ROOT.y, width: ROOT.width, height: ROOT.height}}>
            <span>SHARED CORE</span><strong>{architectureMindMap.root.label}</strong><small>{architectureMindMap.root.detail}</small>
          </div>
          {architectureMindMap.branches.map(branch => {
            const box = branchBox(branch);
            return <div key={branch.id} className="mindmap-branch-fragment">
              <div className="mindmap-branch" data-branch-id={branch.id} style={{
                left: box.x, top: box.y, width: BRANCH.width, height: BRANCH.height,
                borderColor: branch.color, '--mindmap-color': branch.color,
              }}>
                <strong>{branch.label}</strong><span>{branch.detail}</span>
              </div>
              {positionedNodes(branch).map(({node, x, y}) => {
                const mapped = moduleById.get(node.moduleId);
                return <button key={node.id} type="button" className={`mindmap-node ${node.status === 'planned' ? 'is-planned' : ''}`}
                  style={{left: x, top: y, width: LEAF.width, height: LEAF.height, '--mindmap-color': branch.color}}
                  data-testid={node.testId ?? `mindmap-node-${node.id}`}
                  data-module-id={node.moduleId}
                  aria-label={`${node.label}：${node.detail}。查看${mapped?.label ?? node.moduleId}源码证据`}
                  title={mapped ? `${mapped.purpose}\n注意：${mapped.caution}` : node.detail}
                  onClick={() => onSelectModule(node.moduleId)}>
                  <strong>{node.label}</strong><span>{node.detail}</span>
                  {node.status === 'planned' ? <em>PLANNED</em> : null}
                </button>;
              })}
            </div>;
          })}
        </div>
      </div>
    </div>
    <div className="mindmap-legend" aria-label="思维导图图例">
      <span><i className="mindmap-legend-solid" />源码已映射的职责节点</span>
      <span><i className="mindmap-legend-dashed" />拟建节点，仅表示计划</span>
      <span>点击叶节点 → 模块证据 → 来源文件清单</span>
    </div>
    <details className="mindmap-text-outline">
      <summary>查看纯文本结构</summary>
      <ul>{architectureMindMap.branches.map(branch => <li key={branch.id}><strong>{branch.label}</strong>
        <span>{branch.nodes.map(node => node.label).join(' → ')}</span></li>)}</ul>
    </details>
  </section>;
}
