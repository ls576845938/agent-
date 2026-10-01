import json
from pathlib import Path

import pandas as pd
import pytest

from integrations.qlib_adapter import trend_environment as env
from integrations.qlib_adapter.research_pipeline import read_sealed_evidence, seal_run
from integrations.qlib_adapter.schemas import resolve_git_commit, write_json, read_json, QlibAdapterError
from quant_shared.trend_environment.model import digest


def fixture(root: Path, run_id="env-fixture"):
    run = root / run_id
    (run / "qlib_input").mkdir(parents=True)
    times = pd.date_range("2026-01-01", periods=240, freq="h", tz="UTC")
    frame = pd.DataFrame({"event_time": times, "decision_time": times+pd.Timedelta(hours=1),
        "available_time": times+pd.Timedelta(hours=1), "symbol": "BTC-USDT-SWAP", "confirm": 1,
        "close": [60000 + i + (i%3) for i in range(len(times))]})
    bars = run / "qlib_input/daily_bars.parquet"; frame.to_parquet(bars, index=False)
    write_json(run / "qlib_input/dataset_manifest.json", {"run_id": run_id, "symbols_exported": ["BTC-USDT-SWAP"],
        "input_contract": {"data_version_request": "synthetic-v1", "bar_size": "1h", "asset_class": "crypto", "annualization": 8760},
        "input_sha256": env.sha(bars), "calendar": {"name": "UTC_24x7", "trading_days": [t.isoformat() for t in times]},
        "validation": {"available_time_semantics": "synthetic_fixture"}})
    write_json(run / "qlib_run_metadata.json", {"run_id": run_id, "code_version": resolve_git_commit(Path.cwd()), "config_sha256": "a"*64})
    write_json(run / "pipeline_result.json", {"run_id": run_id, "status": "completed", "asset_class": "crypto", "bar_size": "1h"})
    return run


def test_producer_persistence_api_and_existing_context(monkeypatch, tmp_path):
    root = fixture(tmp_path)
    ref = env.build_sidecar(root)
    assert ref["status"] == "completed"
    seal_run(root)
    verified = read_sealed_evidence(root)
    assert verified["integrity_status"] == "passed"
    payload = verified["trend_environment"]
    assert len(payload["preview"]) == 48 and payload["observation_count"] == 720
    assert payload["identity"]["run_id"] == root.name and payload["context"]["schema_version"] == "strategy_decision_context_v1"
    from backend.app.api import app_factory
    from fastapi.testclient import TestClient
    monkeypatch.setattr(app_factory, "QLIB_ARTIFACTS_ROOT", tmp_path)
    client = TestClient(app_factory.create_app())
    result = client.get("/api/integrations/qlib/runs/"+root.name).json()
    assert result["trend_environment"] == payload
    assert result["summary"]["run_id"] == root.name
    assert all(result["trend_environment"][key] is False for key in env.SAFETY)
    assert not result["research_trace"]  # Never manufacture a seven-layer trace.
    assert env.sha(root/env.EVIDENCE) == ref["sha256"]


def test_old_runs_are_missing_and_reads_never_recompute(tmp_path, monkeypatch):
    root = fixture(tmp_path); seal_run(root)
    monkeypatch.setattr(env, "build_sidecar", lambda *a,**k: pytest.fail("GET cannot compute"))
    result = read_sealed_evidence(root)
    assert result["integrity_status"] == "passed"
    assert result["trend_environment"]["status"] == "missing"
    assert not (root/env.EVIDENCE).exists()


def test_disabled_and_failed_observer_preserve_original_research_files(tmp_path, monkeypatch):
    for mode in ("off", "on", "failure"):
        root = fixture(tmp_path, mode)
        before = {p.relative_to(root).as_posix(): env.sha(p) for p in root.rglob("*") if p.is_file()}
        with monkeypatch.context() as patch:
            if mode == "failure": patch.setattr(env, "estimate", lambda *a,**k: (_ for _ in ()).throw(ValueError("injected_observer_failure")))
            receipt = env.build_sidecar(root, enabled=mode != "off")
        assert receipt["status"] == {"off":"disabled", "on":"completed", "failure":"blocked"}[mode]
        assert before == {name: env.sha(root/name) for name in before}
        seal_run(root)
        assert read_sealed_evidence(root)["integrity_status"] == "passed"


@pytest.mark.parametrize("attack", ["bytes", "run", "data", "config", "context", "permission", "count"])
def test_hash_and_semantic_rebinding_fail_closed(tmp_path, attack):
    root = fixture(tmp_path); env.build_sidecar(root); seal = seal_run(root)
    payload = read_json(root/env.EVIDENCE)
    if attack == "run": payload["identity"]["run_id"] = "other"
    elif attack == "data": payload["identity"]["data_version"] = "other"
    elif attack == "config": payload["config"]["periods_per_year"] = 252
    elif attack == "context": payload["context"]["parameters"]["evidence_refs"]["trend_environment_v1"]["run_id"] = "other"
    elif attack == "permission": payload["order"] = True
    elif attack == "count": payload["observation_count"] = 0
    else: payload["status"] = "tampered"
    write_json(root/env.EVIDENCE, payload)
    if attack != "bytes":
        # Even a hash-consistent copied/rebound envelope must fail semantic checks.
        seal["files"][env.EVIDENCE] = env.sha(root/env.EVIDENCE); write_json(root/"run_seal.json",seal)
    result = read_sealed_evidence(root)
    assert result["integrity_status"] == "blocked" and not result.get("trend_environment")


def test_factory_sidecar_resolves_exact_sealed_input_and_caps_observation_window(tmp_path):
    source = fixture(tmp_path, "source"); source_seal = seal_run(source)
    trial = fixture(tmp_path, "trial")
    manifest = read_json(trial/"qlib_input/dataset_manifest.json")
    manifest.update(source_input_run_id="source", source_input_seal_sha256=digest(source_seal), factory_run_id="campaign")
    write_json(trial/"qlib_input/dataset_manifest.json", manifest)
    cutoff = "2026-01-09T00:00:00+00:00"
    write_json(trial/"factory_trial.json", {"segments":{"test":["2026-01-08T00:00:00+00:00", cutoff]}})
    assert env.build_sidecar(trial)["status"] == "completed"
    seal_run(trial)
    payload = read_sealed_evidence(trial)["trend_environment"]
    assert pd.Timestamp(payload["as_of"]) == pd.Timestamp(cutoff)
    assert payload["identity"]["factory_run_id"] == "campaign"
    write_json(source/"pipeline_result.json", {"run_id":"other"})
    assert read_sealed_evidence(trial)["integrity_status"] == "blocked"


def test_completed_run_never_rewritten(tmp_path):
    root = fixture(tmp_path); env.build_sidecar(root); seal_run(root)
    with pytest.raises(QlibAdapterError, match="immutable"): env.build_sidecar(root)
