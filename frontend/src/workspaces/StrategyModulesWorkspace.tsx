import {useEffect, useMemo, useState} from 'react';
import {QlibTraceExplorer} from './research/QlibDecisionTrace';
import {
  ArrowDown,
  ArrowRight,
  ChartBar,
  ChartLineUp,
  CheckCircle,
  Database,
  List,
  Lock,
  ShieldCheck,
  Target,
  TrendUp,
  WarningCircle,
} from '@phosphor-icons/react';

import {apiGet} from '../lib/api';
import type {BtcStrategyRegistryResponse} from '../lib/shared-types';
import {
  strategyAdapterLabel,
  strategyCapabilityText,
  strategyPresentationName,
  strategyVariantLabel,
} from '../lib/strategy-presentation';
import '../strategy-modules.css';

type MarketKey = 'crypto' | 'us' | 'cn';
type FamilyKey = 'btc-trend' | 'btc-options' | 'btc-funding' | 'us-factors' | 'us-portfolio' | 'us-events' | 'cn-pit' | 'cn-rules' | 'cn-replay';
type InstrumentKey = 'btc-usdt-swap' | 'us-research-universe' | 'cn-research-universe';
type StrategyKey = string;
type ModuleKey = 'hypothesis' | 'market-state' | 'failure-condition' | 'failure-detection' | 'position' | 'exit';
type ModuleStatus = '已登记' | '正在验证' | '待补';

type FamilyDefinition = {key: FamilyKey; label: string; shortLabel: string; focus: string};
type StrategyDefinition = {
  key: StrategyKey;
  strategyId: string;
  candidateId: string;
  strategyVersion: string;
  paramsHash: string;
  params?: Record<string, unknown>;
  variantLabel: string;
  canonicalName: string;
  label: string;
  description: string;
  availability: string;
  familyKey: FamilyKey;
  hypothesis: string;
  marketState: string;
  failureCondition: string;
  exit: string;
  evidence: string;
};
type InstrumentDefinition = {key: InstrumentKey; label: string; venue: string; strategies: StrategyDefinition[]};
type MarketDefinition = {key: MarketKey; label: string; subtitle: string; families: FamilyDefinition[]; instruments: InstrumentDefinition[]};
type ModuleDefinition = {key: ModuleKey; label: string; subtitle: string; icon: typeof Target; status: ModuleStatus};

const MARKET_DEFINITIONS: MarketDefinition[] = [
  {
    key: 'crypto', label: '加密资产', subtitle: 'BTC 永续研究：先验证数据、风险与账本，再谈运行权限。',
    families: [
      {key: 'btc-trend', label: 'BTC 趋势', shortLabel: '趋势', focus: '趋势确认、回撤与波动过滤；下面的策略选择是真实注册策略，不是家族别名。'},
      {key: 'btc-options', label: 'BTC 期权', shortLabel: '期权', focus: '波动率与期限结构研究方向；当前不声明可交易策略。'},
      {key: 'btc-funding', label: '资金费 / 基差', shortLabel: '资金费 / 基差', focus: 'funding、mark/index 与 basis 作为成本和风险观察。'},
    ],
    instruments: [{key: 'btc-usdt-swap', label: 'BTC-USDT-SWAP', venue: 'OKX Demo / research-only', strategies: []}],
  },
  {
    key: 'us', label: '美股', subtitle: '数据、因子、组合和 paper 门禁分层；研究结果不能直接越过执行边界。',
    families: [
      {key: 'us-factors', label: '因子与多周期', shortLabel: '因子 / 多周期', focus: 'PIT 特征、因子 IC / Rank IC 与多周期评估。'},
      {key: 'us-portfolio', label: '组合与风险预算', shortLabel: '组合 / 风险', focus: '候选 manifest、组合模拟与风险预算，保留人工复核。'},
      {key: 'us-events', label: '事件驱动回测', shortLabel: '事件回测', focus: '事件、成交、仓位与现金账本统一回放。'},
    ],
    instruments: [{key: 'us-research-universe', label: '美股研究组合', venue: '统一历史目录 / paper disabled', strategies: []}],
  },
  {
    key: 'cn', label: 'A 股', subtitle: '数据 / PIT、市场规则、回测证据与 Replay 分层；当前页仅做进度地图。',
    families: [
      {key: 'cn-pit', label: '数据 / PIT', shortLabel: '数据 / PIT', focus: '数据版本、可见时间、复权与质量检查先行。'},
      {key: 'cn-rules', label: '市场规则 / QMT', shortLabel: '规则 / QMT', focus: '交易制度、标的约束与 QMT 合同作为执行前置。'},
      {key: 'cn-replay', label: '回测证据 / Replay', shortLabel: '回测 / Replay', focus: '回放只消费带身份的历史 audit DAG、snapshot 与风险状态。'},
    ],
    instruments: [{key: 'cn-research-universe', label: 'A 股研究组合', venue: '统一历史目录 / paper disabled', strategies: []}],
  },
];

