"""Read a committed, sealed report; never open or recover a runtime directory."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess

REPORT_PATH = '.agent/offline_evidence/v3-readonly-20260920.json'
FLAGS = ('execution_permission', 'live', 'order', 'paper', 'private', 'promotion',
         'real_order', 'runtime_observed', 'transfer', 'withdraw')
BINDING_KEYS = ('qlib_run_id', 'candidate_id', 'strategy_id', 'strategy_version',
                'data_version', 'dataset_manifest_sha256')


def summary_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def validate_summary(envelope, research_identity, current_head):
    if envelope.get('schema_version') != 'offline_execution_summary_seal_v1':
        raise ValueError('offline_summary_schema_invalid')
    summary = envelope['summary']
    if envelope.get('sha256') != summary_digest(summary):
        raise ValueError('offline_summary_digest_mismatch')
    if summary.get('truth_kind') != 'offline_execution_simulation' or summary.get('status') != 'sealed_offline_summary':
        raise ValueError('offline_summary_truth_kind_invalid')
    if any(summary.get('permissions', {}).get(key) is not False for key in FLAGS):
        raise ValueError('offline_summary_permission_invalid')
    binding = summary['research_binding']
    if any(not isinstance(binding.get(key), str) or not binding[key]
           or binding[key] != research_identity.get(key) for key in BINDING_KEYS):
        raise ValueError('offline_summary_research_identity_mismatch')
    if not re.fullmatch('[0-9a-f]{64}', summary.get('model_sha256', '')) or summary['model_sha256'] != research_identity.get('model_sha256'):
        raise ValueError('offline_summary_model_mismatch')
    if not re.fullmatch('[0-9a-f]{40}', summary.get('source_head', '')):
        raise ValueError('offline_summary_source_head_invalid')
    if any(type(summary['counts'].get(key)) is not int or summary['counts'][key] < 0
           for key in ('decisions', 'events', 'rejected_batches', 'approved', 'fills', 'submitted_orders')):
        raise ValueError('offline_summary_counts_invalid')
    return {**summary, 'historical_source': summary['source_head'] != current_head,
            'summary_sha256': envelope['sha256'], 'publication_head': current_head,
            'manifest_ref': f'{current_head}:{REPORT_PATH}', 'read_only': True}


def read_offline_summary(repo_root: Path, research_identity: dict):
    """No path/ref selector, no working-tree fallback, bounded immutable Git reads."""
    blocked = {'status': 'blocked', 'read_only': True,
               'permissions': {key: False for key in FLAGS}}
    if research_identity.get('qlib_run_id') != 'm1-okx-qlib':
        return {**blocked, 'status': 'not_bound', 'reason': 'offline_summary_not_bound'}
    try:
        def git(*args):
            return subprocess.run(['git', '-C', str(repo_root), *args], check=True,
                                  capture_output=True, timeout=5).stdout
        head = git('rev-parse', 'HEAD').decode('ascii').strip()
        spec = f'{head}:{REPORT_PATH}'
        if int(git('cat-file', '-s', spec)) > 65536:
            raise ValueError('offline_summary_size_invalid')
        envelope = json.loads(git('show', spec))
        return validate_summary(envelope, research_identity, head)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return {**blocked, 'reason': 'offline_summary_missing_or_invalid'}
