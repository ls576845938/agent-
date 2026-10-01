import type {SetStateAction} from 'react';
import {researchApi} from '../lib/research-api';
import {runEvidenceErrors, firstTargetImportAllowed} from './research/workspace-evidence';
import {taskApi} from '../lib/task-api';
import type {TaskResponse} from '../lib/shared-types';
import type {WorkspaceContext} from './research/workspace-links';
type LooseRecord = Record<string, any>;
interface Context {
  surface: 'research' | 'portfolio' | 'review';
  actionBlocked: boolean;
  actionLock: {current: boolean};
  draftBinding: {current: {runId: string; configKey: string} | null};
  dataRoot: string;
  selectedQlibRunId: string;
  selectedPortfolioRunId: string;
  selectedManifestIds: string[];
  manifests: LooseRecord[];
  qlibRuns: LooseRecord[];
  portfolioIntegrationRuns: LooseRecord[];
  source: WorkspaceContext;
  portfolioIntegrationDetail: LooseRecord | null;
  qlibRunDetail: LooseRecord | null;
  matchingPortfolioConfig: boolean;
  refresh: (root?: string) => Promise<void>;
  refreshIntegrationPanels: () => Promise<void>;
  upsertTask: (task: TaskResponse) => void;
  trackTask: (id: string, onComplete?: (task: TaskResponse) => Promise<void> | void) => Promise<TaskResponse>;
  portfolioForm: {manifestIds: string; initialCash: string; reviewer: string; reviewReason: string};
  qlibForm: {dataVersion: string; universe: string; qlibConfig: string; startDate: string; endDate: string; runId: string; artifactsRoot: string; source: string; dryRun: boolean};
  pypfoptForm: {scoreRunId: string; portfolioRunId: string; config: string; artifactsRoot: string; fallbackOptimizer: string; strategyId: string};
  setPypfoptForm: (value: SetStateAction<{scoreRunId: string; portfolioRunId: string; config: string; artifactsRoot: string; fallbackOptimizer: string; strategyId: string}>) => void;
  setPortfolioResult: (value: LooseRecord | null) => void;
  setPypfoptActionResult: (value: LooseRecord | null) => void;
  setPortfolioIntegrationDetail: (value: LooseRecord | null) => void;
  setExecutionPipelineResult: (value: LooseRecord | null) => void;
  setBusy: (value: string) => void;
  setError: (value: string) => void;
  setMessage: (value: string) => void;
}

