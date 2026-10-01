// Browser preparation only. Neither these objects nor local storage are an
// approval receipt, an executable package, or an input to the runtime registry.
export const SAFETY_FLAGS = ['demo_control_enabled','execution_permission','runtime_observed',
  'promotion','paper','live','private','order','real_order','transfer','withdraw'] as const;
const QLIB_REQUIRED_FLAGS = ['execution_permission','runtime_observed','promotion','paper','live','private','order'];
const FACTORY_REQUIRED_FLAGS = SAFETY_FLAGS.filter(key => key !== 'demo_control_enabled');
const ID = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const HASH = /^[0-9a-f]{64}$/;
export const HANDOFF_STORAGE_PREFIX = 'qs.research-handoff.v1.';
export type SourceKind = 'factory' | 'qlib';
export type HandoffTarget = 'offline' | 'okx_demo';
type RecordLike = Record<string, any>;
export type HandoffArtifact = {key: string; label: string; reference: string; kind: 'sealed_reference' | 'research_reference' | 'missing'};
export type HandoffSource = {
  kind: SourceKind; runId: string; candidateId: string; qlibRunId: string;
  strategyId: string; sourceHead: string; dataVersion: string; market: string;
  instrument: string; barSize: string; asOf: string; researchStatus: string;
  artifacts: HandoffArtifact[]; blockers: string[];
};
export type HandoffDraft = {
  schema_version: 'research_candidate_handoff_draft_v1'; id: string; created_at: string;
  status: 'local_draft'; source: HandoffSource; source_fingerprint: string;
  target: HandoffTarget; account_binding: 'not_bound'; note: string;
  acknowledgement: true; permissions: Record<typeof SAFETY_FLAGS[number], false>;
};
const value = (input: unknown) => typeof input === 'string' ? input.trim().slice(0,512) : '';
const strings = (input: unknown) => Array.isArray(input) ? input.filter((v): v is string => typeof v === 'string').slice(0,50).map(value) : [];
function requireFact(condition: unknown, message: string): asserts condition {if (!condition) throw new Error(message);}
function validId(id: unknown) {return typeof id === 'string' && ID.test(id) && id !== 'latest';}
function validUuid(id: unknown) {return typeof id === 'string' && UUID.test(id);}
function safe(input: RecordLike, required: readonly string[]) {
  return !!input && required.every(key => input[key] === false)
    && SAFETY_FLAGS.every(key => input[key] === undefined || input[key] === false);
}
function agree(values: unknown[], label: string) {
  const known = values.map(value).filter(Boolean);
  requireFact(new Set(known).size <= 1, `${label}冲突；不自动选择一份来源。`);
  return known[0] || '';
}
function artifact(key: string, label: string, hash: unknown, researchOnly = false): HandoffArtifact {
  const ref = value(hash);
  return {key,label,reference: HASH.test(ref) ? ref : '',
    kind: HASH.test(ref) ? researchOnly ? 'research_reference' : 'sealed_reference' : 'missing'};
}
export function resolveHandoffSource(kind: SourceKind, runId: string, data: RecordLike | null, candidateId = ''): HandoffSource {
  requireFact(validId(runId) && (kind === 'factory' || kind === 'qlib'), '研究运行引用无效；不解析 latest。');
  requireFact(data?.integrity_status === 'passed', '研究证据未通过完整性校验。');
  requireFact(safe(data,kind === 'factory' ? FACTORY_REQUIRED_FLAGS : QLIB_REQUIRED_FLAGS), '研究安全合同缺失或异常。');
  if (kind === 'factory') {
    requireFact(data.run_id === runId, '工厂运行身份不匹配。');
    const candidates = Array.isArray(data.result?.candidates) ? data.result.candidates : [];
    const matches = candidates.filter((row: RecordLike) => row.candidate_id === candidateId);
    requireFact(validId(candidateId) && matches.length === 1, '必须选择唯一、精确的工厂候选；不回退到第一条或训练子试验。');
    const row = matches[0], profile = data.result?.profile || {};
    requireFact(row.factory_run_id === runId && safe(row,FACTORY_REQUIRED_FLAGS), '工厂候选身份或安全合同不匹配。');
    requireFact(validId(row.qlib_run_id || '') && row.audit_qlib_reference?.qlib_run_id === row.qlib_run_id,
      '最终审计 Qlib 引用不匹配；不能使用训练折模型替代。');
    return {kind,runId,candidateId,qlibRunId:row.qlib_run_id,strategyId:value(row.strategy_config?.strategy_id),
      sourceHead:value(data.source_head),dataVersion:value(row.data_version),market:value(profile.market),
      instrument:strings(profile.symbols).join(', '),barSize:value(profile.bar_size),asOf:value(data.result?.lineage?.as_of),
      researchStatus:value(row.status),blockers:strings(row.gate?.blockers),artifacts:[
        artifact('audit','最终审计 Qlib 封印引用',row.audit_qlib_reference?.seal_sha256),
        artifact('features','冻结特征定义',row.frozen_champion?.feature_spec_hash),
        artifact('model','模型文件与预处理包',null),artifact('calibration','校准／输出单位与期限',null),
        artifact('position','候选仓位规则版本',null),artifact('exit','候选退出规则版本',null),
        artifact('cost','成本／时间／数量单位合同',null),artifact('package','可运行策略包与审定回执',null)]};
  }
  const summary = data.summary || {}, manifest = data.strategy_manifest || {}, trace = data.research_trace || {};
  requireFact(SAFETY_FLAGS.every(key => manifest[key] === undefined || manifest[key] === false), '策略清单权限合同异常。');
  requireFact(summary.run_id === runId && data.seal?.run_id === runId, 'Qlib 运行或封印身份不匹配。');
  requireFact(!manifest.run_id || manifest.run_id === runId, 'Qlib 策略清单不属于当前运行。');
  requireFact(!data.research_trace || trace.identity?.qlib_run_id === runId, 'Qlib 决策来源不匹配。');
  requireFact(!data.research_trace || SAFETY_FLAGS.every(key => trace[key] === undefined || trace[key] === false), '研究决策权限合同异常。');
  const resolvedCandidate = agree([manifest.candidate_id,trace.identity?.candidate_id], '候选身份');
  requireFact(validId(resolvedCandidate) && (!candidateId || resolvedCandidate === candidateId), '此研究运行没有精确候选身份，不能生成部署交接。');
  const head = agree([summary.source_head,data.seal?.source_head,trace.identity?.source_head,manifest.commit_hash], '源码版本');
  const files = data.seal?.files || {};
  return {kind,runId,candidateId:resolvedCandidate,qlibRunId:runId,
    strategyId:agree([manifest.strategy_id,trace.identity?.strategy_id], '策略身份'),sourceHead:head,
    dataVersion:agree([summary.data_version,trace.identity?.data_version], '数据版本'),
    market:agree([summary.asset_class,manifest.asset_class], '市场'),
    instrument:agree([strings(summary.symbols).join(', '),strings(manifest.symbols).join(', '),trace.identity?.instrument], '标的'),
    barSize:agree([summary.bar_size,manifest.timeframe,trace.identity?.bar_size], '周期'),asOf:value(trace.as_of),
    researchStatus:value(manifest.promotion_status || summary.promotion_status) || 'unknown',
    blockers:strings(trace.blockers),artifacts:[artifact('model','模型文件',files['model.txt']),
      artifact('features','特征与预处理研究配置',files['qlib_workflow_config.yaml'],true),
      artifact('calibration','校准／输出单位与期限',files['research_trace.json'],true),
      artifact('position','仓位规则（研究清单，非运行审定）',files['qlib_strategy_manifest.json'],true),
      artifact('exit','退出规则（研究清单，非运行审定）',files['qlib_strategy_manifest.json'],true),
      artifact('cost','成本／时间／数量单位（研究清单）',files['qlib_strategy_manifest.json'],true),
      artifact('package','可运行策略包与审定回执',null)]};
}
export const isBtcSource = (source: HandoffSource) => source.market === 'crypto' && source.instrument === 'BTC-USDT-SWAP';
export const canPublishRuntimeCandidate = (): false => false;
export const sourceFingerprint = (source: HandoffSource) => JSON.stringify(source);
export function handoffSourceLink(source: HandoffSource) {
  return '/research?' + new URLSearchParams({view:'run-details',
    [source.kind === 'factory' ? 'factoryRun' : 'qlibRun']:source.runId}).toString();
}
export function createHandoffDraft(source: HandoffSource, target: HandoffTarget, note: string,
  acknowledged: boolean, id: string, createdAt: string): HandoffDraft {
  requireFact(acknowledged, '请先确认：交接草稿不构成部署或交易授权。');
  requireFact(validUuid(id) && Number.isFinite(Date.parse(createdAt)), '交接草稿编号或时间无效。');
  requireFact(target === 'offline' || (target === 'okx_demo' && isBtcSource(source)), '目标环境不受支持，不能路由到 BTC Demo。');
  requireFact(typeof note === 'string' && note.length <= 500, '交接说明最多 500 字。');
  return {schema_version:'research_candidate_handoff_draft_v1',id,created_at:createdAt,status:'local_draft',
    source,source_fingerprint:sourceFingerprint(source),target,account_binding:'not_bound',note,
    acknowledgement:true,permissions:Object.fromEntries(SAFETY_FLAGS.map(key=>[key,false])) as HandoffDraft['permissions']};
}
export function parseHandoffDraft(raw: string): HandoffDraft {
  requireFact(raw.length < 30000, '本地交接草稿过大。');
  const draft = JSON.parse(raw);
  requireFact(draft?.schema_version === 'research_candidate_handoff_draft_v1' && draft.status === 'local_draft'
    && draft.account_binding === 'not_bound' && draft.acknowledgement === true
    && SAFETY_FLAGS.every(key=>draft.permissions?.[key] === false), '本地草稿格式或权限异常；不能作为审批回执。');
  const source = draft.source;
  requireFact(source && ['factory','qlib'].includes(source.kind) && validId(source.runId) && validId(source.candidateId)
    && validId(source.qlibRunId) && Array.isArray(source.artifacts) && source.artifacts.length <= 12
    && source.artifacts.every((row: HandoffArtifact)=>row && ['key','label','reference'].every(key=>typeof row[key as keyof HandoffArtifact] === 'string')
      && ['sealed_reference','research_reference','missing'].includes(row.kind))
    && ['strategyId','sourceHead','dataVersion','market','instrument','barSize','asOf','researchStatus'].every(key=>typeof source[key] === 'string')
    && Array.isArray(source.blockers) && source.blockers.every((row: unknown)=>typeof row === 'string')
    && draft.source_fingerprint === sourceFingerprint(source), '本地草稿来源损坏；请从研究页重新创建。');
  // Reconstruct the whitelist. Never propagate injected approval or account fields.
  return createHandoffDraft(source,draft.target,draft.note,true,draft.id,draft.created_at);
}
export function parseHandoffSelector(search: string): string | null {
  const values = new URLSearchParams(search).getAll('researchHandoff');
  if (!values.length) return null;
  requireFact(values.length === 1 && validUuid(values[0]), '交接引用无效或重复；未选择其他草稿。');
  return values[0];
}
export function readHandoffDraft(storage: Pick<Storage,'getItem'>, id: string) {
  requireFact(validUuid(id), '交接草稿编号无效。');
  const raw=storage.getItem(HANDOFF_STORAGE_PREFIX+id);
  requireFact(raw, '当前标签页没有此交接草稿；请从研究页重新准备。');
  const draft=parseHandoffDraft(raw);
  requireFact(draft.id===id, '草稿编号不匹配。');
  return draft;
}
export const reconcileHandoffDraft = (draft: HandoffDraft, source: HandoffSource) =>
  draft.source_fingerprint === sourceFingerprint(source) ? 'matched' : 'changed';
