import {useEffect, useState} from 'react';

import {
  blockedUSEquityDomainReadModel,
  fetchUSEquityDomainReadModel,
  type USEquityDomainReadModel,
} from './domain-read-model';


const LAYER_LABELS: Record<string, string> = {
  data: '数据 / PIT',
  backtest: 'Canonical 回测',
  portfolio: '组合与风险',
  oms: 'OMS 生命周期',
  ledger: 'Fill / 账本',
  replay: '恢复 / 回放',
};


export default function USEquityDomainReadModelView() {
  const [model, setModel] = useState<USEquityDomainReadModel | null>(null);

  useEffect(() => {
    let active = true;
    void fetchUSEquityDomainReadModel()
      .then(payload => {
        if (active) setModel(payload);
      })
      .catch(error => {
        if (active) {
          const code = error instanceof Error
            ? error.message
            : 'us_equity_domain_read_model_unavailable';
          setModel(blockedUSEquityDomainReadModel(code));
        }
      });
    return () => {
      active = false;
    };
  }, []);

  if (!model) {
    return (
      <section className="panel" data-testid="us-equity-domain-read-model">
        <div className="panel-header">
          <h3>当前 HEAD 运营证据</h3>
          <span>只读加载中</span>
        </div>
      </section>
    );
  }

  const safetyFalse = Object.values(model.safety).every(value => value === false);
  return (
    <section
      className="panel ops-evidence-panel"
      data-testid="us-equity-domain-read-model"
      data-view-zone="operator-evidence"
    >
      <div className="panel-header">
        <div>
          <p className="eyebrow">Operator evidence · GET only</p>
          <h3>当前 HEAD 运营证据</h3>
        </div>
        <span>{model.status} · {model.freshness}</span>
      </div>

      <div className="ops-portfolio-summary-grid">
        <div className="metric-card metric-bad">
          <span>Gate decision</span>
          <strong>{model.gate_decision}</strong>
        </div>
        <div className="metric-card">
          <span>阶段 / readiness</span>
          <strong>{model.current_stage}</strong>
          <p className="ops-portfolio-detail">{model.readiness_class}</p>
        </div>
        <div className="metric-card">
          <span>Source HEAD</span>
          <strong>{model.source_head ? model.source_head.slice(0, 12) : 'missing'}</strong>
          <p className="ops-portfolio-detail">{model.generated_at_utc || 'not generated'}</p>
        </div>
        <div className={`metric-card ${safetyFalse ? 'metric-good' : 'metric-bad'}`}>
          <span>交易安全状态</span>
          <strong>{safetyFalse ? '全部 false' : '异常'}</strong>
          <p className="ops-portfolio-detail">paper / live / private / order 均未解锁</p>
        </div>
      </div>

      <div className="ops-gates-grid" style={{marginTop: 14}}>
        {Object.entries(model.layers).map(([layerId, layer]) => (
          <article
            className={`ops-gate-card ${layer.freshness === 'current_head' ? 'ops-gate-neutral' : 'ops-gate-bad'}`}
            key={layerId}
            data-testid={`us-equity-domain-layer-${layerId}`}
          >
            <div className="ops-gate-header">
              <span>{LAYER_LABELS[layerId] ?? layerId}</span>
              <strong>{layer.freshness}</strong>
            </div>
            <p>{layer.status} · {layer.readiness_class}</p>
            <small>{layer.artifact_path}</small>
          </article>
        ))}
      </div>

      <div className="ops-evidence-list" style={{marginTop: 14}}>
        {model.blockers.length > 0 ? model.blockers.map(blocker => (
          <div className="ops-evidence-row" key={blocker.code}>
            <span>{blocker.owner}</span>
            <strong>{blocker.code}</strong>
            <small>{blocker.next_action}</small>
          </div>
        )) : (
          <div className="ops-evidence-row">
            <span>blocker</span>
            <strong>none</strong>
          </div>
        )}
      </div>
    </section>
  );
}
