import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const root=resolve(fileURLToPath(new URL('../..',import.meta.url)));
const require=createRequire(import.meta.url);
const ts=require('typescript');
const React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
const read=path=>readFileSync(resolve(root,path),'utf8');
function load(path) {
  const module={exports:{}};
  const compiled=ts.transpileModule(read(path),{compilerOptions:{
    module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,
    jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true,
  }}).outputText;
  new Function('exports','require','module',compiled)(module.exports,require,module);
  return module.exports;
}

const component=load('frontend/src/workspaces/research/MarketStateEvidence.tsx').default;
const artifact=JSON.parse(read('.agent/market_state_evidence/donchian-stage-market-state-v2-20260927.json'));
const evidence={...artifact,read_only:true,
  publication_head:'e2e7496acaa16b9fd5eda37dd65ea328a18ab032',
  artifact_sha256:'2a4345a7d9a867cd1888addad00659583ea744911aa0b5b8486ad8c282c9c00b',
  manifest_ref:'committed:market-state'};
const safety={demo_control_enabled:false,execution_permission:false,live:false,order:false,paper:false,
  private:false,promotion:false,real_order:false,runtime_observed:false,transfer:false,withdraw:false,
  network_accessed:false};
const stateMetricFields=['direction_score','direction_label','normalized_trend_strength',
  'path_efficiency_by_horizon.24','path_efficiency_by_horizon.72','path_efficiency_by_horizon.168',
  'multi_scale_agreement','bar_volatility','annualized_volatility','volatility_relative_position',
  'volatility_expansion_ratio','volatility_regime','shock_score','direction_persistence','switching_frequency'].sort();
const completedTrial={
  schema_version:'market_policy_trial_report_v1',
  trial_id:'donchian-stage-market-policy-trial-20260927-v1',
  status:'completed_exploratory_research_only',truth_kind:'offline_policy_ab_replay',
  usage:'policy_effect_estimation_only_not_promotion',read_only:true,effect_verified:true,
  arms:{
    original_donchian:{arm_id:'original_donchian',processed_events:2960,new_entries_proposed:30,
      new_entries_rejected:0,new_entries_executed:30,roundtrips:28,exposure_contract_hours:'200',
      holding_hours:'180',net_usdt:'-0.243294323038495647991',max_drawdown_usdt:'0.6'},
    original_donchian_plus_frozen_entry_policy:{arm_id:'original_donchian_plus_frozen_entry_policy',
      processed_events:2960,new_entries_proposed:30,new_entries_rejected:18,new_entries_executed:12,
      roundtrips:11,exposure_contract_hours:'80',holding_hours:'70',net_usdt:'0.015',max_drawdown_usdt:'0.3'},
  },
  comparison:{new_entries_rejected_delta:18,roundtrips_delta:-17,
    exposure_contract_hours_delta:'-120',holding_hours_delta:'-110',
    net_usdt_delta:'0.258294323038495647991',max_drawdown_usdt_delta:'-0.3',
    effect_interpretation:'exploratory_only',improvement_claim_supported:false,promotion_supported:false},
  invariants:{same_base_strategy:true,same_data:true,same_cost:true,same_time_contract:true,
    same_simulated_account:true,no_training:true,no_parameter_search:true,
    entry_policy_only_changed_new_entry:true,existing_position_exit_and_protection_not_overridden:true},
  decision_effects:Array.from({length:18},(_,index)=>({
    event_id:`event-${index}`,phase:'market_entry_policy',
    market_entry_policy:{state_status:'observed',state_reasons:[],state_cutoff_utc:'2025-11-01T01:00:00+00:00',
      state_version:'market_state_descriptive_v2',state_definition_hash:'c'.repeat(64),
      state_source_binding_hash:'7'.repeat(64),state_input_hash:'a'.repeat(64),state_content_hash:'b'.repeat(64),
      original_target_contracts:'0.01',effective_target_contracts:'0',reason:'path_efficiency_below_threshold',
      state_binding_status:'verified'},
    selected_state:{projection_source:'exact_state_hash_join',projection_status:'complete',missing_fields:[],
      asset:'BTC-USDT-SWAP',decision_time:'2025-11-01T01:00:00+00:00',
      cutoff_time:'2025-11-01T01:00:00+00:00',status:'observed',reasons:[],direction_score:0.42,
      direction_label:'up',normalized_trend_strength:0.37,
      path_efficiency_by_horizon:{'24':0.16,'72':0.18,'168':0.31},multi_scale_agreement:0.66,
      bar_volatility:0.011,annualized_volatility:0.52,volatility_relative_position:0.74,
      volatility_expansion_ratio:1.08,volatility_regime:'stable',shock_score:0.35,
      direction_persistence:0.61,switching_frequency:0.12,
      definition_version:'market_state_descriptive_v2',definition_hash:'c'.repeat(64),
      source_binding_hash:'7'.repeat(64),input_hash:'a'.repeat(64),content_hash:'b'.repeat(64)},
  })),
  ...safety,
};
const blockedTrial={
  ...JSON.parse(read('.agent/market_state_evidence/donchian-stage-market-policy-trial-v1.json')),
  read_only:true,effect_verified:false,
};

