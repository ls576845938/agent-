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
  if(value?.job?.schema_version==='candidate_offline_cohort_job_v1')return verifyCohortOfflineResult(value,id);
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
      ||value.result.schema_version!=='candidate_offline_result_v2'||!safetyClosed(value.result.permissions)
      ||(value.result.adapter_id!==undefined
        &&!['factory_lgbm_ast_v1','btc_donchian_history_offline_v1'].includes(value.result.adapter_id))
      ||(value.result.adapter_id==='btc_donchian_history_offline_v1'
        &&value.job.status==='complete'&&(value.result.finalized!==true||value.result.artifact_status!=='complete'))))
    ||!Array.isArray(value.decisions)
    ||value.decisions.some((d:any)=>!bound(d)||d.schema_version!=='candidate_offline_decision_v2')) {
    throw new Error('离线结果身份或安全合同不匹配；不回退到其他作业。');
  }
  return value;
}

function verifyCohortOfflineResult(value:any,id:string){
  const authority=value?.job?.job_identity;
  const member=(row:any)=>row&&typeof row==='object'&&!Array.isArray(row)
    &&Object.keys(row).sort().join('|')===['adapter_id','binding_digest','content_digest','input_digest','input_evidence_kind',
      'input_head','input_revision_id','member_id','registration_id','registration_revision','source_account_ref',
      'source_account_identity_hash','source_head','strategy_id','strategy_version'].sort().join('|')
    &&['member_id','registration_id','input_revision_id','strategy_id','strategy_version'].every(k=>typeof row[k]==='string'&&row[k].length>0)
    &&Number.isInteger(row.registration_revision)&&row.registration_revision>0
    &&['binding_digest','content_digest','input_digest','source_account_identity_hash'].every(k=>/^[0-9a-f]{64}$/.test(row[k]))
    &&['input_head','source_head'].every(k=>/^[0-9a-f]{40}$/.test(row[k]))
    &&/^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$/.test(row.source_account_ref)
    &&['factory_lgbm_ast_v1','btc_donchian_history_offline_v1'].includes(row.adapter_id)
    &&['synthetic_fixture','verified_historical_observations'].includes(row.input_evidence_kind);
  const shape=authority&&typeof authority==='object'&&!Array.isArray(authority)
    &&authority.schema_version==='candidate_offline_cohort_job_identity_v1'
    &&authority.job_id===id&&Array.isArray(authority.members)&&authority.members.length===2
    &&authority.members.every(member)
    &&new Set(authority.members.map((row:any)=>row.registration_id)).size===2
    &&new Set(authority.members.map((row:any)=>row.adapter_id)).size===2
    &&['cohort_authority_sha256','account_identity_hash','binding_digest','runtime_contract_digest',
      'state_directory_sha256','member_list_sha256','budget_policy_sha256','event_clock_sha256','catalog_sha256']
      .every(k=>/^[0-9a-f]{64}$/.test(authority[k]))
    &&/^[0-9a-f]{40}$/.test(authority.execution_head)
    &&typeof authority.account_ref==='string'&&typeof authority.run_id==='string';
  const bound=(entry:any)=>entry?.job_identity?.schema_version==='candidate_offline_cohort_job_identity_v1'
    &&entry.job_identity_digest===value.job.job_identity_digest
    &&JSON.stringify(entry.job_identity)===JSON.stringify(authority);
  if(!registeredOfflineId(id)||value?.job?.id!==id||!shape||!bound(value.job)
    ||!safetyClosed(value?.permissions)||!safetyClosed(value?.job?.permissions)
    ||value?.start_allowed!==false||value?.result_bound!==(value?.result!==null)
    ||(value.result&&(!bound(value.result)||value.result.schema_version!=='candidate_offline_cohort_result_v1'
      ||!safetyClosed(value.result.permissions)
      ||value.result.member_ownership_conserved!==true
      ||!['compatible_exact2_long_only','blocked_before_economics'].includes(value.result.support_scope)))
    ||!Array.isArray(value.decisions)
    ||value.decisions.some((entry:any)=>!bound(entry)||entry.schema_version!=='candidate_offline_cohort_decision_v1')){
    throw new Error('共同账户组合结果身份、成员归属或安全合同不匹配；不回退到单策略或其他作业。');
  }
  return value;
}
