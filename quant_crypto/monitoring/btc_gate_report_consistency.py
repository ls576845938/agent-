from __future__ import annotations

import json
import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_crypto.monitoring.artifact_schema import stable_payload_hash


SCHEMA_VERSION = "btc_gate_report_consistency_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_gate_report_consistency/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_gate_report_consistency_report.json"
DEFAULT_SUMMARY_CN_PATH = DEFAULT_OUTPUT_DIR / "btc_gate_report_consistency_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

DEFAULT_GATE_DASHBOARD_PATH = Path("artifacts/btc_gate_dashboard/latest/btc_gate_dashboard.json")
DEFAULT_PERPETUAL_EXECUTION_EVIDENCE_PATH = Path(
    "artifacts/btc_perpetual_execution_evidence/latest/btc_perpetual_execution_evidence_report.json"
)


def build_btc_gate_report_consistency(
    *,
    repo_root: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    gate_dashboard_path: Path = DEFAULT_GATE_DASHBOARD_PATH,
    perpetual_execution_evidence_path: Path = DEFAULT_PERPETUAL_EXECUTION_EVIDENCE_PATH,
    generated_at_utc: datetime | None = None,
    aggregation_batch_id: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    output = _resolve(root, output_dir)
    output.mkdir(parents=True, exist_ok=True)
    generated = (generated_at_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)

    dashboard_source = _read_json(_resolve(root, gate_dashboard_path))
    evidence_source = _read_json(_resolve(root, perpetual_execution_evidence_path))
    dashboard = dashboard_source["payload"]
    evidence = evidence_source["payload"]
    source_fingerprints = {
        "gate_dashboard": _source_fingerprint(gate_dashboard_path, dashboard_source),
        "perpetual_execution_evidence": _source_fingerprint(perpetual_execution_evidence_path, evidence_source),
    }
    dashboard_summary = _mapping(_mapping(dashboard.get("artifacts")).get("perpetual_execution_evidence"))
    dashboard_hash = str(dashboard_summary.get("artifact_hash") or "")
    expected_hash = _artifact_hash(evidence)

    checks = [
        _check(
            "dashboard_json_parseable",
            dashboard_source["exists"] and not dashboard_source["error"] and bool(dashboard),
            {
                "path": _portable_path(gate_dashboard_path),
                "error": dashboard_source["error"],
            },
        ),
        _check(
            "perpetual_execution_evidence_json_parseable",
            evidence_source["exists"] and not evidence_source["error"] and bool(evidence),
            {
                "path": _portable_path(perpetual_execution_evidence_path),
                "error": evidence_source["error"],
            },
        ),
        _check(
            "dashboard_perpetual_execution_evidence_summary_present",
            bool(dashboard_summary),
            {
                "dashboard_path": _portable_path(gate_dashboard_path),
                "artifact_summary_keys": sorted(str(key) for key in dashboard_summary.keys()),
            },
        ),
        _check(
            "dashboard_perpetual_execution_evidence_hash_matches_current_artifact",
            bool(dashboard_hash) and bool(expected_hash) and dashboard_hash == expected_hash,
            {
                "dashboard_path": _portable_path(gate_dashboard_path),
                "perpetual_execution_evidence_path": _portable_path(perpetual_execution_evidence_path),
                "dashboard_artifact_hash": dashboard_hash,
                "current_evidence_artifact_hash": expected_hash,
                "evidence_hash_source": "artifact_hash_field" if evidence.get("artifact_hash") else "stable_payload_hash",
                "dashboard_summary_status": dashboard_summary.get("status"),
                "evidence_status": evidence.get("status"),
            },
        ),
    ]
    blockers = [
        f"btc_gate_report_consistency:{row['check_id']}"
        for row in checks
        if row["status"] != "pass"
    ]
    status = "pass" if not blockers else "blocked_research_only"
    report_path = output / DEFAULT_REPORT_PATH.name
    summary_path = output / DEFAULT_SUMMARY_CN_PATH.name
    safety_path = output / DEFAULT_SAFETY_PATH.name
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "aggregation_batch_id": aggregation_batch_id or "",
        "code_commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "status": status,
        "decision": (
            "btc_gate_report_consistency_passed_research_only_no_paper_no_live"
            if status == "pass"
            else "btc_gate_report_consistency_blocked_fail_closed_no_paper_no_live"
        ),
        "scope": "read_only_dashboard_source_artifact_consistency_no_paper_no_live",
        "inputs": {
            "gate_dashboard": _portable_path(gate_dashboard_path),
            "perpetual_execution_evidence": _portable_path(perpetual_execution_evidence_path),
        },
        "source_fingerprints": source_fingerprints,
        "checks": checks,
        "summary": {
            "pass_count": sum(1 for row in checks if row["status"] == "pass"),
            "fail_count": sum(1 for row in checks if row["status"] != "pass"),
            "dashboard_perpetual_execution_evidence_hash": dashboard_hash,
            "current_evidence_artifact_hash": expected_hash,
            "dashboard_hash_matches_current_evidence": dashboard_hash == expected_hash if dashboard_hash and expected_hash else False,
            "source_fingerprint_count": len(source_fingerprints),
        },
        "gate": _gate(),
        "guardrails": _guardrails(),
        "blockers": blockers,
        "outputs": {
            "json": _portable_path(report_path),
            "summary_cn": _portable_path(summary_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_text(summary_path, render_btc_gate_report_consistency_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_btc_gate_report_consistency_markdown(report: Mapping[str, Any]) -> str:
    summary = _mapping(report.get("summary"))
    lines = [
        "# BTC Gate Report Consistency",
        "",
        f"- status: `{report.get('status')}`",
        f"- decision: `{report.get('decision')}`",
        f"- pass_count: `{summary.get('pass_count')}`",
        f"- fail_count: `{summary.get('fail_count')}`",
        f"- dashboard hash: `{summary.get('dashboard_perpetual_execution_evidence_hash')}`",
        f"- current evidence hash: `{summary.get('current_evidence_artifact_hash')}`",
        f"- hash matches: `{summary.get('dashboard_hash_matches_current_evidence')}`",
        "",
        "## Checks",
        "",
    ]
    for row in _list_of_mappings(report.get("checks")):
        lines.append(f"- `{row.get('check_id')}`: `{row.get('status')}`")
    lines.extend(
        [
            "",
            "Boundary: this is an artifact consistency check only. It cannot write paper queues, unlock live, or connect to broker/order surfaces.",
        ]
    )
    return "\n".join(lines) + "\n"


def _check(check_id: str, passed: bool, details: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": "pass" if passed else "fail",
        "details": dict(details),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _artifact_hash(payload: Mapping[str, Any]) -> str:
    if not payload:
        return ""
    return str(payload.get("artifact_hash") or stable_payload_hash(payload))


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "payload": {}, "error": "missing"}
    stat = path.stat()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - fail-closed artifact boundary.
        return {
            "exists": True,
            "payload": {},
            "error": f"{type(exc).__name__}: {exc}",
            "file_mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "file_mtime_ns": stat.st_mtime_ns,
            "file_size_bytes": stat.st_size,
            "file_sha256": _file_sha256(path),
            "stable_hash": "",
        }
    payload_dict = payload if isinstance(payload, dict) else {}
    return {
        "exists": True,
        "payload": payload_dict,
        "error": "",
        "file_mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "file_mtime_ns": stat.st_mtime_ns,
        "file_size_bytes": stat.st_size,
        "file_sha256": _file_sha256(path),
        "stable_hash": stable_payload_hash(payload_dict) if payload_dict else "",
    }


def _source_fingerprint(path: Path, source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": _portable_path(path),
        "exists": source.get("exists") is True,
        "error": str(source.get("error") or ""),
        "file_mtime_utc": source.get("file_mtime_utc"),
        "file_mtime_ns": source.get("file_mtime_ns"),
        "file_size_bytes": source.get("file_size_bytes"),
        "file_sha256": source.get("file_sha256"),
        "stable_hash": source.get("stable_hash"),
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _portable_path(path: Path | str) -> str:
    return str(path).replace("\\", "/")


def _git(args: Sequence[str], *, cwd: Path) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, check=False, capture_output=True, text=True)
    except OSError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _gate() -> dict[str, bool]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_candidate_created": False,
        "paper_order_intake_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_or_order_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "order_endpoint_used": False,
        "private_endpoint_used": False,
        "real_order_submitted": False,
    }


def _guardrails() -> dict[str, bool]:
    return {
        "read_only_consistency_check": True,
        "does_not_modify_objective": True,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "broker_or_order_allowed": False,
        "order_endpoint_used": False,
        "private_endpoint_used": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_paper_live_safety_status_v1",
        "generated_at_utc": report.get("generated_at_utc"),
        "status": "research_only",
        "source_report": _mapping(report.get("outputs")).get("json"),
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_candidate_created": False,
        "paper_order_intake_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_or_order_allowed": False,
        "order_endpoint_used": False,
        "private_endpoint_used": False,
        "real_order_submitted": False,
        "blockers": list(report.get("blockers", [])),
    }
