import {useEffect, useState} from 'react';
import {
  ArrowsOut,
  CaretDown,
  ChartLineUp,
  ClipboardText,
  Database,
  FileMagnifyingGlass,
  GearSix,
  List,
  Lock,
  MagnifyingGlass,
  ShieldCheck,
  SlidersHorizontal,
  SquaresFour,
  Target,
  WarningCircle,
  X,
} from '@phosphor-icons/react';

type WorkbenchContent = unknown;

export type WorkbenchTone = 'good' | 'warn' | 'bad' | 'info' | 'neutral';

export type WorkbenchMetaItem = {
  label: string;
  value: WorkbenchContent;
  tone?: WorkbenchTone;
};

export type WorkbenchTabItem = {
  key: string;
  index?: string;
  label: string;
  status?: WorkbenchContent;
  detail?: WorkbenchContent;
  tone?: WorkbenchTone;
};

export type WorkbenchMetricItem = {
  label: string;
  value: WorkbenchContent;
  detail?: WorkbenchContent;
  tone?: WorkbenchTone;
};

type TerminalMode = 'us-equity' | 'cn-equity' | 'research' | 'portfolio' | 'execution' | 'strategies' | 'architecture';
type WorkspaceLayout = 'split' | 'chart' | 'report';
type ToolKey = 'overview' | 'data' | 'risk' | 'evidence' | 'audit';
type DockKey = 'evidence' | 'contracts' | 'queue' | 'audit';
type ToolbarPanel = 'domain' | 'pipeline' | '';

type TerminalRow = {
  label: string;
  value: string;
  tone?: WorkbenchTone;
};

type TerminalPreset = {
  code: string;
  symbol: string;
  market: string;
  timeframe: string;
  canvasTitle: string;
  inspectorTitle: string;
  source: string;
  pipeline: string[];
  guardrails: TerminalRow[];
  dock: Record<DockKey, TerminalRow[]>;
};

type WorkbenchFrameProps = {
  children: WorkbenchContent;
  className?: string;
  testId?: string;
  mode?: TerminalMode;
};

type WorkbenchHeaderProps = {
  code: string;
  eyebrow: string;
  title: WorkbenchContent;
  description: WorkbenchContent;
  status: WorkbenchContent;
  statusTone?: WorkbenchTone;
  secondaryStatus?: WorkbenchContent;
  meta?: WorkbenchMetaItem[];
  actions?: WorkbenchContent;
};

type WorkbenchTabsProps = {
  items: WorkbenchTabItem[];
  activeKey: string;
  onChange: (key: string) => void;
  ariaLabel: string;
  itemClassName?: string;
};

type WorkbenchPanelProps = {
  children: WorkbenchContent;
  title?: WorkbenchContent;
  kicker?: WorkbenchContent;
  meta?: WorkbenchContent;
  actions?: WorkbenchContent;
  className?: string;
};

type WorkbenchNoticeProps = {
  children: WorkbenchContent;
  title?: WorkbenchContent;
  tone?: WorkbenchTone;
};

