import {useEffect, useState} from 'react';
import {useLocation} from 'react-router-dom';
import {alphaFactoryApi} from '../../lib/alpha-factory-api';
import {researchApi} from '../../lib/research-api';
import {HandoffSourceFacts} from './CandidateHandoff';
import CandidateDelivery from './CandidateDelivery';
import {handoffSourceLink, parseHandoffSelector, readHandoffDraft, reconcileHandoffDraft,
  resolveHandoffSource, isBtcSource, type HandoffDraft, type HandoffSource} from './candidate-handoff';

// Deliberately no runtime catalog / operator-controller props or callbacks.
// A research candidate must never auto-select a different registered strategy.
export default function CandidateHandoffInbox() {
  const {search}=useLocation();
  const [state,setState]=useState<{key:string;draft?:HandoffDraft;source?:HandoffSource;error?:string}>({key:''});
  let selector: string | null=null,selectorError='';
  try {selector=parseHandoffSelector(search);} catch(error) {selectorError=String(error);}
  useEffect(()=>{
    let active=true;
    setState({key:search});
    if (!selector || selectorError) return;
    const load=async()=>{
      try {
        const draft=readHandoffDraft(sessionStorage,selector);
        if (!isBtcSource(draft.source)) throw new Error('该草稿不是 BTC 来源，不能交给本控制台。');
        const data=draft.source.kind==='factory' ? await alphaFactoryApi.detail(draft.source.runId)
          : await researchApi.getQlibRun(draft.source.runId,'artifacts/qlib_runs');
        if (!active) return;
        const source=resolveHandoffSource(draft.source.kind,draft.source.runId,data,draft.source.candidateId);
        if (reconcileHandoffDraft(draft,source)!=='matched') {
          setState({key:search,draft,error:'研究来源或封印引用已变化，草稿失效；请回到研究页重新核对，未自动更新或注册。'});return;
        }
        setState({key:search,draft,source});
      } catch(error) {if(active)setState({key:search,error:`交接不可用：${String(error)}。未绑定其他候选。`});}
    };
    void load();return()=>{active=false;};
  },[search,selector,selectorError]);
  if (!selector && !selectorError) return null;
  const current=state.key===search ? state : {key:search};
  return <section className="candidate-handoff candidate-handoff-inbox" data-testid="candidate-handoff-inbox" aria-label="研究候选交接">
    <header><h3>研究候选交接</h3><span>未注册 · 未启动</span></header>
    {selectorError || current.error ? <p role="alert">{selectorError || current.error}</p>
      : !current.source ? <p role="status">正在重新读取精确研究来源…</p>
      : <><p>已重新匹配研究引用；不是运行审定回执。下方原策略目录和启动流程未被改变。</p>
        <details><summary>{current.source.candidateId} · 查看交接来源</summary><HandoffSourceFacts source={current.source}/></details>
        <p>交接意向：{current.draft?.target==='okx_demo' ? 'OKX Demo' : '离线执行验证'}；账户绑定：未绑定。</p>
        {current.draft?.note && <p>本地说明（未审核）：{current.draft.note}</p>}
      </>}
    {current.draft && <a href={handoffSourceLink(current.draft.source)}>返回精确研究运行 →</a>}
    <p>交接草稿不是登记结果；不能使用下面已有的 Donchian 候选代替这份研究模型。</p>
    {current.source&&current.draft&&<div key={search}><CandidateDelivery source={current.source} target={current.draft.target}/></div>}
  </section>;
}
