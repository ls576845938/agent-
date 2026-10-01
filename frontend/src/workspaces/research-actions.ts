import type {SetStateAction} from 'react';
import {researchApi} from '../lib/research-api';
import {parseWorkspaceContext} from './research/workspace-links';
import {taskApi} from '../lib/task-api';
import type {TaskResponse} from '../lib/shared-types';
import type {WorkspaceContext} from './research/workspace-links';
type LooseRecord = Record<string, any>;
interface Context {
  surface: 'research' | 'portfolio' | 'review';
  actionBlocked: boolean;
  actionLock: {current: boolean};
  dataRoot: string;
  selectedQlibRunId: string;
  source: WorkspaceContext;
  refresh: (root?: string) => Promise<void>;
  refreshIntegrationPanels: () => Promise<void>;
  upsertTask: (task: TaskResponse) => void;
  trackTask: (id: string, onComplete?: (task: TaskResponse) => Promise<void> | void) => Promise<TaskResponse>;
  autoForm: {strategyId: string; symbols: string; family: string; params: string; paramGrid: string; start: string; end: string; barSize: string; dataVersion: string; featureVersion: string};
  factorForm: {factorId: string; symbols: string; start: string; end: string; barSize: string; forwardPeriod: string};
  featureForm: {featureId: string; version: string; symbols: string; start: string; end: string; barSize: string};
  qlibForm: {profileId: string; dataVersion: string; universe: string; qlibConfig: string; startDate: string; endDate: string; runId: string; artifactsRoot: string; source: string; dryRun: boolean};
  setQlibForm: (value: SetStateAction<{profileId: string; dataVersion: string; universe: string; qlibConfig: string; startDate: string; endDate: string; runId: string; artifactsRoot: string; source: string; dryRun: boolean}>) => void;
  setAutoResult: (value: LooseRecord | null) => void;
  setFactorResult: (value: LooseRecord | null) => void;
  setFactorPreview: (value: LooseRecord | null) => void;
  setFactorMiningResult: (value: LooseRecord | null) => void;
  setFeatureResult: (value: LooseRecord | null) => void;
  setRegistry: (value: LooseRecord | null) => void;
  setCandidateActionResult: (value: LooseRecord | null) => void;
  setQlibActionResult: (value: LooseRecord | null) => void;
  setQlibRunDetail: (value: LooseRecord | null) => void;
  setBusy: (value: string) => void;
  setError: (value: string) => void;
  setMessage: (value: string) => void;
}
const splitCsv = (value: string) => value.split(/[,\n]/).map(v => v.trim()).filter(Boolean);
const parseJsonObject = (value: string): LooseRecord => {
 const parsed: unknown = JSON.parse(value || '{}');
 if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('参数必须是 JSON 对象');
 return parsed as LooseRecord;
};

