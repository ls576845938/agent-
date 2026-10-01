"""Explicit one-writer publication; never called by a backend GET."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.app.services.strategy_parameter_evidence import PARAMETER_POINTER, SCHEMA, project_parameter_evidence
from quant_crypto.adapters.btc_runtime_artifact_store import BTCRuntimeArtifactReader, BTCRuntimeArtifactWriter
from quant_crypto.application.btc_strategy_history import HISTORY_INDEX_PATH, HISTORY_POINTER_PATH, load_btc_strategy_history, load_btc_strategy_history_catalog


def publish(*, history_root: Path, grid_source: Path, expected_sha256: str, output_root: Path) -> dict:
    source = BTCRuntimeArtifactReader.from_environment(source_repo_root=REPO, environment={"QS_BTC_RUNTIME_ARTIFACT_ROOT": str(history_root)})
    catalog = load_btc_strategy_history_catalog(source)  # verify pointer, index, candidate set and report hashes before copying
    raw = grid_source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("parameter_source_hash_changed")
    report = json.loads(raw)
    payload = project_parameter_evidence(report, source_sha256=expected_sha256)
    rows_by_id = {row["candidate_id"]: row for row in payload["rows"]}
    for candidate in catalog["candidates"]:
        if candidate["strategy_id"] != "long_short_donchian_top5":
            continue
        detail = load_btc_strategy_history(source, strategy_id=candidate["strategy_id"], candidate_id=candidate["candidate_id"])
        row = rows_by_id.get(candidate["candidate_id"])
        if row is None or row["params"] != detail["details"]["params"] or any(row["metrics"][key] != detail["details"]["full_metrics"].get(key) for key in row["metrics"]):
            raise ValueError("top5_and_grid_evidence_identity_or_metric_mismatch")
    source_commit = subprocess.check_output(["git", "rev-parse", "--verify", f"{report['code_commit']}^{{commit}}"], cwd=REPO, text=True).strip()
    payload["source"]["code_commit"] = source_commit
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    path = f"artifacts/strategy_parameter_map/runs/{digest}/evidence.json"
    writer = BTCRuntimeArtifactWriter.from_environment(source_repo_root=REPO, environment={"QS_BTC_RUNTIME_ARTIFACT_ROOT": str(output_root)})
    # Use a newly bootstrapped task-owned root. Never alter an existing publication.
    if any(child.name != '.qs_btc_runtime_artifact_root_owner.json' for child in output_root.iterdir()):
        raise ValueError("publication_root_not_empty")
    index_raw = source.read_bytes(HISTORY_INDEX_PATH)
    pointer_raw = source.read_bytes(HISTORY_POINTER_PATH)
    index = json.loads(index_raw)
    with writer.exclusive() as session:
        for entry in index["runs"]:
            data = source.read_bytes(entry["report_path"])
            if hashlib.sha256(data).hexdigest() != entry["source_sha256"]:
                raise ValueError("history_source_changed_during_publication")
            session.write_bytes_atomic(entry["report_path"], data)
        session.write_bytes_atomic(HISTORY_INDEX_PATH, index_raw)
        session.write_bytes_atomic(path, encoded)
        session.write_json_atomic(PARAMETER_POINTER, {"schema_version": SCHEMA, "path": path, "sha256": digest, "source_sha256": expected_sha256, "row_count": len(payload["rows"]), "scope": "historical_research_parameter_results"})
        session.write_bytes_atomic(HISTORY_POINTER_PATH, pointer_raw)
    # Read the published snapshot through the same fail-closed reader used by GET.
    from backend.app.services.strategy_parameter_evidence import load_parameter_evidence
    checked = load_parameter_evidence(writer, strategy_id="long_short_donchian_top5")
    restored_catalog = load_btc_strategy_history_catalog(writer)
    return {"status": "published_historical_research_only", "path": path, "sha256": digest, "source_sha256": expected_sha256, "rows": len(checked["rows"]), "history_candidates": len(restored_catalog["candidates"]), "safety": checked["safety"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-root", type=Path, required=True)
    parser.add_argument("--grid-source", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(publish(history_root=args.history_root, grid_source=args.grid_source, expected_sha256=args.expected_sha256, output_root=args.output_root), ensure_ascii=False, indent=2))
