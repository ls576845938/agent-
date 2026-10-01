"""One frozen, disabled candidate manager: evidence checks only, no activation."""
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = '55f039ae5fbcd48730cc55cb0ade2c0d92eb3066'
SOURCE = '1fc70fec77a6bac7b5699e99b503a10b92af659c'
TICKET = 'candidate-management-delivery-governance-20260924'
CONTRACT = 'docs/agent_playbooks/candidate_management_readonly_delivery.json'
CONTRACT_HASH = 'ab7389e7d54cb5d825ce703b7c846f4a37bd59a7135adc7f3dad30b23c84a23d'
REVIEW = 'docs/operations/candidate-management-delivery-governance-review-20260924.md'
INTEGRATION = 'docs/operations/candidate-management-readonly-integration-20260924.md'
ACCEPTANCE = 'docs/operations/candidate-management-readonly-acceptance-20260924.md'
ROLLBACK = 'refs/tags/codex/candidate-management-before-release-20260924'
GOVERNANCE = frozenset({CONTRACT,
    'docs/agent_playbooks/candidate_management_readonly_delivery.md',
    'tools/agent_governance/candidate_management_readonly_delivery.py',
    'tests/agent_governance/test_candidate_management_readonly_delivery.py',
    'docs/operations/candidate-management-delivery-governance-20260924.md'})
HANDOFFS = ('.agent/handoffs/'+TICKET+'/',
            '.agent/handoffs/candidate-management-readonly-integration-20260924/')
IDENTITY = 'frontend/public/frontend-identity.json'
SOURCE_CHECKS = ('explicit_user_authorization', 'scoped_clean', 'source_handoffs_verified',
    'independent_source_review', 'independent_governance_review', 'independent_integrator',
    'fresh_governance_context', 'frozen_source_verified', 'compatibility_and_safety_tests',
    'frontend_identity_refresh_verified', 'no_private_or_trading_access')
DEPLOY_CHECKS = ('canonical_launchers_checked', 'backend_current_main_identity',
    'frontend_current_main_identity', 'registered_listeners_and_health',
    'canonical_browser_acceptance', 'management_commands_blocked',
    'no_management_storage_created', 'rollback_verified')
FALSE_FLAGS = ('candidate_management_enabled', 'management_root_configured',
    'management_operator_configured', 'management_auth_configured',
    'demo_control_enabled', 'promotion', 'paper', 'live', 'private', 'order',
    'real_order', 'transfer', 'withdraw', 'execution_permission',
    'runtime_worker_enabled', 'runtime_observed')


def _git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.PIPE, timeout=30)


