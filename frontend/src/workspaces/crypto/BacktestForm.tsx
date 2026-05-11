import {FormEvent} from 'react';
import type {FormState, ValueEvent} from '../../lib/shared-types';
import type {StrategyInfo} from '../../lib/view-model';

type Mode = 'single' | 'portfolio';

interface BacktestFormProps {
  form: FormState;
  mode: Mode;
  strategies: StrategyInfo[];
  weightMap: Record<string, number>;
  loading: boolean;
  optimizedStrategyParams: Record<string, number> | null;
  onChangeForm: (form: FormState) => void;
  onChangeMode: (mode: Mode) => void;
  onChangeWeightMap: (weightMap: Record<string, number>) => void;
  onSubmit: (event: FormEvent) => void;
}

export default function BacktestForm({
  form, mode, strategies, weightMap,
  loading, optimizedStrategyParams,
  onChangeForm, onChangeMode, onChangeWeightMap, onSubmit,
}: BacktestFormProps) {
  return (
    <form className="panel control-panel" onSubmit={onSubmit}>
      <div className="panel-header">
        <h2>事件驱动回测</h2>
        <div className="mode-toggle">
          <button type="button" className={mode === 'portfolio' ? 'active' : ''} onClick={() => onChangeMode('portfolio')}>组合研究回测</button>
          <button type="button" className={mode === 'single' ? 'active' : ''} onClick={() => onChangeMode('single')}>单策略 event-driven</button>
        </div>
      </div>
      <div className="hero-status" style={{marginBottom: 12}}>
        <span className="status-chip">event-driven</span>
        <span className="status-chip muted">SQLite / BTC</span>
      </div>
      <div className="form-grid">
        <label>数据源
          <select value={form.source} onChange={(e: ValueEvent) => onChangeForm({...form, source: e.target.value as FormState['source']})}>
            <option value="sqlite">SQLite</option><option value="auto">Auto</option><option value="fixture">Fixture</option>
          </select>
        </label>
        <label>标的<input value={form.symbol} onChange={(e: ValueEvent) => onChangeForm({...form, symbol: e.target.value})} /></label>
        <label>周期
          <select value={form.interval} onChange={(e: ValueEvent) => onChangeForm({...form, interval: e.target.value as FormState['interval']})}>
            {['1m', '5m', '15m', '1h', '4h', '1d'].map((i) => <option key={i} value={i}>{i}</option>)}
          </select>
        </label>
        <label>资金基准
          <select value={form.positionBasis} onChange={(e: ValueEvent) => onChangeForm({...form, positionBasis: e.target.value as FormState['positionBasis']})}>
            <option value="equity">动态权益</option><option value="capital">固定本金</option>
          </select>
        </label>
        <label>开始日期<input type="date" value={form.startDate} onChange={(e: ValueEvent) => onChangeForm({...form, startDate: e.target.value})} /></label>
        <label>结束日期<input type="date" value={form.endDate} onChange={(e: ValueEvent) => onChangeForm({...form, endDate: e.target.value})} /></label>
        <label>初始资金<input type="number" value={form.capital} onChange={(e: ValueEvent) => onChangeForm({...form, capital: Number(e.target.value)})} /></label>
        <label>杠杆<input type="number" step="0.1" value={form.leverage} onChange={(e: ValueEvent) => onChangeForm({...form, leverage: Number(e.target.value)})} /></label>
        <label>手续费率<input type="number" step="0.0001" value={form.commissionRate} onChange={(e: ValueEvent) => onChangeForm({...form, commissionRate: Number(e.target.value)})} /></label>
        <label>滑点<input type="number" step="0.1" value={form.slippage} onChange={(e: ValueEvent) => onChangeForm({...form, slippage: Number(e.target.value)})} /></label>
        <label className="wide-grid-field">SQLite 数据库
          <input value={form.dataDbPath} placeholder="留空使用默认库" onChange={(e: ValueEvent) => onChangeForm({...form, dataDbPath: e.target.value})} />
        </label>
      </div>
      {mode === 'single' ? (
        <label className="wide-field">策略
          <select value={form.strategyId} onChange={(e: ValueEvent) => { /* optimizedStrategyParams cleared in parent */ onChangeForm({...form, strategyId: e.target.value}); }}>
            {strategies.map((s) => <option key={s.id} value={s.id}>{s.display_name}</option>)}
          </select>
        </label>
      ) : (
        <div className="weights-panel">
          <div className="weights-header"><h3>组合权重</h3><span>归一化正权重</span></div>
          {strategies.map((s) => (
            <div key={s.id} className="weight-row">
              <div><strong>{s.display_name}</strong><p>{s.description}</p></div>
              <input type="number" step="0.01" min="0" value={weightMap[s.id] ?? 0} onChange={(e: ValueEvent) => onChangeWeightMap({...weightMap, [s.id]: Number(e.target.value)})} />
            </div>
          ))}
        </div>
      )}
      <button type="submit" className="primary-button" disabled={loading}>{loading ? '运行中...' : mode === 'single' ? '启动 event-driven 回测' : '启动组合研究回测'}</button>
    </form>
  );
}