test('market state evidence keeps description, stratification and policy trial separate',()=>{
  const html=renderToStaticMarkup(React.createElement(component,{evidence}));
  assert.match(html,/2960 根状态观测/);
  assert.match(html,/28 次开平仓/);
  assert.match(html,/170 个连续状态片段/);
  assert.match(html,/低效率 18/);
  assert.match(html,/混合 9/);
  assert.match(html,/方向性 1/);
  assert.match(html,/不能解释为概率、胜率或独立样本/);
  assert.match(html,/尚无已封存 A\/B 结果；这不代表后台任务未运行/);
  assert.match(html,/效果尚未验证/);
  assert.match(html,/不代表少交易后表现改善/);
  assert.match(html,/资金费仅有总体/);
  assert.match(html,/IC／Rank IC 不适用/);
  assert.match(html,/资金费、OI、深度均未进入本次状态输入/);
  assert.match(html,/运行时未消费/);
  assert.doesNotMatch(html,/<button|部署成功|有效概率/);
});

test('invalid or permission-bearing evidence is not rendered as trusted',()=>{
  for(const bad of [
    {...evidence,status:'promotion_ready'},
    {...evidence,policy_trial:{...evidence.policy_trial,effect_verified:true}},
    {...evidence,runtime_status:{...evidence.runtime_status,entry_policy_enabled:true}},
    {...evidence,order:true},
    {...evidence,stratification:{...evidence.stratification,sample_units:{bars:2960,roundtrips:170,contiguous_state_segments:28}}},
  ]) {
    const html=renderToStaticMarkup(React.createElement(component,{evidence:bad}));
    assert.match(html,/市场状态证据不可核验/);
    assert.doesNotMatch(html,/低效率 18|尚无已封存 A\/B 结果/);
  }
});

test('missing or independently blocked evidence stays explicit',()=>{
  const blocked=renderToStaticMarkup(React.createElement(component,{evidence:{status:'blocked',reason:'market_state_diagnostic_missing_or_invalid'}}));
  assert.match(blocked,/市场状态证据不可核验/);
  assert.match(blocked,/独立封存缺失或校验失败/);
});

test('completed sealed two-arm trial renders actual effect and exposure without promotion claim',()=>{
  const html=renderToStaticMarkup(React.createElement(component,{evidence:{...evidence,
    policy_trial_evidence:completedTrial}}));
  assert.match(html,/固定 A\/B 已完成 · 探索性证据/);
  assert.match(html,/原 Donchian/);
  assert.match(html,/条件政策臂/);
  assert.match(html,/拒绝新增 18/);
  assert.match(html,/敞口 200 → 80 合约小时/);
  assert.match(html,/持仓 180 → 70 小时/);
  assert.match(html,/净额差 0.258294323038495647991 USDT/);
  assert.match(html,/最大回撤差 -0.3 USDT/);
  assert.match(html,/18 条拒绝决策已绑定/);
  assert.match(html,/拒绝决策明细/);
  assert.match(html,/<select/);
  assert.match(html,/24h 0.16 · 72h 0.18 · 168h 0.31/);
  assert.match(html,/方向 up · 方向分数 0.42 · 归一化强度 0.37/);
  assert.match(html,/Bar 波动 0.011 · 年化 0.52 · 历史相对位置 0.74/);
  assert.match(html,/冲击 0.35 · 扩缩 1.08（stable）/);
  assert.match(html,/质量 observed · 原因 无 · 截止 2025-11-01T01:00:00\+00:00/);
  assert.match(html,/目标 0.01 → 0 · path_efficiency_below_threshold/);
  assert.match(html,/不能单凭净额或回撤差宣布改善/);
  assert.match(html,/不支持晋级/);
});

