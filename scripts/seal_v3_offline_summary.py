"""One-shot, read-only report builder for the reviewed zero-fill V3 capture.

Prints JSON only; never runs a strategy, opens a broker, or modifies a store.
Nonzero/other captures are deliberately outside this report's scope.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.services.offline_execution_views import FLAGS, summary_digest
from quant_crypto.oms.runtime_store import BTCRuntimeStore
from quant_crypto.oms.account_risk_facts import replay_account_ledger_uows

EXPECTED = {
    'candidate_policy_evidence.jsonl': '13a43a9723547bd8f517850567e79497ced5523f234efc7c255a37b41faaf51b',
    'candidate_runtime/qlib_fixture_replay_identity.json': '9cdb7d39a01d9788884899af34f4a40f169d616cc6ad3a5df76ccff81af0a0be',
    'candidate_runtime/runtime/events.jsonl': 'f9b8a87f05757ef2562b39c5dfe2ce352e262019f5f0c216abc7a8ad9db97741',
    'candidate_runtime/runtime/state.json': 'ef87de4fbfa6ec6dd693d784e6a587a6ac0f9b342dc8fddf6204a512434d4734',
    'candidate_runtime/offline_venue.json': '95dc592a2c4010fec8ad94b95230bbfaf8af6d0f7f9fe96da22b865fe2c7fe45',
}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def build(root: Path):
    root = root.resolve(strict=True)
    raw = {}
    for name, expected in EXPECTED.items():
        path = (root / name).resolve(strict=True)
        require(path.is_relative_to(root), 'source_path_escape')
        raw[name] = path.read_bytes()
        require(hashlib.sha256(raw[name]).hexdigest() == expected, 'source_hash_mismatch:' + name)
    identity = json.loads(raw['candidate_runtime/qlib_fixture_replay_identity.json'])
    require(identity['identity_digest'] == summary_digest({k:v for k,v in identity.items() if k != 'identity_digest'}), 'identity_digest_mismatch')
    recovery = BTCRuntimeStore(root / 'candidate_runtime/runtime').recover()
    require(not recovery.blockers and not recovery.truncated_tail, 'runtime_recovery_blocked')
    events = list(recovery.events)
    checkpoint = json.loads(raw['candidate_runtime/runtime/state.json'])
    require(checkpoint['last_sequence'] == len(events) and checkpoint['last_event_hash'] == events[-1]['event_hash'], 'checkpoint_not_at_tip')
    require(events[-1]['event_type'] == 'qlib_offline_clean_stopped', 'not_clean_stopped')
    for event in events:
        require(event['semantic_hash'] == summary_digest({k:event[k] for k in ('event_type','payload','run_id')}), 'event_semantic_hash_mismatch')
    for key in ('exchange','account_risk_facts','ledger_reconciliation'):
        require(checkpoint['state'][key] == events[-1]['state_after'][key], 'economic_checkpoint_mismatch')
    rows = [json.loads(line) for line in raw['candidate_policy_evidence.jsonl'].splitlines()]
    require(len({row['decision_id'] for row in rows}) == len(rows), 'duplicate_decision')
    batches = [event for event in events if event['event_type'] == 'qlib_offline_rejected_batch']
    previous = '0' * 64
    linked = set()
    for batch in batches:
        payload = batch['payload']
        decisions = payload['decisions']
        require(payload['identity_digest'] == identity['identity_digest'], 'batch_identity_mismatch')
        require(payload['logical_decision_count'] == len(decisions), 'batch_count_mismatch')
        require(payload['first_decision_hash'] == decisions[0]['decision_hash'] and payload['last_decision_hash'] == decisions[-1]['decision_hash'], 'batch_boundary_mismatch')
        for decision in decisions:
            require(decision['previous_decision_hash'] == previous, 'decision_chain_broken')
            require(decision['decision_hash'] == summary_digest({k:v for k,v in decision.items() if k != 'decision_hash'}), 'decision_digest_mismatch')
            previous = decision['decision_hash']
    for row in rows:
        seq, index = row['runtime_batch_event_sequence'], row['runtime_batch_index']
        event = events[seq-1]
        require(event['event_type'] == 'qlib_offline_rejected_batch', 'decision_not_rejected_batch')
        decision = event['payload']['decisions'][index]
        require((seq,index) not in linked, 'duplicate_link')
        linked.add((seq,index))
        require(row['runtime_batch_event_hash'] == event['event_hash'] and row['runtime_decision_hash'] == decision['decision_hash'], 'decision_event_hash_mismatch')
        for outer, inner in [('runtime_decision_event_id','event_id'),('target_position_id','target_position_id')]:
            require(row[outer] == decision[inner], 'decision_identity_mismatch')
        require(row['forecast_id'] == decision['input_binding']['forecast_id'], 'forecast_mismatch')
        require(row['package_sha256'] == identity['verified_package_sha256'] == decision['input_binding']['verified_package_sha256'], 'package_mismatch')
        require(row['forecast_sha256'] == decision['input_binding']['forecast_sha256'], 'forecast_hash_mismatch')
        require(row['reasons'] == decision['policy_reasons'] and row['execution_blockers'] == decision['result']['execution_blockers'], 'decision_reasons_mismatch')
        require(row['approved'] is False and row['outcome'] == 'no_trade_rejected', 'not_zero_fill_rejection')
        require(all(row['permissions'].get(k) is False and decision['result']['permissions'].get(k) is False for k in FLAGS), 'permission_enabled')
    require(len(linked) == sum(len(event['payload']['decisions']) for event in batches), 'unlinked_decisions')
    venue = json.loads(raw['candidate_runtime/offline_venue.json'])
    require(venue['submit_count'] == 0 and venue['fills'] == [] and venue['bills'] == [] and float(venue['position']) == 0, 'not_reviewed_zero_fill_capture')
    stored = checkpoint['state']['ledger_reconciliation']['account_ledger_replay']
    ledger = replay_account_ledger_uows(
        uow_payloads=[event['payload'] for event in events if event['event_type'] == 'ledger_uow_committed'],
        baseline_equity_usdt=identity['initial_equity_usdt'], baseline_observed_at_utc=stored['baseline_observed_at_utc'],
        final_observed_at_utc=venue['last_observed_at_utc'], currency='USDT',
        final_exchange_snapshot={'balance':{'equity_usdt':venue['equity']}, 'mark':{'mark_price':venue['market_price']},
                                 'positions':[{'contracts':venue['position'],'position_side':'net'}]},
    )
    require(all(stored[k] == v for k,v in ledger.items()), 'replayed_ledger_mismatch')
    sample_keys = ('decision_id','decision_time','event_time','reasons','execution_blockers','forecast_id',
                   'target_position_id','target_quantity_btc','runtime_batch_event_sequence',
                   'runtime_batch_event_hash','runtime_decision_hash','runtime_decision_event_id')
    summary = {
        'status':'sealed_offline_summary','truth_kind':'offline_execution_simulation',
        'replay_id':'v3-readonly-20260920-7d686dbd6', 'source_head':identity['code_version'],
        'research_binding':{'qlib_run_id':identity['run_id'], 'candidate_id':identity['candidate_id'],
            'strategy_id':identity['strategy_id'],'strategy_version':identity['strategy_version'],
            'data_version':identity['data_version'], 'dataset_manifest_sha256':rows[0]['dataset_manifest_sha256']},
        'model_sha256':identity['model_sha256'], 'policy_sha256':identity['policy_sha256'],
        'package_sha256':identity['verified_package_sha256'], 'identity_digest':identity['identity_digest'],
        'permissions':{k:False for k in FLAGS},
        'counts':{'decisions':len(rows),'events':len(events),'rejected_batches':len(batches),'approved':0,'fills':0,'submitted_orders':0},
        'decision_start':rows[0]['event_time'], 'decision_end':rows[-1]['event_time'],
        'account_observed_at':venue['last_observed_at_utc'], 'stop_recorded_at':events[-1]['timestamp_utc'],
        'ledger':ledger, 'ledger_event_sequence':events[0]['sequence'], 'ledger_event_hash':events[0]['event_hash'],
        'rejection_reasons':dict(Counter(reason for row in rows for reason in row['execution_blockers'])),
        'samples':[{k:row[k] for k in sample_keys} for row in (rows[0],rows[-1])],
        'sample_scope':'first_and_last_only_all_links_verified_at_sealing',
        'limitations':['zero_fill_no_nonzero_execution_coverage','initial_simulated_account_not_real_account',
                       'summary_only_not_live_ledger','decision_end_is_not_account_observation_time'],
        'source_files':[{'path':name,'sha256':digest,'bytes':len(raw[name])} for name,digest in EXPECTED.items()],
    }
    require(all(row['dataset_manifest_sha256'] == summary['research_binding']['dataset_manifest_sha256'] for row in rows), 'dataset_mismatch')
    # Detect concurrent source changes before sealing; reader never updates these files.
    require(all((root/name).read_bytes() == contents for name,contents in raw.items()), 'source_changed_during_sealing')
    return {'schema_version':'offline_execution_summary_seal_v1','sha256':summary_digest(summary),'summary':summary}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.source), ensure_ascii=False, indent=2, allow_nan=False))