const MODULE_DEFINITIONS: ModuleDefinition[] = [
  {key: 'hypothesis', label: '超额收益来源假设', subtitle: '把“可能有效”拆成可证伪的研究命题。', icon: Target, status: '正在验证'},
  {key: 'market-state', label: '适用的市场状态', subtitle: '先判断趋势、回撤、波动与数据可用性。', icon: TrendUp, status: '已登记'},
  {key: 'failure-condition', label: '策略失效条件', subtitle: '明确何时不再支持当前收益假设。', icon: WarningCircle, status: '正在验证'},
  {key: 'failure-detection', label: '失效检测', subtitle: '把结构、数据与连接异常转成可审计阻断。', icon: ShieldCheck, status: '正在验证'},
  {key: 'position', label: '仓位管理', subtitle: '把风险预算转成可核验的目标暴露。', icon: ChartBar, status: '已登记'},
  {key: 'exit', label: '退出机制', subtitle: '退出是保护、对账与审计动作，不是收益展示。', icon: Database, status: '正在验证'},
];

const MARKET_ICONS: Record<MarketKey, typeof ChartLineUp> = {crypto: ChartLineUp, us: ChartBar, cn: Database};

const BTC_STRATEGY_REGISTRY_PATH = '/api/research/btc/strategy-registry';
const UNIFIED_HISTORY_CATALOG_PATH = '/api/research/strategy-history/catalog';

type UnifiedHistoryRecord = {
  catalog_key?: string;
  source?: string;
  domain?: string;
  record_kind?: string;
  strategy_id?: string;
  candidate_id?: string;
  strategy_version?: string;
  params_hash?: string;
  display_name?: string;
  research_status?: string;
  promotion_status?: string;
  backtest_supported?: boolean;
  paper_allowed?: boolean;
  live_allowed?: boolean;
};
type UnifiedHistoryCatalog = {status?: string; records?: UnifiedHistoryRecord[]};

function strategyIdentityKey(strategyId: string, candidateId: string): string {
  return `${strategyId}::${candidateId}`;
}

function familyForStrategy(marketKey: MarketKey, strategyId: string): FamilyKey {
  const value = strategyId.toLowerCase();
  if (marketKey === 'crypto') {
    if (value.includes('option')) return 'btc-options';
    if (value.includes('funding') || value.includes('basis')) return 'btc-funding';
    return 'btc-trend';
  }
  if (marketKey === 'us') {
    if (value.includes('event') || value.includes('earn')) return 'us-events';
    if (value.includes('portfolio') || value.includes('risk')) return 'us-portfolio';
    return 'us-factors';
  }
  if (value.includes('replay')) return 'cn-replay';
  if (value.includes('qmt') || value.includes('rule')) return 'cn-rules';
  return 'cn-pit';
}

function catalogCapability(status: {
  canonicalSignalAvailable?: boolean;
  backtestSupported?: boolean;
  promotionCreditEligible?: boolean;
  demoSelectable?: boolean;
  adapterFidelity?: string;
}): string {
  return strategyCapabilityText(status);
}

function historyRecordMatchesMarket(record: UnifiedHistoryRecord, marketKey: MarketKey): boolean {
  const domain = String(record.domain ?? '').trim().toLowerCase();
  if (marketKey === 'us') return domain === 'us' || domain === 'us_equity';
  if (marketKey === 'cn') return domain === 'cn' || domain === 'cn_equity' || domain === 'a_share' || domain === 'a-share';
  return false;
}

