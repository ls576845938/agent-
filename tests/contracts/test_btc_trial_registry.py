from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_trial_registry import build_btc_trial_registry, write_btc_trial_registry


SCHEMA = Path("schemas/btc_trial_registry.schema.json")


def test_btc_trial_registry_schema_valid() -> None:
    payload = build_btc_trial_registry(generated_at="2026-06-26T00:00:00Z")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)

    assert payload["schema_version"] == "btc_trial_registry_v1"
    assert payload["status"] == "complete"
    assert payload["blockers"] == []
    assert payload["trial_count"] == len(payload["trials"])
    assert payload["status_counts"]["selected"] >= 1
    assert payload["status_counts"]["rejected"] + payload["status_counts"]["failed"] >= 1
    assert payload["artifact_hash"]


def test_btc_trial_registry_tracks_selected_failed_and_rejected_trials() -> None:
    payload = build_btc_trial_registry(generated_at="2026-06-26T00:00:00Z")
    trials = payload["trials"]
    selected = [trial for trial in trials if trial["status"] == "selected"]
    rejected_or_failed = [trial for trial in trials if trial["status"] in {"rejected", "failed"}]

    assert selected
    assert rejected_or_failed
    assert any(
        trial["run_id"] == "20260620T000000Z_high_vol_non_expansion_trend_guard_eventledger"
        and trial["params_hash"] == "b75aeb196cc66488cd5495d66654d0a35023e011b3dd15de6d25aab36ea3981f"
        and trial["selected_by"] == "btc_intraday_short_cycle_paper_candidate_gate"
        for trial in selected
    )
    assert all(trial["run_id"] for trial in trials)
    assert all(trial["params_hash"] for trial in trials)
    assert all(trial["selected_by"] for trial in trials)
    assert all(trial["rejection_reason"] for trial in rejected_or_failed)
    assert any("event_profit_factor" in trial["rejection_reason"] for trial in rejected_or_failed)


def test_btc_trial_registry_writes_artifact(tmp_path: Path) -> None:
    payload = build_btc_trial_registry(generated_at="2026-06-26T00:00:00Z")
    output = tmp_path / "btc_trial_registry.json"

    written = write_btc_trial_registry(payload, output=output)

    assert Path(written).exists()
    loaded = json.loads(output.read_text(encoding="utf-8"))
    assert loaded["artifact_hash"] == payload["artifact_hash"]
    assert loaded["trial_count"] == payload["trial_count"]


def test_btc_trial_registry_blocks_without_sources(tmp_path: Path) -> None:
    payload = build_btc_trial_registry(repo_root=tmp_path, generated_at="2026-06-26T00:00:00Z")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    assert payload["status"] == "blocked"
    assert "btc_trial_registry_empty" in payload["blockers"]
    assert "btc_trial_registry_selected_trial_missing" in payload["blockers"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)
