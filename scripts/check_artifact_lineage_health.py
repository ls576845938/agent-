#!/usr/bin/env python3
"""Check artifact lineage health without changing promotion gates."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import jsonschema


DEFAULT_OUTPUT = Path("artifacts/artifact_health/latest/artifact_health_report.json")

DEFAULT_ARTIFACT_SPECS = [
    ("global_registry", "artifacts/global_research_registry/research_registry.json", "schemas/global_research_registry.schema.json", True),
    ("us_data_status", "artifacts/us_equity_data_status/latest/data_status_report.json", "schemas/us_equity_data_status_report.schema.json", True),
    ("provider_verification", "artifacts/us_equity_data_lineage/latest/provider_verification_report.json", "schemas/us_equity_provider_verification_report.schema.json", True),
    ("production_preflight", "artifacts/us_equity_data_lineage/latest/production_bundle_preflight_report.json", "schemas/us_equity_production_bundle_preflight_report.schema.json", True),
    ("factor_evidence", "artifacts/us_equity_factor_evidence/latest/factor_evidence_pack.json", "schemas/us_equity_factor_evidence_pack.schema.json", True),
    ("portfolio_canonical", "artifacts/us_equity_portfolio/latest/portfolio_canonical_report.json", "schemas/us_equity_portfolio_canonical_report.schema.json", True),
    ("portfolio_fixture_ledger", "artifacts/us_equity_portfolio_fixture_ledger/latest/portfolio_fixture_event_ledger_report.json", "schemas/us_equity_portfolio_fixture_event_ledger_report.schema.json", False),
    ("btc_registry", "artifacts/btc_research_registry/research_registry.json", "schemas/btc_research_registry.schema.json", True),
    ("btc_data_status", "artifacts/btc_data_status/latest/btc_data_status_report.json", "schemas/btc_data_status_report.schema.json", True),
    ("btc_provider_verification", "artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json", "schemas/btc_perpetual_provider_verification_report.schema.json", True),
    ("btc_public_metadata_capture_attempt", "artifacts/btc_data_status/latest/btc_public_metadata_capture_attempt_report.json", "schemas/btc_public_metadata_capture_attempt_report.schema.json", True),
    ("btc_manual_metadata_capture_readiness", "artifacts/btc_data_status/latest/btc_manual_metadata_capture_readiness_report.json", "schemas/btc_manual_metadata_capture_readiness_report.schema.json", True),
    ("btc_manual_metadata_capture_operator_packet", "artifacts/btc_data_status/latest/btc_manual_metadata_capture_operator_packet.json", "schemas/btc_manual_metadata_capture_operator_packet.schema.json", True),
    ("btc_manual_metadata_import_report", "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json", "schemas/btc_manual_metadata_import_report.schema.json", False),
    ("btc_objective_completion_audit", "artifacts/btc_data_status/latest/btc_objective_completion_audit_report.json", "schemas/btc_objective_completion_audit_report.schema.json", True),
    ("btc_funding_ledger", "artifacts/btc_cost_model/latest/btc_funding_ledger_report.json", "schemas/btc_funding_ledger_report.schema.json", True),
    ("btc_cost_model", "artifacts/btc_cost_model/latest/btc_cost_model_report.json", "schemas/btc_cost_model_contract.schema.json", True),
    ("btc_fold_regime", "artifacts/btc_fold_regime/latest/fold_regime_contract_report.json", "schemas/btc_fold_regime_contract.schema.json", True),
    ("btc_tail_dependency", "artifacts/btc_tail_dependency/latest/tail_dependency_report.json", "schemas/btc_tail_dependency_report.schema.json", True),
    ("btc_candidate_gate", "artifacts/btc_candidate_gate/latest/candidate_gate_audit_report.json", "schemas/btc_candidate_gate_audit_report.schema.json", True),
    ("btc_attribution", "artifacts/btc_candidate_attribution/latest_compression_expansion_attribution/attribution_report.json", "schemas/btc_compression_expansion_attribution_bundle.schema.json", True),
]


def build_artifact_lineage_health_report(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
    artifact_specs: list[tuple[str, str, str, bool]] | None = None,
    stale_after_hours: int = 168,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = _utc_z_timestamp(generated_at) if generated_at else _utc_z_now()
    specs = artifact_specs or DEFAULT_ARTIFACT_SPECS
    checked_artifacts: list[dict[str, Any]] = []
    missing: list[str] = []
    schema_invalid: list[dict[str, str]] = []
    stale: list[str] = []
    path_escape: list[str] = []
    hash_mismatch: list[str] = []
    now = _parse_time(generated) or datetime.now(timezone.utc)

    for name, artifact_ref, schema_ref, critical in specs:
        artifact_path = _resolve(root, artifact_ref)
        schema_path = _resolve(root, schema_ref)
        exists = artifact_path.exists()
        schema_valid = False
        generated_at_value: str | None = None
        blockers: list[str] = []
        if not exists:
            blockers.append("artifact_missing")
            if critical:
                missing.append(artifact_ref)
        else:
            payload = _read_json(artifact_path)
            generated_at_value = str(payload.get("generated_at") or "")
            schema_valid, schema_error = _schema_valid(payload, schema_path)
            if not schema_valid:
                blockers.append("schema_invalid")
                schema_invalid.append({"artifact": artifact_ref, "error": schema_error})
            for escaped in _path_escape_risks(payload, root):
                path_escape.append(f"{artifact_ref}:{escaped}")
            for mismatch in _hash_mismatches(payload):
                hash_mismatch.append(f"{artifact_ref}:{mismatch}")
            if generated_at_value and _is_stale(generated_at_value, now, stale_after_hours):
                blockers.append("artifact_stale")
                stale.append(artifact_ref)
        checked_artifacts.append(
            {
                "name": name,
                "path": artifact_ref,
                "schema": schema_ref,
                "critical": critical,
                "exists": exists,
                "schema_valid": schema_valid,
                "generated_at": generated_at_value,
                "blockers": blockers,
            }
        )

    blockers = []
    if missing:
        blockers.append("critical_artifact_missing")
    if schema_invalid:
        blockers.append("schema_invalid_artifact")
    if path_escape:
        blockers.append("path_escape_risk")
    if hash_mismatch:
        blockers.append("hash_mismatch_artifact")
    if stale:
        blockers.append("stale_artifact")
    health_status = "fail" if any([missing, schema_invalid, path_escape, hash_mismatch]) else ("warn" if stale else "pass")
    return {
        "schema_version": "artifact_health_report_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "checked_artifacts": checked_artifacts,
        "missing_artifacts": missing,
        "schema_invalid_artifacts": schema_invalid,
        "stale_artifacts": stale,
        "path_escape_risks": path_escape,
        "hash_mismatch_artifacts": hash_mismatch,
        "health_status": health_status,
        "promotion_safe": False,
        "blockers": blockers,
    }


def write_artifact_lineage_health_report(payload: Mapping[str, Any], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--stale-after-hours", type=int, default=168)
    args = parser.parse_args()
    payload = build_artifact_lineage_health_report(
        repo_root=Path(args.repo_root),
        generated_at=args.generated_at or None,
        stale_after_hours=args.stale_after_hours,
    )
    print(write_artifact_lineage_health_report(payload, Path(args.output)))


def _schema_valid(payload: Mapping[str, Any], schema_path: Path) -> tuple[bool, str]:
    if not schema_path.exists():
        return False, "schema_missing"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(dict(payload), schema)
        return True, ""
    except Exception as exc:
        return False, str(exc).splitlines()[0]


def _path_escape_risks(value: Any, root: Path) -> list[str]:
    risks: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(item, str) and _looks_path_key(str(key)):
                path = Path(item)
                if path.is_absolute():
                    try:
                        path.resolve().relative_to(root.resolve())
                    except ValueError:
                        risks.append(item)
                if ".." in path.parts:
                    risks.append(item)
            else:
                risks.extend(_path_escape_risks(item, root))
    elif isinstance(value, list):
        for item in value:
            risks.extend(_path_escape_risks(item, root))
    return risks


def _hash_mismatches(value: Any) -> list[str]:
    mismatches: list[str] = []
    if isinstance(value, Mapping):
        expected = value.get("sha256")
        actual = value.get("actual_sha256")
        if expected and actual and expected != actual:
            mismatches.append(str(value.get("path") or "unknown_path"))
        for item in value.values():
            mismatches.extend(_hash_mismatches(item))
    elif isinstance(value, list):
        for item in value:
            mismatches.extend(_hash_mismatches(item))
    return mismatches


def _looks_path_key(key: str) -> bool:
    return key.endswith("_path") or key.endswith("_report") or key.endswith("_manifest") or key in {"path", "source_run_dir"}


def _is_stale(generated_at: str, now: datetime, stale_after_hours: int) -> bool:
    parsed = _parse_time(generated_at)
    if parsed is None:
        return False
    age_hours = (now - parsed).total_seconds() / 3600.0
    return age_hours > stale_after_hours


def _parse_time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _utc_z_timestamp(value: str) -> str:
    parsed = _parse_time(value)
    if parsed is None:
        raise ValueError("generated_at must be an ISO-8601 timestamp")
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