function btcRegistryStrategy(spec: BtcStrategyRegistryResponse['specs'][number]): StrategyDefinition {
  const canonicalName = strategyPresentationName(spec.strategy_id, spec.strategy_id) || spec.strategy_id;
  const variantLabel = strategyVariantLabel(spec.candidate_id, spec.strategy_id);
  const capability = catalogCapability({
    canonicalSignalAvailable: spec.canonical_signal_available,
    backtestSupported: undefined,
    promotionCreditEligible: spec.promotion_credit_eligible,
    demoSelectable: false,
    adapterFidelity: spec.adapter_fidelity,
  });
  const paramsSummary = Object.keys(spec.params ?? {}).length ? `参数键：${Object.keys(spec.params).slice(0, 4).join('、')}` : '参数摘要未提供';
  return {
    key: strategyIdentityKey(spec.strategy_id, spec.candidate_id),
    strategyId: spec.strategy_id,
    candidateId: spec.candidate_id,
    strategyVersion: spec.strategy_version,
    paramsHash: spec.params_hash,
    params: spec.params,
    variantLabel,
    canonicalName,
    label: `${canonicalName} · ${variantLabel}`,
    description: `${spec.timeframe || '周期未知'} · ${spec.direction_policy || '方向策略未知'} · ${strategyAdapterLabel(spec.adapter_fidelity)}`,
    availability: capability,
    familyKey: familyForStrategy('crypto', spec.strategy_id),
    hypothesis: '当前目录只提供真实身份、版本与参数摘要；收益假设必须由对应历史报告或证据包证明，本页不推断收益结论。',
    marketState: `${spec.timeframe || '周期未知'} · 信号源 ${spec.signal_data_venue || '未知'} · 执行标的 ${spec.execution_instrument || spec.instrument || '未知'}。`,
    failureCondition: '目录未提供完整失效条件字段；当前页不把策略 ID 或参数反推成具体失效结论。',
    exit: '当前页只展示研究机制，不提供退出执行；风险、OMS、保护与账本边界保持独立。',
    evidence: `BTC strategy registry · ${capability} · ${paramsSummary} · 仅研究只读。`,
  };
}

function unifiedHistoryStrategy(record: UnifiedHistoryRecord, marketKey: MarketKey): StrategyDefinition | null {
  const strategyId = String(record.strategy_id ?? '').trim();
  const candidateId = String(record.candidate_id ?? '').trim();
  if (!strategyId || !candidateId) return null;
  const canonicalName = strategyPresentationName(record.display_name, strategyId) || strategyId;
  const variantLabel = strategyVariantLabel(candidateId, strategyId);
  const capability = catalogCapability({backtestSupported: record.backtest_supported === true, demoSelectable: false});
  const domainLabel = marketKey === 'us' ? '美股' : 'A 股';
  return {
    key: strategyIdentityKey(strategyId, candidateId),
    strategyId,
    candidateId,
    strategyVersion: String(record.strategy_version ?? ''),
    paramsHash: String(record.params_hash ?? ''),
    variantLabel,
    canonicalName,
    label: `${canonicalName} · ${variantLabel}`,
    description: `${domainLabel} · ${record.record_kind || '历史记录'} · ${record.source || '统一历史目录'}`,
    availability: `${capability} · 纸盘/实盘：禁用`,
    familyKey: familyForStrategy(marketKey, strategyId),
    hypothesis: '当前历史目录提供真实身份与历史记录索引；收益假设、成本与样本边界以对应发布报告为准，本页不补写结论。',
    marketState: `${domainLabel} · ${record.research_status || '研究状态未知'} · 仅在目录记录可核验时显示。`,
    failureCondition: '目录记录未提供可执行失效条件；当前页不从展示名或历史状态推断。',
    exit: '当前页只读展示历史策略身份，不提供退出、订单或权限动作。',
    evidence: `统一历史目录 · ${record.promotion_status || '晋级状态未知'} · ${capability} · 仅研究只读。`,
  };
}

function statusClass(status: ModuleStatus): string {
  if (status === '已登记') return 'is-good';
  if (status === '正在验证') return 'is-progress';
  return 'is-pending';
}

function strategyForFamily(strategies: StrategyDefinition[], familyKey: FamilyKey): StrategyDefinition | undefined {
  return strategies.find(item => item.familyKey === familyKey) ?? strategies[0];
}

function moduleCopy(module: ModuleKey, strategy: StrategyDefinition): {shared: boolean; sharedText: string; uniqueText: string; evidence: string} {
  if (module === 'position') return {shared: true, sharedText: '同一标的共享组合仓位上限、Risk / OMS 前置、position 与 cash ledger 对账。', uniqueText: '本策略只改变信号解释，不改变仓位层的安全边界。', evidence: '仓位层已登记；不代表 paper 或 live ready。'};
  if (module === 'failure-detection') return {shared: true, sharedText: '同一标的共享 stale、连接、结构突变、risk-off 与 dead-man / fail-closed 检查。', uniqueText: '当前策略的失效条件会被映射到同一套阻断与审计事件。', evidence: '失效检测有运行 / Demo 语义；当前页不启动运行。'};
  if (module === 'market-state') return {shared: true, sharedText: '同一标的先消费已完成数据、市场状态与风险过滤，再呈现当前真实候选的差异。', uniqueText: strategy.marketState, evidence: strategy.evidence};
  const uniqueText = module === 'hypothesis' ? strategy.hypothesis : module === 'failure-condition' ? strategy.failureCondition : strategy.exit;
  return {shared: false, sharedText: '', uniqueText, evidence: strategy.evidence};
}

