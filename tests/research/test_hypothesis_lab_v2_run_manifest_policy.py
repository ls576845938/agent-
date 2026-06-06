import json
import re
from pathlib import Path


RUN = Path("artifacts/btc_hypothesis/20260517T020000Z_hypothesis_lab_v2_lifecycle")
REGISTRY = Path("artifacts/btc_research_registry/research_registry.json")
UTC_Z_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def test_hypothesis_lab_v2_manifest_records_controlled_search_policy() -> None:
    manifest = json.loads((RUN / "run_manifest.json").read_text(encoding="utf-8"))

    assert manifest["controlled_search_policy"]["mode"] == "hypothesis_level_only"
    assert manifest["controlled_search_policy"]["strategy_skeleton_generation_allowed"] is False
    assert manifest["controlled_search_policy"]["candidate_generation_allowed"] is False
    assert manifest["controlled_search_policy"]["paper_or_live_side_effects_allowed"] is False
    assert manifest["allowed_output_level"] == "hypothesis"
    assert manifest["strategy_skeleton_generated"] is False
    assert manifest["strategy_skeleton_path"] == ""
    assert manifest["candidate_generated"] is False
    assert "strategy_skeleton" in manifest["forbidden_outputs"]
    assert "candidate_config" in manifest["forbidden_outputs"]
    assert "paper_order" in manifest["forbidden_outputs"]


def test_hypothesis_lab_v2_manifest_artifact_inventory_is_hypothesis_only() -> None:
    manifest = json.loads((RUN / "run_manifest.json").read_text(encoding="utf-8"))

    assert "hypothesis_decision_v2.json" in manifest["generated_artifacts"]
    assert "paper_live_safety_status.json" in manifest["generated_artifacts"]
    assert all("skeleton" not in item for item in manifest["generated_artifacts"])
    assert all("candidate_config" not in item for item in manifest["generated_artifacts"])


def test_hypothesis_lab_v2_manifest_generated_at_is_strict_utc_z() -> None:
    manifest = json.loads((RUN / "run_manifest.json").read_text(encoding="utf-8"))

    assert UTC_Z_PATTERN.match(manifest["generated_at"])
    assert "+00:00" not in manifest["generated_at"]


def test_hypothesis_lab_v2_preserves_authoritative_btc_registry_shape() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    assert UTC_Z_PATTERN.match(registry["generated_at"])
    assert "commit" in registry
    assert "branch" in registry
    assert "btc" in registry
    assert registry["items"]["compression_expansion_breakout"]["next_action"] == (
        "do_not_retest_without_new_hypothesis"
    )