const TERMINAL_PRESETS: Record<TerminalMode, TerminalPreset> = {
  architecture: {
    code: 'MAP', symbol: 'SOURCE ARCHITECTURE', market: 'source-only · review in progress', timeframe: 'SNAPSHOT',
    canvasTitle: '源码架构与阅读记录', inspectorTitle: 'SOURCE REVIEW', source: 'versioned code-map catalog',
    pipeline: ['源码清单', '职责边界', '引用证据', '未读范围'],
    guardrails: [
      {label: '地图性质', value: '源码审阅，不是运行监控', tone: 'info'},
      {label: '全仓阅读', value: '进行中，未完成范围显式列出', tone: 'warn'},
      {label: '交易权限', value: '页面不授予任何权限', tone: 'warn'},
    ],
    dock: {
      evidence: [{label: '证据源', value: 'catalog.json · 路径 / 行号 / Git blob'}, {label: '运行验证', value: '本地图未执行', tone: 'warn'}],
      contracts: [{label: '阅读合同', value: '清单 ≠ 通读 ≠ 测试通过'}, {label: '执行合同', value: '保留 Portfolio / Risk / OMS / Ledger 权威边界'}],
      queue: [{label: '增量阅读', value: '补读未读文件；源码变化后重审'}, {label: 'M1', value: '暂停；M2—M4 不自动启动', tone: 'warn'}],
      audit: [{label: '版本', value: '基准提交 + 逐文件 blob'}, {label: '安全边界', value: '本页面只读文档，不是授权快照', tone: 'warn'}],
    },
  },
  'us-equity': {
    code: 'ETF26',
    symbol: 'US ETF RESEARCH',
    market: 'PIT-lite · research-only',
    timeframe: '1D',
    canvasTitle: '事件驱动研究与回测画布',
    inspectorTitle: 'RESEARCH CONTROL',
    source: 'shared ETF26 manifest resolver',
    pipeline: ['Data', 'Signal', 'Portfolio', 'Risk', 'Backtest', 'Ledger', 'Report'],
    guardrails: [
      {label: '策略输出', value: 'Signal / Forecast / TargetPosition', tone: 'info'},
      {label: 'Broker adapter', value: '禁止直接接触', tone: 'good'},
      {label: 'Promotion', value: '证据不足即 fail-closed', tone: 'warn'},
      {label: 'Live order', value: 'false', tone: 'bad'},
    ],
    dock: {
      evidence: [
        {label: '数据证据', value: 'manifest → resolver → current-HEAD', tone: 'info'},
        {label: '回测证据', value: 'cost-after + walk-forward + ledger', tone: 'info'},
        {label: '升级条件', value: 'fixture 永远不得 promotion', tone: 'warn'},
      ],
      contracts: [
        {label: '策略合同', value: 'Signal → Forecast → TargetPosition'},
        {label: '风控合同', value: 'TargetPosition → RiskDecision'},
        {label: '回测合同', value: 'Intent → Fill → Ledger → Report'},
      ],
      queue: [
        {label: '研究队列', value: '数据 → 信号 → 组合 → 成本后验证'},
        {label: '操作边界', value: '仅允许本地研究与证据重建', tone: 'good'},
        {label: '待办出口', value: '缺口必须带 owner、原因、证据路径'},
      ],
      audit: [
        {label: 'HEAD', value: '只接受 current-HEAD evidence'},
        {label: 'Lineage', value: 'data / params / cost / run / code version'},
        {label: '权限', value: 'paper=false · live=false', tone: 'bad'},
      ],
    },
  },
  'cn-equity': {
    code: 'CN',
    symbol: 'A-SHARE EVIDENCE',
    market: 'current-HEAD · GET-only · fail-closed',
    timeframe: 'LOCKED',
    canvasTitle: 'A 股六层证据与操作阻塞画布',
    inspectorTitle: 'CN EVIDENCE CONTROL',
    source: 'current-main CN domain read model',
    pipeline: ['Data / PIT', 'Market Rules', 'Backtest', 'OMS / Ledger', 'Replay', 'QMT Contract'],
    guardrails: [
      {label: 'Read model', value: 'GET + no-store + schema validation', tone: 'info'},
      {label: 'Current HEAD', value: '缺失或 mismatch 即 blocked', tone: 'warn'},
      {label: 'Paper / order', value: 'false', tone: 'bad'},
      {label: 'Live / private / network', value: 'false', tone: 'bad'},
    ],
    dock: {
      evidence: [
        {label: '层级证据', value: 'data → rules → backtest → OMS → replay → QMT'},
        {label: '证据身份', value: 'commit / input sha256 / generation hash'},
        {label: '缺口语义', value: 'missing / stale / unavailable 保持可见', tone: 'warn'},
      ],
      contracts: [
        {label: '市场合同', value: '涨跌停 / T+1 / lot / 可交易日'},
        {label: '执行合同', value: 'OrderIntent → OMS → Fill → Ledger'},
        {label: 'QMT 合同', value: 'SDK / network / broker 默认禁止'},
      ],
      queue: [
        {label: '阻塞队列', value: 'owner / detail / next action'},
        {label: '恢复顺序', value: '数据 → 规则 → 回测 → OMS → replay'},
        {label: '写入边界', value: '本页面不采集、不下单、不解锁', tone: 'good'},
      ],
      audit: [
        {label: 'HEAD', value: '只接受 current-HEAD evidence'},
        {label: 'Safety', value: 'all declared capabilities must remain false', tone: 'bad'},
        {label: 'Promotion', value: 'handoff 与 UI 不构成 promotion', tone: 'warn'},
      ],
    },
  },
  research: {
    code: 'RQ',
    symbol: 'RESEARCH REGISTRY',
    market: 'evidence · candidates · review',
    timeframe: 'CURRENT',
    canvasTitle: '研究证据与候选策略工作区',
    inspectorTitle: 'RESEARCH OPS',
    source: 'research registry read model',
    pipeline: ['Evidence', 'Candidate', 'Validation', 'Review', 'Decision'],
    guardrails: [
      {label: '候选状态', value: '与 promotion evidence 分离', tone: 'info'},
      {label: '人工复核', value: 'decision record 必填', tone: 'warn'},
      {label: '上游缺口', value: '继续 blocked', tone: 'warn'},
      {label: 'Live order', value: 'false', tone: 'bad'},
    ],
    dock: {
      evidence: [
        {label: '证据入口', value: '注册表与不可变报告'},
        {label: '可追溯性', value: 'candidate → run → artifact → HEAD'},
        {label: '状态语义', value: 'fixture / candidate / promotion 分层'},
      ],
      contracts: [
        {label: '研究合同', value: '数据与标签不得使用未来信息'},
        {label: '验证合同', value: 'walk-forward + cost stress'},
        {label: '审批合同', value: '人工记录不替代上游 gate'},
      ],
      queue: [
        {label: '任务队列', value: '只显示可审计的研究操作'},
        {label: '失败策略', value: '错误不静默降级', tone: 'warn'},
        {label: '写入边界', value: '无 broker / order / live'},
      ],
      audit: [
        {label: 'Registry', value: 'read model 与证据路径对齐'},
        {label: 'Decision', value: 'reviewer / time / ticket / outcome'},
        {label: '安全旗标', value: 'paper=false · live=false', tone: 'bad'},
      ],
    },
  },
  portfolio: {
    code: 'PF',
    symbol: 'PORTFOLIO & RISK',
    market: 'forecast allocation',
    timeframe: 'EOD',
    canvasTitle: '目标仓位与风险预算画布',
    inspectorTitle: 'PORTFOLIO CONTROL',
    source: 'portfolio status read model',
    pipeline: ['Forecast', 'TargetPosition', 'Exposure', 'RiskDecision', 'Rebalance'],
    guardrails: [
      {label: '组合输入', value: 'Forecast only', tone: 'info'},
      {label: '风险维度', value: 'vol / sector / style / liquidity'},
      {label: '成本压力', value: 'turnover + slippage', tone: 'warn'},
      {label: 'Order intent', value: '必须经 RiskDecision', tone: 'good'},
    ],
    dock: {
      evidence: [
        {label: '仓位证据', value: 'weights / exposures / cash'},
        {label: '成本证据', value: 'turnover / liquidity / stress'},
        {label: '推广条件', value: 'ledger 缺失即 blocked', tone: 'warn'},
      ],
      contracts: [
        {label: '输入合同', value: 'Forecast → allocator'},
        {label: '输出合同', value: 'TargetPosition'},
        {label: '风控合同', value: 'TargetPosition → RiskDecision'},
      ],
      queue: [
        {label: '再平衡队列', value: '只读展示，不创建订单'},
        {label: '风险队列', value: '暴露或流动性异常 fail-closed', tone: 'warn'},
        {label: '人工动作', value: '审批仅记录，不越过 gate'},
      ],
      audit: [
        {label: 'PnL 来源', value: 'fills / positions / cash ledger'},
        {label: 'Exposure', value: 'sector / style / concentration'},
        {label: 'Live order', value: 'false', tone: 'bad'},
      ],
    },
  },
  execution: {
    code: 'SAFE',
    symbol: '执行安全',
    market: 'Paper / OMS / 对账',
    timeframe: '已锁定',
    canvasTitle: 'OMS、账本与对账安全画布',
    inspectorTitle: '执行控制',
    source: '执行就绪只读模型',
    pipeline: ['风险批准意图', 'OMS', '成交', '账本', '对账'],
    guardrails: [
      {label: '输入边界', value: '仅接收 risk-approved intents', tone: 'good'},
      {label: 'OMS', value: '幂等 / 撤单 / 拒单 / 部分成交'},
      {label: 'Paper ledger', value: '必须独立运行', tone: 'warn'},
      {label: '实盘订单', value: 'false', tone: 'bad'},
    ],
    dock: {
      evidence: [
        {label: '订单证据', value: 'intent → order lifecycle'},
        {label: '成交证据', value: 'fills → positions → cash'},
        {label: '对账证据', value: 'ledger 与 broker snapshot 对齐'},
      ],
      contracts: [
        {label: 'OMS 合同', value: 'idempotency / reject / cancel / partial fill'},
        {label: '账本合同', value: 'PnL 不得从报告值反推'},
        {label: '权限合同', value: 'credential review ≠ live unlock'},
      ],
      queue: [
        {label: '操作队列', value: '阻塞原因与下一动作可追溯'},
        {label: 'Paper 启动', value: '依赖完整人工决策', tone: 'warn'},
        {label: 'Live 启动', value: '本页面永不自动解锁', tone: 'bad'},
      ],
      audit: [
        {label: '异常演练', value: '拒单 / 撤单 / outage / reconciliation'},
        {label: '独立账本', value: 'fills / positions / cash / daily report'},
        {label: '安全旗标', value: 'real_order=false · live=false', tone: 'bad'},
      ],
    },
  },
  strategies: {
    code: 'ST',
    symbol: 'STRATEGY REGISTRY',
    market: 'shared strategy interface',
    timeframe: 'VERSIONED',
    canvasTitle: '策略目录、参数与接口画布',
    inspectorTitle: 'REGISTRY CONTROL',
    source: 'strategy registry API',
    pipeline: ['Strategy', 'Signal', 'Forecast', 'TargetPosition', 'Evidence'],
    guardrails: [
      {label: '核心接口', value: 'backtest / paper / live 共享'},
      {label: '适配器', value: '执行权限必须隔离', tone: 'good'},
      {label: '参数证据', value: 'params hash + code version'},
      {label: 'Broker adapter', value: '策略层禁止接触', tone: 'bad'},
    ],
    dock: {
      evidence: [
        {label: '策略版本', value: 'strategy id / version / params hash'},
        {label: '运行版本', value: 'run id / code HEAD / data manifest'},
        {label: '推广状态', value: '目录可见不等于可 promotion', tone: 'warn'},
      ],
      contracts: [
        {label: '策略输出', value: 'Signal / Forecast / TargetPosition'},
        {label: '执行隔离', value: '无 broker adapter 依赖'},
        {label: '账本来源', value: 'Fill / Position / Cash'},
      ],
      queue: [
        {label: '筛选队列', value: '仅改变本地视图'},
        {label: '参数队列', value: '默认参数只读展示'},
        {label: '运行队列', value: '必须进入研究与验证服务'},
      ],
      audit: [
        {label: '变更记录', value: 'strategy / params / code version'},
        {label: '兼容边界', value: 'BTC 专属语义保持隔离'},
        {label: '安全旗标', value: 'paper=false · live=false', tone: 'bad'},
      ],
    },
  },
};