type MarketStateTone = 'green' | 'blue' | 'amber' | 'red';
type MarketStateCard = {key: string; label: string; value: string; meta: string; tone: MarketStateTone; icon: typeof ChartLineUp; bars: number[]};

const MARKET_STATE_CARDS: MarketStateCard[] = [
  {key: 'trend', label: '趋势状态', value: '方向确认', meta: '4h 派生趋势', tone: 'green', icon: TrendUp, bars: [35, 48, 42, 64, 57, 78, 70, 92]},
  {key: 'volatility', label: '波动环境', value: '波动可分位', meta: 'ATR / 波动率分位', tone: 'blue', icon: ChartLineUp, bars: [28, 51, 76, 44, 62, 35, 55, 46]},
  {key: 'liquidity', label: '成交与流动性', value: '监测中', meta: '成交量、价差、深度', tone: 'amber', icon: ChartBar, bars: [42, 66, 34, 78, 52, 88, 61, 74]},
  {key: 'crowding', label: '拥挤程度', value: 'Funding / OI', meta: '资金费与持仓过滤', tone: 'red', icon: Database, bars: [65, 48, 78, 58, 72, 86, 60, 75]},
];

const MARKET_STATE_FLOW = [
  {label: '1 小时确认 K 线', subtitle: '使用已完成的 1h K 线', tone: 'green', icon: ChartLineUp},
  {label: '聚合 4 小时趋势', subtitle: '得到 4h 趋势状态', tone: 'blue', icon: TrendUp},
  {label: '策略过滤判断', subtitle: '应用当前策略条件', tone: 'purple', icon: ChartBar},
  {label: 'Demo / 研究复盘', subtitle: '持续跟踪与复盘', tone: 'cyan', icon: ShieldCheck},
] as const;

function MarketStateVisualPanel({strategy}: {strategy: StrategyDefinition; family?: FamilyDefinition; scopeLabel?: string}) {
  const params = strategy.params;
  const funding = params?.use_derivatives_risk_filter;
  return <div className="strategy-market-state-visual" data-testid="strategy-market-state-visual">
    <section className="strategy-market-state-section">
      <h3>机制假设 / 说明</h3>
      <p>趋势、回撤、波动及衍生品数据是可研究的状态维度；本区不展示固定数值曲线，也不声明“当前”市场状态。</p>
      <p>{strategy.marketState}</p>
    </section>
    <section className="strategy-market-state-section" data-testid="strategy-market-state-methods">
      <h3>候选配置 / 注册表事实</h3>
      <p>版本：{strategy.strategyVersion || '未知'} · 参数 hash：{strategy.paramsHash || '未知'}</p>
      <p>衍生品风险过滤：{funding === true ? '该候选配置启用' : funding === false ? '该候选配置未启用' : '注册表未提供，未知'}；
        risk_filter_mode：{String(params?.risk_filter_mode ?? '未知')}。</p>
      <p>候选过滤开关不是系统级风控开关。开启配置也不证明对应行情已被实时监测。</p>
      <details><summary>当前候选原始参数</summary><pre>{JSON.stringify(params ?? {status:'unknown'},null,2)}</pre></details>
    </section>
    <section className="strategy-market-state-section" data-testid="strategy-market-state-results">
      <h3>研究观测 / 运行观测</h3>
      <p>请选择上方明确的 Qlib run 查看可追溯研究事实。未建立该 run 与此注册候选的精确映射时，两者不能合并成一次决策。</p>
      <p>本候选的实时状态、真实订单与真实账本：未在此绑定，保持未知。</p>
    </section>
    <section className="strategy-market-state-section" data-testid="strategy-market-state-gaps">
      <h3>证据边界</h3><p>缺少 Funding / OI 覆盖、运行决策 ID 或账本 hash 时显示缺口，不用示意图补齐。</p>
    </section>
  </div>;
}

