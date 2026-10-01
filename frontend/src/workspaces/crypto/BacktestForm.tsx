import {FormEvent} from 'react';
import type {BtcStrategyRegistrySpec, FormState, ValueEvent} from '../../lib/shared-types';
import type {StrategyInfo} from '../../lib/view-model';
import {strategyPresentationName} from '../../lib/strategy-presentation';

type Mode = 'single' | 'portfolio';

interface BacktestFormProps {
  form: FormState;
  mode: Mode;
  strategies: StrategyInfo[];
  btcStrategySpecs: BtcStrategyRegistrySpec[];
  btcStrategyRegistryMessage: string;
  weightMap: Record<string, number>;
  loading: boolean;
  optimizedStrategyParams: Record<string, number> | null;
  onChangeForm: (form: FormState) => void;
  onChangeMode: (mode: Mode) => void;
  onChangeWeightMap: (weightMap: Record<string, number>) => void;
  onSubmit: (event: FormEvent) => void;
}

export default function BacktestForm({
  form, mode, strategies, btcStrategySpecs, btcStrategyRegistryMessage, weightMap,
  loading, optimizedStrategyParams,
  onChangeForm, onChangeMode, onChangeWeightMap, onSubmit,
}: BacktestFormProps) {
  const registeredStrategyIds = [...new Set(btcStrategySpecs.map((spec) => spec.strategy_id))];
  const selectedCandidates = btcStrategySpecs.filter((spec) => spec.strategy_id === form.strategyId);
  const selectedSpec = selectedCandidates.find((spec) => spec.candidate_id === form.candidateId) ?? selectedCandidates[0];
  const selectedIsRegistered = selectedCandidates.length > 0;
  const registeredButNotRunnable = selectedIsRegistered && !selectedSpec?.canonical_signal_available;
  const submitDisabled = loading || (mode === 'single' && (registeredButNotRunnable || (selectedIsRegistered && !selectedSpec)));

  const selectStrategy = (strategyId: string) => {
    const registered = btcStrategySpecs.find((spec) => spec.strategy_id === strategyId);
    onChangeForm({
      ...form,
      strategyId,
      candidateId: registered?.candidate_id ?? '',
      strategyVersion: registered?.strategy_version ?? '',
      source: registered ? 'sqlite' : form.source,
      symbol: registered ? 'BTCUSDT' : form.symbol,
      interval: registered ? '1h' : form.interval,
      leverage: registered ? 1 : form.leverage,
    });
  };

  const selectCandidate = (candidateId: string) => {
    const candidate = selectedCandidates.find((spec) => spec.candidate_id === candidateId);
    onChangeForm({
      ...form,
      candidateId,
      strategyVersion: candidate?.strategy_version ?? '',
      source: 'sqlite',
      symbol: 'BTCUSDT',
      interval: '1h',
      leverage: 1,
    });
  };

  return (
    <form className="panel control-panel" onSubmit={onSubmit}>
      <div className="panel-header">
        <h2>事件驱动回测</h2>
        <div className="mode-toggle">
          <button type="button" className={mode === 'portfolio' ? 'active' : ''} onClick={() => onChangeMode('portfolio')}>组合研究回测</button>
          <button type="button" className={mode === 'single' ? 'active' : ''} onClick={() => onChangeMode('single')}>单策略事件驱动</button>
        </div>
      </div>
      <div className="hero-status" style={{marginBottom: 12}}>
        <span className="status-chip">事件驱动</span>
        <span className="status-chip muted">SQLite / BTC</span>
      </div>
      <div className="form-grid">
        <label>数据源
          <select value={form.source} disabled={mode === 'single' && selectedIsRegistered} onChange={(e: ValueEvent) => onChangeForm({...form, source: e.target.value as FormState['source']})}>
            <option value="sqlite">SQLite</option><option value="auto">自动</option><option value="fixture">测试样本</option>
          </select>
        </label>
        <label>标的<input value={form.symbol} disabled={mode === 'single' && selectedIsRegistered} onChange={(e: ValueEvent) => onChangeForm({...form, symbol: e.target.value})} /></label>
        <label>周期
          <select value={form.interval} disabled={mode === 'single' && selectedIsRegistered} onChange={(e: ValueEvent) => onChangeForm({...form, interval: e.target.value as FormState['interval']})}>
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
        <label>杠杆<input type="number" step="0.1" value={form.leverage} disabled={mode === 'single' && selectedIsRegistered} onChange={(e: ValueEvent) => onChangeForm({...form, leverage: Number(e.target.value)})} /></label>
        <label>手续费率<input type="number" step="0.0001" value={form.commissionRate} onChange={(e: ValueEvent) => onChangeForm({...form, commissionRate: Number(e.target.value)})} /></label>
        <label>滑点<input type="number" step="0.1" value={form.slippage} onChange={(e: ValueEvent) => onChangeForm({...form, slippage: Number(e.target.value)})} /></label>
        <label className="wide-grid-field">SQLite 数据库
          <input value={form.dataDbPath} placeholder="留空使用默认库" onChange={(e: ValueEvent) => onChangeForm({...form, dataDbPath: e.target.value})} />
        </label>
      </div>
      {mode === 'single' ? (
        <div className="wide-field">
          <label>策略身份
            <select value={form.strategyId} onChange={(e: ValueEvent) => selectStrategy(e.target.value)}>
              <optgroup label="BTC 冻结候选">
                {registeredStrategyIds.map((strategyId) => (
                  <option key={strategyId} value={strategyId}>{strategyPresentationName(strategyId)}</option>
                ))}
              </optgroup>
              <optgroup label="旧诊断策略（无晋级信用）">
                {strategies.map((s) => <option key={s.id} value={s.id}>{strategyPresentationName(s.display_name, s.id)}</option>)}
              </optgroup>
            </select>
          </label>
          {selectedIsRegistered ? (
            <label style={{marginTop: 10}}>冻结候选
              <select value={selectedSpec?.candidate_id ?? ''} onChange={(e: ValueEvent) => selectCandidate(e.target.value)}>
                {selectedCandidates.map((spec) => (
                  <option key={spec.candidate_id} value={spec.candidate_id}>{candidateLabel(spec)}</option>
                ))}
              </select>
            </label>
          ) : null}
          <div className="hero-status" style={{marginTop: 10}}>
            <span className={`status-chip ${selectedSpec?.promotion_credit_eligible ? '' : 'muted'}`}>
              {selectedSpec?.promotion_credit_eligible ? '身份可参与晋级复核' : 'research-only / 无晋级信用'}
            </span>
            <span className="status-chip muted">{selectedSpec?.params_hash ? `参数 ${selectedSpec.params_hash.slice(0, 10)}` : 'legacy diagnostic'}</span>
            {registeredButNotRunnable ? <span className="status-chip bad">单仓回测器不适配</span> : null}
          </div>
          {selectedSpec ? (
            <small className="data-message" style={{display: 'block', marginTop: 8}}>
              {selectedSpec.signal_data_venue} → {selectedSpec.execution_venue} · {selectedSpec.timeframe} · {selectedSpec.strategy_version}
            </small>
          ) : (
            <small className="data-message" style={{display: 'block', marginTop: 8}}>{btcStrategyRegistryMessage || '旧策略仅作诊断，不计入 BTC promotion。'}</small>
          )}
        </div>
      ) : (
        <div className="weights-panel">
          <div className="weights-header"><h3>组合权重</h3><span>归一化正权重</span></div>
          {strategies.map((s) => (
            <div key={s.id} className="weight-row">
              <div><strong>{strategyPresentationName(s.display_name, s.id)}</strong><p>{s.description}</p></div>
              <input type="number" step="0.01" min="0" value={weightMap[s.id] ?? 0} onChange={(e: ValueEvent) => onChangeWeightMap({...weightMap, [s.id]: Number(e.target.value)})} />
            </div>
          ))}
        </div>
      )}
      <button type="submit" className="primary-button" disabled={submitDisabled}>{loading ? '运行中...' : registeredButNotRunnable ? '当前候选需专用 overlay ledger' : mode === 'single' ? '启动事件驱动回测' : '启动组合研究回测'}</button>
    </form>
  );
}

function candidateLabel(spec: BtcStrategyRegistrySpec): string {
  const params = spec.params;
  if (spec.strategy_id === 'long_short_donchian_top5') {
    return `Donchian ${String(params.entry_window ?? '?')} · EMA ${String(params.daily_fast ?? '?')}/${String(params.daily_slow ?? '?')} · 冷却 ${String(params.cooldown_bars ?? '?')}`;
  }
  return spec.candidate_id;
}
