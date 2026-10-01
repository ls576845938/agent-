import {useState} from 'react';
import {frontendIdentity} from '../../frontendIdentity';
import {createHandoffDraft, HANDOFF_STORAGE_PREFIX, isBtcSource,
  readHandoffDraft, resolveHandoffSource, sourceFingerprint,
  type HandoffDraft, type HandoffSource, type HandoffTarget, type SourceKind} from './candidate-handoff';
import './candidate-handoff.css';
import CandidateDelivery from './CandidateDelivery';

const kindLabels = {sealed_reference:'已封印研究引用',research_reference:'研究配置引用',missing:'待补齐／未审定'};
export function HandoffSourceFacts({source}: {source: HandoffSource}) {
  return <><dl className="candidate-handoff-facts">
    <div><dt>来源运行</dt><dd>{source.kind === 'factory' ? 'Alpha 工厂' : 'Qlib'} · {source.runId}</dd></div>
    <div><dt>精确候选</dt><dd>{source.candidateId}</dd></div>
    <div><dt>最终 Qlib 运行</dt><dd>{source.qlibRunId}</dd></div>
    <div><dt>策略／市场</dt><dd>{source.strategyId || '未知'} · {source.market || '未知'} · {source.instrument || '未知'} · {source.barSize || '未知'}</dd></div>
    <div><dt>研究源码</dt><dd>{source.sourceHead || '未知'}</dd></div>
    <div><dt>数据版本／截止</dt><dd>{source.dataVersion || '未知'} · {source.asOf || '未提供'}</dd></div>
  </dl><p className="candidate-handoff-note">{source.sourceHead !== frontendIdentity.source_head
    ? '研究源码与当前页面版本不同，保留原始来源；须由服务端复核兼容，不能冒充当前运行证据。'
    : '源码版本相同也不代表通过运行审定。'}</p></>;
}