function RichModuleVisualPanel({module, strategy, scopeLabel}: {module: ModuleDefinition; strategy: StrategyDefinition; scopeLabel: string}) {
  const details = module.key === 'hypothesis'
    ? {how: ['定义可观测的趋势或回撤现象', '写下成本、样本外与风险边界', '把策略差异保留在可证伪假设内'], result: strategy.hypothesis, next: '补足跨市场样本、holdout 与人工复核记录。'}
    : module.key === 'failure-condition'
      ? {how: ['列出趋势 / 波动 / 数据失效条件', '把风险状态映射到暂停或退出', '保留当前策略的独有判断'], result: strategy.failureCondition, next: '把每类失效映射到可回放 receipt 与审计事件。'}
      : module.key === 'failure-detection'
        ? {how: ['检测结构突变、数据 stale 或连接异常', '触发硬止损、时间止损或暂停条件', '异常路径默认不打开新风险'], result: '本标的共享 stale、risk-off、连接与 dead-man / fail-closed 检查。', next: '补充确定性 fault drill 的 current-head 证据与 operator 复核。'}
        : module.key === 'position'
          ? {how: ['读取组合、保证金和成本边界', '限制单标的、单策略与组合暴露', '用 position / cash ledger 验证结果'], result: '本标的共享仓位上限、Risk / OMS 前置与 position / cash ledger 对账。', next: '补齐跨策略相关性、容量与压力场景。'}
          : {how: ['通过 OCO / 止损 / 时间条件保护持仓', 'dead-man、cancel-only 与单写者先于新风险', 'flat 后用 fills、positions、cash 对账'], result: strategy.exit, next: '补完确定性 fault drill 的 current-head 证据与人工复核。'};
  const shared = module.key === 'failure-detection' || module.key === 'position';
  return <div className="strategy-rich-module" data-testid="strategy-rich-module">
    <section className="strategy-modules-detail-section strategy-modules-solution"><div className="strategy-modules-section-heading"><span>A</span><div><h3>系统如何解决</h3><p>把 {strategy.label} 的研究假设拆成可检查步骤。</p></div></div><div className="strategy-modules-detail-steps">{details.how.map((step, index) => <div className="strategy-modules-step" key={step}><span>{index + 1}</span><strong>{step}</strong>{index < details.how.length - 1 ? <ArrowRight size={19} aria-hidden="true" /> : null}</div>)}</div></section>
    <section className="strategy-modules-detail-section"><div className="strategy-modules-section-heading"><span>B</span><div><h3>已用在哪里</h3><p>只列当前仓库已有机制或明确研究方向。</p></div><span className={`strategy-modules-section-state ${shared ? 'is-good' : 'is-progress'}`}>{scopeLabel}</span></div><div className="strategy-modules-tags"><span>{strategy.label}</span><span>{strategy.strategyId}</span><span>{shared ? '同一 Risk / OMS 层' : '当前策略特有条件'}</span></div></section>
    <section className="strategy-modules-detail-grid"><article className="strategy-modules-detail-section strategy-modules-result-card"><div className="strategy-modules-section-heading"><span>C</span><div><h3>已取得什么</h3><p>状态不等于晋级。</p></div></div><p>{details.result}</p><div className="strategy-modules-evidence-strip"><span className="is-good">已登记</span><span className="is-progress">研究 / Demo</span><span className="is-pending">Promotion blocked</span></div></article><article className="strategy-modules-detail-section strategy-modules-next-card"><div className="strategy-modules-section-heading"><span>D</span><div><h3>下一步补什么</h3><p>只显示当前模块的最小缺口。</p></div></div><p>{details.next}</p><div className="strategy-modules-next-note"><WarningCircle size={19} weight="fill" aria-hidden="true" /><span>{strategy.evidence}</span></div></article></section>
  </div>;
}

