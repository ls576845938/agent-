import {test} from 'node:test';
import assert from 'node:assert/strict';
import {diagnosticAdmissionState,offlineWorkerSupported} from '../src/workspaces/research/candidate-delivery-api';

const base:any={target:'offline',content_digest:'b'.repeat(64),consumer_head:'c'.repeat(40),
  package:{adapter_id:'factory_lgbm_ast_v1',admission_blockers:['no_simulated_fills']},
  diagnostic_admission:{schema_version:'strategy_delivery_diagnostic_admission_v1',mode:'isolated_offline_diagnostic',target:'offline',status:'admitted',
    package_digest:'b'.repeat(64),consumer_head:'c'.repeat(40),
    strict_package_blockers:['no_simulated_fills'],research_blockers:['no_simulated_fills'],blocking_reasons:[],decision_digest:'a'.repeat(64)}};

test('offline diagnostic admission remains distinct from research and runtime readiness',()=>{
  assert.deepEqual(diagnosticAdmissionState(base),{admitted:true,researchBlocked:true,blockingReasons:[],researchBlockers:['no_simulated_fills']});
  const capability={supported_adapter_ids:['factory_lgbm_ast_v1']};
  assert.equal(offlineWorkerSupported(base,capability),true);
  assert.equal(offlineWorkerSupported({...base,package:{...base.package,adapter_id:'btc_frozen_qlib_offline_v1'}},capability),false);
  assert.equal(offlineWorkerSupported(base,{}),false);
});

test('legacy, malformed, and hard-blocked decisions stay fail closed',()=>{
  assert.deepEqual(diagnosticAdmissionState({...base,diagnostic_admission:undefined}),{admitted:false,researchBlocked:true,blockingReasons:['diagnostic_admission_missing'],researchBlockers:['no_simulated_fills']});
  assert.deepEqual(diagnosticAdmissionState({...base,diagnostic_admission:{...base.diagnostic_admission,status:'blocked',
      strict_package_blockers:['no_simulated_fills','model_hash_mismatch'],blocking_reasons:['model_hash_mismatch']}}),
    {admitted:false,researchBlocked:true,blockingReasons:['model_hash_mismatch'],researchBlockers:['no_simulated_fills']});
});

test('source research failures remain visible beyond the two diagnostic exemptions',()=>{
  const row={...base,package:{...base.package,
    admission_blockers:['no_simulated_fills','candidate_calibration_quality_not_passed']},
    diagnostic_admission:{...base.diagnostic_admission,status:'blocked',
      strict_package_blockers:['no_simulated_fills','candidate_calibration_quality_not_passed'],
      research_blockers:['no_simulated_fills'],blocking_reasons:['candidate_calibration_quality_not_passed']}};
  assert.deepEqual(diagnosticAdmissionState(row),{admitted:false,researchBlocked:true,
    blockingReasons:['candidate_calibration_quality_not_passed'],
    researchBlockers:['candidate_calibration_quality_not_passed','no_simulated_fills']});
});
