import {SAFETY_FLAGS, type HandoffSource, type HandoffTarget} from './candidate-handoff';

const ROOT = '/api/strategy-delivery';
export type DeliveryRecord = {
  schema_version: 'strategy_delivery_record_v1'; id: string; revision: number;
  source: {kind:string;run_id:string;candidate_id:string}; target: HandoffTarget;
  status: 'validated'|'validation_blocked'|'bound'|'reviewed'|'rejected'|'registered'|'revoked';
  content_digest: string; consumer_head: string; permissions: Record<string,boolean>;
  validation: {status:string;blockers:string[]};
  binding: {account_ref:string;offline_runtime?:{schema_version:string;adapter_id?:string;currency:string;
    initial_equity_usdt:number;contract_digest:string}}|null;
  review: {decision:string;actor:string;expires_at:string;reason:string}|null;
  registration: {registration_id:string;environment:string;start_allowed:false;diagnostic_admission_digest?:string|null}|null;
  diagnostic_admission?: {schema_version:'strategy_delivery_diagnostic_admission_v1';mode:'isolated_offline_diagnostic';target:HandoffTarget;
    status:'admitted'|'blocked';package_digest:string;consumer_head:string;strict_package_blockers:string[];
    research_blockers:string[];blocking_reasons:string[];decision_digest:string};
  package: {adapter_id:string;limitations:string[];
    package_validation?:{status:string;blockers:string[]}; admission_blockers?:string[];
    evidence_validation?:{status:string;blockers:string[]}; evidence_receipt_sha256?:string;
    source_head?:string;data_version?:string;instrument?:string;bar_size?:string;settlement_currency?:string;
    contracts?:Record<string,unknown>;
    audit_binding?:{qlib_run_id:string;seal_sha256:string};
    model?:{sha256:string}};
};
export function diagnosticAdmissionState(row:Pick<DeliveryRecord,'target'|'package'|'diagnostic_admission'|'content_digest'|'consumer_head'>){
  const value=row.diagnostic_admission;
  const packageResearchBlockers=Array.isArray(row.package?.admission_blockers)
    ?row.package.admission_blockers.filter((v):v is string=>typeof v==='string'):[];
  const decisionResearchBlockers=Array.isArray(value?.research_blockers)
    ?value!.research_blockers.filter((v):v is string=>typeof v==='string'):[];
  // The decision's research_blockers are only the two diagnostic exemptions.
  // Display the immutable source package's complete research verdict as well,
  // otherwise a quality failure could be hidden behind a diagnostic rejection.
  const researchBlockers=[...new Set([...packageResearchBlockers,...decisionResearchBlockers])].sort();
  if(!value)return {admitted:false,researchBlocked:researchBlockers.length>0,
    blockingReasons:['diagnostic_admission_missing'],researchBlockers};
  const valid=value.schema_version==='strategy_delivery_diagnostic_admission_v1'&&value.mode==='isolated_offline_diagnostic'
    &&value.target===row.target&&value.package_digest===row.content_digest&&value.consumer_head===row.consumer_head
    &&['admitted','blocked'].includes(value.status)
    &&/^[0-9a-f]{64}$/.test(value.decision_digest)&&Array.isArray(value.strict_package_blockers)
    &&Array.isArray(value.research_blockers)&&Array.isArray(value.blocking_reasons)
    &&[...value.strict_package_blockers,...value.research_blockers,...value.blocking_reasons].every(v=>typeof v==='string')
    &&(row.target==='offline'||value.research_blockers.length===0)
    &&value.research_blockers.every(v=>['no_simulated_fills','research_admission_not_proven'].includes(v))
    &&value.research_blockers.every(v=>value.strict_package_blockers.includes(v))
    &&value.blocking_reasons.every(v=>value.strict_package_blockers.includes(v))
    &&value.strict_package_blockers.every(v=>value.research_blockers.includes(v)!==value.blocking_reasons.includes(v));
  if(!valid)return {admitted:false,researchBlocked:researchBlockers.length>0,
    blockingReasons:['diagnostic_admission_invalid'],researchBlockers};
  return {admitted:value.status==='admitted'&&value.blocking_reasons.length===0,
    researchBlocked:researchBlockers.length>0,blockingReasons:value.blocking_reasons,
    researchBlockers};
}
export function offlineWorkerSupported(row:Pick<DeliveryRecord,'package'>,capability:{supported_adapter_ids?:unknown}){
  return Array.isArray(capability?.supported_adapter_ids)
    &&capability.supported_adapter_ids.every(v=>typeof v==='string')
    &&capability.supported_adapter_ids.includes(row.package.adapter_id);
}
export type DeliveryAccount = {account_ref:string;environment:string;expires_at:string;verified:boolean};
export type DeliveryCapabilities = {schema_version:string;commands_enabled:boolean;authenticated:boolean;
  management_configured:boolean;operator:string|null;permissions:Record<string,boolean>;auth_mode?:'key'|'local_no_password'};
