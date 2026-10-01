import copy
import json
from pathlib import Path
import subprocess

import pytest

from backend.app.services.offline_execution_views import validate_summary, summary_digest, read_offline_summary


def fixture():
    payload = json.loads((Path(__file__).resolve().parents[2] / '.agent/offline_evidence/v3-readonly-20260920.json').read_text(encoding='utf-8'))
    identity = {**payload['summary']['research_binding'], 'model_sha256':payload['summary']['model_sha256']}
    return payload, identity


def test_valid_snapshot():
    payload, identity = fixture()
    result = validate_summary(payload, identity, 'f' * 40)
    assert result['status'] == 'sealed_offline_summary'
    assert result['historical_source'] is True
    assert result['counts']['fills'] == 0
    assert result['permissions']['live'] is False


@pytest.mark.parametrize('field', ['qlib_run_id', 'candidate_id', 'strategy_version', 'data_version', 'dataset_manifest_sha256', 'model_sha256'])
def test_exact_binding_required(field):
    payload, identity = fixture()
    identity = dict(identity)
    identity[field] = 'wrong'
    with pytest.raises(ValueError):
        validate_summary(payload, identity, 'f' * 40)


def test_tamper_and_permission_fail_closed():
    payload, identity = fixture()
    bad = copy.deepcopy(payload)
    bad['summary']['counts']['fills'] = 1
    with pytest.raises(ValueError):
        validate_summary(bad, identity, 'f' * 40)
    bad = copy.deepcopy(payload)
    bad['summary']['permissions']['order'] = True
    bad['sha256'] = summary_digest(bad['summary'])
    with pytest.raises(ValueError):
        validate_summary(bad, identity, 'f' * 40)


def test_missing_commit_has_no_filesystem_fallback(tmp_path):
    payload, identity = fixture()
    target = tmp_path / '.agent/offline_evidence/v3-readonly-20260920.json'
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(payload), encoding='utf-8')
    result = read_offline_summary(tmp_path, identity)
    assert result['status'] == 'blocked'
    assert 'summary' not in result


def test_committed_object_not_dirty_worktree(tmp_path):
    payload, identity = fixture()
    def git(*args):
        return subprocess.run(['git','-C',str(tmp_path),*args], check=True, capture_output=True)
    git('init')
    git('config','user.name','Readonly Test')
    git('config','user.email','readonly@example.invalid')
    path = tmp_path / '.agent/offline_evidence/v3-readonly-20260920.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload),encoding='utf-8')
    git('add','.agent')
    git('commit','-m','fixture')
    path.write_text('corrupt uncommitted file',encoding='utf-8')
    result = read_offline_summary(tmp_path,identity)
    assert result['status'] == 'sealed_offline_summary'
    assert result['read_only'] is True
    assert path.read_text() == 'corrupt uncommitted file'


def test_sealer_rejects_wrong_source_before_runtime_reads(tmp_path):
    from scripts.seal_v3_offline_summary import build
    (tmp_path / 'candidate_policy_evidence.jsonl').write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='source_hash_mismatch'):
        build(tmp_path)
