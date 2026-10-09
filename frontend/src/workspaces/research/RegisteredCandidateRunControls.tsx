import {useEffect,useState} from 'react';
import {Link} from 'react-router-dom';
import {DeliveryApiError,offlineWorkerSupported,safetyClosed,type DeliveryRecord,type DeliveryAccount} from './candidate-delivery-api';
import {offlineRequest,type OfflineCommand} from './candidate-offline-api';
import {researchRunLink} from './research-run-links';

type CohortDeliveryAccount=DeliveryAccount&{offline_runtime?:{
  schema_version:string;adapter_id?:string;adapter_ids?:string[];initial_equity_usdt:number;
  currency:string;contract_digest:string
}};

export default function RegisteredCandidateRunControls({row,credential,accounts=[]}:{row:DeliveryRecord;credential:string;accounts?:CohortDeliveryAccount[];key?:string}){
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
      const compatible=catalog.inputs.filter((input:any)=>Array.isArray(input.supported_adapter_ids)
        &&input.supported_adapter_ids.every((value:unknown)=>typeof value==='string')
        &&input.supported_adapter_ids.includes(row.package.adapter_id));
      setInputs(compatible);setJob(matches[0]||null);
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
  const protection=(row.package.adapter_id==='btc_donchian_history_offline_v1'
    ?'历史 OHLC／mark 保护按原回放规则执行；同一根 bar 双触碰或时序不明时阻断，不猜测成交。'
    :cap?.protection_execution_supported===true
      ?'保护按显式采样 mark 执行；采样间隔内路径未知，旧阻断封存结果保持原标记。'
      :'此适配器未声明保护成交能力；不会补造保护成交。');
  return <><section aria-label="注册候选离线作业">
    <h5>离线计算入口（独立授权，默认关闭）</h5>
    <p>源码支持：是；部署配置：{cap?.deployed_configured?'已配置':'未配置'}；离线能力：{cap?.offline_commands_enabled?'已授权':'禁用'}；作业执行：{job?.cursor>0?'已有离线事件':'尚无已核验事件'}。交易权限始终关闭。</p>
    {!adapterSupported&&<p role="status">当前离线 worker 不支持适配器 {row.package?.adapter_id||'未知'}；该记录仅可用于候选管理与诊断审定，不能从此入口启动。</p>}
    <p>{protection}</p>
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
      <button type="button" disabled={disabled||!['stopped','interrupted'].includes(job.status)||job.protection_blocked} onClick={()=>command('resume')}>恢复原作业／安全核账</button></>}
  </section><RegisteredCohortControls row={row} credential={credential} accounts={accounts}/></>;
}