export type PendingDeliveryRequest = {key:string;path:string;body:Record<string,unknown>};
export class DeliveryApiError extends Error {
  constructor(public status:number, message:string) {super(message);}
  get outcomeUnknown() {return this.status===0 || this.status===408 || this.status>=500;}
}
export function safetyClosed(value: unknown): boolean {
  const flags=value as Record<string,unknown>|null;
  return !!flags && SAFETY_FLAGS.every(key=>flags[key]===false);
}
export function sourceReference(source:HandoffSource) {
  return {kind:source.kind,run_id:source.runId,candidate_id:source.candidateId};
}
export function matchesDelivery(row:DeliveryRecord,source:HandoffSource,target:HandoffTarget) {
  return row.source?.kind===source.kind && row.source?.run_id===source.runId
    && row.source?.candidate_id===source.candidateId && row.target===target;
}
export function verifyDelivery(value:unknown, source:HandoffSource,target:HandoffTarget):DeliveryRecord {
  const row=value as DeliveryRecord;
  if (!row || row.schema_version!=='strategy_delivery_record_v1' || !/^delivery_[0-9a-f]{32}$/.test(row.id)
      || !Number.isInteger(row.revision) || row.revision<1 || !safetyClosed(row.permissions)
      || !matchesDelivery(row,source,target) || !/^[0-9a-f]{64}$/.test(row.content_digest)
      || !['validated','validation_blocked','bound','reviewed','rejected','registered','revoked'].includes(row.status)
      || !Array.isArray(row.validation?.blockers)
      || (row.diagnostic_admission!==undefined && diagnosticAdmissionState(row).blockingReasons.includes('diagnostic_admission_invalid'))
      || (row.registration && row.registration.start_allowed!==false)) {
    throw new Error('服务端交接身份或安全合同不匹配；未接收其他候选。');
  }
  return row;
}
export function createDeliveryRequest(path:string,body:Record<string,unknown>,key=crypto.randomUUID()):PendingDeliveryRequest {
  if (!(path==='/packages' || /^\/packages\/delivery_[0-9a-f]{32}\/(bind|review|register|revoke)$/.test(path))) {
    throw new Error('未允许的候选管理命令');
  }
  return {path,body,key};
}
export async function deliveryRequest(path:string,key:string,request?:PendingDeliveryRequest, signal?:AbortSignal):Promise<unknown> {
  const controller=new AbortController();
  const cancel=()=>controller.abort();
  signal?.addEventListener('abort',cancel,{once:true});
  const timer=setTimeout(cancel,30000);
  try {
    if(signal?.aborted)cancel();
    const response=await fetch(ROOT+path,{method:request?'POST':'GET',signal:controller.signal,
      headers:{'X-QS-Candidate-Intent':'candidate-management',...(key?{'X-API-Key':key}:{}),
        ...(request?{'Content-Type':'application/json','Idempotency-Key':request.key}:{})},
      ...(request?{body:JSON.stringify(request.body)}:{})});
    if(!response.ok) {
      const data=await response.json().catch(()=>null);
      const reason=typeof data?.detail==='string'?data.detail:'candidate_management_request_failed';
      throw new DeliveryApiError(response.status,reason);
    }
    return await response.json();
  } catch(error) {
    if(error instanceof DeliveryApiError)throw error;
    throw new DeliveryApiError(0,'请求结果未知；请查询回执或重试同一个幂等请求，不要创建新的登记。');
  } finally {clearTimeout(timer);signal?.removeEventListener('abort',cancel);}
}