const TOOL_COPY: Record<ToolKey, {title: string; body: string}> = {
  overview: {title: '工作区总览', body: '查看当前域的完整处理链、状态与安全边界。'},
  data: {title: '数据与输入', body: '所有输入必须带来源、时间范围、schema 与 current-HEAD 证据。'},
  risk: {title: '风险边界', body: '任何数据、风控、账本、连接或凭证异常默认 fail-closed。'},
  evidence: {title: '证据链', body: '候选、报告与 promotion evidence 分层，不允许用 fixture 解锁。'},
  audit: {title: '审计与回放', body: '保留运行版本、证据路径、阻塞原因、owner 与下一动作。'},
};

const DOCK_LABELS: Record<DockKey, string> = {
  evidence: '证据链',
  contracts: '层级合同',
  queue: '操作队列',
  audit: '审计与安全',
};

const LAYOUT_LABELS: Record<WorkspaceLayout, string> = {
  split: '分屏',
  chart: '画布聚焦',
  report: '证据聚焦',
};

function classes(...values: Array<string | undefined | false>): string {
  return values.filter(Boolean).join(' ');
}

function modeFromClassName(className = ''): TerminalMode {
  if (className.includes('architecture-workbench')) return 'architecture';
  if (className.includes('cn-equity-workbench')) return 'cn-equity';
  if (className.includes('research-workbench')) return 'research';
  if (className.includes('portfolio-workbench')) return 'portfolio';
  if (className.includes('execution-workbench')) return 'execution';
  if (className.includes('strategy-workbench')) return 'strategies';
  return 'us-equity';
}

