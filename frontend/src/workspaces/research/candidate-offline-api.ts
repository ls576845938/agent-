import {DeliveryApiError,safetyClosed} from './candidate-delivery-api';

export const registeredOfflineId=(value:string)=>/^coff_[0-9a-f]{32}$/.test(value);
export type OfflineCommand={path:string;body:Record<string,unknown>;key:string};
export async function offlineRequest(path:string,credential:string,command?:OfflineCommand,signal?:AbortSignal):Promise<any> {
  if(!/^\/(capabilities|catalog|jobs|publish|jobs\/coff_[0-9a-f]{32}(\/(result(\?before=[1-9][0-9]{0,9})?|stop|resume))?)$/.test(path))throw new Error('未知离线路径');
  try {
    const response=await fetch('/api/candidate-offline'+path,{method:command?'POST':'GET',signal,
      headers:{'X-QS-Candidate-Intent':'candidate-management',...(credential?{'X-API-Key':credential}:{}),
        ...(command?{'Content-Type':'application/json','Idempotency-Key':command.key}:{})},
      ...(command?{body:JSON.stringify(command.body)}:{})});
    if(!response.ok){const result=await response.json().catch(()=>null);throw new DeliveryApiError(response.status,result?.detail||'离线请求被拒绝');}
    return await response.json();
  }catch(error){if(error instanceof DeliveryApiError)throw error;throw new DeliveryApiError(0,'结果未知，请保留原幂等键重试；不会新建作业。');}
}
export function verifyOfflineResult(value:any,id:string){
  const fields=['job_id','registration_id','content_digest','binding_digest','account_ref','account_identity_hash',
    'runtime_contract_digest','state_directory_sha256','input_revision_id','input_digest','input_head',
    'input_evidence_kind','source_head','execution_head','catalog_sha256'];
  const authority=value?.job?.job_identity;
  const shape=(identity:any)=>identity&&typeof identity==='object'&&!Array.isArray(identity)
    &&Object.keys(identity).sort().join('|')===['schema_version',...fields].sort().join('|')
    &&identity.schema_version==='candidate_offline_job_identity_v1'
    &&fields.every(k=>typeof identity[k]==='string'&&identity[k].length>0)
    &&['content_digest','binding_digest','account_identity_hash','runtime_contract_digest',
      'state_directory_sha256','input_digest','catalog_sha256'].every(k=>/^[0-9a-f]{64}$/.test(identity[k]))
    &&['source_head','execution_head','input_head'].every(k=>/^[0-9a-f]{40}$/.test(identity[k]))
    &&['registration_id','account_ref','input_revision_id'].every(k=>/^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$/.test(identity[k])&&identity[k]!=='latest')
    &&['synthetic_fixture','verified_historical_observations'].includes(identity.input_evidence_kind);
  // Compare every canonical field to the authoritative job, not the evidence's
  // self-recomputed SHA. The server also recomputes the canonical identity digest.
  const bound=(entry:any)=>shape(entry?.job_identity)
    &&/^[0-9a-f]{64}$/.test(entry?.job_identity_digest)
    &&entry.job_identity_digest===value.job.job_identity_digest
    &&fields.every(k=>entry[k]===authority[k]&&entry.job_identity[k]===authority[k]);
  if(!registeredOfflineId(id)||value?.job?.id!==id||!safetyClosed(value?.permissions)||!safetyClosed(value?.job?.permissions)
    ||!shape(authority)||authority.job_id!==id||value.job.schema_version!=='candidate_offline_job_v2'||!bound(value.job)
    ||value?.start_allowed!==false||value?.result_bound!==(value?.result!==null)
    ||(value.result&&(!bound(value.result)
      ||value.result.schema_version!=='candidate_offline_result_v2'||!safetyClosed(value.result.permissions)))
    ||!Array.isArray(value.decisions)
    ||value.decisions.some((d:any)=>!bound(d)||d.schema_version!=='candidate_offline_decision_v2')) {
    throw new Error('离线结果身份或安全合同不匹配；不回退到其他作业。');
  }
  return value;
}