function RegisteredCohortControls({row,credential,accounts}:{row:DeliveryRecord;credential:string;accounts:CohortDeliveryAccount[]}){
  const [cap,setCap]=useState<any>(null),[registrations,setRegistrations]=useState<any[]>([]),[inputs,setInputs]=useState<any[]>([]);
  const [bindings,setBindings]=useState<any[]>([]),[bindingId,setBindingId]=useState(''),[commonAccount,setCommonAccount]=useState('');
  const [secondId,setSecondId]=useState(''),[firstInput,setFirstInput]=useState(''),[secondInput,setSecondInput]=useState('');
  const [firstNotional,setFirstNotional]=useState('20'),[secondNotional,setSecondNotional]=useState('20');
  const [firstLoss,setFirstLoss]=useState('4'),[secondLoss,setSecondLoss]=useState('4');
  const [accountNotional,setAccountNotional]=useState('50'),[accountLoss,setAccountLoss]=useState('10');
  const [reason,setReason]=useState(''),[reviewExpires,setReviewExpires]=useState('');
  const [job,setJob]=useState<any>(null),[ack,setAck]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [pending,setPending]=useState<OfflineCommand|null>(null);
  async function refresh(){
    const [capability,catalog,list]=await Promise.all([
      offlineRequest('/capabilities',credential),offlineRequest('/catalog',credential),offlineRequest('/jobs',credential)]);
    if(!safetyClosed(capability.permissions))throw new Error('共同账户离线能力安全合同不符');
    const records=Array.isArray(catalog.registrations)?catalog.registrations:[];
    const current=list.jobs.filter((item:any)=>item.schema_version==='candidate_offline_cohort_job_v1'
      &&Array.isArray(item.job_identity?.members)&&item.job_identity.members.some((member:any)=>member.registration_id===row.id));
    if(current.length>1||current.some((item:any)=>!safetyClosed(item.permissions)))throw new Error('共同账户作业绑定歧义');
    const availableBindings=Array.isArray(catalog.cohort_bindings)?catalog.cohort_bindings:[];
    setCap(capability);setRegistrations(records);setInputs(Array.isArray(catalog.inputs)?catalog.inputs:[]);
    setBindings(availableBindings.filter((item:any)=>item.members?.some((member:any)=>member.registration_id===row.id)));
    setJob(current[0]||null);
  }
  useEffect(()=>{setSecondId('');setFirstInput('');setSecondInput('');setAck(false);setPending(null);setJob(null);
    void refresh().catch(e=>setError(String(e)));},[row.id,credential]);
  const secondCandidates=registrations.filter((item:any)=>item.id!==row.id&&item.status==='registered'
    &&item.target==='offline'
    &&item.package?.adapter_id!==row.package.adapter_id
    &&['factory_lgbm_ast_v1','btc_donchian_history_offline_v1'].includes(item.package?.adapter_id));
  const second=secondCandidates.find((item:any)=>item.id===secondId);
  const inputFor=(record:any,id:string)=>inputs.find((item:any)=>item.input_revision_id===id
    &&item.evidence_kind==='verified_historical_observations'
    &&item.supported_adapter_ids?.includes(record?.package?.adapter_id));
  const firstInputRow=inputFor(row,firstInput),secondInputRow=inputFor(second,secondInput);
  const numeric=[firstNotional,secondNotional,firstLoss,secondLoss,accountNotional,accountLoss].map(Number);
  const budgetsValid=numeric.every(value=>Number.isFinite(value)&&value>0)
    &&numeric[0]+numeric[1]<=numeric[4]&&numeric[2]+numeric[3]<=numeric[5]
    &&numeric[4]<=50&&numeric[5]<=10;
  const commonAccountRow=accounts.find(item=>item.account_ref===commonAccount);
  const commonRuntime=commonAccountRow?.offline_runtime;
  const executionCompatible=cap?.cohort_execution_policy_compatible===true;
  const protectionCompatible=cap?.cohort_protection_policy_compatible===true;
  const eligible=executionCompatible&&protectionCompatible&&commonRuntime?.schema_version==='delivery_offline_runtime_v3'
    &&commonRuntime?.initial_equity_usdt===5000&&commonRuntime?.currency==='USDT'
    &&Array.isArray(commonRuntime?.adapter_ids)
    &&commonRuntime.adapter_ids.join('|')==='btc_donchian_history_offline_v1|factory_lgbm_ast_v1'
    &&commonAccount!==row.binding?.account_ref&&commonAccount!==second?.binding?.account_ref;
  const selectedBinding=bindings.find(item=>item.id===bindingId);
  async function submit(command:OfflineCommand){setBusy(true);setError('');setPending(command);
    try{await offlineRequest(command.path,credential,command);setPending(null);setAck(false);await refresh();}
    catch(e){setError(String(e));if(e instanceof DeliveryApiError&&!e.outcomeUnknown)setPending(null);}finally{setBusy(false);}}
  function propose(){if(!second||!firstInputRow||!secondInputRow||!budgetsValid||!eligible)return;
    const member=(record:any,input:any,notional:string,loss:string)=>({registration_id:record.id,
      content_digest:record.content_digest,expected_revision:record.revision,input_revision_id:input.input_revision_id,
      input_digest:input.content_digest,member_max_notional_usdt:notional,member_max_loss_usdt:loss});
    const members=[member(row,firstInputRow,firstNotional,firstLoss),member(second,secondInputRow,secondNotional,secondLoss)]
      .sort((a,b)=>a.registration_id.localeCompare(b.registration_id));
    void submit({path:'/jobs',key:crypto.randomUUID(),body:{schema_version:'candidate_offline_cohort_proposal_v1',
      common_account_ref:commonAccount,members,account_max_notional_usdt:accountNotional,
      account_max_loss_usdt:accountLoss,reason}});}
  function review(){if(!executionCompatible||!protectionCompatible||!selectedBinding||selectedBinding.status!=='proposed')return;
    void submit({path:'/jobs',key:crypto.randomUUID(),body:{schema_version:'candidate_offline_cohort_review_v1',
      cohort_binding_id:selectedBinding.id,binding_digest:selectedBinding.binding_digest,
      expected_revision:selectedBinding.revision,decision:'approve',reason,expires_at:reviewExpires}});}
  function start(){if(!executionCompatible||!protectionCompatible||!selectedBinding||selectedBinding.status!=='approved')return;
    void submit({path:'/jobs',key:crypto.randomUUID(),body:{schema_version:'candidate_offline_cohort_start_v1',
      cohort_binding_id:selectedBinding.id,binding_digest:selectedBinding.binding_digest,
      expected_revision:selectedBinding.revision}});}
  function command(action:'stop'|'resume'){if(job)void submit({path:`/jobs/${job.id}/${action}`,key:crypto.randomUUID(),body:{expected_revision:job.revision}});}
  const disabled=busy||!!pending||cap?.offline_commands_enabled!==true;
  return <section aria-label="注册候选共同账户组合离线作业">
    <h5>共同账户组合离线入口（exact-2，独立授权）</h5>
    {!executionCompatible&&<p role="status">当前 Donchian t+1 成交与冻结 Qlib t+2 延迟开盘／成本合同不兼容；现有单一共同订单无法同时保持两者，proposal／start 保持禁用（cohort_member_execution_policy_incompatible）。</p>}
    {!protectionCompatible&&<p role="status">当前 Donchian 100/200bps 与注册 Qlib 400/800bps 的完整保护 policy hash 不同；不会统一 hash 或修改原退出参数（multi_strategy_cohort_protection_policy_incompatible）。</p>}
    <p>支持范围：仅两个已登记成员、同一审定共同模拟账户、保护政策完全兼容、long／hold／各自减仓；short、冲突、加仓、反转、保护证据不完整均在经济动作前阻断。</p>
    <p>两个成员保留各自已审源账户；第三个共同模拟账户才是 Risk／OMS／Fill／Funding／Ledger 的经济权威。共同初始权益必须精确 5000 USDT，不合并两个源账户余额；页面另列成员归属。</p>
    {!eligible&&<p role="status">尚未选择与两个源账户不同的 versioned 共同模拟 runtime；proposal 必须先显式封印账户、输入与预算，人工审定后 start 只能引用该 binding。</p>}
    {!secondCandidates.length&&<p role="status">没有互补适配器且已登记的第二成员。缺合格真实 Qlib final 包时保持 blocked；合成 fixture 不作为实际候选。</p>}
    {error&&<p role="alert">{error}</p>}
    <button type="button" disabled={busy} onClick={()=>void refresh().catch(e=>setError(String(e)))}>刷新共同账户能力与精确登记</button>
    {pending&&<p role="status">共同账户请求结果未知：{pending.key} <button type="button" disabled={busy} onClick={()=>void submit(pending)}>重试同一幂等请求</button></p>}
    {!job&&<>
      <label>第二个精确登记<select value={secondId} disabled={disabled} onChange={(e:{target:HTMLSelectElement})=>{setSecondId(e.target.value);setSecondInput('');setAck(false);}}>
        <option value="">选择互补登记，不自动选最新</option>{secondCandidates.map((item:any)=><option key={item.id} value={item.id}>{item.id} · {item.package.adapter_id} · 源账户 {item.binding?.account_ref}</option>)}</select></label>
      <label>第三个共同经济账户<select value={commonAccount} disabled={disabled} onChange={(e:{target:HTMLSelectElement})=>{setCommonAccount(e.target.value);setAck(false);}}>
        <option value="">选择 V3 共同模拟账户</option>{accounts.filter(item=>item.offline_runtime?.schema_version==='delivery_offline_runtime_v3').map(item=><option key={item.account_ref} value={item.account_ref}>{item.account_ref} · 5000 USDT</option>)}</select></label>
      <label>成员一输入<select value={firstInput} disabled={disabled} onChange={(e:{target:HTMLSelectElement})=>{setFirstInput(e.target.value);setAck(false);}}>
        <option value="">选择 verified 输入</option>{inputs.filter((item:any)=>item.evidence_kind==='verified_historical_observations'&&item.supported_adapter_ids?.includes(row.package.adapter_id)).map((item:any)=><option key={item.input_revision_id} value={item.input_revision_id}>{item.input_revision_id}</option>)}</select></label>
      <label>成员二输入<select value={secondInput} disabled={disabled||!second} onChange={(e:{target:HTMLSelectElement})=>{setSecondInput(e.target.value);setAck(false);}}>
        <option value="">选择 verified 输入</option>{inputs.filter((item:any)=>item.evidence_kind==='verified_historical_observations'&&item.supported_adapter_ids?.includes(second?.package?.adapter_id)).map((item:any)=><option key={item.input_revision_id} value={item.input_revision_id}>{item.input_revision_id}</option>)}</select></label>
      <fieldset><legend>显式成员与账户预算（USDT，不自动 25/25）</legend>
        <label>成员一名义上限<input value={firstNotional} onChange={(e:{target:HTMLInputElement})=>{setFirstNotional(e.target.value);setAck(false);}}/></label>
        <label>成员一亏损上限<input value={firstLoss} onChange={(e:{target:HTMLInputElement})=>{setFirstLoss(e.target.value);setAck(false);}}/></label>
        <label>成员二名义上限<input value={secondNotional} onChange={(e:{target:HTMLInputElement})=>{setSecondNotional(e.target.value);setAck(false);}}/></label>
        <label>成员二亏损上限<input value={secondLoss} onChange={(e:{target:HTMLInputElement})=>{setSecondLoss(e.target.value);setAck(false);}}/></label>
        <label>共同名义上限（≤50）<input value={accountNotional} onChange={(e:{target:HTMLInputElement})=>{setAccountNotional(e.target.value);setAck(false);}}/></label>
        <label>共同亏损上限（≤10）<input value={accountLoss} onChange={(e:{target:HTMLInputElement})=>{setAccountLoss(e.target.value);setAck(false);}}/></label>
      </fieldset>
      {!budgetsValid&&<p role="status">预算必须为正，成员合计不得超过共同上限，共同上限不得超过 50/10 USDT；原策略 target 超预算会拒绝，不缩仓。</p>}
      <label>proposal／审定说明<textarea value={reason} maxLength={500} onChange={(e:{target:HTMLTextAreaElement})=>{setReason(e.target.value);setAck(false);}}/></label>
      <label><input type="checkbox" checked={ack} disabled={disabled} onChange={(e:{target:HTMLInputElement})=>setAck(e.target.checked)}/>确认两个精确登记、各自输入、共同账户、共同观察时钟与显式预算；登记不授予交易权限。</label>
      <button type="button" disabled={disabled||!eligible||!second||!firstInputRow||!secondInputRow||!budgetsValid||!reason.trim()||!ack} onClick={propose}>提交共同账户组合 proposal（不启动）</button>
      {!!bindings.length&&<label>精确 cohort binding<select value={bindingId} disabled={disabled} onChange={(e:{target:HTMLSelectElement})=>{setBindingId(e.target.value);setAck(false);}}>
        <option value="">选择精确 binding</option>{bindings.map(item=><option key={item.id} value={item.id}>{item.id} · {item.status} · revision {item.revision}</option>)}</select></label>}
      {selectedBinding?.status==='proposed'&&<><label>审定有效截止（ISO UTC）<input value={reviewExpires} onChange={(e:{target:HTMLInputElement})=>{setReviewExpires(e.target.value);setAck(false);}}/></label>
        <button type="button" disabled={disabled||!executionCompatible||!protectionCompatible||!reason.trim()||!reviewExpires||!ack} onClick={review}>人工审定此 binding（仍不启动）</button></>}
      {selectedBinding?.status==='approved'&&<button type="button" disabled={disabled||!executionCompatible||!protectionCompatible||!ack} onClick={start}>凭已审 binding 启动共同账户组合离线作业</button>}
    </>}
    {job&&<><p>组合状态：{job.status} · 进度 {job.cursor}/{job.total??'待校验'} · {job.blocker||'无已记录阻断'}</p>
      <p>组合作业：{job.id}；共同账户：{job.account_ref}；成员：{job.job_identity?.members?.map((item:any)=>item.registration_id).join(' + ')}。</p>
      <Link to={researchRunLink('offline',job.id)}>查看共同账户决策、归属守恒、模拟成交与账本 →</Link>
      <button type="button" disabled={disabled||!['queued','running','stop_requested'].includes(job.status)} onClick={()=>command('stop')}>安全停止（不平仓）</button>
      <button type="button" disabled={disabled||!['stopped','interrupted'].includes(job.status)} onClick={()=>command('resume')}>恢复原组合作业／修复投影</button></>}
  </section>;
}
