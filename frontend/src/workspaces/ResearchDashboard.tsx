import {useEffect, useMemo, useState} from 'react';

import {LoadingSpinner} from '../components/LoadingSpinner';
import {researchApi} from '../lib/research-api';
import ExperimentList from './research/ExperimentList';
import CandidateTable from './research/CandidateTable';
import ExperimentReport from './research/ExperimentReport';
import ExperimentCompare from './research/ExperimentCompare';

type LooseRecord = Record<string, any>;

interface Experiment {
  experiment_id: string;
  strategy_id: string;
  strategy_family: string;
  symbols: string[];
  status: string;
  start_date: string;
  end_date: string;
  created_at: string;
}

interface Candidate {
  candidate_id: string;
  experiment_id: string;
  strategy_id: string;
  symbols?: string[];
  timeframe?: string;
  data_source?: string;
  asset_class?: string;
  promotion_status: string;
  robustness_score?: number;
  overfit_score?: number;
  alpha_score?: number;
  risk_score?: number;
  turnover_score: number;
  backtest_manifest_path?: string;
  scorecard_path?: string;
  walk_forward_result_path?: string;
  cost_stress_result_path?: string;
  metrics?: LooseRecord;
  created_at: string;
}

const tabs = [
  {key: 'cycle', label: '研究闭环'},
  {key: 'factors', label: '因子特征'},
  {key: 'evidence', label: '候选证据'},
  {key: 'review', label: '组合复核'},
  {key: 'records', label: '列表报告'},
];

const inputStyle = {
  width: '100%',
  minWidth: 0,
  padding: '8px 10px',
  borderRadius: 6,
  border: '1px solid rgba(148,163,184,0.28)',
  background: 'rgba(15,23,42,0.72)',
  color: '#e2e8f0',
  outline: 'none',
} as const;

const labelStyle = {
  display: 'grid',
  gap: 6,
  fontSize: '0.78rem',
  color: '#94a3b8',
} as const;

const buttonStyle = {
  border: '1px solid rgba(99,102,241,0.42)',
  background: 'rgba(99,102,241,0.18)',
  color: '#c7d2fe',
  borderRadius: 6,
  padding: '8px 12px',
  fontWeight: 650,
  cursor: 'pointer',
} as const;

const ghostButtonStyle = {
  ...buttonStyle,
  border: '1px solid rgba(148,163,184,0.24)',
  background: 'rgba(15,23,42,0.66)',
  color: '#cbd5e1',
} as const;

const dangerButtonStyle = {
  ...buttonStyle,
  border: '1px solid rgba(239,68,68,0.42)',
  background: 'rgba(239,68,68,0.14)',
  color: '#fecaca',
} as const;

const sectionStyle = {
  border: '1px solid rgba(148,163,184,0.16)',
  background: 'rgba(15,23,42,0.58)',
  borderRadius: 8,
  padding: 16,
} as const;

function splitCsv(value: string): string[] {
  return value.split(',').map(item => item.trim().toUpperCase()).filter(Boolean);
}

function parseJsonObject(value: string, fallback: LooseRecord = {}): LooseRecord {
  const trimmed = value.trim();
  if (!trimmed) return fallback;
  const parsed = JSON.parse(trimmed);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('JSON 必须是对象');
  }
  return parsed;
}

function fmt(value: unknown, digits = 2): string {
  if (typeof value === 'number' && Number.isFinite(value)) return value.toFixed(digits);
  if (typeof value === 'string' && value.trim()) return value;
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return '-';
}

function pct(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '-';
  const normalized = Math.abs(value) <= 1 ? value * 100 : value;
  return `${normalized.toFixed(1)}%`;
}

function tone(status?: string): string {
  const normalized = String(status || '').toUpperCase();
  if (['COMPLETED', 'READY_FOR_PAPER_REVIEW', 'READY_FOR_REVIEW', 'PASS', 'PASSED', 'READY_FOR_PORTFOLIO_SIM'].includes(normalized)) {
    return '#22c55e';
  }
  if (['FAILED', 'BLOCKED', 'REJECTED', 'FAIL', 'ERROR'].includes(normalized)) {
    return '#ef4444';
  }
  if (['WATCHLIST', 'NEED_MORE_RESEARCH', 'PENDING_HUMAN_REVIEW', 'RUNNING'].includes(normalized)) {
    return '#eab308';
  }
  return '#94a3b8';
}