export function WorkbenchFrame({children, className, testId, mode: explicitMode}: WorkbenchFrameProps) {
  const mode = explicitMode ?? modeFromClassName(className);
  const preset = TERMINAL_PRESETS[mode];
  const [activeTool, setActiveTool] = useState<ToolKey>('overview');
  const [dockTab, setDockTab] = useState<DockKey>('evidence');
  const [dockOpen, setDockOpen] = useState(false);
  const [toolbarPanel, setToolbarPanel] = useState<ToolbarPanel>('');
  const [workspaceLayout, setWorkspaceLayout] = useState<WorkspaceLayout>('split');
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [interactionStatus, setInteractionStatus] = useState('高级审计检查器与底部证据坞默认折叠');

  useEffect(() => {
    document.body.classList.toggle('system-sidebar-collapsed', sidebarCollapsed);
    return () => document.body.classList.remove('system-sidebar-collapsed');
  }, [sidebarCollapsed]);

  const cycleLayout = () => {
    const next = workspaceLayout === 'split' ? 'chart' : workspaceLayout === 'chart' ? 'report' : 'split';
    setWorkspaceLayout(next);
    setInteractionStatus(`画布布局：${LAYOUT_LABELS[next]}`);
  };

  const selectLayout = (layout: WorkspaceLayout) => {
    setWorkspaceLayout(layout);
    setInteractionStatus(`画布布局：${LAYOUT_LABELS[layout]}`);
  };

  const toggleLayout = (layout: WorkspaceLayout) => {
    selectLayout(workspaceLayout === layout ? 'split' : layout);
  };

  const selectTool = (tool: ToolKey) => {
    setActiveTool(tool);
    setInspectorOpen(true);
    setInteractionStatus(`${TOOL_COPY[tool].title}检查器已打开`);
  };

  const toggleToolbarPanel = (panel: Exclude<ToolbarPanel, ''>) => {
    const next = toolbarPanel === panel ? '' : panel;
    setToolbarPanel(next);
    setInteractionStatus(
      next
        ? `${panel === 'domain' ? '工作域' : '领域处理链'}菜单已打开`
        : `${panel === 'domain' ? '工作域' : '领域处理链'}菜单已关闭`,
    );
  };

  const closeToolbarPanel = (panel: Exclude<ToolbarPanel, ''>) => {
    setToolbarPanel('');
    setInteractionStatus(`${panel === 'domain' ? '工作域' : '领域处理链'}菜单已关闭`);
  };

  const toggleInspector = () => {
    const next = !inspectorOpen;
    setInspectorOpen(next);
    setInteractionStatus(`控制台已${next ? '打开' : '关闭'}`);
  };

  const selectDock = (key: DockKey) => {
    const nextOpen = dockTab !== key || !dockOpen;
    setDockTab(key);
    setDockOpen(nextOpen);
    setInteractionStatus(`证据坞：${DOCK_LABELS[key]}已${nextOpen ? '展开' : '收起'}`);
  };

  const focusFirstControl = () => {
    const control = document.querySelector<HTMLElement>(
      '.system-tv-canvas-scroll input:not(:disabled), .system-tv-canvas-scroll select:not(:disabled), .system-tv-canvas-scroll button:not(:disabled)',
    );
    if (!control) {
      setInteractionStatus('当前画布没有可定位的控件');
      return;
    }
    control.focus();
    const label = control.getAttribute('aria-label')
      || control.getAttribute('title')
      || control.textContent?.trim()
      || control.tagName.toLowerCase();
    setInteractionStatus(`已定位：${label}`);
  };

  return (
    <main
      className={classes('system-workbench', 'system-tv-shell', `terminal-${mode}`, `layout-${workspaceLayout}`, className)}
      data-testid={testId}
      data-terminal-mode={mode}
    >
      <header className="tv-global-toolbar" data-testid="terminal-global-toolbar">
        <div className="tv-toolbar-cluster">
          <button
            type="button"
            className="tv-icon-button"
            title={sidebarCollapsed ? '展开主导航' : '收起主导航'}
            aria-pressed={sidebarCollapsed}
            onClick={() => {
              const next = !sidebarCollapsed;
              setSidebarCollapsed(next);
              setInteractionStatus(`主导航已${next ? '收起' : '展开'}`);
            }}
          >
            <List size={19} />
          </button>
          <button
            type="button"
            className={classes('tv-symbol-switcher', toolbarPanel === 'domain' && 'active')}
            aria-expanded={toolbarPanel === 'domain'}
            aria-controls="terminal-domain-menu"
            onClick={() => toggleToolbarPanel('domain')}
          >
            <span className="terminal-symbol-mark">{preset.code}</span>
            <strong>{preset.symbol}</strong>
            <CaretDown size={13} />
          </button>
          <button type="button" className="tv-icon-button" title="定位首个可操作控件" onClick={focusFirstControl}>
            <MagnifyingGlass size={18} />
          </button>
          <span className="tv-toolbar-separator" />
          <button
            type="button"
            className={classes('tv-toolbar-button', toolbarPanel === 'pipeline' && 'active')}
            aria-expanded={toolbarPanel === 'pipeline'}
            aria-controls="terminal-pipeline-menu"
            onClick={() => toggleToolbarPanel('pipeline')}
          >
            {preset.timeframe}<CaretDown size={12} />
          </button>
          <button
            type="button"
            className={classes('tv-icon-button', workspaceLayout === 'chart' && 'active')}
            title="主画布聚焦"
            aria-pressed={workspaceLayout === 'chart'}
            onClick={() => toggleLayout('chart')}
          >
            <ChartLineUp size={19} />
          </button>
          <button
            type="button"
            className={classes('tv-toolbar-button', activeTool === 'evidence' && 'active')}
            aria-pressed={activeTool === 'evidence' && inspectorOpen}
            onClick={() => selectTool('evidence')}
          >
            <FileMagnifyingGlass size={18} />证据
          </button>
          <button
            type="button"
            className={classes('tv-toolbar-button', activeTool === 'risk' && 'active')}
            aria-pressed={activeTool === 'risk' && inspectorOpen}
            onClick={() => selectTool('risk')}
          >
            <ShieldCheck size={18} />风控
          </button>
        </div>

        <div className="tv-toolbar-cluster tv-toolbar-actions">
          <button
            type="button"
            className={classes('tv-icon-button', workspaceLayout === 'report' && 'active')}
            title="底部证据坞聚焦"
            aria-pressed={workspaceLayout === 'report'}
            onClick={() => toggleLayout('report')}
          >
            <SlidersHorizontal size={18} />
          </button>
          <button type="button" className="tv-icon-button" title="循环切换工作区布局" onClick={cycleLayout}>
            <SquaresFour size={18} />
          </button>
          <button
            type="button"
            className={classes('tv-icon-button', workspaceLayout === 'chart' && 'active')}
            title="画布全屏"
            aria-pressed={workspaceLayout === 'chart'}
            onClick={() => toggleLayout('chart')}
          >
            {workspaceLayout === 'chart' ? <X size={18} /> : <ArrowsOut size={18} />}
          </button>
          <button
            type="button"
            className={classes('tv-icon-button', activeTool === 'audit' && 'active')}
            title="审计检查器"
            aria-pressed={activeTool === 'audit' && inspectorOpen}
            onClick={() => selectTool('audit')}
          >
            <GearSix size={18} />
          </button>
          <button
            type="button"
            className={classes('tv-trade-panel-toggle', inspectorOpen && 'active')}
            aria-pressed={inspectorOpen}
            aria-expanded={inspectorOpen}
            aria-controls="terminal-inspector-panel"
            onClick={toggleInspector}
          >
            <ShieldCheck size={18} />控制台
          </button>
        </div>

        {toolbarPanel === 'domain' ? (
          <div id="terminal-domain-menu" className="tv-toolbar-popover terminal-toolbar-popover" data-testid="terminal-domain-menu">
            <div className="tv-popover-head">
              <div><Target size={18} /><strong>{preset.symbol}</strong></div>
              <button type="button" aria-label="关闭工作域菜单" onClick={() => closeToolbarPanel('domain')}><X size={16} /></button>
            </div>
            <dl>
              <div><dt>工作域</dt><dd>{preset.market}</dd></div>
              <div><dt>主画布</dt><dd>{preset.canvasTitle}</dd></div>
              <div><dt>只读来源</dt><dd>{preset.source}</dd></div>
            </dl>
          </div>
        ) : null}

        {toolbarPanel === 'pipeline' ? (
          <div id="terminal-pipeline-menu" className="tv-toolbar-popover terminal-toolbar-popover terminal-pipeline-popover" data-testid="terminal-pipeline-menu">
            <div className="tv-popover-head">
              <div><ChartLineUp size={18} /><strong>领域处理链</strong></div>
              <button type="button" aria-label="关闭领域处理链菜单" onClick={() => closeToolbarPanel('pipeline')}><X size={16} /></button>
            </div>
            <ol>
              {preset.pipeline.map((step, index) => (
                <li key={step}><span>{String(index + 1).padStart(2, '0')}</span><strong>{step}</strong></li>
              ))}
            </ol>
          </div>
        ) : null}
      </header>

      <div className={classes('tv-primary-grid', !inspectorOpen && 'console-collapsed')} data-testid="terminal-primary-grid">
        <section className="tv-chart-panel" data-testid="terminal-main-canvas">
          <div className="system-tv-canvas-toolbar">
            <div>
              <ChartLineUp size={17} />
              <strong>{preset.canvasTitle}</strong>
              <span>{preset.market}</span>
            </div>
            <div className="system-tv-layout-switcher" aria-label="画布布局">
              <button type="button" className={workspaceLayout === 'split' ? 'active' : ''} aria-pressed={workspaceLayout === 'split'} onClick={() => selectLayout('split')}>分屏</button>
              <button type="button" className={workspaceLayout === 'chart' ? 'active' : ''} aria-pressed={workspaceLayout === 'chart'} onClick={() => selectLayout('chart')}>画布</button>
              <button type="button" className={workspaceLayout === 'report' ? 'active' : ''} aria-pressed={workspaceLayout === 'report'} onClick={() => selectLayout('report')}>证据</button>
            </div>
          </div>
          <div className="system-tv-canvas-context">
            <span><Database size={14} />{preset.source}</span>
            <span><Target size={14} />{TOOL_COPY[activeTool].title}</span>
            <span className="terminal-interaction-status" role="status" aria-live="polite">{interactionStatus}</span>
              <span className="locked"><Lock size={14} />{mode === 'execution' ? 'Paper / Live 已锁定' : 'paper / live locked'}</span>
          </div>
          <div className="system-tv-canvas-scroll">{children}</div>
          <footer className="tv-chart-foot">
            <span>{mode === 'execution' ? 'QuantStation 终端 · 本地只读模型' : 'QuantStation terminal · local read model'}</span>
            <span>{mode === 'execution' ? '策略层无 broker adapter · 订单路径必须经风险 / OMS / 账本' : '策略层无 broker adapter · 订单路径必须经 Risk / OMS / Ledger'}</span>
            <span>{mode === 'execution' ? '实盘订单：FALSE' : 'LIVE ORDER: FALSE'}</span>
          </footer>
        </section>

        {inspectorOpen ? (
          <aside id="terminal-inspector-panel" className="tv-demo-console system-tv-inspector" aria-label={`${TOOL_COPY[activeTool].title}检查器`} data-testid="terminal-inspector">
            <header>
              <div>
                <small>{preset.inspectorTitle}</small>
                <strong>{TOOL_COPY[activeTool].title}</strong>
              </div>
            <span className="terminal-lock-badge"><Lock size={13} />{mode === 'execution' ? '已锁定' : 'LOCKED'}</span>
            </header>
            <section className="terminal-inspector-section">
              <div className="terminal-inspector-heading">
                <strong>当前检查器</strong>
                <span>只读</span>
              </div>
              <p>{TOOL_COPY[activeTool].body}</p>
            </section>
            <section className="terminal-inspector-section">
              <div className="terminal-inspector-heading">
                <strong>处理链</strong>
                <span>{preset.pipeline.length} 层</span>
              </div>
              <ol className="terminal-pipeline">
                {preset.pipeline.map((step, index) => (
                  <li key={step}>
                    <span>{String(index + 1).padStart(2, '0')}</span>
                    <strong>{step}</strong>
                  </li>
                ))}
              </ol>
            </section>
            <section className="terminal-inspector-section">
              <div className="terminal-inspector-heading">
                <strong>安全边界</strong>
                <span>fail-closed</span>
              </div>
              <div className="terminal-guardrail-grid">
                {preset.guardrails.map((row) => (
                  <div key={row.label} className={classes(row.tone && `tone-${row.tone}`)}>
                    <span>{row.label}</span>
                    <strong>{row.value}</strong>
                  </div>
                ))}
              </div>
            </section>
            <div className="terminal-inspector-warning">
              <WarningCircle size={16} />
              <span>任何 gate blocked 都不会自动解锁 paper 或 live。</span>
            </div>
          </aside>
        ) : null}
      </div>

      <section className={classes('tv-bottom-dock', !dockOpen && 'dock-collapsed')} data-testid="terminal-bottom-dock">
        <nav className="tv-bottom-tabs" aria-label="终端证据坞">
          {(Object.keys(DOCK_LABELS) as DockKey[]).map((key) => (
            <button
              key={key}
              type="button"
              className={dockTab === key ? 'active' : ''}
              aria-pressed={dockTab === key}
              aria-expanded={dockOpen && dockTab === key}
              aria-controls="terminal-dock-panel"
              onClick={() => selectDock(key)}
            >
              {DOCK_LABELS[key]}
            </button>
          ))}
        </nav>
        {dockOpen ? <div id="terminal-dock-panel" className="tv-dock-content">
          <header className="terminal-dock-commandbar">
            <div>
              <ClipboardText size={18} />
              <strong>{DOCK_LABELS[dockTab]}</strong>
              <span>{preset.symbol} · current local state</span>
            </div>
            <button type="button" className="terminal-dock-collapse" aria-label="收起证据坞" onClick={() => { setDockOpen(false); setInteractionStatus(`证据坞：${DOCK_LABELS[dockTab]}已收起`); }}><X size={16} />收起</button>
            <span className="terminal-research-only">{mode === 'execution' ? '仅只读校验' : 'RESEARCH ONLY'}</span>
          </header>
          <div className="terminal-dock-table">
            {preset.dock[dockTab].map((row) => (
              <div key={row.label} className={classes(row.tone && `tone-${row.tone}`)}>
                <span>{row.label}</span>
                <strong>{row.value}</strong>
                <small>{row.tone === 'bad' ? '保持冻结' : row.tone === 'warn' ? '需要证据' : '只读合同'}</small>
              </div>
            ))}
          </div>
        </div> : null}
      </section>
    </main>
  );
}

