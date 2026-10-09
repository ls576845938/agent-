import {useEffect,useState} from 'react';
import {offlineRequest,verifyOfflineResult} from './candidate-offline-api';
import {safetyClosed} from './candidate-delivery-api';

export default function RegisteredCandidateOfflineEvidence({runId}:{runId:string;key?:string}){
  const [key,setKey]=useState(''),[value,setValue]=useState<any>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [authMode,setAuthMode]=useState<'key'|'local_no_password'|null>(null);
  const [capability,setCapability]=useState<any>(null);
  useEffect(()=>{setValue(null);setError('');setKey('');setAuthMode(null);setCapability(null);
    const abort=new AbortController();
    void offlineRequest('/capabilities','',undefined,abort.signal).then(cap=>{
      if(!safetyClosed(cap.permissions)||typeof cap.authenticated!=='boolean'
        ||![undefined,'key','local_no_password'].includes(cap.auth_mode))throw new Error('离线能力未开放或合同无效。');
      if(!abort.signal.aborted){setCapability(cap);setAuthMode(cap.auth_mode==='local_no_password'?'local_no_password':'key');}
    }).catch(e=>{if(!abort.signal.aborted)setError(String(e));});
    return()=>abort.abort();
  },[runId]);
  async function read(before?:number){setBusy(true);setError('');setValue(null);
    try{setValue(verifyOfflineResult(await offlineRequest(`/jobs/${runId}/result`+(before?`?before=${before}`:''),key),runId));}
    catch(e){setError(String(e));}finally{setBusy(false);}}
  const current=value?.job?.id===runId?value:null;
  const result=current?.result;
  const cohort=current?.job?.schema_version==='candidate_offline_cohort_job_v1';
  const protection=current?.job?.protection_blocked
    ?'旧 blocked 封存结果保持原标记；不会重算或补造保护成交。'
    :result?.adapter_id==='btc_donchian_history_offline_v1'
    ?'历史 OHLC／mark 保护由原回放执行；双触碰或时序歧义保持 blocked，不猜测成交。'
    :capability?.protection_execution_supported===true
      ?'显式采样 mark 保护已接入；采样间隔路径未知，旧 blocked 封存结果保持原标记。'
      :'该结果未声明保护成交能力；不会补造保护成交。';
  return <section aria-label="注册候选离线结果">
    <h3>注册候选离线结果 · {runId}</h3>
    {authMode==='key'&&<label>本机管理口令（旧密钥模式，读取不启动／恢复）<input type="password" autoComplete="off" value={key} onChange={(e:{target:HTMLInputElement})=>setKey(e.target.value)}/></label>}
    {authMode==='local_no_password'&&<p>本机免口令读取；不会启动或恢复作业。</p>}
    {!authMode&&<p>离线读取模式尚未开放或待读取。</p>}
    <button type="button" disabled={busy||!authMode||(authMode==='key'&&!key)} onClick={()=>void read()}>读取精确结果</button>
    {error&&<p role="alert">{error}</p>}
    {!current&&<p>结果未绑定；源码或配置存在不代表作业已经运行。</p>}
    {current&&<><p>状态：{current.job.status}；完成事件：{current.job.cursor}/{current.job.total??'待核验'}；{current.job.blocker||'无已记录阻断'}。</p>
      {cohort?<>
        <p>共同账户：{current.job.account_ref}；成员：{current.job.job_identity.members.map((item:any)=>`${item.registration_id} (${item.adapter_id})`).join(' + ')}。</p>
        <p>支持范围：exact-2、保护政策兼容、long／hold／各自减仓。short、冲突、加仓、反转或保护证明不完整保持经济动作前 blocked。</p>
        <p>共同初始权益固定 5000 USDT；不是两个独立余额相加。成员份额用于各自策略判断，Risk／OMS／Fill／Funding／Ledger 以共同账户总事实为权威。</p>
      </>:<p>注册：{current.job.registration_id}；包摘要：{current.job.content_digest}。</p>}
      <p>作业身份摘要：{current.job.job_identity_digest}；绑定账户：{current.job.account_ref}。结果与每条回执均须匹配该固定身份。</p>
      {cohort?<p>成员源代码与输入逐项绑定在组合作业身份；计算：{current.job.execution_head}；页面服务部署：{current.job.deployment_head}。不同版本不等同。</p>
        :<p>源代码：{current.job.source_head}；输入：{current.job.input_head}；计算：{current.job.execution_head}；页面服务部署：{current.job.deployment_head}。不同版本不等同。</p>}
      {!result?<p>尚无已提交的结果投影；不是零成交证明。</p>:<>
        {cohort?<>
          <p>共同模拟订单 {result.order_count}，共同模拟成交 {result.fill_count}，共同仓位 {result.position_contracts} 张；成员归属守恒：{result.member_ownership_conserved?'是':'否／未证明'}。</p>
          <p>共同观察源：{result.common_market_source?.input_revision_id||'未记录'}；mark／index／funding 冲突会拒绝，不择一。</p>
          <details><summary>成员份额与预算</summary><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{JSON.stringify({members:result.members,budget_policy:result.budget_policy,strategy_allocations:result.strategy_allocations},null,2)}</pre></details>
        </>:<p>数据性质：{result.input_evidence_kind}；模拟订单 {result.order_count}，模拟成交 {result.fill_count}，保留仓位 {result.position_contracts} 张。</p>}
        <p>结果摘要：{result.sha256}。停止／阻断／部分结果不代表完整回放成功。</p>
        <p>最后已核验事件：{result.verified_through_event||'尚无已完成事件'}。</p>
        <p>保护成交：{cohort?'仅在两个原策略保护政策摘要完全兼容时复用共同 OCO；不新增成员独立保护。':protection}</p>
        {(cohort?['decision_receipt','orders','fills','ledger','protection','strategy_allocations']:['decision_receipt','orders','fills','ledger','protection']).map(name=><details key={name}><summary>{name}</summary>
          <pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{JSON.stringify(result[name],null,2)}</pre></details>)}
        <details><summary>逐事件决策引用（本页最多 20 条）</summary><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{JSON.stringify(current.decisions,null,2)}</pre></details>
        {current.next_before>1&&<button type="button" disabled={busy} onClick={()=>void read(current.next_before)}>读取更早决策回执</button>}
        <p>仅展示最近 20 条模拟订单和成交；决策回执含原权威账本事件引用。研究与离线结果不授予交易权限。</p>
      </>}
    </>}
  </section>;
}