// Only this page's factory owns these commands. Navigation never invokes a command.
export function createPortfolioActions(context: Context) {
  const {surface, actionBlocked, actionLock, dataRoot, selectedQlibRunId, selectedPortfolioRunId, selectedManifestIds, manifests, qlibRuns, portfolioIntegrationRuns, source, portfolioIntegrationDetail, refresh, refreshIntegrationPanels, upsertTask, trackTask, portfolioForm, qlibForm, pypfoptForm, setPypfoptForm, setPortfolioResult, setPypfoptActionResult, setPortfolioIntegrationDetail, setExecutionPipelineResult, setBusy, setError, setMessage} = context;
  const runTask = async (label: string, task: () => Promise<void>) => {
    if (surface !== 'portfolio' || actionBlocked || actionLock.current) {setError('来源未就绪或任务进行中，未提交操作。'); return;}
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
const handlePortfolioSim = () => runTask('portfolio-sim', async () => {
    const manifestIds = selectedManifestIds;
    if (dataRoot !== 'data') throw new Error('现有组合模拟接口仅支持默认 data 目录；自定义目录仅可查看，不会提交到其他目录。');
    if (!manifestIds.length) throw new Error('请明确选择策略证据，不会默认运行全部候选。');
    if (manifestIds.some(id => !manifests.some(m => m.strategy_candidate_id === id && ['READY_FOR_PORTFOLIO_SIM','PAPER_REVIEW_CANDIDATE'].includes(String(m.promotion_status))))) throw new Error('所选策略证据缺失或不满足组合模拟入口要求。');
    if (!Number.isFinite(Number(portfolioForm.initialCash)) || Number(portfolioForm.initialCash) <= 0) throw new Error('初始资金必须为正数');
    const result = await researchApi.runPortfolioSim(manifestIds, {
      initial_cash: Number(portfolioForm.initialCash || 50000),
    });
    setPortfolioResult(result);
  });

const pypfoptPayload = () => ({
    score_run_id: pypfoptForm.scoreRunId.trim() || selectedQlibRunId,
    portfolio_run_id: pypfoptForm.portfolioRunId.trim() || undefined,
    config: pypfoptForm.config,
    fallback_optimizer: pypfoptForm.fallbackOptimizer || undefined,
    strategy_id: pypfoptForm.strategyId.trim() || undefined,
  });

const handlePypfoptAction = (action: string) => {
    if (!['expected','covariance','optimize','import'].includes(action)) {setError('未知的组合操作；未提交。');return;}
    if (actionBlocked || surface !== 'portfolio') {setError('来源未就绪，未提交组合操作。'); return;}
    const configKey = JSON.stringify([pypfoptForm.scoreRunId,pypfoptForm.config,pypfoptForm.fallbackOptimizer,pypfoptForm.strategyId,dataRoot,qlibForm.artifactsRoot,pypfoptForm.artifactsRoot]);
    if (!source.portfolioRun && pypfoptForm.portfolioRunId && action !== 'import' && (context.draftBinding.current?.runId !== pypfoptForm.portfolioRunId || context.draftBinding.current.configKey !== configKey)) {setError('草稿配置绑定缺失或已改变；请新建版本，不能混用中间产物。');return;}
    if ((source.portfolioRun || portfolioIntegrationRuns.some(run => run.portfolio_run_id === pypfoptForm.portfolioRunId && (run.has_target_positions || Number(run.target_weight_rows) > 0))) && action !== 'import') {setError('已有组合版本不允许覆盖；请新建版本。'); return;}
    if (dataRoot !== 'data' || qlibForm.artifactsRoot !== 'artifacts/qlib_runs' || pypfoptForm.artifactsRoot !== 'artifacts/portfolio_runs') {setError('现有优化器配置绑定默认数据和产物目录。此自定义来源只读，不能静默改用默认目录执行。'); return;}
    if (runEvidenceErrors(pypfoptForm.scoreRunId, qlibForm.artifactsRoot, context.qlibRunDetail, 'qlib').length || !pypfoptForm.scoreRunId) {setError('评分原件未核验，未提交组合操作。');return;}
    if (action === 'import' && (runEvidenceErrors(selectedPortfolioRunId,pypfoptForm.artifactsRoot,portfolioIntegrationDetail,'portfolio',pypfoptForm.scoreRunId).length || !context.matchingPortfolioConfig)) {setError('组合原件或配置尚未匹配，禁止导入。');return;}
    if (action === 'import' && !firstTargetImportAllowed(portfolioIntegrationRuns,portfolioIntegrationDetail,selectedPortfolioRunId)) {setError('目标持仓已存在、状态未知或尚无权重；禁止重复导入覆盖。');return;}
    if (action !== 'import' && !qlibRuns.some(run => run.run_id === pypfoptForm.scoreRunId && Number(run.score_rows) > 0)) {setError('请选择当前来源中有评分记录的 Qlib 运行。'); return;}
    if (action === 'optimize') {
      void submitTrackedTask('pypfopt-optimize', async () => taskApi.submitPortfolioOptimizeWeightsTask(pypfoptPayload()), async (task) => {
        const result = (task.result ?? {}) as LooseRecord;
        setPypfoptActionResult({action, task_id: task.task_id, ...result});
        await refreshIntegrationPanels();
        const portfolioRunId = String(result.portfolio_run_id || pypfoptPayload().portfolio_run_id || selectedPortfolioRunId || '');
        if (portfolioRunId) {
          context.draftBinding.current = {runId: portfolioRunId, configKey};
          setPypfoptForm(current => ({...current, portfolioRunId: current.portfolioRunId || portfolioRunId}));
          setPortfolioIntegrationDetail(await researchApi.getPortfolioIntegrationRun(portfolioRunId, pypfoptForm.artifactsRoot).catch(() => null));
        }
        setMessage(`PyPortfolioOpt task ${task.status.toUpperCase()}: ${task.label}`);
      });
      return;
    }

    void runTask(`pypfopt-${action}`, async () => {
      const payload = pypfoptPayload();
      if (action !== 'import' && !payload.score_run_id) throw new Error('先填写 score_run_id 或选择 Qlib run');
      if (action === 'import' && !selectedPortfolioRunId) throw new Error('先填写或选择 portfolio_run_id');
      let result: LooseRecord;
      if (action === 'expected') {
        result = await researchApi.buildPortfolioExpectedReturns(payload);
      } else if (action === 'covariance') {
        result = await researchApi.buildPortfolioCovariance(payload);
      } else {
        result = await researchApi.importPortfolioTargetWeights({...payload, portfolio_run_id: selectedPortfolioRunId});
      }
      setPypfoptActionResult({action, ...result});
      await refreshIntegrationPanels();
      const portfolioRunId = String(result.portfolio_run_id || payload.portfolio_run_id || selectedPortfolioRunId || '');
      if (portfolioRunId) {
        context.draftBinding.current = {runId: portfolioRunId, configKey};
        setPypfoptForm(current => ({...current, portfolioRunId: current.portfolioRunId || portfolioRunId}));
        setPortfolioIntegrationDetail(await researchApi.getPortfolioIntegrationRun(portfolioRunId, pypfoptForm.artifactsRoot).catch(() => null));
      }
    });
  };

const handleResearchExecutionPipeline = () => runTask('research-execution-pipeline', async () => {
    const qlibRunId = pypfoptForm.scoreRunId.trim();
    const portfolioRunId = selectedPortfolioRunId || pypfoptForm.portfolioRunId.trim();
    if (!qlibRunId) throw new Error('先选择 Qlib score run');
    if (!portfolioRunId) throw new Error('先生成或选择 portfolio run');
    const selected = portfolioIntegrationRuns.find(run => run.portfolio_run_id === portfolioRunId);
    if (!selected?.has_target_positions || selected.source_score_run_id !== qlibRunId) throw new Error('组合版本缺少目标持仓，或与评分来源不匹配。');
    if (!portfolioIntegrationDetail?.run_manifest) throw new Error('请先加载所选组合的完整来源与配置，再运行验证。');
    if (!context.matchingPortfolioConfig) throw new Error('当前配置与组合原件未匹配，禁止使用默认配置冒充原版本。');
    if (dataRoot !== 'data' || qlibForm.artifactsRoot !== 'artifacts/qlib_runs' || pypfoptForm.artifactsRoot !== 'artifacts/portfolio_runs') throw new Error('自定义来源仅可查看。');
    const result = await researchApi.runResearchExecutionPipeline({
      qlib_run_id: qlibRunId,
      qlib_config: qlibForm.qlibConfig,
      portfolio_config: pypfoptForm.config,
      portfolio_run_id: portfolioRunId,
      strategy_id: pypfoptForm.strategyId,
      qlib_runs_root: qlibForm.artifactsRoot,
      portfolio_runs_root: pypfoptForm.artifactsRoot,
      pipeline_runs_root: 'artifacts/research_execution_runs',
      initial_cash: Number(portfolioForm.initialCash || 50000),
      risk_max_order_notional_pct: 0.25,
      walk_forward_train_bars: 252,
      walk_forward_test_bars: 63,
      walk_forward_step_bars: 63,
    });
    setExecutionPipelineResult(result);
    setMessage(`研究执行流水线返回: ${result.status || 'unknown'}；请逐项核验，返回响应不代表全部通过。`);
    await refresh(dataRoot);
  });
  return {handlePortfolioSim, handlePypfoptAction, handleResearchExecutionPipeline};
}
