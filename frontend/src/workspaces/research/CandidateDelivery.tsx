import {useEffect,useRef,useState} from 'react';
import {apiGet} from '../../lib/api';
import {researchWorkspaceAccess, type ResearchWorkspaceAccess, type ResearchWorkspaceHealth} from '../../lib/research-workspace-access';
import RegisteredCandidateRunControls from './RegisteredCandidateRunControls';
import type {HandoffSource,HandoffTarget} from './candidate-handoff';
import {createDeliveryRequest,deliveryRequest,DeliveryApiError,diagnosticAdmissionState,matchesDelivery,safetyClosed,sourceReference,verifyDelivery,
  type DeliveryRecord,type DeliveryAccount,type DeliveryCapabilities,type PendingDeliveryRequest} from './candidate-delivery-api';

const labels:Record<DeliveryRecord['status'],string>={validated:'包验证通过 · 待绑定',validation_blocked:'验证受阻',
  bound:'已绑定 · 待审定',reviewed:'审定通过 · 待登记',rejected:'审定拒绝',registered:'已登记候选管理记录 · 运行另查',revoked:'已撤销'};

export default function CandidateDelivery({source,target}:{
  source:HandoffSource;
  target:HandoffTarget;
}) {
  const [open,setOpen]=useState(false),[key,setKey]=useState('');
  const [workspaceAccess,setWorkspaceAccess]=useState<ResearchWorkspaceAccess>(()=>researchWorkspaceAccess(null));
  const [cap,setCap]=useState<DeliveryCapabilities|null>(null);
  const [authMode,setAuthMode]=useState<'key'|'local_no_password'|null>(null);
  const [rows,setRows]=useState<DeliveryRecord[]>([]),[row,setRow]=useState<DeliveryRecord|null>(null);
  const [accounts,setAccounts]=useState<DeliveryAccount[]>([]),[account,setAccount]=useState('');
  const [reason,setReason]=useState(''),[ack,setAck]=useState(false);
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const [unknown,setUnknown]=useState<PendingDeliveryRequest|null>(null);
  const alive=useRef(true),abort=useRef(new AbortController());
  useEffect(()=>{alive.current=true;abort.current=new AbortController();return()=>{alive.current=false;abort.current.abort();};},[]);
  useEffect(()=>{
    apiGet<ResearchWorkspaceHealth>('/api/health',{signal:abort.current.signal})
      .then(value=>{if(alive.current)setWorkspaceAccess(researchWorkspaceAccess(value));})
      .catch(()=>{if(alive.current)setWorkspaceAccess(researchWorkspaceAccess(null));});
  },[]);
  const receive=(value:unknown)=>{
    const result=verifyDelivery(value,source,target);
    if(alive.current){setRow(result);setRows(old=>[result,...old.filter(item=>item.id!==result.id)]);setAck(false);setUnknown(null);}
  };
  const authenticate=async()=>{
    setBusy(true);setError('');setCap(null);
    try {
      const result=await deliveryRequest('/capabilities',key,undefined,abort.current.signal) as DeliveryCapabilities;
      if(result.schema_version!=='strategy_delivery_capabilities_v1' || !safetyClosed(result.permissions)
          || ![undefined,'key','local_no_password'].includes(result.auth_mode))throw new Error('候选管理能力合同无效。');
      if(alive.current)setAuthMode(result.auth_mode==='local_no_password'?'local_no_password':'key');
      if(result.commands_enabled!==true || result.authenticated!==true)throw new Error('候选管理未启用、未配置或未认证；交易权限仍关闭。');
      const [catalog,bindings]=await Promise.all([
        deliveryRequest('/packages',key,undefined,abort.current.signal) as Promise<{records:DeliveryRecord[]}>,
        deliveryRequest('/accounts',key,undefined,abort.current.signal) as Promise<{accounts:DeliveryAccount[]}>]);
      const records=catalog.records.filter(item=>matchesDelivery(item,source,target)).map(item=>verifyDelivery(item,source,target));
      if(alive.current){setCap(result);setRows(records);setAccounts(bindings.accounts.filter(item=>item.environment===target && item.verified===true));}
    } catch(e){if(alive.current)setError(String(e));}
    finally{if(alive.current)setBusy(false);}
  };
  const submit=async(request:PendingDeliveryRequest)=>{
    setBusy(true);setError('');
    try{receive(await deliveryRequest(request.path,key,request,abort.current.signal));}
    catch(e){if(alive.current){setError(String(e));if(!(e instanceof DeliveryApiError)||e.outcomeUnknown)setUnknown(request);else setUnknown(null);}}
    finally{if(alive.current)setBusy(false);}
  };
  const act=(action:string,extra:Record<string,unknown>={})=>{
    if(!row)return;
    void submit(createDeliveryRequest(`/packages/${row.id}/${action}`,{expected_revision:row.revision,...extra}));
  };
  const queryReceipt=async()=>{
    if(!unknown)return;setBusy(true);setError('');
    try{receive(await deliveryRequest('/requests/'+encodeURIComponent(unknown.key),key,undefined,abort.current.signal));}
    catch(e){if(alive.current)setError('尚未确认提交结果：'+String(e)+'。保留原幂等键，不自动新建请求。');}
    finally{if(alive.current)setBusy(false);}
  };
  const refresh=async()=>{
    if(!row)return;setBusy(true);setError('');
    try{receive(await deliveryRequest('/packages/'+row.id,key,undefined,abort.current.signal));}
    catch(e){if(alive.current)setError(String(e));}
    finally{if(alive.current)setBusy(false);}
  };
  const disabled=busy||!cap?.commands_enabled||!!unknown;
  useEffect(()=>{if(open)void authenticate();},[open]); // GET-only discovery; never submits a command.
  if(!workspaceAccess.candidateManagement)return <section className="candidate-delivery" aria-label="服务端候选交付">
    <p><strong>候选管理写入口保持关闭。</strong> {workspaceAccess.reason}</p>
    <p>交接草稿、精确来源与只读证据仍可查看；此处不会请求 <code>/api/strategy-delivery/*</code>。</p>
  </section>;
  return <section className="candidate-delivery" aria-label="服务端候选交付">
    <button type="button" aria-expanded={open} onClick={()=>setOpen(!open)}>服务端验证、审定与登记</button>
    {open&&<>
      <p>目标：{target==='offline'?'离线执行验证':'OKX Demo'}。验证、审定与登记不自动启动；离线作业另需下方独立授权。研究只读部署仍禁用全部写入。</p>
      {authMode==='key'&&<label>本机候选管理口令（旧密钥模式，仅保留在本组件内存）<input type="password" autoComplete="off" value={key}
        disabled={busy||!!unknown} onChange={(e:{target:HTMLInputElement})=>{setKey(e.target.value);setCap(null);}}/></label>}
      {authMode==='local_no_password'&&<p>本机免口令模式：已验证本机请求边界；不代表个人身份强认证，不授予交易权限。</p>}
      {!authMode&&<p>候选管理模式尚未读取或未开放；不会要求输入未知模式的口令。</p>}
      <button type="button" disabled={(authMode==='key'&&!key)||busy||!!unknown} onClick={()=>void authenticate()}>读取候选管理能力与记录</button>
      {cap&&<p>服务端操作员：{cap.operator}。候选管理开放；账户采集及交易仍未授权。</p>}
      {error&&<p role="alert">{error}</p>}
      {unknown&&<div role="status"><p>提交结果待确认。请求编号：{unknown.key}</p>
        <button type="button" disabled={busy} onClick={()=>void queryReceipt()}>查询本次提交回执</button>
        <button type="button" disabled={busy} onClick={()=>void submit(unknown)}>重试同一幂等请求</button></div>}
      {cap&&<>
        <label>本来源已有交接记录（不自动选择）<select value={row?.id||''} disabled={disabled} onChange={(e:{target:HTMLSelectElement})=>{
          const selected=rows.find(item=>item.id===e.target.value)||null;setRow(selected);setAck(false);}}>
          <option value="">请选择精确记录</option>{rows.map(item=><option key={item.id} value={item.id}>{item.id} · {labels[item.status]}</option>)}
        </select></label>
        <button type="button" disabled={disabled} onClick={()=>void submit(createDeliveryRequest('/packages',{
          source:sourceReference(source),target}))}>提交一次服务端包验证</button>
        {row&&<>
          <h5>{labels[row.status]}</h5><p>包摘要：<code>{row.content_digest}</code> · 记录版本 {row.revision}</p>
          <button type="button" disabled={disabled} onClick={()=>void refresh()}>刷新精确记录</button>
          <p>目标适配器：{row.package.adapter_id}；账户：{row.binding?.account_ref||'未绑定'}</p>
          {row.diagnostic_admission&&(()=>{const state=diagnosticAdmissionState(row);return <div>
            <p>离线诊断准入：{state.admitted?'可进入隔离诊断':'拒绝'}。这不等于研究通过，也不授予运行或交易权限。</p>
            {state.researchBlocked&&<p>原研究状态仍受阻：{state.researchBlockers.join('；')}。零成交原样保留。</p>}
            {!!state.blockingReasons.length&&<p>诊断硬阻断：{state.blockingReasons.join('；')}。</p>}
          </div>})()}
          {row.package.package_validation&&<p>包结构与合同校验：{row.package.package_validation.status==='passed'?'通过':'受阻'}。
            最终审计内容复算：{row.package.evidence_validation?.status==='passed'?'通过':'未通过或缺失'}。
            研究准入：{row.package.admission_blockers?.length?'受阻':'以原研究及审定绑定为准'}。离线执行须在作业区按精确登记另查；交易权限关闭。</p>}
          {row.package.audit_binding&&<p>最终审计运行：{row.package.audit_binding.qlib_run_id}；模型摘要：
            <code>{row.package.model?.sha256||'缺失'}</code>；封印摘要：<code>{row.package.audit_binding.seal_sha256}</code></p>}
          {row.package.contracts&&<details><summary>本包摘要绑定的完整合同（审定前核对）</summary>
            <p>数据版本：{row.package.data_version}；资产／周期：{row.package.instrument}／{row.package.bar_size}；结算币：{row.package.settlement_currency}。</p>
            <p>源代码：<code>{row.package.source_head}</code>；内容证据摘要：<code>{row.package.evidence_receipt_sha256||'缺失'}</code>。</p>
            {['features','preprocessing','calibration','output','time','position','exit','cost','state'].map(name=><details key={name}>
              <summary>{name}</summary><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{JSON.stringify(row.package.contracts?.[name]??'缺失',null,2)}</pre>
            </details>)}
          </details>}
          {!!row.validation.blockers.length&&<ul>{row.validation.blockers.map(item=><li key={item}>{item}</li>)}</ul>}
          {!!row.package.limitations?.length&&<details><summary>适用范围与限制</summary><ul>{row.package.limitations.map(item=><li key={item}>{item}</li>)}</ul></details>}
          {['validated','bound','reviewed'].includes(row.status)&&<>
            <label>服务端允许的目标账户<select value={account} disabled={disabled} onChange={(e:{target:HTMLSelectElement})=>{setAccount(e.target.value);setAck(false);}}>
              <option value="">请选择；没有记录时不得手填</option>{accounts.map(item=><option key={item.account_ref} value={item.account_ref}>{item.account_ref} · {item.environment}</option>)}
            </select></label>
            {!accounts.length&&<p>没有可绑定账户证据；不会自动采集私有账户。</p>}
            <button type="button" disabled={disabled||!account} onClick={()=>act('bind',{account_ref:account})}>绑定账户（使旧审定失效）</button>
          </>}
          {row.review&&<p>审定：{row.review.decision} · {row.review.actor} · 有效截止 {row.review.expires_at}</p>}
          {!['registered','revoked','rejected'].includes(row.status)&&<>
            <label>审定说明<textarea value={reason} maxLength={500} onChange={(e:{target:HTMLTextAreaElement})=>{setReason(e.target.value);setAck(false);}}/></label>
            <label><input type="checkbox" checked={ack} disabled={disabled} onChange={(e:{target:HTMLInputElement})=>setAck(e.target.checked)}/>
              我已核对上述包、目标、账户和限制；本次审定或登记不授权启动。</label>
            <button type="button" disabled={disabled||row.status!=='bound'||!reason.trim()||!ack} onClick={()=>act('review',{decision:'approve',reason})}>审定该精确绑定</button>
            <button type="button" disabled={disabled||!reason.trim()||!ack} onClick={()=>act('review',{decision:'reject',reason})}>记录拒绝结论</button>
            <button type="button" disabled={disabled||row.status!=='reviewed'||!ack} onClick={()=>act('register')}>登记到候选管理目录</button>
          </>}
          {row.status==='registered'&&<><p>候选管理登记回执：{row.registration?.registration_id}。登记不自动启动。
            运行证据须从下方精确作业另行读取；登记本身不证明执行成功。Demo 操作仍禁用。</p>
            <label>撤销原因<textarea value={reason} maxLength={500} onChange={(e:{target:HTMLTextAreaElement})=>setReason(e.target.value)}/></label>
            <button type="button" disabled={disabled||!reason.trim()} onClick={()=>act('revoke',{reason})}>撤销登记（不执行平仓或撤单）</button></>}
          {target==='offline'&&row.registration&&<RegisteredCandidateRunControls key={row.id} row={row} credential={key}/>}
        </>}
      </>}
    </>}
  </section>;
}