export default function StrategyModulesWorkspace() {
  const [marketKey, setMarketKey] = useState<MarketKey>('crypto');
  const [instrumentKey, setInstrumentKey] = useState<InstrumentKey>('btc-usdt-swap');
  const [familyKey, setFamilyKey] = useState<FamilyKey>('btc-trend');
  const [strategyKey, setStrategyKey] = useState<StrategyKey>('');
  const [moduleKey, setModuleKey] = useState<ModuleKey>('market-state');
  const [btcRegistry, setBtcRegistry] = useState<BtcStrategyRegistryResponse | null>(null);
  const [btcRegistryError, setBtcRegistryError] = useState('');
  const [btcRegistryLoading, setBtcRegistryLoading] = useState(true);
  const [historyCatalog, setHistoryCatalog] = useState<UnifiedHistoryCatalog | null>(null);
  const [historyCatalogError, setHistoryCatalogError] = useState('');
  const [historyCatalogLoading, setHistoryCatalogLoading] = useState(true);

  useEffect(() => {
    let active = true;
    void apiGet<BtcStrategyRegistryResponse>(BTC_STRATEGY_REGISTRY_PATH, 30_000).then((payload) => {
      if (!Array.isArray(payload?.specs)) throw new Error(`GET ${BTC_STRATEGY_REGISTRY_PATH}: payload missing specs`);
      if (!active) return;
      setBtcRegistry(payload);
      setBtcRegistryError('');
    }).catch((error) => {
        if (!active) return;
        setBtcRegistry(null);
        setBtcRegistryError(error instanceof Error ? error.message : String(error));
    }).finally(() => { if (active) setBtcRegistryLoading(false); });
    void apiGet<UnifiedHistoryCatalog>(UNIFIED_HISTORY_CATALOG_PATH, 30_000).then((payload) => {
      if (!Array.isArray(payload?.records)) throw new Error(`GET ${UNIFIED_HISTORY_CATALOG_PATH}: payload missing records`);
      if (!active) return;
      setHistoryCatalog(payload);
      setHistoryCatalogError('');
    }).catch((error) => {
        if (!active) return;
        setHistoryCatalog(null);
        setHistoryCatalogError(error instanceof Error ? error.message : String(error));
    }).finally(() => { if (active) setHistoryCatalogLoading(false); });
    return () => { active = false; };
  }, []);

  const market = useMemo(() => MARKET_DEFINITIONS.find(item => item.key === marketKey) ?? MARKET_DEFINITIONS[0], [marketKey]);
  const btcStrategies = useMemo(() => btcRegistry?.specs.map(btcRegistryStrategy) ?? [], [btcRegistry]);
  const unifiedStrategies = useMemo(() => {
    const seen = new Set<string>();
    return (historyCatalog?.records ?? [])
      .filter((record) => historyRecordMatchesMarket(record, marketKey))
      .map((record) => unifiedHistoryStrategy(record, marketKey))
      .filter((strategy): strategy is StrategyDefinition => {
        if (!strategy || seen.has(strategy.key)) return false;
        seen.add(strategy.key);
        return true;
      });
  }, [historyCatalog, marketKey]);
  const availableStrategies = marketKey === 'crypto' ? btcStrategies : unifiedStrategies;
  const instrument = useMemo(() => {
    const base = market.instruments.find(item => item.key === instrumentKey) ?? market.instruments[0];
    return {...base, strategies: availableStrategies};
  }, [availableStrategies, instrumentKey, market]);
  const family = useMemo(() => market.families.find(item => item.key === familyKey) ?? market.families[0], [familyKey, market]);
  const strategy = useMemo(() => instrument.strategies.find(item => item.key === strategyKey) ?? undefined, [instrument, strategyKey]);
  const module = MODULE_DEFINITIONS.find(item => item.key === moduleKey) ?? MODULE_DEFINITIONS[1];
  const moduleIndex = MODULE_DEFINITIONS.findIndex(item => item.key === module.key);
  const moduleContent = strategy ? moduleCopy(module.key, strategy) : null;
  const detailScopeLabel = moduleContent ? (module.key === 'position' ? `同一 ${instrument.label} 标的共享` : module.key === 'failure-detection' ? '同一标的共享' : moduleContent.shared ? '本标的共享' : '策略独有') : '真实策略目录未就绪';
  const MarketIcon = MARKET_ICONS[market.key];
  const ModuleIcon = module.icon;
  const catalogLoading = marketKey === 'crypto' ? btcRegistryLoading : historyCatalogLoading;
  const catalogError = marketKey === 'crypto' ? btcRegistryError : historyCatalogError;
  const catalogState = catalogLoading
    ? '正在加载真实策略目录'
    : catalogError
      ? `真实策略目录暂不可用：${catalogError}`
      : '当前没有已发布真实策略';

  function chooseMarket(next: MarketKey) {
    const nextMarket = MARKET_DEFINITIONS.find(item => item.key === next) ?? MARKET_DEFINITIONS[0];
    const nextInstrument = nextMarket.instruments[0];
    const nextFamily = nextMarket.families[0];
    setMarketKey(next); setInstrumentKey(nextInstrument.key); setFamilyKey(nextFamily.key); setStrategyKey(''); setModuleKey('market-state');
  }
  function chooseInstrument(next: InstrumentKey) {
    const nextInstrument = market.instruments.find(item => item.key === next) ?? market.instruments[0];
    setInstrumentKey(nextInstrument.key); setStrategyKey(''); setModuleKey('market-state');
  }
  function chooseFamily(next: FamilyKey) {
    setFamilyKey(next); setStrategyKey(strategyForFamily(availableStrategies, next)?.key ?? ''); setModuleKey('market-state');
  }

  useEffect(() => {
    if (catalogLoading) return;
    if (!availableStrategies.length) {
      if (strategyKey) setStrategyKey('');
      return;
    }
    if (!availableStrategies.some((item) => item.key === strategyKey)) {
      const registryDefault = marketKey === 'crypto' && btcRegistry
        ? availableStrategies.find((item) => item.strategyId === btcRegistry.default_strategy_id && item.candidateId === btcRegistry.default_candidate_id)
        : undefined;
      setStrategyKey(registryDefault?.key ?? strategyForFamily(availableStrategies, family.key)?.key ?? availableStrategies[0].key);
    }
  }, [availableStrategies, btcRegistry, catalogLoading, family.key, marketKey, strategyKey]);

  return (
    <main className="strategy-modules-workspace" data-testid="strategy-modules-workspace">
      <header className="strategy-modules-header">
        <div><p className="strategy-modules-eyebrow">STRATEGY MAP / READ ONLY / CURRENT RESEARCH</p><h1>策略模块</h1><p className="strategy-modules-lede">按市场 → 标的 → 策略 → 六模块查看机制差异；这是研究进度地图，不是交易控制台。</p></div>
        <div className="strategy-modules-lock" data-testid="strategy-modules-safety"><Lock size={20} weight="bold" aria-hidden="true" /><div><strong>研究进度地图</strong><span>只读 · POST 0 · paper / private / order / live 全锁定</span></div></div>
      </header>

      <QlibTraceExplorer />
      <section className="strategy-modules-market-switcher" aria-label="策略选择层级">
        <div className="strategy-modules-market-tabs" role="tablist" aria-label="市场">
          {MARKET_DEFINITIONS.map(item => { const Icon = MARKET_ICONS[item.key]; const selected = item.key === market.key; return <button key={item.key} type="button" role="tab" aria-selected={selected} aria-current={selected ? 'page' : undefined} className={selected ? 'is-selected' : ''} data-testid={`strategy-market-${item.key}`} onClick={() => chooseMarket(item.key)}><Icon size={21} weight={selected ? 'fill' : 'regular'} aria-hidden="true" /><span><strong>{item.label}</strong><small>{item.subtitle}</small></span></button>; })}
        </div>
        <div className="strategy-modules-selection-row">
          <div className="strategy-modules-select-group"><label htmlFor="strategy-instrument-select">标的</label><select id="strategy-instrument-select" aria-label="标的选择" data-testid="strategy-instrument-select" value={instrument.key} onChange={(event: any) => chooseInstrument(event.target.value as InstrumentKey)}>{market.instruments.map(item => <option key={item.key} value={item.key}>{item.label}</option>)}</select><small>{instrument.venue}</small></div>
          <div className="strategy-modules-select-group strategy-modules-strategy-select"><label htmlFor="strategy-selector">策略选择</label><select id="strategy-selector" aria-label="策略选择" data-testid="strategy-selector" value={strategy?.key ?? ''} disabled={catalogLoading || !availableStrategies.length} onChange={(event: any) => setStrategyKey(event.target.value as StrategyKey)}>{!availableStrategies.length ? <option value="">{catalogState}</option> : availableStrategies.map(item => <option key={item.key} value={item.key}>{item.label} · {item.availability}</option>)}</select><small>{catalogLoading ? '正在加载真实策略目录' : catalogError ? `真实策略目录暂不可用：${catalogError}` : availableStrategies.length ? '真实 strategy_id + candidate_id；不等同于策略家族' : '当前没有已发布真实策略；不会生成占位条目'}</small></div>
        </div>
        <div className="strategy-modules-family-row"><span className="strategy-modules-filter-label">策略方向 / 家族</span><div className="strategy-modules-family-tabs" role="tablist" aria-label={`${market.label}策略方向 / 家族`}>{market.families.map(item => <button key={item.key} type="button" role="tab" aria-selected={item.key === family.key} className={item.key === family.key ? 'is-selected' : ''} data-testid={`strategy-family-${item.key}`} onClick={() => chooseFamily(item.key)}>{item.label}</button>)}</div></div>
      </section>

      {strategy ? <div className="strategy-modules-main" data-testid="strategy-modules-main" data-left-ratio="32" data-right-ratio="68">
        <section className="strategy-modules-flow-panel" aria-labelledby="strategy-flow-title">
          <header className="strategy-modules-panel-heading"><div><p className="strategy-modules-kicker">{market.label} / {instrument.label}</p><h2 id="strategy-flow-title">六模块比较</h2></div><span className="strategy-modules-count">06 个模块</span></header>
          <div className="strategy-modules-selected-strategy"><span>当前真实策略</span><strong>{strategy.label}</strong><small>{strategy.strategyId} · {strategy.candidateId} · {strategy.variantLabel}</small></div>
          <p className="strategy-modules-family-focus">{family.focus}</p>
          <div className="strategy-modules-flow" data-testid="strategy-module-flow" data-module-grid="2x3">
            {MODULE_DEFINITIONS.map((item, index) => { const Icon = item.icon; const selected = item.key === module.key; const shared = moduleCopy(item.key, strategy).shared; return <div className={`strategy-module-flow-item ${selected ? 'is-selected' : ''}`} key={item.key}><button type="button" className="strategy-module-card" aria-pressed={selected} aria-label={`${item.label}${shared ? ' · 本标的共享' : ' · 策略独有'}`} data-module-scope={shared ? 'shared' : 'unique'} data-testid={`strategy-module-card-${item.key}`} onClick={() => setModuleKey(item.key)}><span className="strategy-module-number">{String(index + 1).padStart(2, '0')}</span><span className="strategy-module-icon"><Icon size={25} weight="duotone" aria-hidden="true" /></span><span className="strategy-module-copy"><strong>{item.label}</strong><small>{item.subtitle}</small></span><span className={`strategy-module-scope ${shared ? 'is-shared' : 'is-unique'}`}>{shared ? '本标的共享' : '策略独有'}</span><span className={`strategy-module-status ${statusClass(item.status)}`}>{item.status}</span></button>{index < MODULE_DEFINITIONS.length - 1 ? <ArrowDown className="strategy-module-down" size={16} aria-hidden="true" /> : null}</div>; })}
          </div>
          <footer className="strategy-modules-flow-footer"><ShieldCheck size={18} weight="fill" aria-hidden="true" /><span>只解释机制与证据状态；不会启动策略、创建订单或改变 gate。</span></footer>
        </section>

        <section className="strategy-modules-detail-panel" aria-labelledby="strategy-detail-title" data-testid="strategy-module-detail">
          <header className="strategy-modules-detail-heading"><div className="strategy-modules-detail-index"><ModuleIcon size={25} weight="duotone" aria-hidden="true" /><span>{String(moduleIndex + 1).padStart(2, '0')}</span></div><div><p className="strategy-modules-kicker">{strategy.label} · {module.status}</p><h2 id="strategy-detail-title">{module.label}</h2><p>{module.subtitle}</p><span className="strategy-detail-scope-pill" data-testid="strategy-detail-scope">{detailScopeLabel}</span></div><MarketIcon className="strategy-modules-detail-market-icon" size={32} weight="duotone" aria-hidden="true" /></header>
          <div className="strategy-modules-detail-body">
            {module.key === 'market-state' ? <MarketStateVisualPanel family={family} strategy={strategy} /> : <RichModuleVisualPanel module={module} strategy={strategy} scopeLabel={detailScopeLabel} />}
            <div className="strategy-modules-detail-identity" data-testid="strategy-evidence-line"><span data-testid="strategy-real-identity">strategy_id：{strategy.strategyId} · candidate_id：{strategy.candidateId} · strategy_version：{strategy.strategyVersion || '未提供'} · params_hash：{strategy.paramsHash || '未提供'}</span><span>当前证据 / 待补：{moduleContent?.evidence}</span></div>
          </div>
          <footer className="strategy-modules-detail-footer"><List size={18} aria-hidden="true" /><span>证据等级：quality_checked / research-only / backtest-only；不构成 paper、private、order 或 live 授权。</span></footer>
        </section>
      </div> : <div className="strategy-modules-main" data-testid="strategy-modules-main" data-left-ratio="32" data-right-ratio="68">
        <section className="strategy-modules-flow-panel" aria-labelledby="strategy-flow-title">
          <header className="strategy-modules-panel-heading"><div><p className="strategy-modules-kicker">{market.label} / {instrument.label}</p><h2 id="strategy-flow-title">六模块比较</h2></div><span className="strategy-modules-count">真实目录</span></header>
          <div className="strategy-modules-selected-strategy" data-testid="strategy-catalog-state"><span>策略选择</span><strong>{catalogState}</strong><small>选择器已禁用；不会生成假策略条目或占位身份。</small></div>
          <p className="strategy-modules-family-focus">{family.focus}</p>
        </section>
        <section className="strategy-modules-detail-panel" aria-labelledby="strategy-detail-title" data-testid="strategy-module-detail">
          <header className="strategy-modules-detail-heading"><div className="strategy-modules-detail-index"><ModuleIcon size={25} weight="duotone" aria-hidden="true" /><span>—</span></div><div><p className="strategy-modules-kicker">真实策略目录</p><h2 id="strategy-detail-title">{catalogLoading ? '正在加载真实策略目录' : '真实策略不可用'}</h2><p>{catalogState}</p><span className="strategy-detail-scope-pill" data-testid="strategy-detail-scope">不生成占位身份</span></div><MarketIcon className="strategy-modules-detail-market-icon" size={32} weight="duotone" aria-hidden="true" /></header>
          <div className="strategy-modules-detail-body"><div className="strategy-modules-detail-identity" data-testid="strategy-evidence-line"><span>真实 strategy_id / candidate_id 未就绪</span><span>当前页保持只读、GET-only 与 fail-closed。</span></div></div>
          <footer className="strategy-modules-detail-footer"><List size={18} aria-hidden="true" /><span>证据等级：quality_checked / research-only / backtest-only；不构成 paper、private、order 或 live 授权。</span></footer>
        </section>
      </div>}
    </main>
  );
}
