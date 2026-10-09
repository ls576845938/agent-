import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const read=(name)=>readFileSync(new URL(`../src/workspaces/research/${name}`,import.meta.url),'utf8');
const controls=read('RegisteredCandidateRunControls.tsx');
const evidence=read('RegisteredCandidateOfflineEvidence.tsx');
const offlineApi=read('candidate-offline-api.ts');

assert.match(controls,/supported_adapter_ids\.includes\(row\.package\.adapter_id\)/);
assert.match(controls,/\['stopped','interrupted'\]\.includes\(job\.status\)/);
assert.doesNotMatch(controls,/\['stopped','interrupted','blocked'\]/);
assert.match(controls,/历史 OHLC／mark 保护/);
assert.match(controls,/显式采样 mark 执行/);
assert.match(evidence,/双触碰或时序歧义保持 blocked/);
assert.match(evidence,/旧 blocked 封存结果保持原标记/);
assert.match(offlineApi,/btc_donchian_history_offline_v1/);
assert.match(offlineApi,/value\.result\.finalized!==true/);
assert.doesNotMatch(controls,/保护成交尚未接入/);

console.log('unified candidate offline static contracts: ok');
