import {useEffect,useState} from 'react';
import {offlineRequest,verifyOfflineResult} from './candidate-offline-api';
import {safetyClosed} from './candidate-delivery-api';

export default function RegisteredCandidateOfflineEvidence({runId}:{runId:string;key?:string}){
  const [key,setKey]=useState(''),[value,setValue]=useState<any>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [authMode,setAuthMode]=useState<'key'|'local_no_password'|null>(null);
  useEffect(()=>{setValue(null);setError('');setKey('');setAuthMode(null);
    const abort=new AbortController();
    void offlineRequest('/capabilities','',undefined,abort.signal).then(cap=>{
      if(!safetyClosed(cap.permissions)||typeof cap.authenticated!=='boolean'
        ||![undefined,'key','local_no_password'].includes(cap.auth_mode))throw new Error('离线能力未开放或合同无效。');
      if(!abort.signal.aborted)setAuthMode(cap.auth_mode==='local_no_password'?'local_no_password':'key');
    }).catch(e=>{if(!abort.signal.aborted)setError(String(e));});
    return()=>abort.abort();
  },[runId]);
  async function read(before?:number){setBusy(true);setError('');setValue(null);
    try{setValue(verifyOfflineResult(await offlineRequest(`/jobs/${runId}/result`+(before?`?before=${before}`:''),key),runId));}
    catch(e){setError(String(e));}finally{setBusy(false);}}
  const current=value?.job?.id===runId?value:null;
  const result=current?.result;
  return <section aria-label="注册候选离线结果">
    <h3>注册候选离线结果 · {runId}</h3>
    {authMode==='key'&&<label>本机管理口令（旧密钥模式，读取不启动／恢复）<input type="password" autoComplete="off" value={key} onChange={(e:{target:HTMLInputElement})=>setKey(e.target.value)}/></label>}
    {authMode==='local_no_password'&&<p>本机免口令读取；不会启动或恢复作业。</p>}
    {!authMode&&<p>离线读取模式尚未开放或待读取。</p>}
    <button type="button" disabled={busy||!authMode||(authMode==='key'&&!key)} onClick={()=>void read()}>读取精确结果</button>
    {error&&<p role="alert">{error}</p>}
    {!current&&<p>结果未绑定；源码或配置存在不代表作业已经运行。</p>}
    {current&&<><p>状态：{current.job.status}；完成事件：{current.job.cursor}/{current.job.total??'待核验'}；{current.job.blocker||'无已记录阻断'}。</p>
      <p>注册：{current.job.registration_id}；包摘要：{current.job.content_digest}。</p>
      <p>作业身份摘要：{current.job.job_identity_digest}；绑定账户：{current.job.account_ref}。结果与每条回执均须匹配该固定身份。</p>
      <p>源代码：{current.job.source_head}；输入：{current.job.input_head}；计算：{current.job.execution_head}；页面服务部署：{current.job.deployment_head}。不同版本不等同。</p>
      {!result?<p>尚无已提交的结果投影；不是零成交证明。</p>:<>
        <p>数据性质：{result.input_evidence_kind}；模拟订单 {result.order_count}，模拟成交 {result.fill_count}，保留仓位 {result.position_contracts} 张。</p>
        <p>结果摘要：{result.sha256}。停止／阻断／部分结果不代表完整回放成功。</p>
        <p>最后已核验事件：{result.verified_through_event||'尚无已完成事件'}。</p>
        <p>保护成交：未支持；仅核验离散可见行情，触及时保留断点，不补造保护成交。</p>
        {['decision_receipt','orders','fills','ledger','protection'].map(name=><details key={name}><summary>{name}</summary>
          <pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{JSON.stringify(result[name],null,2)}</pre></details>)}
        <details><summary>逐事件决策引用（本页最多 20 条）</summary><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{JSON.stringify(current.decisions,null,2)}</pre></details>
        {current.next_before>1&&<button type="button" disabled={busy} onClick={()=>void read(current.next_before)}>读取更早决策回执</button>}
        <p>仅展示最近 20 条模拟订单和成交；决策回执含原权威账本事件引用。研究与离线结果不授予交易权限。</p>
      </>}
    </>}
  </section>;
}