export function CandidateHandoffPanel({source}: {source: HandoffSource}) {
  const [formId]=useState(()=> 'handoff-'+crypto.randomUUID());
  const [step,setStep]=useState(1);
  const [target,setTarget]=useState<HandoffTarget>('offline');
  const [note,setNote]=useState('');
  const [ack,setAck]=useState(false);
  const [draft,setDraft]=useState<HandoffDraft | null>(null);
  const [saved,setSaved]=useState(false);
  const [feedback,setFeedback]=useState('');
  const update = () => {setDraft(null);setSaved(false);setFeedback('');setAck(false);};
  const prepare = () => draft || createHandoffDraft(source,target,note,ack,crypto.randomUUID(),new Date().toISOString());
  const save = () => {
    try {
      const next=prepare();
      sessionStorage.setItem(HANDOFF_STORAGE_PREFIX+next.id,JSON.stringify(next));
      readHandoffDraft(sessionStorage,next.id);
      setDraft(next);setSaved(true);setFeedback('交接草稿已保存在当前标签页；没有提交审核、绑定账户或注册策略。');
    } catch(error) {setSaved(false);setFeedback(`草稿保存失败：${String(error)}。可导出交接清单；未创建服务器记录。`);}
  };
  const download = () => {
    try {
      const next=prepare();setDraft(next);
      const url=URL.createObjectURL(new Blob([JSON.stringify(next,null,2)],{type:'application/json'}));
      const link=document.createElement('a');link.href=url;link.download=`research-handoff-${next.id}.json`;
      link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
      setFeedback('已导出未审定交接清单；这不是可运行模型包或审批回执。');
    } catch(error) {setFeedback(`导出失败：${String(error)}`);}
  };
  return <section className="candidate-handoff" aria-label="研究候选部署交接" data-testid="candidate-handoff-panel">
    <header><div><small>RESEARCH → RUNTIME / 人工交接</small><h4>部署交接</h4></div><span>研究准备 · 未审定</span></header>
    <p>准备研究候选的交接材料，再由服务端审定、登记运行候选。此处不修改策略参数，不训练，不启动交易。</p>
    <nav className="candidate-handoff-steps" aria-label="交接准备步骤">{['核对候选与交付包','选择目标与说明','确认并交接'].map((label,index)=><button
      type="button" key={label} aria-current={step===index+1 ? 'step' : undefined}
      onClick={()=>setStep(index+1)}>{index+1}. {label}</button>)}</nav>
    {step===1 && <><HandoffSourceFacts source={source}/>
      <h5>交付包清单</h5><p className="candidate-handoff-note">封印仅证明研究文件的完整性；不证明模型有效、运行包完整或交易获准。</p>
      <ul className="candidate-handoff-artifacts">{source.artifacts.map(row=><li key={row.key}><div><strong>{row.label}</strong><span>{kindLabels[row.kind]}</span></div>
        {row.reference && <code>{row.reference}</code>}</li>)}</ul>
      <p>研究结论：{source.researchStatus || '未知'}。不将研究提名视为运行审定。</p>
      {!!source.blockers.length && <details open><summary>原研究阻塞／限制（原样保留）</summary><ul>{source.blockers.map((item,index)=><li key={index}>{item}</li>)}</ul></details>}
      <button type="button" onClick={()=>setStep(2)}>下一步：目标与说明</button></>}
    {step===2 && <div className="candidate-handoff-form">
      <label htmlFor={formId+'target'}>拟交接环境（仅意向，不切换部署模式）</label>
      <select id={formId+'target'} value={target} onChange={(event: {target: HTMLSelectElement})=>{update();setTarget(event.target.value as HandoffTarget);}}>
        <option value="offline">离线执行验证</option><option value="okx_demo" disabled={!isBtcSource(source)}>OKX Demo（须另行准入与授权）</option>
      </select>
      {!isBtcSource(source) && <p>当前候选不是明确的 BTC-USDT-SWAP 来源；不能交给 BTC Demo。其他市场保留研究交接，不自动扩展执行链。</p>}
      <p>本地草稿账户：<strong>未绑定</strong>。服务端交付面板另行读取已核验账户目录；不接收手填账号、账户哈希或交易所密钥作为授权。</p>
      <label htmlFor={formId+'note'}>交接说明（选填，最多 500 字；勿填账号、密钥或敏感信息）</label>
      <textarea id={formId+'note'} maxLength={500} rows={3} value={note} onChange={(event: {target: HTMLTextAreaElement})=>{update();setNote(event.target.value);}}/>
      <p>仓位、退出、成本和数量单位沿用候选封存版本；这里只展示，不通过表单覆盖。</p>
      <button type="button" onClick={()=>setStep(3)}>下一步：确认交接</button>
    </div>}
    {step===3 && <><p>候选 {source.candidateId} → {target==='offline' ? '离线执行验证' : 'OKX Demo 意向'}；账户未绑定。</p>
      <label className="candidate-handoff-ack"><input type="checkbox" checked={ack} onChange={(event: {target: HTMLInputElement})=>{setAck(event.target.checked);setSaved(false);setDraft(null);}}/>
        我已核对来源与缺项，理解草稿／下载／页面跳转均不构成审核通过、部署成功或交易授权。</label>
      <div className="candidate-handoff-actions"><button type="button" disabled={!ack} onClick={save}>保存交接草稿</button>
        <button type="button" disabled={!ack} onClick={download}>导出交接清单</button></div>
      {saved && draft && <><p>草稿编号：<code>{draft.id}</code></p>{isBtcSource(source)
        ? <a className="candidate-handoff-link" href={'/crypto?researchHandoff='+draft.id}>到 BTC 控制台查看交接 →</a>
        : <p>已保留共享交接材料；当前没有此市场的运行接收入口。</p>}</>}
    </>}
    {feedback && <p role="status" className="candidate-handoff-feedback">{feedback}</p>}
    <footer><strong>本地草稿不是服务端审定或登记回执</strong>
      <p id={formId+'blocked'}>本地草稿不能直接发布。只有候选管理部署可在下方读取服务端能力并执行审定或登记；其他模式保持只读。</p>
      <div key={sourceFingerprint(source)+target}><CandidateDelivery source={source} target={target}/></div>
    </footer>
  </section>;
}

export default function CandidateHandoff({kind,runId,detail,candidateId=''}: {
  kind: SourceKind; runId: string; detail: Record<string, any> | null; candidateId?: string;
}) {
  const [open,setOpen]=useState(false);
  const [regionId]=useState(()=> 'handoff-entry-'+crypto.randomUUID());
  let source: HandoffSource | null=null,error='';
  try {source=resolveHandoffSource(kind,runId,detail,candidateId);} catch(reason) {error=String(reason);}
  return <div className="candidate-handoff-entry">
    <button type="button" onClick={()=>setOpen(!open)} aria-expanded={open} aria-controls={regionId}>准备部署交接</button>
    {open && <div id={regionId}>{source ? <div key={sourceFingerprint(source)}><CandidateHandoffPanel source={source}/></div>
      : <p role="alert">无法准备交接：{error} 未读取替代候选。</p>}</div>}
  </div>;
}