def _commit(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{40}', value) is not None


def _ancestor(root, before, after):
    if not _commit(before) or not _commit(after):
        raise ValueError('commit_required')
    _git(root, 'merge-base', '--is-ancestor', before, after)


def _paths(root, before, after):
    return set(_git(root, 'diff', '--name-only', before, after, '--').decode().splitlines())


def _handoff(path):
    return any(path.startswith(prefix) and re.fullmatch('[A-Za-z0-9_-]+\\.json', path[len(prefix):])
               for prefix in HANDOFFS)


def allowed_delta(path):
    if not isinstance(path, str) or '\\' in path or ':' in path or any(p in ('', '.', '..') for p in path.split('/')):
        return False
    return path in GOVERNANCE or path in (REVIEW, INTEGRATION, ACCEPTANCE, IDENTITY) or bool(_handoff(path))


def _delta(root, before, after):
    if any(not allowed_delta(p) for p in _paths(root, before, after)):
        raise ValueError('unreviewed_delta')


def _metadata_only(root, before, after, reports):
    if any(p not in reports and not _handoff(p) for p in _paths(root, before, after)):
        raise ValueError('review_changed_code')


def contract(root=ROOT):
    value = json.loads((root/CONTRACT).read_text(encoding='utf-8'))
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    if hashlib.sha256(encoded).hexdigest() != CONTRACT_HASH:
        raise ValueError('fixed_contract_changed')
    return value


def frozen_source(root=ROOT):
    value = contract(root)
    _ancestor(root, BASE, SOURCE)
    if _paths(root, BASE, SOURCE) != set(value['source_files']):
        raise ValueError('source_touch_set_mismatch')
    for path, expected in value['source_files'].items():
        if hashlib.sha256(_git(root, 'show', SOURCE+':'+path)).hexdigest() != expected:
            raise ValueError('source_hash_mismatch:'+path)


def _report(root, ref, path):
    if not isinstance(ref, dict) or set(ref) != {'commit','path','sha256'} or ref['path'] != path or not _commit(ref['commit']):
        raise ValueError('report_reference_invalid')
    if hashlib.sha256(_git(root,'show',ref['commit']+':'+path)).hexdigest() != ref['sha256']:
        raise ValueError('report_digest_mismatch')
    return ref['commit']


def _evidence(root, receipt):
    frozen_source(root)
    gov, target = receipt['governance_commit'], receipt['target_commit']
    review = _report(root, receipt['governance_review'], REVIEW)
    integration = _report(root, receipt['integration_review'], INTEGRATION)
    if gov == review or gov == BASE or target == SOURCE:
        raise ValueError('distinct_committed_review_required')
    _ancestor(root, BASE, gov)
    if any(p not in GOVERNANCE and not _handoff(p) for p in _paths(root,BASE,gov)):
        raise ValueError('governance_contains_business_or_unrelated_changes')
    _ancestor(root, gov, review)
    _metadata_only(root,gov,review,{REVIEW})
    _ancestor(root, review, integration)
    _ancestor(root, SOURCE, integration)
    _ancestor(root, integration, target)
    _metadata_only(root,integration,target,{INTEGRATION})
    _delta(root,SOURCE,target)
    for path in GOVERNANCE:
        if _git(root,'show',gov+':'+path) != _git(root,'show',target+':'+path):
            raise ValueError('reviewed_governance_changed:'+path)
    if receipt['phase'] == 'deployment_acceptance':
        acceptance = _report(root,receipt['acceptance'],ACCEPTANCE)
        _ancestor(root,target,acceptance)
        _metadata_only(root,target,acceptance,{ACCEPTANCE})
        if _git(root,'rev-parse','refs/heads/main').decode().strip() != target:
            raise ValueError('current_main_mismatch')
        if _git(root,'rev-parse',ROLLBACK+'^{commit}').decode().strip() != BASE:
            raise ValueError('rollback_mismatch')


def blockers(receipt, *, repo_root=ROOT):
    if not isinstance(receipt,dict): return ['receipt_not_object']
    fixed={'schema_version':'candidate_management_readonly_receipt_v1','ticket_id':TICKET,
           'source_commit':SOURCE,'baseline_commit':BASE,'deployment_profile':'research_readonly'}
    problems=[key+'_mismatch' for key,value in fixed.items() if receipt.get(key)!=value]
    phase=receipt.get('phase')
    if phase not in ('source_review','deployment_acceptance'): problems.append('unknown_phase')
    fields=set(fixed)|{'phase','governance_commit','target_commit','governance_review','integration_review','checks','safety_flags'}
    if phase=='deployment_acceptance': fields.add('acceptance')
    if set(receipt)!=fields: problems.append('receipt_fields_missing_or_unknown')
    required=set(SOURCE_CHECKS)|(set(DEPLOY_CHECKS) if phase=='deployment_acceptance' else set())
    for section,names,expected in [('checks',required,True),('safety_flags',set(FALSE_FLAGS),False)]:
        value=receipt.get(section)
        if not isinstance(value,dict) or set(value)!=names: problems.append(section+'_missing_or_unknown')
        elif any(v is not expected for v in value.values()): problems.append(section+'_not_literal_boolean')
    if problems: return sorted(set(problems))
    try:
        contract(repo_root)
        _evidence(repo_root,receipt)
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
        return ['evidence_invalid:'+(str(exc) if isinstance(exc,ValueError) else type(exc).__name__)]
    return []