export function WorkbenchHeader({
  code,
  eyebrow,
  title,
  description,
  status,
  statusTone = 'neutral',
  secondaryStatus,
  meta = [],
  actions,
}: WorkbenchHeaderProps) {
  return (
    <section className="workbench-command-header tv-symbol-bar">
      <div className="workbench-identity tv-symbol-identity">
        <span className="workbench-code" aria-hidden="true">{code}</span>
        <div className="workbench-title-copy">
          <p>{eyebrow}</p>
          <h2>{title}</h2>
          <small>{description}</small>
        </div>
      </div>

      {meta.length ? (
        <div className="workbench-header-meta tv-provenance-strip">
          {meta.map((item) => (
            <div key={item.label} className={classes('workbench-meta-cell', item.tone && `tone-${item.tone}`)}>
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </div>
          ))}
        </div>
      ) : null}

      <div className="workbench-header-control">
        <div className="workbench-header-status">
          <span className={classes('workbench-status-pill', `tone-${statusTone}`)}>{status}</span>
          {secondaryStatus ? <span className="workbench-status-pill tone-neutral">{secondaryStatus}</span> : null}
        </div>
        {actions ? <div className="workbench-header-actions">{actions}</div> : null}
      </div>
    </section>
  );
}

export function WorkbenchTabs({items, activeKey, onChange, ariaLabel, itemClassName}: WorkbenchTabsProps) {
  const activeItem = items.find((item) => item.key === activeKey);
  return (
    <nav className="workbench-tabs" aria-label={ariaLabel}>
      {items.map((item, position) => {
        const active = item.key === activeKey;
        return (
          <button
            key={item.key}
            type="button"
            className={classes('workbench-tab', itemClassName, active && 'active', item.tone && `tone-${item.tone}`)}
            aria-pressed={active}
            onClick={() => onChange(item.key)}
          >
            <span className="workbench-tab-index">{item.index ?? String(position + 1).padStart(2, '0')}</span>
            <span className="workbench-tab-copy">
              <strong>{item.label}</strong>
              {item.status ? <small>{item.status}</small> : null}
            </span>
            {item.detail ? <span className="workbench-tab-detail">{item.detail}</span> : null}
          </button>
        );
      })}
      <span className="workbench-tab-feedback" role="status" aria-live="polite">
        当前视图：<strong>{activeItem?.label ?? activeKey}</strong>
      </span>
    </nav>
  );
}

