#!/usr/bin/env python3
"""Build a FRED macro data preflight report for the US equity system.

The preflight separates three states:
- macro data import is usable for research;
- the current shell/API-key setup may be incomplete;
- release/vintage evidence is still not production point-in-time clean.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SCHEMA_VERSION = "us_equity_fred_macro_preflight_report_v1"
DEFAULT_IMPORT_REPORT = Path("artifacts/us_equity_data_status/latest/fred_macro_import_report.json")
DEFAULT_FRESHNESS_REPORT = Path("artifacts/us_equity_data_status/latest/us_equity_data_freshness_daily_report.json")
DEFAULT_MACRO_LAG_REPORT = Path("artifacts/us_equity_data_lineage/latest/us_equity_macro_release_lag_policy_report.json")
DEFAULT_MACRO_CSV = Path("data/external/us_equity_macro/fred_macro.csv")
DEFAULT_OUTPUT = Path("artifacts/us_equity_data_status/latest/us_equity_fred_macro_preflight_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity FRED 宏观数据预检.md")
ALLOWED_STATUSES = {"fred_macro_preflight_pass", "fred_macro_preflight_warn", "fred_macro_preflight_blocked"}


def build_us_equity_fred_macro_preflight_report(
    *,
    repo_root: Path | None = None,
    import_report: Path = DEFAULT_IMPORT_REPORT,
    freshness_report: Path = DEFAULT_FRESHNESS_REPORT,
    macro_lag_report: Path = DEFAULT_MACRO_LAG_REPORT,
    macro_csv: Path = DEFAULT_MACRO_CSV,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
    api_key_env_var: str = "FRED_API_KEY",
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    import_path = _resolve(root, import_report)
    freshness_path = _resolve(root, freshness_report)
    macro_lag_path = _resolve(root, macro_lag_report)
    csv_path = _resolve(root, macro_csv)
    import_payload = _read_json(import_path)
    freshness = _read_json(freshness_path)
    macro_lag = _read_json(macro_lag_path)
    csv_profile = _csv_profile(csv_path)

    current_api_key_present = bool(os.environ.get(api_key_env_var, ""))
    import_guardrails = _mapping(import_payload.get("guardrails"))
    freshness_guardrails = _mapping(freshness.get("guardrails"))
    macro_lag_guardrails = _mapping(macro_lag.get("guardrails"))
    blockers: list[str] = []
    warnings: list[str] = []
    csv_usable = bool(csv_profile["exists"]) and int(csv_profile["row_count"]) > 0 and bool(csv_profile["latest_timestamp_utc"])

    if not import_payload:
        blockers.append("fred_macro_import_report_missing")
    elif str(import_payload.get("status", "")) != "pass":
        if csv_usable:
            warnings.append("fred_import_blocked_using_existing_macro_csv_snapshot")
            warnings.extend(_list_of_str(import_payload.get("blockers")) or ["fred_macro_import_not_pass"])
        else:
            blockers.extend(_list_of_str(import_payload.get("blockers")) or ["fred_macro_import_not_pass"])
    if not csv_usable:
        blockers.append("fred_macro_csv_missing_or_empty")
    if freshness and str(freshness.get("status", "")) != "pass":
        freshness_blockers = _list_of_str(freshness.get("blockers")) or ["us_equity_data_freshness_not_pass"]
        if csv_usable and set(freshness_blockers).issubset({"us_equity_freshness_fred_macro_data_missing"}):
            warnings.append("fred_freshness_blocked_using_existing_macro_csv_snapshot")
            warnings.extend(freshness_blockers)
        else:
            blockers.extend(freshness_blockers)
    if _unsafe_true({"import": import_payload, "freshness": freshness, "macro_lag": macro_lag}):
        blockers.append("fred_macro_preflight_unsafe_flag_detected")

    if not current_api_key_present:
        warnings.append("fred_api_key_missing_in_current_session")
    if import_guardrails.get("api_key_used_for_macro_data") is True and not current_api_key_present:
        warnings.append("previous_fred_import_used_api_key_but_current_session_key_missing")
    if not macro_lag:
        warnings.append("macro_release_lag_policy_report_missing")
    elif str(macro_lag.get("status", "")) == "research_lag_only_release_calendar_missing":
        warnings.extend(_list_of_str(macro_lag.get("blockers")))
    elif str(macro_lag.get("status", "")) == "blocked":
        blockers.extend(_list_of_str(macro_lag.get("blockers")) or ["macro_release_lag_policy_blocked"])

    status = "fred_macro_preflight_blocked" if blockers else ("fred_macro_preflight_warn" if warnings else "fred_macro_preflight_pass")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "provider": "FRED",
        "status": status,
        "allowed_statuses": sorted(ALLOWED_STATUSES),
        "decision": "repair_fred_macro_data_chain" if status == "fred_macro_preflight_blocked" else "research_macro_data_available_with_caveats",
        "current_session_api_key_present": current_api_key_present,
        "api_key_env_var": api_key_env_var,
        "api_key_value_recorded": False,
        "import_report": {
            "status": import_payload.get("status"),
            "source_type": import_payload.get("source_type"),
            "latest_common_date": import_payload.get("latest_common_date"),
            "api_key_used_for_macro_data": import_guardrails.get("api_key_used_for_macro_data"),
            "token_written_to_artifacts": import_guardrails.get("token_written_to_artifacts"),
            "series": import_payload.get("series", []),
            "latest_by_series": import_payload.get("latest_by_series", {}),
        },
        "freshness_report": {
            "status": freshness.get("status"),
            "macro_freshness_status": _nested(freshness, "macro_freshness.status"),
            "blockers": _list_of_str(freshness.get("blockers")),
        },
        "macro_release_lag": {
            "status": macro_lag.get("status"),
            "macro_lag_days": _nested(macro_lag, "policy.macro_lag_days"),
            "release_calendar_fields_present": _nested(macro_lag, "macro_source.release_calendar_fields_present"),
            "research_proxy_only": macro_lag_guardrails.get("research_lag_proxy_is_not_production_pit"),
        },
        "csv_profile": csv_profile,
        "warnings": _dedupe(warnings),
        "blockers": _dedupe(blockers),
        "guardrails": {
            "macro_preflight_only": True,
            "api_key_value_recorded": False,
            "token_written_to_artifacts": False,
            "research_macro_data_is_not_production_pit": macro_lag_guardrails.get("research_lag_proxy_is_not_production_pit") is True,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
            "freshness_gate_only": freshness_guardrails.get("freshness_gate_only"),
        },
        "source_files": {
            "import_report": _relpath(import_path, root),
            "freshness_report": _relpath(freshness_path, root),
            "macro_release_lag_report": _relpath(macro_lag_path, root),
            "macro_csv": _relpath(csv_path, root),
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    if payload["status"] not in ALLOWED_STATUSES:
        raise AssertionError(f"invalid status: {payload['status']}")
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _csv_profile(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "row_count": 0, "columns": [], "latest_timestamp_utc": None}
    frame = pd.read_csv(path)
    latest = None
    if "timestamp_utc" in frame.columns and not frame.empty:
        latest = str(frame["timestamp_utc"].dropna().iloc[-1]) if not frame["timestamp_utc"].dropna().empty else None
    return {"exists": True, "row_count": int(len(frame)), "columns": list(frame.columns), "latest_timestamp_utc": latest}


def _unsafe_true(payloads: Mapping[str, Mapping[str, Any]]) -> list[str]:
    unsafe = []
    unsafe_keys = {"live_order_allowed", "paper_simulation_allowed", "private_endpoint_used", "private_endpoint_allowed", "order_endpoint_used", "order_endpoint_allowed", "real_order_submitted", "token_written_to_artifacts"}
    for root_name, payload in payloads.items():
        for path, value in _walk(payload):
            if path.split(".")[-1] in unsafe_keys and value is True:
                unsafe.append(f"{root_name}.{path}=true")
    return unsafe


def _markdown(payload: Mapping[str, Any]) -> str:
    import_report = _mapping(payload.get("import_report"))
    macro_lag = _mapping(payload.get("macro_release_lag"))
    csv_profile = _mapping(payload.get("csv_profile"))
    lines = [
        "# US Equity FRED 宏观数据预检",
        "",
        f"- generated_at: `{payload.get('generated_at')}`",
        f"- status: `{payload.get('status')}`",
        f"- decision: `{payload.get('decision')}`",
        f"- current_session_api_key_present: `{payload.get('current_session_api_key_present')}`",
        f"- import_status: `{import_report.get('status')}`",
        f"- source_type: `{import_report.get('source_type')}`",
        f"- latest_common_date: `{import_report.get('latest_common_date')}`",
        f"- csv_rows: `{csv_profile.get('row_count')}`",
        f"- csv_latest_timestamp_utc: `{csv_profile.get('latest_timestamp_utc')}`",
        f"- macro_lag_status: `{macro_lag.get('status')}`",
        f"- release_calendar_fields_present: `{macro_lag.get('release_calendar_fields_present')}`",
        "",
        "## Warnings",
        "",
    ]
    warnings = _list_of_str(payload.get("warnings"))
    lines.extend([f"- `{item}`" for item in warnings] if warnings else ["- None"])
    lines.extend(["", "## Blockers", ""])
    blockers = _list_of_str(payload.get("blockers"))
    lines.extend([f"- `{item}`" for item in blockers] if blockers else ["- None"])
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- This report never records the FRED API key value.",
            "- FRED data may be research-usable while still missing release/vintage evidence for production PIT promotion.",
            "- This report cannot unlock paper simulation or live orders.",
            "",
        ]
    )
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else (root / path).resolve()


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _nested(payload: Mapping[str, Any], dotted: str, default: Any = None) -> Any:
    current: Any = payload
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def _walk(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.extend(_walk(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            out.extend(_walk(item, f"{prefix}.{index}"))
    else:
        out.append((prefix, value))
    return out


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git(args: list[str], *, cwd: Path) -> str | None:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, check=False, capture_output=True, text=True)
    except OSError:
        return None
    value = result.stdout.strip()
    return value or None


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--import-report", type=Path, default=DEFAULT_IMPORT_REPORT)
    parser.add_argument("--freshness-report", type=Path, default=DEFAULT_FRESHNESS_REPORT)
    parser.add_argument("--macro-lag-report", type=Path, default=DEFAULT_MACRO_LAG_REPORT)
    parser.add_argument("--macro-csv", type=Path, default=DEFAULT_MACRO_CSV)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--api-key-env-var", default="FRED_API_KEY")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_us_equity_fred_macro_preflight_report(
        repo_root=args.repo_root,
        import_report=args.import_report,
        freshness_report=args.freshness_report,
        macro_lag_report=args.macro_lag_report,
        macro_csv=args.macro_csv,
        output=args.output,
        markdown_output=args.markdown_output,
        api_key_env_var=args.api_key_env_var,
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if payload["status"] != "fred_macro_preflight_blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
