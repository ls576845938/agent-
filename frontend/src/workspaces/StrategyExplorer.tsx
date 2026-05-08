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
};

export default function StrategyExplorer({strategies}: StrategyExplorerProps) {
  const categories = [...new Set(strategies.map(s => s.category))];

  return (
    <main className="strategy-explorer">
      <div className="panel-header" style={{marginBottom: 16}}>
        <h2>策略浏览器</h2>
        <span>{strategies.length} 个策略注册</span>
      </div>

      {strategies.length === 0 ? (
        <div className="panel"><p className="text-muted" style={{padding: 40, textAlign: 'center'}}>等待加载策略列表...</p></div>
      ) : (
        categories.map(cat => {
          const catStrategies = strategies.filter(s => s.category === cat);
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