export function WorkbenchMetricStrip({items}: {items: WorkbenchMetricItem[]}) {
  return (
    <section className="workbench-metric-strip">
      {items.map((item) => (
        <div key={item.label} className={classes('workbench-metric', item.tone && `tone-${item.tone}`)}>
          <span>{item.label}</span>
          <strong>{item.value}</strong>
          {item.detail ? <small>{item.detail}</small> : null}
        </div>
      ))}
    </section>
  );
}

export function WorkbenchFlow({items}: {items: WorkbenchMetricItem[]}) {
  return (
    <section className="workbench-flow" aria-label="系统处理链">
      {items.map((item, index) => (
        <div key={item.label} className={classes('workbench-flow-step', item.tone && `tone-${item.tone}`)}>
          <span>{String(index + 1).padStart(2, '0')}</span>
          <div>
            <strong>{item.label}</strong>
            <small>{item.value}</small>
          </div>
        </div>
      ))}
    </section>
  );
}

export function WorkbenchPanel({
  children,
  title,
  kicker,
  meta,
  actions,
  className,
}: WorkbenchPanelProps) {
  return (
    <section className={classes('workbench-panel', className)}>
      {title || kicker || meta || actions ? (
        <header className="workbench-panel-header">
          <div>
            {kicker ? <p>{kicker}</p> : null}
            {title ? <h3>{title}</h3> : null}
          </div>
          <div className="workbench-panel-tools">
            {meta ? <span>{meta}</span> : null}
            {actions}
          </div>
        </header>
      ) : null}
      <div className="workbench-panel-body">{children}</div>
    </section>
  );
}

export function WorkbenchNotice({children, title, tone = 'neutral'}: WorkbenchNoticeProps) {
  return (
    <div className={classes('workbench-notice', `tone-${tone}`)} role={tone === 'bad' ? 'alert' : 'status'}>
      {title ? <strong>{title}</strong> : null}
      <span>{children}</span>
    </div>
  );
}

export function WorkbenchEmptyState({children, title}: {children: WorkbenchContent; title: WorkbenchContent}) {
  return (
    <div className="workbench-empty-state">
      <strong>{title}</strong>
      <p>{children}</p>
    </div>
  );
}
