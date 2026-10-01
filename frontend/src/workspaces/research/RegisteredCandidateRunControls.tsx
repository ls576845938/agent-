import {useEffect,useState} from 'react';
import {Link} from 'react-router-dom';
import {DeliveryApiError,offlineWorkerSupported,safetyClosed,type DeliveryRecord} from './candidate-delivery-api';
import {offlineRequest,type OfflineCommand} from './candidate-offline-api';
import {researchRunLink} from './research-run-links';

export default function RegisteredCandidateRunControls({row,credential}:{row:DeliveryRecord;credential:string;key?:string}){
  const [cap,setCap]=useState<any>(null),[inputs,setInputs]=useState<any[]>([]),[selected,setSelected]=useState('');
  const [job,setJob]=useState<any>(null),[ack,setAck]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [pending,setPending]=useState<OfflineCommand|null>(null);
  async function refresh(){
    const c=await offlineRequest('/capabilities',credential);
    if(!safetyClosed(c.permissions))throw new Error('离线能力安全合同不符');
    setCap(c);
    if(c.authenticated){
      const [catalog,list]=await Promise.all([offlineRequest('/catalog',credential),offlineRequest('/jobs',credential)]);
      const matches=list.jobs.filter((j:any)=>j.registration_id===row.id);
      if(matches.length>1||matches.some((j:any)=>j.content_digest!==row.content_digest||!safetyClosed(j.permissions)))throw new Error('作业绑定歧义或包摘要不符');
      setInputs(catalog.inputs);setJob(matches[0]||null);
    }
  }
  useEffect(()=>{setJob(null);setCap(null);setSelected('');setAck(false);setPending(null);void refresh().catch(e=>setError(String(e)));},[row.id,credential]);
  async function submit(command:OfflineCommand){
    setBusy(true);setError('');setPending(command);
    try{await offlineRequest(command.path,credential,command);setPending(null);setAck(false);await refresh();}
    catch(e){setError(String(e));if(e instanceof DeliveryApiError&&!e.outcomeUnknown)setPending(null);}
    finally{setBusy(false);}
  }
  function start(){
    const input=inputs.find(i=>i.input_revision_id===selected);if(!input)return;
    void submit({path:'/jobs',key:crypto.randomUUID(),body:{registration_id:row.id,content_digest:row.content_digest,
      expected_revision:row.revision,input_revision_id:input.input_revision_id,input_digest:input.content_digest}});
  }
  function command(action:'stop'|'resume'){
    if(job)void submit({path:`/jobs/${job.id}/${action}`,key:crypto.randomUUID(),body:{expected_revision:job.revision}});
  }
  const adapterSupported=offlineWorkerSupported(row,cap||{});
  const disabled=busy||!!pending||cap?.offline_commands_enabled!==true||!adapterSupported;
  return <section aria-label="注册候选离线作业">
    <h5>离线计算入口（独立授权，默认关闭）</h5>
    <p>源码支持：是；部署配置：{cap?.deployed_configured?'已配置':'未配置'}；离线能力：{cap?.offline_commands_enabled?'已授权':'禁用'}；作业执行：{job?.cursor>0?'已有离线事件':'尚无已核验事件'}。交易权限始终关闭。</p>
    {!adapterSupported&&<p role="status">当前离线 worker 不支持适配器 {row.package?.adapter_id||'未知'}；该记录仅可用于候选管理与诊断审定，不能从此入口启动。</p>}
    <p>保护成交尚未接入；触及保护价时阻断并保留仓位。离散行情采样不能证明区间内未触发。</p>
    {!cap?.offline_commands_enabled&&<p role="status">{cap?.blockers?.join('；')||'未读取离线能力；不能启动。'}</p>}
    {error&&<p role="alert">{error}</p>}
    <button type="button" disabled={busy} onClick={()=>void refresh().catch(e=>setError(String(e)))}>刷新精确作业状态</button>
    {pending&&<div role="status">请求结果未知：{pending.key}<button type="button" disabled={busy} onClick={()=>void submit(pending)}>重试同一离线请求</button></div>}
    {!job&&<><label>已登记的不可变输入<select value={selected} disabled={disabled} onChange={(e:{target:HTMLSelectElement})=>{setSelected(e.target.value);setAck(false);}}>
      <option value="">选择输入版本，不自动选最新</option>{inputs.map(i=><option key={i.input_revision_id} value={i.input_revision_id}>{i.input_revision_id} · {i.evidence_kind}</option>)}</select></label>
      <label><input type="checkbox" checked={ack} disabled={disabled} onChange={(e:{target:HTMLInputElement})=>setAck(e.target.checked)}/>确认此包、账户和输入仅用于受限离线模拟；登记本身不授权运行。</label>
      <button type="button" disabled={disabled||!selected||!ack||row.status!=='registered'} onClick={start}>启动该精确离线作业</button></>}
    {job&&<><p>状态：{job.status} · 进度 {job.cursor}/{job.total??'待校验'} · {job.blocker||'无已记录阻断'}</p>
      <p>作业：{job.id}；输入：{job.input_revision_id}。</p>
      <Link to={researchRunLink('offline',job.id)}>查看此作业决策、模拟成交与账本 →</Link>
      <button type="button" disabled={disabled||!['queued','running','stop_requested'].includes(job.status)} onClick={()=>command('stop')}>安全停止（不平仓）</button>
      <button type="button" disabled={disabled||!['stopped','interrupted','blocked'].includes(job.status)||job.protection_blocked} onClick={()=>command('resume')}>恢复原作业／安全核账</button></>}
  </section>;
}
