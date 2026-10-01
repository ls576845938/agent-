import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createRequire} from 'node:module';

const require = createRequire(import.meta.url);
const exports = {};
const input = fs.readFileSync(new URL('../src/workspaces/research/TrendEnvironmentEvidence.tsx', import.meta.url),'utf8');
new Function('exports','require',ts.transpileModule(input,{compilerOptions:{module:ts.ModuleKind.CommonJS,
  target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText)(exports,require);
const flags = Object.fromEntries(['execution_permission','runtime_observed','promotion','paper','live','private','order','real_order','transfer','withdraw'].map(k=>[k,false]));
const environment = {schema_version:'trend_environment_evidence_v1',usage:'observation_only',status:'completed',
  identity:{run_id:'same'},...flags,preview:[{asset:'BTC',decision_time:'2026-01-01',horizon_bars:24,status:'observed',
  calendar:'UTC_24x7',direction:'up',trend_fit:.7234,bar_volatility:.01,shock_score:null,transition_score:0}]};
const detail = {summary:{run_id:'same'},integrity_status:'passed',trend_environment:environment};
const render = value => renderToStaticMarkup(React.createElement(exports.default,{detail:value,runId:'same'}));
assert.match(render(detail), /0\.7234/);
assert.match(render(detail), /非概率/);
assert.match(render(detail), /不授予交易权限/);
assert.doesNotMatch(render({...detail,summary:{run_id:'other'}}), /0\.7234/);
assert.doesNotMatch(render({...detail,integrity_status:'blocked'}), /0\.7234/);
assert.doesNotMatch(render({...detail,trend_environment:{...environment,identity:{run_id:'other'}}}), /0\.7234/);
for (const key of Object.keys(flags)) assert.doesNotMatch(render({...detail,trend_environment:{...environment,[key]:true}}), /0\.7234/);
for (const key of Object.keys(flags)) assert.doesNotMatch(render({...detail,[key]:true}), /0\.7234/);
assert.match(render({...detail,trend_environment:{status:'missing'}}), /旧运行无环境证据/);
assert.match(render({...detail,trend_environment:{...environment,status:'blocked',blockers:['missing_time']}}), /missing_time/);
assert.match(render({...detail,trend_environment:{...environment,source_stale:true}}), /不作 current-HEAD 证据/);
assert.doesNotMatch(input, /researchApi|alphaFactoryApi|fetch\(|Math\.random|submitOrder/);
const summary = fs.readFileSync(new URL('../src/workspaces/research/QlibDecisionTrace.tsx',import.meta.url),'utf8');
const pages = fs.readFileSync(new URL('../src/workspaces/ResearchPortfolioWorkspace.tsx',import.meta.url),'utf8');
assert.match(summary, /<TrendEnvironmentEvidence detail=\{detail\} runId=\{runId\}/);
assert.match(pages, /QlibRunSummary detail=\{checkedQlibDetail\}/);
assert.match(summary, /QlibRunSummary detail=\{detail\?\.summary\?\.run_id === runId/);
console.log('PASS rendered evidence, missing/stale/mismatched/unsafe states and existing three-page reuse; not browser acceptance');