function StatusPill({value}: {value?: string}) {
  const label = value || '-';
  return (
    <span style={{
      color: tone(label),
      border: `1px solid ${tone(label)}55`,
      background: `${tone(label)}18`,
      borderRadius: 999,
      padding: '3px 8px',
      fontSize: '0.74rem',
      fontWeight: 700,
      whiteSpace: 'nowrap',
    }}>
      {label}
    </span>
  );
}

function Field({label, children}: {label: string; children: any}) {
  return <label style={labelStyle}><span>{label}</span>{children}</label>;
}

function ResultBlock({title, value}: {title: string; value: unknown}) {
  if (!value) return null;
  return (
    <section style={sectionStyle}>
      <h3 style={{margin: '0 0 10px', fontSize: '0.95rem'}}>{title}</h3>
      <pre style={{
        margin: 0,
        maxHeight: 320,
        overflow: 'auto',
        whiteSpace: 'pre-wrap',
        color: '#cbd5e1',
        fontSize: '0.76rem',
      }}>
        {JSON.stringify(value, null, 2)}
      </pre>
    </section>
  );
}

export default function ResearchDashboard() {
  const [dataRoot, setDataRoot] = useState('data');
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [features, setFeatures] = useState<LooseRecord[]>([]);
  const [factors, setFactors] = useState<LooseRecord[]>([]);
  const [manifests, setManifests] = useState<LooseRecord[]>([]);
  const [pendingReviews, setPendingReviews] = useState<LooseRecord[]>([]);
  const [registry, setRegistry] = useState<LooseRecord | null>(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [tab, setTab] = useState('cycle');
  const [selectedExp, setSelectedExp] = useState<Experiment | null>(null);
  const [selectedReportExp, setSelectedReportExp] = useState('');

  const [autoForm, setAutoForm] = useState({
    strategyId: 'momentum',
    symbols: 'AAPL,MSFT',
    family: 'frontend_research_cycle',
    params: '{"lookback": 20}',
    paramGrid: '{"lookback": [10, 20, 60]}',
    start: '2024-01-01',
    end: '2024-12-31',
    barSize: '1d',
    dataVersion: '',
    featureVersion: '',
  });
  const [factorForm, setFactorForm] = useState({
    factorId: 'momentum_60d',
    symbols: 'AAPL,MSFT',
    start: '2024-01-01',
    end: '2024-12-31',
    barSize: '1d',
    forwardPeriod: '5',
  });
  const [featureForm, setFeatureForm] = useState({
    featureId: 'momentum_60d',
    version: 'v1',
    symbols: 'AAPL,MSFT',
    start: '2024-01-01',
    end: '2024-12-31',
    barSize: '1d',
  });
  const [portfolioForm, setPortfolioForm] = useState({
    manifestIds: '',
    initialCash: '50000',
    reviewer: '',
    reviewReason: 'manual frontend review',
  });

  const [autoResult, setAutoResult] = useState<LooseRecord | null>(null);
  const [factorResult, setFactorResult] = useState<LooseRecord | null>(null);
  const [factorPreview, setFactorPreview] = useState<LooseRecord | null>(null);
  const [factorMiningResult, setFactorMiningResult] = useState<LooseRecord | null>(null);
  const [featureResult, setFeatureResult] = useState<LooseRecord | null>(null);
  const [candidateActionResult, setCandidateActionResult] = useState<LooseRecord | null>(null);
  const [portfolioResult, setPortfolioResult] = useState<LooseRecord | null>(null);

  const refresh = async (root = dataRoot) => {
    setError('');
    const [exps, cands, snaps, factorDefs, manifestRows, reviews, registryPayload] = await Promise.all([
      researchApi.listExperiments(root).catch(() => []),
      researchApi.listCandidates(root).catch(() => []),
      researchApi.listFeatures().catch(() => []),
      researchApi.listFactors().catch(() => []),
      researchApi.listStrategyManifests(root).catch(() => []),
      researchApi.listPendingReviews().catch(() => []),
      researchApi.getEvidenceRegistry(root).catch(() => null),
    ]);
    setExperiments(exps || []);
    setCandidates(cands || []);
    setFeatures(snaps || []);
    setFactors(factorDefs || []);
    setManifests(manifestRows || []);
    setPendingReviews(reviews || []);
    setRegistry(registryPayload);
    if ((factorDefs || []).length && !factorDefs.find((f: LooseRecord) => f.factor_id === factorForm.factorId)) {
      setFactorForm(current => ({...current, factorId: String(factorDefs[0].factor_id)}));
      setFeatureForm(current => ({...current, featureId: String(factorDefs[0].factor_id)}));
    }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await refresh(dataRoot);
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : '加载研究数据失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const candidatesForExp = selectedExp
    ? candidates.filter(c => c.experiment_id === selectedExp.experiment_id)
    : candidates;

  const paperReadyCount = useMemo(() => {
    return candidates.filter(c => ['READY_FOR_PAPER_REVIEW', 'PAPER_ELIGIBLE'].includes(String(c.promotion_status))).length;
  }, [candidates]);

  const updateAuto = (key: string, value: string) => setAutoForm(current => ({...current, [key]: value}));
  const updateFactor = (key: string, value: string) => setFactorForm(current => ({...current, [key]: value}));
  const updateFeature = (key: string, value: string) => setFeatureForm(current => ({...current, [key]: value}));
  const updatePortfolio = (key: string, value: string) => setPortfolioForm(current => ({...current, [key]: value}));

  const runTask = async (label: string, task: () => Promise<void>) => {
    setBusy(label);
    setError('');
    setMessage('');
    try {
      await task();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy('');
    }
  };

  const handleAutoCycle = () => runTask('auto-cycle', async () => {
    const payload = {
      strategy_id: autoForm.strategyId,
      symbols: splitCsv(autoForm.symbols),
      experiment_name: autoForm.family,
      params: parseJsonObject(autoForm.params),
      param_grid: parseJsonObject(autoForm.paramGrid),
      start_date: autoForm.start,
      end_date: autoForm.end,
      bar_size: autoForm.barSize,
      timeframe: autoForm.barSize,
      data_version: autoForm.dataVersion,
      feature_version: autoForm.featureVersion,
      data_root: dataRoot,
    };
    const result = await researchApi.runAutoCycle(payload);
    setAutoResult(result);
    setMessage(`研究闭环完成: ${result.status || 'unknown'}`);
    await refresh(dataRoot);
  });

  const handleFactorEvaluate = () => runTask('factor-evaluate', async () => {
    const result = await researchApi.evaluateFactor({
      factor_id: factorForm.factorId,
      symbols: splitCsv(factorForm.symbols),
      start: factorForm.start,
      end: factorForm.end,
      bar_size: factorForm.barSize,
      timeframe: factorForm.barSize,
      forward_period: Number(factorForm.forwardPeriod || 5),
      data_root: dataRoot,
    });
    setFactorResult(result);
  });

  const handleFactorCompute = () => runTask('factor-compute', async () => {
    const result = await researchApi.computeFactor({
      factor_ids: [factorForm.factorId],
      symbols: splitCsv(factorForm.symbols),
      start: factorForm.start,
      end: factorForm.end,
      bar_size: factorForm.barSize,
      timeframe: factorForm.barSize,
      data_root: dataRoot,
      limit: 25,
    });
    setFactorPreview(result);
  });

  const handleFactorMine = () => runTask('factor-mine', async () => {
    const result = await researchApi.mineFactors({
      symbols: splitCsv(factorForm.symbols),
      start: factorForm.start,
      end: factorForm.end,
      bar_sizes: ['1d', '1m', '5m', '15m'],
      forward_period: Number(factorForm.forwardPeriod || 5),
      min_abs_rank_ic: 0.01,
      min_observations: 20,
      max_abs_correlation: 0.9,
      max_selected: 8,
      data_root: dataRoot,
    });
    setFactorMiningResult(result);
  });

  const handleFactorMineAndRun = () => runTask('factor-mine-run', async () => {
    const result = await researchApi.mineAndRunFactors({
      symbols: splitCsv(factorForm.symbols),
      start: factorForm.start,
      end: factorForm.end,
      bar_sizes: ['1d', '1m', '5m', '15m'],
      forward_period: Number(factorForm.forwardPeriod || 5),
      min_abs_rank_ic: 0.01,
      min_observations: 20,
      max_abs_correlation: 0.9,
      max_selected: 8,
      max_runs: 4,
      data_root: dataRoot,
    });
    setFactorMiningResult(result);
    setMessage(`因子挖掘研究闭环完成: ${result.candidate_ids?.length ?? 0} candidates`);
    await refresh(dataRoot);
  });

  const handleFeatureBuild = () => runTask('feature-build', async () => {
    const result = await researchApi.buildFeature({
      feature_id: featureForm.featureId,
      version: featureForm.version,
      symbols: splitCsv(featureForm.symbols),
      start: featureForm.start,
      end: featureForm.end,
      bar_size: featureForm.barSize,
      timeframe: featureForm.barSize,
      data_root: dataRoot,
    });
    setFeatureResult(result);
    await refresh(dataRoot);
  });

  const handleRegistryRebuild = () => runTask('registry', async () => {
    const result = await researchApi.rebuildEvidenceRegistry(dataRoot);
    setRegistry(result);
    setMessage('证据 registry 已重建');
  });

  const handleCandidateAction = (candidateId: string, action: string) => runTask(`${candidateId}-${action}`, async () => {
    let result: LooseRecord;
    if (action === 'materialize') result = await researchApi.materializeEvidence(candidateId, dataRoot);
    else if (action === 'gate') result = await researchApi.checkPromotionGate(candidateId, dataRoot);
    else if (action === 'pack') result = await researchApi.saveEvidencePack(candidateId, dataRoot);
    else result = await researchApi.runRobustness(candidateId, dataRoot, 200);
    setCandidateActionResult({candidate_id: candidateId, action, result});
    await refresh(dataRoot);
  });

  const handlePortfolioSim = () => runTask('portfolio-sim', async () => {
    const manifestIds = portfolioForm.manifestIds
      ? portfolioForm.manifestIds.split(/[,\n]/).map(id => id.trim()).filter(Boolean)
      : manifests.map(row => String(row.strategy_candidate_id)).filter(Boolean);
    const result = await researchApi.runPortfolioSim(manifestIds, {
      initial_cash: Number(portfolioForm.initialCash || 50000),
    });
    setPortfolioResult(result);
  });

  const handleCreateReview = () => runTask('paper-review-create', async () => {
    const simId = String(portfolioResult?.portfolio_sim_id || '');
    if (!simId) throw new Error('先运行 portfolio simulation');
    const result = await researchApi.createPaperReview(simId);
    setPortfolioResult({...(portfolioResult || {}), paper_review: result});
    await refresh(dataRoot);
  });

  const handleApproveReview = (reviewId: string) => runTask(`approve-${reviewId}`, async () => {
    if (!portfolioForm.reviewer.trim()) throw new Error('填写 reviewer 后才能人工批准');
    const result = await researchApi.approvePaperReview(reviewId, portfolioForm.reviewer, portfolioForm.reviewReason);
    setPortfolioResult({approved_review: result});
    await refresh(dataRoot);
  });

  if (loading) return <LoadingSpinner text="加载研究数据..." />;

  return (
    <div data-testid="research-content" style={{padding: 24, color: '#e2e8f0'}}>
      <div style={{display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'flex-start', marginBottom: 18}}>
        <div>
          <h2 style={{margin: '0 0 4px'}}>研究台</h2>
          <p style={{color: '#94a3b8', margin: 0, fontSize: '0.875rem'}}>
            数据质量、因子研究、候选证据、晋升门和人工复核统一操作；不会启动 paper/live 下单。
          </p>
        </div>
        <div style={{display: 'flex', gap: 8, alignItems: 'end'}}>
          <Field label="data_root">
            <input style={{...inputStyle, width: 180}} value={dataRoot} onChange={(e: any) => setDataRoot(e.target.value)} />
          </Field>
          <button style={ghostButtonStyle} disabled={!!busy} onClick={() => runTask('refresh', async () => refresh(dataRoot))}>刷新</button>
        </div>
      </div>

      {error ? (
        <div style={{...sectionStyle, borderColor: 'rgba(239,68,68,0.5)', color: '#fecaca', marginBottom: 14}}>
          {error}
        </div>
      ) : null}
      {message ? (
        <div style={{...sectionStyle, borderColor: 'rgba(34,197,94,0.42)', color: '#bbf7d0', marginBottom: 14}}>
          {message}
        </div>
      ) : null}

      <div style={{display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 10, marginBottom: 18}}>
        {[
          ['实验', experiments.length],
          ['候选', candidates.length],
          ['证据完整候选', paperReadyCount],
          ['特征快照', features.length],
          ['策略 manifests', manifests.length],
        ].map(([label, value]) => (
          <section key={label} style={sectionStyle}>
            <div style={{fontSize: '0.75rem', color: '#94a3b8'}}>{label}</div>
            <div style={{fontSize: '1.35rem', fontWeight: 750, marginTop: 4}}>{value}</div>
          </section>
        ))}
      </div>

      <div style={{display: 'flex', gap: 4, borderBottom: '1px solid rgba(255,255,255,0.1)', marginBottom: 18}}>
        {tabs.map(item => {
          const active = tab === item.key;
          return (
            <button
              key={item.key}
              onClick={() => setTab(item.key)}
              style={{
                padding: '9px 14px',
                borderRadius: '6px 6px 0 0',
                border: 'none',
                background: active ? 'rgba(99,102,241,0.2)' : 'transparent',
                color: active ? '#c7d2fe' : '#94a3b8',
                cursor: 'pointer',
                borderBottom: active ? '2px solid #818cf8' : '2px solid transparent',
                fontWeight: active ? 700 : 500,
              }}
            >
              {item.label}
            </button>
          );
        })}
      </div>

      {tab === 'cycle' && (
        <div style={{display: 'grid', gridTemplateColumns: 'minmax(340px, 0.9fr) minmax(420px, 1.1fr)', gap: 16}}>
          <section style={sectionStyle}>
            <h3 style={{marginTop: 0}}>一键研究闭环</h3>
            <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12}}>
              <Field label="strategy_id"><input style={inputStyle} value={autoForm.strategyId} onChange={(e: any) => updateAuto('strategyId', e.target.value)} /></Field>
              <Field label="bar_size"><select style={inputStyle} value={autoForm.barSize} onChange={(e: any) => updateAuto('barSize', e.target.value)}><option>1d</option><option>1m</option><option>5m</option><option>15m</option></select></Field>
              <Field label="symbols"><input style={inputStyle} value={autoForm.symbols} onChange={(e: any) => updateAuto('symbols', e.target.value)} /></Field>
              <Field label="family"><input style={inputStyle} value={autoForm.family} onChange={(e: any) => updateAuto('family', e.target.value)} /></Field>
              <Field label="start"><input style={inputStyle} value={autoForm.start} onChange={(e: any) => updateAuto('start', e.target.value)} /></Field>
              <Field label="end"><input style={inputStyle} value={autoForm.end} onChange={(e: any) => updateAuto('end', e.target.value)} /></Field>
              <Field label="data_version"><input style={inputStyle} value={autoForm.dataVersion} onChange={(e: any) => updateAuto('dataVersion', e.target.value)} /></Field>
              <Field label="feature_version"><input style={inputStyle} value={autoForm.featureVersion} onChange={(e: any) => updateAuto('featureVersion', e.target.value)} /></Field>
            </div>
            <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 12}}>
              <Field label="params JSON"><textarea style={{...inputStyle, minHeight: 92}} value={autoForm.params} onChange={(e: any) => updateAuto('params', e.target.value)} /></Field>
              <Field label="param_grid JSON"><textarea style={{...inputStyle, minHeight: 92}} value={autoForm.paramGrid} onChange={(e: any) => updateAuto('paramGrid', e.target.value)} /></Field>
            </div>
            <div style={{display: 'flex', gap: 10, marginTop: 14}}>
              <button style={buttonStyle} disabled={!!busy} onClick={handleAutoCycle}>运行闭环</button>
              <button style={ghostButtonStyle} disabled={!!busy} onClick={handleRegistryRebuild}>重建证据 registry</button>
            </div>
          </section>
          <div style={{display: 'grid', gap: 12}}>
            <section style={sectionStyle}>
              <h3 style={{margin: '0 0 10px'}}>闭环结果</h3>
              <div style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10}}>
                <div><span style={{color: '#94a3b8'}}>status</span><br /><StatusPill value={String(autoResult?.status || '-')} /></div>
                <div><span style={{color: '#94a3b8'}}>pipeline</span><br />{fmt(autoResult?.pipeline_result?.pipeline_id)}</div>
                <div><span style={{color: '#94a3b8'}}>candidates</span><br />{fmt(autoResult?.candidate_ids?.length ?? 0, 0)}</div>
                <div><span style={{color: '#94a3b8'}}>registry</span><br />{fmt(registry?.state || registry?.status || registry?.schema_version)}</div>
              </div>
            </section>
            <ResultBlock title="auto-cycle payload" value={autoResult} />
          </div>
        </div>
      )}

      {tab === 'factors' && (
        <div style={{display: 'grid', gridTemplateColumns: 'minmax(340px, 0.9fr) minmax(420px, 1.1fr)', gap: 16}}>
          <section style={sectionStyle}>
            <h3 style={{marginTop: 0}}>多周期因子评估</h3>
            <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12}}>
              <Field label="factor"><select style={inputStyle} value={factorForm.factorId} onChange={(e: any) => updateFactor('factorId', e.target.value)}>{factors.map(f => <option key={f.factor_id} value={f.factor_id}>{f.factor_id}</option>)}</select></Field>
              <Field label="bar_size"><select style={inputStyle} value={factorForm.barSize} onChange={(e: any) => updateFactor('barSize', e.target.value)}><option>1d</option><option>1m</option><option>5m</option><option>15m</option></select></Field>
              <Field label="symbols"><input style={inputStyle} value={factorForm.symbols} onChange={(e: any) => updateFactor('symbols', e.target.value)} /></Field>
              <Field label="forward_period"><input style={inputStyle} value={factorForm.forwardPeriod} onChange={(e: any) => updateFactor('forwardPeriod', e.target.value)} /></Field>
              <Field label="start"><input style={inputStyle} value={factorForm.start} onChange={(e: any) => updateFactor('start', e.target.value)} /></Field>
              <Field label="end"><input style={inputStyle} value={factorForm.end} onChange={(e: any) => updateFactor('end', e.target.value)} /></Field>
            </div>
            <div style={{display: 'flex', gap: 10, marginTop: 14}}>
              <button style={buttonStyle} disabled={!!busy} onClick={handleFactorEvaluate}>评估 IC</button>
              <button style={ghostButtonStyle} disabled={!!busy} onClick={handleFactorCompute}>计算预览</button>
              <button style={ghostButtonStyle} disabled={!!busy} onClick={handleFactorMine}>自动挖掘</button>
              <button style={ghostButtonStyle} disabled={!!busy} onClick={handleFactorMineAndRun}>挖掘+回测</button>
            </div>
            <h3 style={{margin: '18px 0 10px'}}>冻结特征快照</h3>
            <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12}}>
              <Field label="feature_id"><select style={inputStyle} value={featureForm.featureId} onChange={(e: any) => updateFeature('featureId', e.target.value)}>{factors.map(f => <option key={f.factor_id} value={f.factor_id}>{f.factor_id}</option>)}</select></Field>
              <Field label="version"><input style={inputStyle} value={featureForm.version} onChange={(e: any) => updateFeature('version', e.target.value)} /></Field>
              <Field label="symbols"><input style={inputStyle} value={featureForm.symbols} onChange={(e: any) => updateFeature('symbols', e.target.value)} /></Field>
              <Field label="bar_size"><select style={inputStyle} value={featureForm.barSize} onChange={(e: any) => updateFeature('barSize', e.target.value)}><option>1d</option><option>1m</option><option>5m</option><option>15m</option></select></Field>
              <Field label="start"><input style={inputStyle} value={featureForm.start} onChange={(e: any) => updateFeature('start', e.target.value)} /></Field>
              <Field label="end"><input style={inputStyle} value={featureForm.end} onChange={(e: any) => updateFeature('end', e.target.value)} /></Field>
            </div>
            <button style={{...buttonStyle, marginTop: 14}} disabled={!!busy} onClick={handleFeatureBuild}>构建 feature snapshot</button>
          </section>
          <div style={{display: 'grid', gap: 12}}>
            <section style={sectionStyle}>
              <h3 style={{marginTop: 0}}>Factor metrics</h3>
              <div style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10}}>
                <div><span style={{color: '#94a3b8'}}>IC mean</span><br />{fmt(factorResult?.ic_mean, 4)}</div>
                <div><span style={{color: '#94a3b8'}}>Rank IC</span><br />{fmt(factorResult?.rank_ic_mean, 4)}</div>
                <div><span style={{color: '#94a3b8'}}>ICIR</span><br />{fmt(factorResult?.icir, 3)}</div>
                <div><span style={{color: '#94a3b8'}}>observations</span><br />{fmt(factorResult?.n_observations, 0)}</div>
              </div>
            </section>
            <ResultBlock title="factor preview" value={factorPreview} />
            <ResultBlock title="factor mining" value={factorMiningResult} />
            <ResultBlock title="feature snapshot" value={featureResult} />
            <section style={sectionStyle}>
              <h3 style={{margin: '0 0 10px'}}>已冻结特征</h3>
              <div style={{display: 'grid', gap: 8}}>
                {features.slice(0, 8).map(s => (
                  <div key={s.snapshot_id} style={{display: 'grid', gridTemplateColumns: '1.5fr 0.6fr 0.6fr 0.6fr', gap: 8, fontSize: '0.8rem'}}>
                    <span>{s.snapshot_id}</span><span>{s.bar_size || '1d'}</span><span>{fmt(s.row_count, 0)}</span><span>{s.feature_version}</span>
                  </div>
                ))}
                {!features.length ? <span style={{color: '#94a3b8'}}>暂无 feature snapshot</span> : null}
              </div>
            </section>
          </div>
        </div>
      )}

      {tab === 'evidence' && (
        <div style={{display: 'grid', gridTemplateColumns: 'minmax(620px, 1fr) minmax(360px, 0.7fr)', gap: 16}}>
          <section style={sectionStyle}>
            <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10}}>
              <h3 style={{margin: 0}}>候选证据操作</h3>
              <button style={ghostButtonStyle} disabled={!!busy} onClick={handleRegistryRebuild}>重建 registry</button>
            </div>
            <div style={{overflowX: 'auto'}}>
              <table style={{width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem'}}>
                <thead style={{color: '#94a3b8'}}>
                  <tr>
                    <th style={{textAlign: 'left', padding: 8}}>candidate</th>
                    <th style={{textAlign: 'left', padding: 8}}>strategy</th>
                    <th style={{textAlign: 'left', padding: 8}}>timeframe</th>
                    <th style={{textAlign: 'left', padding: 8}}>status</th>
                    <th style={{textAlign: 'left', padding: 8}}>evidence</th>
                    <th style={{textAlign: 'left', padding: 8}}>actions</th>
                  </tr>
                </thead>
                <tbody>
                  {candidates.map(candidate => {
                    const evidenceCount = [
                      candidate.backtest_manifest_path,
                      candidate.scorecard_path,
                      candidate.walk_forward_result_path,
                      candidate.cost_stress_result_path,
                    ].filter(Boolean).length;
                    return (
                      <tr key={candidate.candidate_id} style={{borderTop: '1px solid rgba(148,163,184,0.12)'}}>
                        <td style={{padding: 8}}>{candidate.candidate_id}</td>
                        <td style={{padding: 8}}>{candidate.strategy_id}</td>
                        <td style={{padding: 8}}>{candidate.timeframe || '-'}</td>
                        <td style={{padding: 8}}><StatusPill value={candidate.promotion_status} /></td>
                        <td style={{padding: 8}}>{evidenceCount}/4</td>
                        <td style={{padding: 8}}>
                          <div style={{display: 'flex', flexWrap: 'wrap', gap: 6}}>
                            <button style={ghostButtonStyle} disabled={!!busy} onClick={() => handleCandidateAction(candidate.candidate_id, 'materialize')}>物化</button>
                            <button style={ghostButtonStyle} disabled={!!busy} onClick={() => handleCandidateAction(candidate.candidate_id, 'gate')}>Gate</button>
                            <button style={ghostButtonStyle} disabled={!!busy} onClick={() => handleCandidateAction(candidate.candidate_id, 'pack')}>证据包</button>
                            <button style={ghostButtonStyle} disabled={!!busy} onClick={() => handleCandidateAction(candidate.candidate_id, 'robustness')}>R6</button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {!candidates.length ? <p style={{color: '#94a3b8'}}>暂无候选。先运行研究闭环。</p> : null}
            </div>
          </section>
          <div style={{display: 'grid', gap: 12}}>
            <section style={sectionStyle}>
              <h3 style={{marginTop: 0}}>Evidence registry</h3>
              <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: '0.82rem'}}>
                <span>schema</span><span>{fmt(registry?.schema_version)}</span>
                <span>state</span><span>{fmt(registry?.state || registry?.status)}</span>
                <span>path</span><span>{fmt(registry?.registry_path || registry?.path)}</span>
              </div>
            </section>
            <ResultBlock title="candidate action result" value={candidateActionResult} />
          </div>
        </div>
      )}

      {tab === 'review' && (
        <div style={{display: 'grid', gridTemplateColumns: 'minmax(360px, 0.8fr) minmax(480px, 1.2fr)', gap: 16}}>
          <section style={sectionStyle}>
            <h3 style={{marginTop: 0}}>Portfolio sim → Paper review</h3>
            <div style={{display: 'grid', gap: 12}}>
              <Field label="manifest_ids">
                <textarea
                  style={{...inputStyle, minHeight: 80}}
                  placeholder={manifests.map(m => m.strategy_candidate_id).join(',') || 'sman_xxx,sman_yyy'}
                  value={portfolioForm.manifestIds}
                  onChange={(e: any) => updatePortfolio('manifestIds', e.target.value)}
                />
              </Field>
              <Field label="initial_cash"><input style={inputStyle} value={portfolioForm.initialCash} onChange={(e: any) => updatePortfolio('initialCash', e.target.value)} /></Field>
              <div style={{display: 'flex', gap: 10}}>
                <button style={buttonStyle} disabled={!!busy} onClick={handlePortfolioSim}>运行组合模拟</button>
                <button style={ghostButtonStyle} disabled={!!busy || !portfolioResult?.portfolio_sim_id} onClick={handleCreateReview}>创建人工复核</button>
              </div>
              <Field label="reviewer"><input style={inputStyle} value={portfolioForm.reviewer} onChange={(e: any) => updatePortfolio('reviewer', e.target.value)} /></Field>
              <Field label="approval reason"><input style={inputStyle} value={portfolioForm.reviewReason} onChange={(e: any) => updatePortfolio('reviewReason', e.target.value)} /></Field>
            </div>
          </section>
          <div style={{display: 'grid', gap: 12}}>
            <section style={sectionStyle}>
              <h3 style={{margin: '0 0 10px'}}>Pending reviews</h3>
              <div style={{display: 'grid', gap: 8}}>
                {pendingReviews.map(review => (
                  <div key={review.paper_review_id} style={{display: 'grid', gridTemplateColumns: '1fr auto auto', gap: 8, alignItems: 'center', borderTop: '1px solid rgba(148,163,184,0.12)', paddingTop: 8}}>
                    <div>
                      <strong>{review.paper_review_id}</strong>
                      <div style={{color: '#94a3b8', fontSize: '0.78rem'}}>{review.strategy_manifest_id || review.portfolio_sim_id}</div>
                    </div>
                    <StatusPill value={review.status} />
                    <button style={dangerButtonStyle} disabled={!!busy} onClick={() => handleApproveReview(String(review.paper_review_id))}>人工批准</button>
                  </div>
                ))}
                {!pendingReviews.length ? <span style={{color: '#94a3b8'}}>暂无待人工复核项</span> : null}
              </div>
            </section>
            <ResultBlock title="portfolio / review result" value={portfolioResult} />
            <section style={sectionStyle}>
              <h3 style={{margin: '0 0 10px'}}>Strategy manifests</h3>
              <div style={{display: 'grid', gap: 8}}>
                {manifests.slice(0, 8).map(manifest => (
                  <div key={manifest.strategy_candidate_id} style={{display: 'grid', gridTemplateColumns: '1fr auto', gap: 8}}>
                    <span>{manifest.strategy_candidate_id}</span>
                    <StatusPill value={manifest.promotion_status} />
                  </div>
                ))}
                {!manifests.length ? <span style={{color: '#94a3b8'}}>暂无 strategy manifest；先在候选证据里物化候选。</span> : null}
              </div>
            </section>
          </div>
        </div>
      )}

      {tab === 'records' && (
        <div style={{display: 'grid', gap: 18}}>
          <section style={sectionStyle}>
            <ExperimentList experiments={experiments} onSelectExperiment={(exp) => { setSelectedExp(exp); setSelectedReportExp(exp.experiment_id); }} />
          </section>
          <section style={sectionStyle}>
            <CandidateTable candidates={candidatesForExp} />
          </section>
          <section style={sectionStyle}>
            <ExperimentCompare />
          </section>
          <section style={sectionStyle}>
            <ExperimentReport
              experiments={experiments}
              candidates={candidatesForExp}
              selectedExpId={selectedReportExp || selectedExp?.experiment_id}
            />
          </section>
        </div>
      )}
    </div>
  );
}
