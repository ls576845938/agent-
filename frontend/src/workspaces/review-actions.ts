import {researchApi} from '../lib/research-api';
import {reviewSourceEligible} from './research/workspace-evidence';

import type {WorkspaceContext} from './research/workspace-links';
type LooseRecord = Record<string, any>;
interface Context {
  surface: 'research' | 'portfolio' | 'review';
  actionBlocked: boolean;
  actionLock: {current: boolean};
  dataRoot: string;
  portfolioResult: LooseRecord | null;
  paperReviewEntry: LooseRecord | null;
  source: WorkspaceContext;
  pendingReviews: LooseRecord[];
  refresh: (root?: string) => Promise<void>;
  portfolioForm: {manifestIds: string; initialCash: string; reviewer: string; reviewReason: string};
  setPortfolioResult: (value: LooseRecord | null) => void;
  setBusy: (value: string) => void;
  setError: (value: string) => void;
  setMessage: (value: string) => void;
}

// Only this page's factory owns these commands. Navigation never invokes a command.
export function createReviewActions(context: Context) {
  const {surface, actionBlocked, actionLock, dataRoot, portfolioResult, paperReviewEntry, refresh, portfolioForm, setPortfolioResult, setBusy, setError, setMessage} = context;
  const runTask = async (label: string, task: () => Promise<void>) => {
    if (surface !== 'review' || dataRoot !== 'data' || actionBlocked || actionLock.current) {setError('来源未就绪、自定义目录只读或任务进行中，未提交操作。'); return;}
    actionLock.current = true;
    setBusy(label); setError(''); setMessage('');
    try { await task(); } catch (e: unknown) { setError(e instanceof Error ? e.message : String(e)); }
    finally { actionLock.current = false; setBusy(''); }
  };

const handleCreateReview = () => runTask('paper-review-create', async () => {
    const simId = String(portfolioResult?.portfolio_sim_id || '');
    if (!simId) throw new Error('先运行 portfolio simulation');
    if (paperReviewEntry?.creation_allowed !== true) throw new Error('当前复核创建门禁未通过');
    const result = await researchApi.createPaperReview(simId, dataRoot);
    setPortfolioResult({...(portfolioResult || {}), paper_review: result});
    await refresh(dataRoot);
  });

const handleCreateReviewFromManifest = (manifestId: string) => runTask(`manifest-review-${manifestId}`, async () => {
    if (!reviewSourceEligible(paperReviewEntry,'manifest',manifestId)) throw new Error('当前策略证据不在已核验的合格列表中');
    if (!context.source.manifests.includes(manifestId)) throw new Error('策略证据不是当前明确选中的来源');
    if (paperReviewEntry?.creation_allowed !== true) throw new Error('当前复核创建门禁未通过');
    const result = await researchApi.createPaperReviewFromManifest(manifestId, dataRoot);
    setPortfolioResult({strategy_manifest_id: manifestId, paper_review: result});
    setMessage(`已把 ${manifestId} 放入 paper review queue。`);
    await refresh(dataRoot);
  });

const handleCreateReviewFromCandidate = (candidateId: string) => runTask(`candidate-review-${candidateId}`, async () => {
    if (!reviewSourceEligible(paperReviewEntry,'candidate',candidateId)) throw new Error('当前候选不在已核验的合格列表中');
    if (!candidateId || candidateId !== context.source.candidate) throw new Error('候选不是当前明确选中的来源');
    if (paperReviewEntry?.creation_allowed !== true) throw new Error('当前复核创建门禁未通过');
    const result = await researchApi.createPaperReviewFromCandidate(candidateId, dataRoot);
    setPortfolioResult({candidate_id: candidateId, paper_review: result});
    setMessage(`已从 candidate ${candidateId} 创建 paper review evidence。`);
    await refresh(dataRoot);
  });

const handleApproveReview = (reviewId: string) => runTask(`approve-${reviewId}`, async () => {
    if (!context.pendingReviews.some(review => review.paper_review_id === reviewId)) throw new Error('复核记录不在当前待审队列');
    if (!portfolioForm.reviewer.trim() || !portfolioForm.reviewReason.trim()) throw new Error('填写复核人和批准理由后才能人工批准');
    const result = await researchApi.approvePaperReview(reviewId, portfolioForm.reviewer, portfolioForm.reviewReason);
    setPortfolioResult({approved_review: result});
    await refresh(dataRoot);
  });
  return {handleCreateReview, handleCreateReviewFromManifest, handleCreateReviewFromCandidate, handleApproveReview};
}
