import {useMemo, useState} from 'react';
import type {StrategyInfo} from '../lib/view-model';
import {formatParams} from '../lib/utils';

export type StrategyExplorerProps = {
  strategies: StrategyInfo[];
};

const categoryMap: Record<string, string> = {
  trend: '趋势跟踪',
  reversion: '均值回归',
  factor: '多因子',
  event: '事件驱动',
  macro: '宏观',
  volatility: '波动率',
  seasonality: '日历效应',
  mean_reversion: '均值回归',
  breakout: '突破',
  sentiment: '情绪',
  order_flow: '订单流',
  regime: '市场状态',
  momentum: '动量',
};

export default function StrategyExplorer({strategies}: StrategyExplorerProps) {
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('all');
  const categories = [...new Set(strategies.map(s => s.category))];
  const filteredStrategies = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return strategies.filter(strategy => {
      const matchesCategory = category === 'all' || strategy.category === category;
      const haystack = `${strategy.display_name} ${strategy.id} ${strategy.description}`.toLowerCase();
      return matchesCategory && (!normalizedQuery || haystack.includes(normalizedQuery));
    });
  }, [category, query, strategies]);
  const visibleCategories = categories.filter(cat => filteredStrategies.some(strategy => strategy.category === cat));

  return (
    <main className="strategy-explorer">
      <div className="panel-header" style={{marginBottom: 16}}>
        <h2>策略浏览器</h2>
        <span>{filteredStrategies.length}/{strategies.length} 个策略</span>
      </div>

      <section className="strategy-toolbar">
        <label>搜索策略
          <input value={query} onChange={(event: any) => setQuery(event.target.value)} placeholder="名称、ID 或描述" />
        </label>
        <label>策略分类
          <select value={category} onChange={(event: any) => setCategory(event.target.value)}>
            <option value="all">全部分类</option>
            {categories.map(cat => <option key={cat} value={cat}>{categoryMap[cat] ?? cat}</option>)}
          </select>
        </label>
      </section>

      {strategies.length === 0 ? (
        <div className="panel"><p className="text-muted" style={{padding: 40, textAlign: 'center'}}>等待加载策略列表...</p></div>
      ) : filteredStrategies.length === 0 ? (
        <div className="panel"><p className="text-muted" style={{padding: 40, textAlign: 'center'}}>没有匹配策略</p></div>
      ) : (
        visibleCategories.map(cat => {
          const catStrategies = filteredStrategies.filter(s => s.category === cat);
          return (
            <section key={cat} className="panel" style={{marginBottom: 16}}>
              <div className="panel-header">
                <h3>{categoryMap[cat] ?? cat}</h3>
                <span>{catStrategies.length} 个</span>
              </div>
              <div className="strategy-grid">
                {catStrategies.map(s => (
                  <div key={s.id} className="strategy-card">
                    <div className="strategy-card-header">
                      <strong>{s.display_name}</strong>
                      <code>{s.id}</code>
                    </div>
                    <p>{s.description}</p>
                    {s.default_params && Object.keys(s.default_params).length > 0 ? (
                      <div className="strategy-params">
                        <span className="text-muted">默认参数:</span>
                        <code>{formatParams(s.default_params)}</code>
                      </div>
                    ) : null}
                    {s.default_weight > 0 ? (
                      <div className="strategy-params">
                        <span className="text-muted">默认权重:</span>
                        <code>{(s.default_weight * 100).toFixed(1)}%</code>
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            </section>
          );
        })
      )}
    </main>
  );
}
