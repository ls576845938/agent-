import {useEffect, useMemo, useState} from 'react';
import {Link} from 'react-router-dom';

import {apiGet} from '../../lib/api';
import {ALPHA_SOURCES, alphaLabel, alphaSourcesFor, type AlphaSource} from '../../lib/strategy-alpha';
import type {BtcStrategyRegistryResponse} from '../../lib/shared-types';
import type {StrategyInfo} from '../../lib/view-model';
import {
  strategyAdapterLabel,
  strategyCapabilityText,
  strategyPresentationName,
  strategySafetyText,
  strategySourceLabel,
  strategyStatusLabel,
  strategyVariantLabel,
} from '../../lib/strategy-presentation';
import type {DemoCatalog} from './demo-types';
import type {BTCStrategyHistoryCatalog} from './strategy-history-types';
import {BTC_ROLLOVER_ARCHIVE, BtcResearchArchiveCard} from './BtcResearchArchive';
import {
  USER_BACKTEST_CATALOG_EVENT,
  discoverImportableLocalRuns,
  readUserBacktestCatalog,
  removeUserBacktestRecord,
  renameUserBacktestRecord,
  upsertUserBacktestRecord,
  type UserBacktestCatalogRecord,
} from './user-backtest-strategy-catalog';

const DEMO_CATALOG_PATH = '/api/research/btc/demo-paper/catalog';
const STRATEGY_REGISTRY_PATH = '/api/research/btc/strategy-registry';
const UNIFIED_HISTORY_CATALOG_PATH = '/api/research/strategy-history/catalog';
const USER_CATEGORY_KEY = 'quantstation.strategy-user-categories.v1';
const USER_CATEGORY_SCHEMA = 'strategy_user_categories_v1';

type SystemCategory = '可运行（当前仅 Demo）' | '研究展示' | '历史危险参照' | '证据不完整';
type UserCategory = {id: string; name: string};
type UserCategoryState = {
  schema_version: typeof USER_CATEGORY_SCHEMA;
  categories: UserCategory[];
  assignments: Record<string, string>;
};
type DiscoveryItem = {
  identity: string;
  strategyId?: string;
  candidateId?: string;
  familyKey?: string;
  familyName?: string;
  variantLabel?: string;
  capabilityText?: string;
  displayName: string;
  systemCategory: SystemCategory;
  sources: string[];
  evidence: string;
  description: string;
  detailPath?: string;
  metrics?: {annual?: number; total?: number; drawdown?: number};
  registryCanonicalSignal?: boolean;
  registryBacktestSupported?: boolean;
  demoSelectable?: boolean;
  promotionCreditEligible?: boolean;
  adapterFidelity?: string;
  userCatalogKey?: string;
};

export type StrategyDiscoverySelection = Pick<
  DiscoveryItem,
  'identity' | 'displayName' | 'familyName' | 'variantLabel' | 'capabilityText' | 'description' | 'sources' | 'evidence' | 'detailPath' | 'metrics'
> & {
  strategyId?: string;
  candidateId?: string;
  canonicalSignalAvailable?: boolean;
};

type RegistrySpec = BtcStrategyRegistryResponse['specs'][number] & {
  display_name?: string;
  backtest_execution?: {supported?: boolean; endpoint?: string} | boolean;
};
type RegistryResponse = Omit<BtcStrategyRegistryResponse, 'specs'> & {specs: RegistrySpec[]};
type UnifiedHistoryRecord = {
  catalog_key: string;
  source: string;
  domain: string;
  record_kind: string;
  strategy_id: string;
  candidate_id?: string;
  experiment_id?: string;
  run_id?: string;
  display_name: string;
  system_category: string;
  metrics?: Record<string, unknown>;
  research_status: string;
  promotion_status: string;
  backtest_supported: boolean;
  paper_allowed: boolean;
  live_allowed: boolean;
  report_href?: string;
  artifact_path?: string;
  artifact_sha256?: string;
  freshness?: string | {status?: string; source?: string; head?: string};
};
type UnifiedHistoryCatalog = {
  schema_version: string;
  status: string;
  records: UnifiedHistoryRecord[];
  coverage?: Record<string, unknown>;
};

let demoCatalogRequest: Promise<DemoCatalog> | null = null;
let strategyRegistryRequest: Promise<RegistryResponse> | null = null;
let unifiedHistoryRequest: Promise<UnifiedHistoryCatalog> | null = null;

function loadDemoCatalog(): Promise<DemoCatalog> {
  if (!demoCatalogRequest) {
    const request = apiGet<DemoCatalog>(DEMO_CATALOG_PATH, 30_000);
    demoCatalogRequest = request;
    const clear = () => {
      if (demoCatalogRequest === request) demoCatalogRequest = null;
    };
    void request.then(clear, clear);
  }
  return demoCatalogRequest;
}

function loadStrategyRegistry(): Promise<RegistryResponse> {
  if (!strategyRegistryRequest) {
    const request = apiGet<RegistryResponse>(STRATEGY_REGISTRY_PATH, 30_000);
    strategyRegistryRequest = request;
    const clear = () => {
      if (strategyRegistryRequest === request) strategyRegistryRequest = null;
    };
    void request.then(clear, clear);
  }
  return strategyRegistryRequest;
}

function loadUnifiedHistoryCatalog(): Promise<UnifiedHistoryCatalog> {
  if (!unifiedHistoryRequest) {
    const request = apiGet<UnifiedHistoryCatalog>(UNIFIED_HISTORY_CATALOG_PATH, 30_000);
    unifiedHistoryRequest = request;
    const clear = () => {
      if (unifiedHistoryRequest === request) unifiedHistoryRequest = null;
    };
    void request.then(clear, clear);
  }
  return unifiedHistoryRequest;
}