test('the original sealed stage wording remains historical when a later trial exists',()=>{
  const html=renderToStaticMarkup(React.createElement(component,{evidence:{...evidence,
    policy_trial_evidence:completedTrial}}));
  assert.match(html,/原阶段封存时.*not_started/);
  assert.match(html,/后续独立 A\/B/);
});

test('unknown selected state is shown as missing instead of zero or healthy',()=>{
  const trial=structuredClone(completedTrial);
  const effect=trial.decision_effects[0];
  Object.assign(effect.market_entry_policy,{state_status:'unknown',
    state_reasons:['insufficient_visible_history'],reason:'state_unknown'});
  Object.assign(effect.selected_state,{status:'unknown',reasons:['insufficient_visible_history'],
    projection_source:'consumer_phase',projection_status:'partial',missing_fields:stateMetricFields,
    direction_score:null,direction_label:null,normalized_trend_strength:null,
    path_efficiency_by_horizon:{'24':null,'72':null,'168':null},multi_scale_agreement:null,
    bar_volatility:null,annualized_volatility:null,volatility_relative_position:null,
    volatility_expansion_ratio:null,volatility_regime:null,shock_score:null,
    direction_persistence:null,switching_frequency:null});
  const html=renderToStaticMarkup(React.createElement(component,{evidence:{...evidence,
    policy_trial_evidence:trial}}));
  assert.match(html,/24h 缺失 · 72h 缺失 · 168h 缺失/);
  assert.match(html,/质量 unknown · 原因 insufficient_visible_history/);
  assert.match(html,/目标 0.01 → 0 · state_unknown/);
  assert.doesNotMatch(html,/24h 0 · 72h 0|质量 observed/);
});

test('consumer phase projection keeps unavailable multiscale metrics explicitly missing',()=>{
  const trial=structuredClone(completedTrial);
  const state=trial.decision_effects[0].selected_state;
  Object.assign(state,{projection_source:'consumer_phase',projection_status:'partial',
    missing_fields:stateMetricFields,direction_score:null,direction_label:null,
    normalized_trend_strength:null,path_efficiency_by_horizon:{'24':null,'72':null,'168':null},
    multi_scale_agreement:null,bar_volatility:null,annualized_volatility:null,
    volatility_relative_position:null,volatility_expansion_ratio:null,volatility_regime:null,
    shock_score:null,direction_persistence:null,switching_frequency:null});
  const html=renderToStaticMarkup(React.createElement(component,{evidence:{...evidence,
    policy_trial_evidence:trial}}));
  assert.match(html,/consumer_phase · partial · 缺失/);
  assert.match(html,/24h 缺失 · 72h 缺失 · 168h 缺失/);
  assert.match(html,/绝不借用最后状态或最近时点/);
  assert.doesNotMatch(html,/24h 0 · 72h 0/);
});

test('blocked trial never renders synthetic arm results',()=>{
  const html=renderToStaticMarkup(React.createElement(component,{evidence:{...evidence,
    policy_trial_evidence:{...completedTrial,status:'blocked',effect_verified:false,reason:'sealed_policy_trial_report_invalid'}}}));
  assert.match(html,/A\/B 封存不可核验/);
  assert.doesNotMatch(html,/敞口 200 → 80|净额差 0.258/);
});

test('a sealed incomplete trial shows the exact fail-closed breakpoint without effect claims',()=>{
  const html=renderToStaticMarkup(React.createElement(component,{evidence:{...evidence,
    policy_trial_evidence:blockedTrial}}));
  assert.match(html,/固定 A\/B 未完成 · 安全阻断/);
  assert.match(html,/原 Donchian.*2960 \/ 2960/);
  assert.match(html,/条件政策臂.*1956 \/ 2960/);
  assert.match(html,/2025-11-21T20:00:00\+08:00/);
  assert.match(html,/同一小时 K 线内保护价位双触达，无法确定先后/);
  assert.match(html,/终态持仓 -0.01 张.*保留，未伪平仓/);
  assert.match(html,/48 条政策拒绝 phase.*本页仅展示封存计数/);
  assert.match(html,/没有完整政策效果结论/);
  assert.doesNotMatch(html,/固定 A\/B 已完成|净额差|改善已验证/);
});