// Only this page's factory owns these commands. Navigation never invokes a command.
export function createResearchActions(context: Context) {
  const {surface, actionBlocked, actionLock, dataRoot, selectedQlibRunId, source, refresh, refreshIntegrationPanels, upsertTask, trackTask, autoForm, factorForm, featureForm, qlibForm, setQlibForm, setAutoResult, setFactorResult, setFactorPreview, setFactorMiningResult, setFeatureResult, setRegistry, setCandidateActionResult, setQlibActionResult, setQlibRunDetail, setBusy, setError, setMessage} = context;
  const runTask = async (label: string, task: () => Promise<void>) => {
    if (surface !== 'research' || actionBlocked || actionLock.current) {setError('来源未就绪或任务进行中，未提交操作。'); return;}
    actionLock.current = true;
    setBusy(label); setError(''); setMessage('');
    try { await task(); } catch (e: unknown) { setError(e instanceof Error ? e.message : String(e)); }
    finally { actionLock.current = false; setBusy(''); }
  };
const submitTrackedTask = (label: string, submit: () => Promise<TaskResponse>, onComplete?: (task: TaskResponse) => Promise<void> | void) => runTask(label, async () => {
    const task = await submit();
    upsertTask(task);
    await trackTask(task.task_id, onComplete);
  });
const handleAutoCycle = () => runTask('auto-cycle', async () => {
    if (!splitCsv(autoForm.symbols).length || !autoForm.start || !autoForm.end || autoForm.start > autoForm.end) throw new Error('标的或研究日期无效');
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
    setMessage(`研究闭环已返回：${result.status || '未知'}。请核对各阶段结果，返回成功不代表候选通过门禁。`);
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
      auto_generate_formulas: true,
      max_generated_factors: 24,
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
      auto_generate_formulas: true,
      max_generated_factors: 24,
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
    await refresh(dataRoot);
  });

const handleCandidateAction = (candidateId: string, action: string) => runTask(`${candidateId}-${action}`, async () => {
    if (!['materialize','gate','pack','robustness'].includes(action) || parseWorkspaceContext(new URLSearchParams({candidate:candidateId}).toString()).errors.length) throw new Error('候选操作或编号无效');
    let result: LooseRecord;
    if (action === 'materialize') result = await researchApi.materializeEvidence(candidateId, dataRoot);
    else if (action === 'gate') result = await researchApi.checkPromotionGate(candidateId, dataRoot);
    else if (action === 'pack') result = await researchApi.saveEvidencePack(candidateId, dataRoot);
    else result = await researchApi.runRobustness(candidateId, dataRoot, 200);
    setCandidateActionResult({candidate_id: candidateId, action, result});
    await refresh(dataRoot);
  });

const qlibPayload = () => ({
    data_root: dataRoot,
    data_version: qlibForm.dataVersion,
    universe: qlibForm.universe,
    config: qlibForm.qlibConfig,
    start_date: qlibForm.startDate,
    end_date: qlibForm.endDate,
    run_id: qlibForm.runId.trim() || undefined,
    artifacts_root: qlibForm.artifactsRoot,
    source: qlibForm.source.trim() || undefined,
    dry_run: qlibForm.dryRun,
    asset_class: 'equity',
    bar_size: '1d',
  });

const handleQlibAction = (action: string) => {
    if (!['pipeline','build','workflow','scores','metrics','manifest'].includes(action) || parseWorkspaceContext(new URLSearchParams({qlibRun:qlibForm.runId,qlibRoot:qlibForm.artifactsRoot}).toString()).errors.length) {setError('Qlib 操作或运行编号无效');return;}
    if (action === 'pipeline') {
      const runId = qlibForm.runId.trim() || 'qlib-' + crypto.randomUUID();
      if (qlibForm.artifactsRoot !== 'artifacts/qlib_runs') {setError('统一流水线只写标准研究目录。');return;}
      void submitTrackedTask('qlib-pipeline', async () => {
        const task = await taskApi.submitQlibPipelineTask({profile_id:qlibForm.profileId,run_id:runId,
          data_version:qlibForm.dataVersion,dry_run:qlibForm.dryRun});
        setQlibForm(current=>({...current,runId}));
        return task;
      }, async task => {
        setQlibActionResult({action,run_id:runId,task_id:task.task_id,status:task.status,error:task.error,...(task.result || {})});
        await refreshIntegrationPanels();
        setQlibRunDetail(await researchApi.getQlibRun(runId,qlibForm.artifactsRoot).catch(()=>null));
        if(task.status === 'failed') {setError('本次 Qlib 任务失败：' + (task.error || '请检查该 run 的失败证据'));return;}
        setMessage(qlibForm.dryRun ? '仅检查完成，尚未训练。' : '研究任务已返回。请分别核对预测质量、七层阻断和账本重算；交易权限未解锁。');
      });
      return;
    }
    if (qlibForm.profileId === 'okx_btc_trend_1h') {setError('此冻结 profile 请使用统一研究流水线，避免阶段配置不一致。');return;}
    if (action === 'build' || action === 'workflow') {
      void submitTrackedTask(`qlib-${action}`, async () => (
        action === 'build'
          ? taskApi.submitQlibBuildDatasetTask(qlibPayload())
          : taskApi.submitQlibWorkflowTask(qlibPayload())
      ), async (task) => {
        if (task.status === 'failed') {
          setQlibActionResult({action,task_id:task.task_id,status:'failed',error:task.error});
          setError('Qlib 阶段失败：' + (task.error || '未知错误'));setQlibRunDetail(null);
          await refreshIntegrationPanels();return;
        }
        const result = (task.result ?? {}) as LooseRecord;
        setQlibActionResult({action, task_id: task.task_id, ...result});
        await refreshIntegrationPanels();
        const runId = String(result.run_id || '');
        if (runId) {
          setQlibRunDetail(await researchApi.getQlibRun(runId, qlibForm.artifactsRoot).catch(() => null));
          setQlibForm(current => ({...current, runId}));
        }
        setMessage(`Qlib task ${task.status.toUpperCase()}: ${task.label}`);
      });
      return;
    }

    void runTask(`qlib-${action}`, async () => {
      let result: LooseRecord;
      if (action === 'scores') {
        if (!selectedQlibRunId) throw new Error('先填写或选择 run_id');
        result = await researchApi.importQlibPredScore({...qlibPayload(), run_id: selectedQlibRunId});
      } else if (action === 'metrics') {
        if (!selectedQlibRunId) throw new Error('先填写或选择 run_id');
        result = await researchApi.importQlibRecorderMetrics({...qlibPayload(), run_id: selectedQlibRunId});
      } else {
        if (!selectedQlibRunId) throw new Error('先填写或选择 run_id');
        result = await researchApi.compileQlibStrategyManifest({...qlibPayload(), run_id: selectedQlibRunId});
      }
      setQlibActionResult({action, ...result});
      await refreshIntegrationPanels();
      const runId = String(result.run_id || selectedQlibRunId || '');
      if (runId) {
        setQlibRunDetail(await researchApi.getQlibRun(runId, qlibForm.artifactsRoot).catch(() => null));
        setQlibForm(current => ({...current, runId}));
      }
    });
  };
  return {handleAutoCycle, handleFactorEvaluate, handleFactorCompute, handleFactorMine, handleFactorMineAndRun, handleFeatureBuild, handleRegistryRebuild, handleCandidateAction, handleQlibAction};
}
