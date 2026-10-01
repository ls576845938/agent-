"""A frozen management implementation can only be published disabled."""
import copy
import importlib
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def module():
    return importlib.import_module('tools.agent_governance.candidate_management_readonly_delivery')


def receipt():
    m = module()
    return {
        'schema_version': 'candidate_management_readonly_receipt_v1',
        'ticket_id': m.TICKET, 'phase': 'source_review',
        'source_commit': m.SOURCE, 'baseline_commit': m.BASE,
        'deployment_profile': 'research_readonly',
        'governance_commit': 'a'*40, 'target_commit': 'd'*40,
        'governance_review': {'commit': 'b'*40, 'path': m.REVIEW, 'sha256': '1'*64},
        'integration_review': {'commit': 'c'*40, 'path': m.INTEGRATION, 'sha256': '2'*64},
        'checks': dict.fromkeys(m.SOURCE_CHECKS, True),
        'safety_flags': dict.fromkeys(m.FALSE_FLAGS, False),
    }


def test_inventory_is_exact_and_legacy_policy_unchanged():
    m = module()
    m.frozen_source(ROOT)
    path = 'docs/agent_playbooks/delivery_risk_policy.json'
    assert json.loads((ROOT/path).read_text(encoding='utf-8')) == json.loads(
        subprocess.check_output(['git', 'show', m.BASE+':'+path], cwd=ROOT))


def test_booleans_cannot_replace_committed_reviews():
    assert module().blockers(receipt(), repo_root=ROOT)


def test_shape_only_with_explicit_evidence_stub(monkeypatch):
    monkeypatch.setattr(module(), '_evidence', lambda *args: None)
    assert module().blockers(receipt(), repo_root=ROOT) == []


@pytest.mark.parametrize('field,value', [('source_commit','f'*40),('baseline_commit','f'*40),
    ('ticket_id','other'),('deployment_profile','candidate_management'),
    ('deployment_profile','demo_quasi_live'),('phase','other')])
def test_wrong_identity_and_enablement_rejected(field,value):
    item=receipt(); item[field]=value
    assert module().blockers(item, repo_root=ROOT)


def test_all_flags_and_checks_strict(monkeypatch):
    monkeypatch.setattr(module(), '_evidence', lambda *args: None)
    for section,valid in [('checks',True),('safety_flags',False)]:
        for name in receipt()[section]:
            for value in [None, 'true', 1, 0, not valid]:
                item=receipt(); item[section][name]=value
                assert module().blockers(item, repo_root=ROOT)
        item=receipt(); item[section]['unknown']=valid
        assert module().blockers(item, repo_root=ROOT)


def test_unknown_fields_and_missing_deployment_evidence():
    item=receipt(); item['extra']=True
    assert module().blockers(item, repo_root=ROOT)
    item=receipt(); item['phase']='deployment_acceptance'
    assert module().blockers(item, repo_root=ROOT)


@pytest.mark.parametrize('path', ['start-backend.cmd','.codex/hooks.json','backend/app/core/config.py',
    'quant_crypto/oms/runtime_store.py','tools/agent_governance/delivery_policy.py',
    '../docs/escape.md','.agent/handoffs/unrelated/x.json'])
def test_no_unreviewed_delta(path):
    assert not module().allowed_delta(path)


def test_forged_report_hash_rejected(monkeypatch):
    monkeypatch.setattr(module(), '_git', lambda *args: b'actual report')
    with pytest.raises(ValueError, match='report_digest_mismatch'):
        module()._report(ROOT, receipt()['governance_review'], module().REVIEW)


def test_source_modification_rejected(monkeypatch):
    m=module()
    monkeypatch.setattr(m, '_git', lambda root,*args: b'backend/app/core/config.py\n')
    with pytest.raises(ValueError, match='unreviewed_delta'):
        m._delta(ROOT, m.SOURCE, 'd'*40)


def test_review_cannot_change_governance(monkeypatch):
    m=module()
    monkeypatch.setattr(m, '_git', lambda root,*args: m.CONTRACT.encode())
    with pytest.raises(ValueError, match='review_changed_code'):
        m._metadata_only(ROOT, 'a'*40, 'b'*40, {m.REVIEW})