export default function StrategyDiscoveryCatalog({
  strategies,
  btcHistory,
  btcHistoryError,
  presentation = 'full',
  selectedIdentity,
  onSelect,
}: {
  strategies: StrategyInfo[];
  btcHistory: BTCStrategyHistoryCatalog | null;
  btcHistoryError: string;
  presentation?: 'full' | 'tree';
  selectedIdentity?: string;
  onSelect?: (selection: StrategyDiscoverySelection) => void;
}) {
  const [demoCatalog, setDemoCatalog] = useState<DemoCatalog | null>(null);
  const [demoCatalogError, setDemoCatalogError] = useState('');
  const [strategyRegistry, setStrategyRegistry] = useState<RegistryResponse | null>(null);
  const [strategyRegistryError, setStrategyRegistryError] = useState('');
  const [unifiedHistory, setUnifiedHistory] = useState<UnifiedHistoryCatalog | null>(null);
  const [unifiedHistoryError, setUnifiedHistoryError] = useState('');
  const [filter, setFilter] = useState('all');
  const [alphaFilter, setAlphaFilter] = useState('all');
  const [groupBy, setGroupBy] = useState<'maturity' | 'alpha'>('maturity');
  const [alphaAssignments, setAlphaAssignments] = useState<Record<string, AlphaSource[]>>(() => {
    try {
      const value = JSON.parse(localStorage.getItem('quantstation.strategy-alpha-sources.v1') || '{}');
      return Object.fromEntries(Object.entries(value).filter(([, ids]) => Array.isArray(ids) && ids.every((id) => ALPHA_SOURCES.some((s) => s.id === id)))) as Record<string, AlphaSource[]>;
    } catch { return {}; }
  });
  const [newCategoryName, setNewCategoryName] = useState('');
  const [categoryEdits, setCategoryEdits] = useState<Record<string, string>>({});
  const [userState, setUserState] = useState<UserCategoryState>(readUserCategories);
  const [userBacktests, setUserBacktests] = useState<UserBacktestCatalogRecord[]>(readUserBacktestCatalog);
  const [importableRuns, setImportableRuns] = useState<UserBacktestCatalogRecord[]>(discoverImportableLocalRuns);
  const [selectedImportKey, setSelectedImportKey] = useState('');
  const [importDisplayName, setImportDisplayName] = useState('');
  const [userNameEdits, setUserNameEdits] = useState<Record<string, string>>({});
  const [treeQuery, setTreeQuery] = useState('');

  useEffect(() => {
    let active = true;
    void loadDemoCatalog().then(
      (payload) => {
        if (!active) return;
        setDemoCatalog(payload);
        setDemoCatalogError('');
      },
      (error) => {
        if (!active) return;
        setDemoCatalog(null);
        setDemoCatalogError(error instanceof Error ? error.message : String(error));
      },
    );
    void loadStrategyRegistry().then(
      (payload) => {
        if (!active) return;
        setStrategyRegistry(payload);
        setStrategyRegistryError('');
      },
      (error) => {
        if (!active) return;
        setStrategyRegistry(null);
        setStrategyRegistryError(error instanceof Error ? error.message : String(error));
      },
    );
    void loadUnifiedHistoryCatalog().then(
      (payload) => {
        if (!active) return;
        setUnifiedHistory(payload);
        setUnifiedHistoryError('');
      },
      (error) => {
        if (!active) return;
        setUnifiedHistory(null);
        setUnifiedHistoryError(error instanceof Error ? error.message : String(error));
      },
    );
    return () => { active = false; };
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(USER_CATEGORY_KEY, JSON.stringify(userState));
    } catch {
      // Category edits remain in memory when storage is unavailable.
    }
  }, [userState]);

  useEffect(() => {
    const refresh = () => {
      setUserBacktests(readUserBacktestCatalog());
      setImportableRuns(discoverImportableLocalRuns());
    };
    window.addEventListener(USER_BACKTEST_CATALOG_EVENT, refresh);
    window.addEventListener('storage', refresh);
    return () => {
      window.removeEventListener(USER_BACKTEST_CATALOG_EVENT, refresh);
      window.removeEventListener('storage', refresh);
    };
  }, []);

  const items = useMemo(
    () => discoverStrategies(strategies, strategyRegistry, demoCatalog, btcHistory, unifiedHistory, userBacktests),
    [btcHistory, demoCatalog, strategies, strategyRegistry, unifiedHistory, userBacktests],
  );
  const alphaFor = (item: DiscoveryItem) => alphaAssignments[item.strategyId || item.identity] ?? alphaSourcesFor(item.strategyId);
  useEffect(() => { try { localStorage.setItem('quantstation.strategy-alpha-sources.v1', JSON.stringify(alphaAssignments)); } catch { /* local metadata remains in memory */ } }, [alphaAssignments]);
  const visibleItems = useMemo(() => items.filter((item) => {
    const sources = alphaAssignments[item.strategyId || item.identity] ?? alphaSourcesFor(item.strategyId);
    if (alphaFilter === 'unclassified' && sources.length) return false;
    if (alphaFilter !== 'all' && alphaFilter !== 'unclassified' && !sources.includes(alphaFilter as AlphaSource)) return false;
    if (filter === 'all') return true;
    if (filter.startsWith('system:')) return item.systemCategory === filter.slice('system:'.length);
    if (filter.startsWith('user:')) return userState.assignments[item.identity] === filter.slice('user:'.length);
    return true;
  }), [filter, items, userState.assignments, alphaAssignments, alphaFilter]);
  const treeItems = useMemo(() => {
    const query = treeQuery.trim().toLowerCase();
    return visibleItems.filter((item) => !query || [
      item.identity,
      item.displayName,
      item.description,
      item.sources.join(' '),
      item.systemCategory,
    ].join(' ').toLowerCase().includes(query));
  }, [treeQuery, visibleItems]);

  const addCategory = () => {
    const name = newCategoryName.trim();
    if (!name) return;
    const id = `user-${Date.now().toString(36)}`;
    setUserState((current) => ({...current, categories: [...current.categories, {id, name}]}));
    setCategoryEdits((current) => ({...current, [id]: name}));
    setNewCategoryName('');
  };

  const renameCategory = (id: string) => {
    const name = (categoryEdits[id] ?? '').trim();
    if (!name) return;
    setUserState((current) => ({
      ...current,
      categories: current.categories.map((category) => category.id === id ? {...category, name} : category),
    }));
  };

  const deleteCategory = (id: string) => {
    setUserState((current) => ({
      ...current,
      categories: current.categories.filter((category) => category.id !== id),
      assignments: Object.fromEntries(Object.entries(current.assignments).filter(([, categoryId]) => categoryId !== id)),
    }));
    if (filter === `user:${id}`) setFilter('all');
  };

  const selectItem = (item: DiscoveryItem) => {
    const [, strategyId, candidateId] = item.identity.split(':');
    onSelect?.({
      identity: item.identity,
      displayName: item.familyName || item.displayName,
      familyName: item.familyName || item.displayName,
      variantLabel: item.variantLabel || '默认变体',
      capabilityText: item.capabilityText || '能力状态：未知',
      description: item.description,
      sources: item.sources,
      evidence: item.evidence,
      detailPath: item.detailPath,
      metrics: item.metrics,
      strategyId: item.strategyId || (item.identity.startsWith('btc:') ? strategyId : undefined),
      candidateId: item.identity.startsWith('btc:') ? candidateId : undefined,
      canonicalSignalAvailable: item.registryCanonicalSignal,
    });
  };

  if (presentation === 'tree') {
    const groups = groupBy === 'alpha'
      ? [...ALPHA_SOURCES.map((source) => ({systemCategory: source.label, entries: treeItems.filter((item) => alphaFor(item).includes(source.id))})), {systemCategory: '待归类', entries: treeItems.filter((item) => !alphaFor(item).length)}]
      : (['可运行（当前仅 Demo）', '研究展示', '历史危险参照', '证据不完整'] as SystemCategory[]).map((systemCategory) => ({systemCategory, entries: treeItems.filter((item) => item.systemCategory === systemCategory)}));
    const currentItem = items.find((item) => item.identity === selectedIdentity);
    return (
      <section className="strategy-workbench-tree" data-testid="strategy-discovery-catalog">
        <label className="strategy-workbench-tree-search">
          <span>搜索策略和历史档案</span>
          <input
            value={treeQuery}
            onChange={(event: any) => setTreeQuery(event.target.value)}
            placeholder="名称、身份或来源"
            data-testid="strategy-workbench-tree-search"
          />
        </label>
        <label className="strategy-workbench-tree-filter">
          <span>目录分类</span>
          <select aria-label="策略分类筛选" value={filter} onChange={(event: any) => setFilter(event.target.value)}>
            <option value="all">全部系统与用户分类</option>
            {(['可运行（当前仅 Demo）', '研究展示', '历史危险参照', '证据不完整'] as SystemCategory[]).map((category) => <option key={category} value={`system:${category}`}>系统 · {category}</option>)}
            {userState.categories.map((category) => <option key={category.id} value={`user:${category.id}`}>用户 · {category.name}</option>)}
          </select>
        </label>
        <label className="strategy-workbench-tree-filter"><span>Alpha 来源</span><select aria-label="Alpha 来源筛选" value={alphaFilter} onChange={(event: any) => setAlphaFilter(event.target.value)}><option value="all">全部 Alpha 来源</option>{ALPHA_SOURCES.map((source) => <option key={source.id} value={source.id}>{source.label}</option>)}<option value="unclassified">待归类</option></select></label>
        <label className="strategy-workbench-tree-filter"><span>目录分组方式</span><select aria-label="目录分组方式" value={groupBy} onChange={(event: any) => setGroupBy(event.target.value)}><option value="maturity">按完成度分组</option><option value="alpha">按 Alpha 来源分组</option></select></label>
        <p className="strategy-alpha-count">{treeItems.length} 个策略 / 变体 · 多来源策略可属于多个 Alpha 分组</p>
        {currentItem ? <details className="strategy-alpha-editor"><summary>标注当前策略的 Alpha 来源</summary><small>保存到本浏览器，同一策略的所有变体共用；不改变完成度。</small>{ALPHA_SOURCES.map((source) => <label key={source.id}><input type="checkbox" checked={alphaFor(currentItem).includes(source.id)} onChange={() => setAlphaAssignments((prev) => {const key = currentItem.strategyId || currentItem.identity; const old = prev[key] ?? alphaSourcesFor(currentItem.strategyId); return {...prev, [key]: old.includes(source.id) ? old.filter((id) => id !== source.id) : [...old, source.id]};})} />{source.label}</label>)}<button type="button" onClick={() => setAlphaAssignments((prev) => {const next = {...prev}; delete next[currentItem.strategyId || currentItem.identity]; return next;})}>恢复策略默认来源</button></details> : null}
        <div className="strategy-workbench-tree-groups" role="tree" aria-label="策略与回测目录">
          {groups.map(({systemCategory, entries}) => (
            <section key={systemCategory} className="strategy-workbench-tree-group" role="group">
              <h3>{systemCategory}<span>{entries.length}</span></h3>
              {groupDiscoveryFamilies(entries).map(({familyKey, familyName, entries: familyEntries}) => (
                <section key={familyKey} className="strategy-workbench-tree-group strategy-workbench-tree-family" role="group">
                  <h3>{familyName}<span>{familyEntries.length} 个变体</span></h3>
                  {familyEntries.map((item) => (
                    <div className={`strategy-workbench-tree-item discovery-${systemCategorySlug(item.systemCategory)}`} key={item.identity} data-strategy-identity={item.identity}>
                      <button
                        type="button"
                        role="treeitem"
                        aria-selected={selectedIdentity === item.identity}
                        className={selectedIdentity === item.identity ? 'selected' : ''}
                        data-testid={`strategy-tree-${item.identity.replace(/[^a-zA-Z0-9_-]/g, '-')}`}
                        onClick={() => selectItem(item)}
                      >
                        <strong>{item.familyName || item.displayName}</strong>
                        <span className="strategy-alpha-tags">{alphaFor(item).map(alphaLabel).join(' · ') || 'Alpha 来源待归类'}</span>
                        <small>变体：{item.variantLabel || '默认变体'} · {item.capabilityText || '能力状态：未知'}</small>
                        <span>{item.evidence}</span>
                      </button>
                      {item.detailPath ? <Link className="strategy-history-link strategy-workbench-tree-history-link" data-testid={item.identity.startsWith('btc:') ? `btc-history-link-${item.identity.split(':')[2]}` : undefined} to={item.detailPath}>历史回测</Link> : <small className="strategy-workbench-tree-history-link">历史未发布</small>}
                    </div>
                  ))}
                </section>
              ))}
            </section>
          ))}
          {!groups.some((group) => group.entries.length) ? <p className="strategy-workbench-empty">没有匹配的策略目录项；不会生成占位报告。</p> : null}
        </div>
        <details className="strategy-workbench-tree-management">
          <summary>本地导入、用户分类与来源覆盖</summary>
          <div className="strategy-source-coverage" data-testid="strategy-source-coverage">
            <SourceStatus label="/api/strategies" ok={strategies.length > 0} detail={strategies.length ? `${strategies.length} 个通用身份` : '暂不可用'} />
            <SourceStatus label="BTC history catalog" ok={Boolean(btcHistory)} detail={btcHistory ? `${btcHistory.candidates.length} 个目录候选` : btcHistoryError || '暂不可用'} />
            <SourceStatus label="BTC strategy registry" ok={Boolean(strategyRegistry)} detail={strategyRegistry ? `${strategyRegistry.specs.length} 个规格` : strategyRegistryError || '加载中'} />
            <SourceStatus label="Cross-market history catalog" ok={Boolean(unifiedHistory)} detail={unifiedHistory ? `${unifiedHistory.records.length} 条记录 · ${unifiedHistory.records.filter((item) => isUsDomain(item.domain)).length} 条美股可信运行` : unifiedHistoryError || '暂不可用'} />
          </div>
          <section className="strategy-local-import" data-testid="strategy-local-backtest-import">
            <div><strong>导入本地完成的回测</strong><span>仅浏览器 localStorage；不会改变 paper/live/order/private。</span></div>
            <select aria-label="选择本地完成的回测" value={selectedImportKey} onChange={(event: any) => {
              const key = event.target.value;
              setSelectedImportKey(key);
              setImportDisplayName(importableRuns.find((item) => item.catalog_key === key)?.display_name ?? '');
            }}>
              <option value="">选择已完成回测</option>
              {importableRuns.map((item) => <option key={item.catalog_key} value={item.catalog_key}>{item.display_name}</option>)}
            </select>
            <input aria-label="导入后的显示名" value={importDisplayName} disabled={!selectedImportKey} onChange={(event: any) => setImportDisplayName(event.target.value)} placeholder="导入后可重命名" />
            <button type="button" disabled={!selectedImportKey} onClick={() => {
              const record = importableRuns.find((item) => item.catalog_key === selectedImportKey);
              if (record) upsertUserBacktestRecord({...record, display_name: importDisplayName.trim() || record.display_name});
            }}>导入策略浏览</button>
            <Link className="strategy-history-link" to="/crypto?panel=backtest">去研究台创建回测</Link>
          </section>
          <div className="strategy-discovery-controls">
            <label>新建用户分类<input aria-label="新建用户分类名称" value={newCategoryName} onChange={(event: any) => setNewCategoryName(event.target.value)} /></label>
            <button type="button" className="secondary-button" onClick={addCategory}>新建分类</button>
            <button type="button" className="ghost-button" onClick={() => { setUserState(defaultUserCategories()); setCategoryEdits({}); setFilter('all'); }}>恢复默认分类</button>
          </div>
          <div className="strategy-user-category-editor" data-testid="strategy-user-category-editor">
          {userState.categories.map((category) => (
            <div className="strategy-workbench-category-row" key={category.id}>
              <input aria-label={`重命名分类 ${category.name}`} value={categoryEdits[category.id] ?? category.name} onChange={(event: any) => setCategoryEdits((current) => ({...current, [category.id]: event.target.value}))} />
              <button type="button" onClick={() => renameCategory(category.id)}>保存</button>
              <button type="button" className="danger" onClick={() => deleteCategory(category.id)}>删除</button>
            </div>
          ))}
          </div>
          <section className="strategy-workbench-tree-assignments" aria-label="用户分类分配">
            <strong>用户分类分配</strong>
            {treeItems.map((item) => <label key={item.identity}>{item.familyName || item.displayName} · {item.variantLabel || '默认变体'}<select aria-label={`调整用户分类 ${item.familyName || item.displayName} · ${item.variantLabel || '默认变体'}`} value={userState.assignments[item.identity] ?? ''} onChange={(event: any) => setUserState((current) => ({...current, assignments: {...current.assignments, [item.identity]: event.target.value}}))}><option value="">未分类</option>{userState.categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>)}
          </section>
        </details>
        <BtcResearchArchiveCard />
      </section>
    );
  }

  return (
    <section className="strategy-discovery" data-testid="strategy-discovery-catalog">
      <BtcResearchArchiveCard />

      <section className="panel strategy-discovery-panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">DISCOVERED STRATEGIES · SOURCE-MERGED · READ ONLY SAFETY</p>
            <h3>可发现策略与历史回测档案</h3>
          </div>
          <span>{visibleItems.length}/{items.length} 项</span>
        </div>
        <p className="text-muted">
          按稳定身份合并通用可执行注册表、BTC 历史目录、BTC 策略注册表与 Demo 目录，并加入已核验的 10x rollover 危险档案。
          同一策略族按变体分组；用户分类只保存在 localStorage，不会修改执行、纸盘、实盘、订单或私有接口能力。
        </p>
        <p className="strategy-coverage-gap">
          当前统一历史目录仅覆盖 BTC；US/CN 尚无统一历史 API。这里只展示当前可发现源，不声称已收齐全项目全部历史回测。
        </p>

        <div className="strategy-source-coverage" data-testid="strategy-source-coverage">
          <SourceStatus label="/api/strategies" ok={strategies.length > 0} detail={strategies.length ? `${strategies.length} 个通用身份 · 暂无回测证据` : '当前返回为空或上游未提供'} />
          <SourceStatus label="BTC history catalog" ok={Boolean(btcHistory)} detail={btcHistory ? `${btcHistory.candidates.length} 个目录候选 / ${new Set(btcHistory.candidates.map((item) => item.source_candidate_id)).size} 个独立来源回测` : btcHistoryError || '暂不可用'} />
          <SourceStatus label="BTC strategy registry" ok={Boolean(strategyRegistry)} detail={strategyRegistry ? `${strategyRegistry.specs.length} 个规格` : strategyRegistryError || '加载中'} />
          <SourceStatus label="BTC Demo catalog" ok={Boolean(demoCatalog)} detail={demoCatalog ? `${demoCatalog.strategies.length} 个候选` : demoCatalogError || '加载中'} />
          <SourceStatus label="BTC 10x rollover archive" ok detail="跟踪说明 · 本地忽略的 latest 边界" />
          <SourceStatus label="Cross-market history catalog" ok={Boolean(unifiedHistory)} detail={unifiedHistory ? `${unifiedHistory.records.length} 条记录 · ${unifiedHistory.records.filter((item) => isUsDomain(item.domain)).length} 条美股可信运行` : unifiedHistoryError || '暂不可用'} />
          <SourceStatus label="US unified history catalog" ok={Boolean(unifiedHistory?.records.some((item) => isUsDomain(item.domain)))} detail={unifiedHistory ? `${unifiedHistory.records.filter((item) => isUsDomain(item.domain)).length} 条可信运行 · 晋级已阻断` : '暂不可用'} />
          <SourceStatus label="CN unified history catalog" ok={false} detail="暂不可用 · 需要后续只读目录票据" />
          <SourceStatus label="用户本机回测目录" ok={userBacktests.length > 0} detail={`${userBacktests.length} 条记录 · 仅浏览器本地 · 账户未同步`} />
        </div>

        <section className="strategy-local-import" data-testid="strategy-local-backtest-import">
          <div><strong>添加回测策略</strong><span>只能导入本机已完成且含稳定身份、完整 metrics 与可恢复报告链接的快照；不能手填收益指标。</span></div>
          <select aria-label="选择本机已完成回测" value={selectedImportKey} onChange={(event: any) => {
            const key = event.target.value;
            setSelectedImportKey(key);
            setImportDisplayName(importableRuns.find((item) => item.catalog_key === key)?.display_name ?? '');
          }}>
            <option value="">选择已完成回测</option>
            {importableRuns.map((item) => <option key={item.catalog_key} value={item.catalog_key}>{item.display_name}</option>)}
          </select>
          <input aria-label="导入后的显示名" value={importDisplayName} disabled={!selectedImportKey} onChange={(event: any) => setImportDisplayName(event.target.value)} placeholder="选择快照后可重命名" />
          <button type="button" disabled={!selectedImportKey} onClick={() => {
            const record = importableRuns.find((item) => item.catalog_key === selectedImportKey);
            if (!record) return;
            upsertUserBacktestRecord({...record, display_name: importDisplayName.trim() || record.display_name});
          }}>导入策略浏览</button>
          <Link className="strategy-history-link" to="/crypto?panel=backtest">去研究台创建回测</Link>
          <small>仅当前浏览器 localStorage；未同步账户，不改变 Demo、纸盘、实盘、订单或私有接口。</small>
        </section>

        <div className="strategy-discovery-controls">
          <label>分类筛选
            <select aria-label="策略分类筛选" value={filter} onChange={(event: any) => setFilter(event.target.value)}>
              <option value="all">全部系统与用户分类</option>
              {(['可运行（当前仅 Demo）', '研究展示', '历史危险参照', '证据不完整'] as SystemCategory[]).map((category) => <option key={category} value={`system:${category}`}>系统 · {category}</option>)}
              {userState.categories.map((category) => <option key={category.id} value={`user:${category.id}`}>用户 · {category.name}</option>)}
            </select>
          </label>
          <label>新建用户分类
            <input aria-label="新建用户分类名称" value={newCategoryName} onChange={(event: any) => setNewCategoryName(event.target.value)} placeholder="例如：重点复核" />
          </label>
          <button type="button" className="secondary-button" onClick={addCategory}>新建分类</button>
          <button type="button" className="ghost-button" onClick={() => {
            const reset = defaultUserCategories();
            setUserState(reset);
            setCategoryEdits({});
            setFilter('all');
          }}>恢复默认分类</button>
        </div>

        {userState.categories.length ? (
          <div className="strategy-user-category-editor" data-testid="strategy-user-category-editor">
            {userState.categories.map((category) => (
              <div key={category.id}>
                <input
                  aria-label={`重命名分类 ${category.name}`}
                  value={categoryEdits[category.id] ?? category.name}
                  onChange={(event: any) => setCategoryEdits((current) => ({...current, [category.id]: event.target.value}))}
                />
                <button type="button" onClick={() => renameCategory(category.id)}>保存重命名</button>
                <button type="button" className="danger" onClick={() => deleteCategory(category.id)}>删除分类</button>
              </div>
            ))}
          </div>
        ) : null}

        <div className="strategy-discovery-grid">
          {visibleItems.map((item) => {
            const userCategoryId = userState.assignments[item.identity] ?? '';
            const userCategory = userState.categories.find((category) => category.id === userCategoryId);
            return (
              <article className={`strategy-card discovery-${systemCategorySlug(item.systemCategory)}`} key={item.identity} data-strategy-identity={item.identity}>
                <div className="strategy-card-header">
                  <div>
                    <strong>{item.familyName || item.displayName}</strong>
                    <small>变体：{item.variantLabel || '默认变体'}</small>
                  </div>
                  <span className="status-chip">{item.systemCategory} · 实盘：禁用</span>
                </div>
                <code>{item.identity}</code>
                <p>{item.description}</p>
                <div className="strategy-card-evidence">
                  <span>来源 <strong>{item.sources.map(strategySourceLabel).join(' + ')}</strong></span>
                  <span>证据 <strong>{item.evidence}</strong></span>
                  <span>能力 <strong>{item.capabilityText || '能力状态：未知'}</strong></span>
                  <span>系统安全 <strong>{strategySafetyText()}</strong></span>
                  <span>用户分类 <strong>{userCategory?.name ?? '未分类'}</strong></span>
                  <span>Alpha 来源 <strong>{alphaFor(item).map(alphaLabel).join(' · ') || '待归类'}</strong></span>
                </div>
                {item.metrics ? (
                  <div className="strategy-history-metrics">
                    <span>年化 <strong>{formatPercent(item.metrics.annual)}</strong></span>
                    <span>总收益 <strong>{formatPercent(item.metrics.total)}</strong></span>
                    <span>最大回撤 <strong>{formatPercent(item.metrics.drawdown)}</strong></span>
                  </div>
                ) : null}
                <label>调整用户分类
                  <select
                    aria-label={`调整用户分类 ${item.familyName || item.displayName} · ${item.variantLabel || '默认变体'}`}
                    value={userCategoryId}
                    onChange={(event: any) => setUserState((current) => ({
                      ...current,
                      assignments: {...current.assignments, [item.identity]: event.target.value},
                    }))}
                  >
                    <option value="">未分类</option>
                    {userState.categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
                  </select>
                </label>
                {item.userCatalogKey ? (
                  <div className="strategy-user-record-editor">
                    <input aria-label={`编辑显示名 ${item.familyName || item.displayName} · ${item.variantLabel || '默认变体'}`} value={userNameEdits[item.userCatalogKey] ?? item.displayName} onChange={(event: any) => setUserNameEdits((current) => ({...current, [item.userCatalogKey!]: event.target.value}))} />
                    <button type="button" onClick={() => renameUserBacktestRecord(item.userCatalogKey!, userNameEdits[item.userCatalogKey!] ?? item.displayName)}>保存显示名</button>
                    <button type="button" className="danger" onClick={() => removeUserBacktestRecord(item.userCatalogKey!)}>移除本机目录项</button>
                  </div>
                ) : null}
                {item.detailPath ? <Link className="strategy-history-link" to={item.detailPath}>查看历史回测与详细报告</Link> : <p className="strategy-detail-unavailable">详细回测未由当前可用源发布；不生成占位报告。</p>}
              </article>
            );
          })}
        </div>
      </section>
    </section>
  );
}

function discoverStrategies(
  strategies: StrategyInfo[],
  strategyRegistry: RegistryResponse | null,
  demoCatalog: DemoCatalog | null,
  btcHistory: BTCStrategyHistoryCatalog | null,
  unifiedHistory: UnifiedHistoryCatalog | null,
  userBacktests: UserBacktestCatalogRecord[],
): DiscoveryItem[] {
  const items = new Map<string, DiscoveryItem>();
  strategies.forEach((strategy) => items.set(`registry:${strategy.id}`, {
    identity: `registry:${strategy.id}`,
    strategyId: strategy.id,
    displayName: strategyPresentationName(strategy.display_name, strategy.id),
    systemCategory: '证据不完整',
    sources: ['/api/strategies'],
    evidence: '通用可执行注册身份 · 暂无版本、候选、运行、指标或报告 · 暂无回测证据',
    description: strategy.description || '通用策略注册身份；仅用于研究目录展示。',
  }));
  strategyRegistry?.specs.forEach((strategy) => {
    const identity = `btc:${strategy.strategy_id}:${strategy.candidate_id}`;
    const highOctane = strategy.strategy_id === 'high_octane_attack_sleeve_v2';
    items.set(identity, {
      identity,
      strategyId: strategy.strategy_id,
      candidateId: strategy.candidate_id,
      displayName: strategyPresentationName(strategy.display_name, strategy.strategy_id) || strategy.candidate_id,
      systemCategory: strategy.canonical_signal_available && registryBacktestSupported(strategy.backtest_execution) ? '研究展示' : '证据不完整',
      sources: ['BTC strategy registry'],
      evidence: `${strategyCapabilityText({
        canonicalSignalAvailable: strategy.canonical_signal_available === true,
        backtestSupported: registryBacktestSupported(strategy.backtest_execution),
        promotionCreditEligible: strategy.promotion_credit_eligible === true,
        adapterFidelity: strategy.adapter_fidelity,
      })}${highOctane ? ' · 未达到晋级条件' : ''}`,
      description: highOctane
        ? '后续派生、不是原始万倍对象；最多 10 暴露，仅 2 个 10x attack。严格 next-bar：年化 275.53% / 总收益 2636.05% / DD 41.30%。'
        : `${strategy.timeframe} · ${strategy.direction_policy} · ${strategyAdapterLabel(strategy.adapter_fidelity)}`,
      detailPath: highOctane ? `/crypto?research_archive=${BTC_ROLLOVER_ARCHIVE.routeId}&panel=backtest#high-octane-derived` : undefined,
      metrics: highOctane ? {annual: 969.07, total: 36627.90, drawdown: 27.10} : undefined,
      registryCanonicalSignal: strategy.canonical_signal_available === true,
      registryBacktestSupported: registryBacktestSupported(strategy.backtest_execution),
      promotionCreditEligible: strategy.promotion_credit_eligible === true,
      adapterFidelity: strategy.adapter_fidelity,
    });
  });
  demoCatalog?.strategies.forEach((strategy) => {
    const identity = `btc:${strategy.strategy_id}:${strategy.candidate_id}`;
    const existing = items.get(identity);
    const runnable = strategy.demo_selectable
      && existing?.registryCanonicalSignal === true
      && existing?.registryBacktestSupported === true;
    items.set(identity, {
      identity,
      strategyId: strategy.strategy_id,
      candidateId: strategy.candidate_id,
      displayName: existing?.displayName || strategyPresentationName(strategy.display_name, strategy.strategy_id),
      systemCategory: runnable ? '可运行（当前仅 Demo）' : existing?.systemCategory ?? '证据不完整',
      sources: [...new Set([...(existing?.sources ?? []), 'BTC Demo catalog'])],
      evidence: `${existing?.evidence ? `${existing.evidence} · ` : ''}${strategyCapabilityText({
        canonicalSignalAvailable: existing?.registryCanonicalSignal,
        backtestSupported: existing?.registryBacktestSupported,
        promotionCreditEligible: existing?.promotionCreditEligible,
        demoSelectable: strategy.demo_selectable === true,
        adapterFidelity: strategy.adapter_fidelity,
      })}${strategy.demo_blocker ? ` · ${strategyStatusLabel(strategy.demo_blocker)}` : ''}`,
      description: existing?.description || `${strategy.timeframe} · ${strategy.direction_policy} · ${strategyAdapterLabel(strategy.adapter_fidelity)}`,
      detailPath: existing?.detailPath,
      metrics: existing?.metrics,
      registryCanonicalSignal: existing?.registryCanonicalSignal,
      registryBacktestSupported: existing?.registryBacktestSupported,
      demoSelectable: strategy.demo_selectable,
      promotionCreditEligible: existing?.promotionCreditEligible,
      adapterFidelity: strategy.adapter_fidelity || existing?.adapterFidelity,
    });
  });
  btcHistory?.candidates.forEach((candidate) => {
    const identity = `btc:${candidate.strategy_id}:${candidate.candidate_id}`;
    const existing = items.get(identity);
    const params = new URLSearchParams({
      strategy_id: candidate.strategy_id,
      candidate_id: candidate.candidate_id,
      panel: 'backtest',
      report_tab: 'overview',
    });
    items.set(identity, {
      identity,
      strategyId: candidate.strategy_id,
      candidateId: candidate.candidate_id,
      displayName: strategyPresentationName(candidate.display_name, candidate.strategy_id),
      systemCategory: existing?.systemCategory === '可运行（当前仅 Demo）' ? '可运行（当前仅 Demo）' : '研究展示',
      sources: [...new Set([...(existing?.sources ?? []), 'BTC history catalog'])],
      evidence: `${strategyStatusLabel(candidate.research_status)} · 历史回测 ${candidate.history_run_count} 次 · 报告 SHA-256 ${candidate.report_sha256.slice(0, 12)}`,
      description: candidate.relationship_label,
      detailPath: `/crypto?${params.toString()}`,
      metrics: {
        annual: candidate.annual_return_pct,
        total: candidate.total_return_pct,
        drawdown: candidate.max_drawdown_pct,
      },
      registryCanonicalSignal: existing?.registryCanonicalSignal,
      registryBacktestSupported: existing?.registryBacktestSupported,
      demoSelectable: existing?.demoSelectable,
      promotionCreditEligible: existing?.promotionCreditEligible,
      adapterFidelity: existing?.adapterFidelity,
    });
  });
  unifiedHistory?.records.forEach((record) => {
    const identity = `catalog:${record.catalog_key}`;
    const annual = numericMetric(record.metrics, 'annual_return_pct', 'annualized_return_pct', 'cagr_pct');
    const total = numericMetric(record.metrics, 'total_return_pct');
    const drawdown = numericMetric(record.metrics, 'max_drawdown_pct', 'max_drawdown_abs_pct');
    items.set(identity, {
      identity,
      strategyId: record.strategy_id,
      candidateId: record.candidate_id,
      displayName: strategyPresentationName(record.display_name, record.strategy_id),
      systemCategory: isUsDomain(record.domain) ? '研究展示' : record.backtest_supported ? '研究展示' : '证据不完整',
      sources: [`cross-market history catalog · ${record.source}`],
      evidence: `${strategyStatusLabel(record.record_kind)} · 运行标识=${record.run_id || '未知'} · 研究状态=${strategyStatusLabel(record.research_status)} · 晋级状态=${strategyStatusLabel(record.promotion_status)} · 新鲜度=${strategyStatusLabel(freshnessStatus(record.freshness))}${record.artifact_sha256 ? ` · SHA-256 ${record.artifact_sha256.slice(0, 12)}` : ''}`,
      description: `${record.domain.toUpperCase()} · ${strategyPresentationName(record.display_name, record.strategy_id)} · ${strategyCapabilityText({backtestSupported: record.backtest_supported, demoSelectable: false})} · 纸盘/实盘：禁用`,
      detailPath: usableInternalHref(record.report_href),
      metrics: annual !== undefined || total !== undefined || drawdown !== undefined ? {annual, total, drawdown} : undefined,
    });
  });
  userBacktests.forEach((record) => items.set(`user-backtest:${record.catalog_key}`, {
    identity: `user-backtest:${record.catalog_key}`,
    strategyId: record.strategy_id,
    candidateId: record.candidate_id,
    displayName: strategyPresentationName(record.display_name, record.strategy_id),
    systemCategory: '研究展示',
    sources: ['用户本机回测'],
    evidence: `本机已完成回测 · 运行标识=${record.run_id} · 来源=${strategyStatusLabel(record.source_snapshot)} · 账户未同步`,
    description: `${record.domain.toUpperCase()} · ${strategyPresentationName(record.display_name, record.strategy_id)} · ${strategyVariantLabel(record.candidate_id, record.strategy_id)} · ${strategySafetyText()}`,
    detailPath: record.report_href,
    metrics: {annual: record.metrics.annual_return_pct, total: record.metrics.total_return_pct, drawdown: record.metrics.max_drawdown_pct},
    userCatalogKey: record.catalog_key,
  }));
  items.set(`archive:${BTC_ROLLOVER_ARCHIVE.archiveId}`, {
    identity: `archive:${BTC_ROLLOVER_ARCHIVE.archiveId}`,
    strategyId: BTC_ROLLOVER_ARCHIVE.archiveId,
    displayName: BTC_ROLLOVER_ARCHIVE.displayName,
    systemCategory: '历史危险参照',
    sources: ['tracked explanation', 'local ignored latest'],
    evidence: '非 current-HEAD immutable · 非 promotion evidence',
    description: '10 isolated sleeves · 10x · split_2_on_double；-5%/-10% shock 可 all-dead。',
    detailPath: `/crypto?research_archive=${BTC_ROLLOVER_ARCHIVE.routeId}&panel=backtest`,
    metrics: {
      annual: BTC_ROLLOVER_ARCHIVE.metrics.annualReturnPct,
      total: BTC_ROLLOVER_ARCHIVE.metrics.totalReturnPct,
      drawdown: BTC_ROLLOVER_ARCHIVE.metrics.maxDrawdownPct,
    },
  });
  return [...items.values()].map(enrichDiscoveryItem).sort((left, right) => left.identity.localeCompare(right.identity));
}

function enrichDiscoveryItem(item: DiscoveryItem): DiscoveryItem {
  const familyName = item.familyName || strategyPresentationName(item.displayName, item.strategyId) || item.displayName;
  return {
    ...item,
    familyKey: item.familyKey || item.strategyId || item.identity,
    familyName,
    variantLabel: item.variantLabel || strategyVariantLabel(item.candidateId, item.strategyId),
    capabilityText: item.capabilityText || strategyCapabilityText({
      canonicalSignalAvailable: item.registryCanonicalSignal,
      backtestSupported: item.registryBacktestSupported,
      promotionCreditEligible: item.promotionCreditEligible,
      demoSelectable: item.demoSelectable,
      adapterFidelity: item.adapterFidelity,
    }),
  };
}

function groupDiscoveryFamilies(entries: DiscoveryItem[]): Array<{familyKey: string; familyName: string; entries: DiscoveryItem[]}> {
  const families = new Map<string, {familyKey: string; familyName: string; entries: DiscoveryItem[]}>();
  entries.forEach((item) => {
    const familyKey = item.familyKey || item.strategyId || item.identity;
    const familyName = item.familyName || item.displayName;
    const family = families.get(familyKey) || {familyKey, familyName, entries: []};
    family.entries.push(item);
    families.set(familyKey, family);
  });
  return [...families.values()].sort((left, right) => left.familyName.localeCompare(right.familyName));
}

function SourceStatus({label, ok, detail}: {label: string; ok: boolean; detail: string}) {
  return <div className={ok ? 'pass' : 'missing'}><span>{strategySourceLabel(label)}</span><strong>{ok ? '可用' : '缺失'}</strong><small>{detail}</small></div>;
}

function readUserCategories(): UserCategoryState {
  try {
    const parsed = JSON.parse(localStorage.getItem(USER_CATEGORY_KEY) ?? 'null') as Partial<UserCategoryState> | null;
    if (
      parsed?.schema_version === USER_CATEGORY_SCHEMA
      && Array.isArray(parsed.categories)
      && parsed.assignments
      && typeof parsed.assignments === 'object'
    ) {
      return {
        schema_version: USER_CATEGORY_SCHEMA,
        categories: parsed.categories.filter((category): category is UserCategory => Boolean(category?.id && category?.name)),
        assignments: Object.fromEntries(Object.entries(parsed.assignments).filter(([, value]) => typeof value === 'string')) as Record<string, string>,
      };
    }
  } catch {
    // Invalid/old storage fails closed to the versioned empty default.
  }
  return defaultUserCategories();
}

function defaultUserCategories(): UserCategoryState {
  return {schema_version: USER_CATEGORY_SCHEMA, categories: [], assignments: {}};
}

function systemCategorySlug(category: SystemCategory): string {
  return category === '可运行（当前仅 Demo）' ? 'runnable' : category === '研究展示' ? 'research' : category === '历史危险参照' ? 'danger' : 'incomplete';
}

function registryBacktestSupported(value: RegistrySpec['backtest_execution']): boolean {
  if (typeof value === 'boolean') return value;
  return value?.supported === true;
}

function formatPercent(value: number | undefined): string {
  return Number.isFinite(value) ? `${Number(value).toLocaleString('en-US', {maximumFractionDigits: 6})}%` : '—';
}

function numericMetric(metrics: Record<string, unknown> | undefined, ...keys: string[]): number | undefined {
  for (const key of keys) {
    const value = metrics?.[key];
    if (typeof value === 'number' && Number.isFinite(value)) return value;
  }
  return undefined;
}

function isUsDomain(domain: string): boolean {
  return domain.toLowerCase() === 'us' || domain.toLowerCase() === 'us_equity';
}

function freshnessStatus(freshness: UnifiedHistoryRecord['freshness']): string {
  if (typeof freshness === 'string') return freshness || 'unknown';
  return freshness?.status || 'unknown';
}

function usableInternalHref(href: string | undefined): string | undefined {
  const normalized = href?.trim();
  return normalized?.startsWith('/') && !normalized.startsWith('//') ? normalized : undefined;
}
