#!/usr/bin/env python3
"""Build the US equity FRED macro release-lag policy report."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant_us.research.us_etf_macro_momentum_rotation import (  # noqa: E402
    MACRO_COLUMNS,
    UsEtfMacroMomentumRotationConfig,
)


SCHEMA_VERSION = "us_equity_macro_release_lag_policy_report_v1"
DEFAULT_MACRO_PATH = Path("data/external/us_equity_macro/fred_macro.csv")
DEFAULT_FRED_IMPORT_REPORT = Path("artifacts/us_equity_data_status/latest/fred_macro_import_report.json")
DEFAULT_OUTPUT = Path("artifacts/us_equity_data_lineage/latest/us_equity_macro_release_lag_policy_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity FRED 宏观发布滞后策略.md")
RELEASE_DATE_FIELD_CANDIDATES = {"release_date", "publication_date", "available_at"}
VINTAGE_FIELD_CANDIDATES = {"realtime_start", "realtime_end", "vintage_date"}
RELEASE_FIELD_CANDIDATES = RELEASE_DATE_FIELD_CANDIDATES | VINTAGE_FIELD_CANDIDATES


def build_us_equity_macro_release_lag_policy_report(
    *,
    repo_root: Path | None = None,
    macro_path: Path = DEFAULT_MACRO_PATH,
    fred_import_report_path: Path = DEFAULT_FRED_IMPORT_REPORT,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    config: UsEtfMacroMomentumRotationConfig | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    cfg = config or UsEtfMacroMomentumRotationConfig()
    generated = generated_at or _utc_z_now()
    macro_abs = _resolve(root, macro_path)
    fred_import = _read_json(_resolve(root, fred_import_report_path))
    macro_summary = _macro_summary(macro_abs)
    source_checks = _source_checks(root)
    blockers: list[str] = []
    warnings: list[str] = []

    if not macro_summary["exists"]:
        blockers.append("fred_macro_data_missing")
    if macro_summary["missing_required_columns"]:
        blockers.append("fred_macro_required_columns_missing")
    if int(cfg.macro_lag_days) < 1:
        blockers.append("macro_lag_days_lt_1")
    if not source_checks["alpha_uses_cfg_macro_lag_shift"]:
        blockers.append("alpha_signal_macro_shift_not_detected")
    if not source_checks["research_uses_cfg_macro_lag_shift"]:
        blockers.append("research_macro_shift_not_detected")
    if not macro_summary["release_date_fields_present"]:
        blockers.extend(["fred_release_calendar_missing", "macro_release_lag_not_production_pit"])
    if not macro_summary["vintage_fields_present"]:
        blockers.append("macro_revision_vintage_missing")
    if not macro_summary["release_date_fields_present"] or not macro_summary["vintage_fields_present"]:
        warnings.append("research_lag_days_used_as_conservative_proxy")

    if blockers and set(blockers) <= {
        "fred_release_calendar_missing",
        "macro_revision_vintage_missing",
        "macro_release_lag_not_production_pit",
    }:
        status = "research_lag_only_release_calendar_missing"
    elif blockers:
        status = "blocked"
    else:
        status = "macro_release_lag_policy_ready_for_validation"

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": status,
        "asset": "us_equity",
        "macro_source": {
            "path": _relpath(macro_abs, root),
            **macro_summary,
        },
        "fred_import_report": {
            "path": _relpath(_resolve(root, fred_import_report_path), root),
            "status": fred_import.get("status"),
            "latest_common_date": fred_import.get("latest_common_date"),
            "token_written_to_artifacts": bool(fred_import.get("token_written_to_artifacts", False)),
        },
        "policy": {
            "macro_lag_days": int(cfg.macro_lag_days),
            "lag_policy_type": "calendar_row_shift",
            "research_interpretation": "Macro observations are shifted by macro_lag_days before signal use.",
            "production_requirement": "Replace the proxy with release-date or vintage-aware available_at timestamps before production promotion.",
            "required_release_fields": sorted(RELEASE_FIELD_CANDIDATES),
        },
        "source_checks": source_checks,
        "accepted_evidence_for_promotion": [
            "FRED release calendar or realtime/vintage columns for each macro series.",
            "Macro feature builder using available_at <= rebalance timestamp for every rebalance.",
            "Revision policy documenting whether final, first-release, or vintage values are used.",
            "No-live gate proving this report cannot unlock broker/private/order endpoints.",
        ],
        "blockers": _dedupe(blockers),
        "warnings": _dedupe(warnings),
        "guardrails": {
            "research_lag_proxy_is_not_production_pit": not (
                macro_summary["release_date_fields_present"] and macro_summary["vintage_fields_present"]
            ),
            "promotion_clean_granted_by_this_report": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _macro_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "exists": False,
            "row_count": 0,
            "columns": [],
            "required_columns": list(MACRO_COLUMNS),
            "missing_required_columns": list(MACRO_COLUMNS),
            "release_calendar_fields_present": False,
            "release_calendar_fields": [],
            "release_date_fields_present": False,
            "release_date_fields": [],
            "vintage_fields_present": False,
            "vintage_fields": [],
            "start_date": None,
            "end_date": None,
        }
    frame = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)
    columns = [str(column) for column in frame.columns]
    time_col = "timestamp_utc" if "timestamp_utc" in frame.columns else ("datetime" if "datetime" in frame.columns else columns[0])
    dates = pd.to_datetime(frame[time_col], utc=True, errors="coerce").dropna() if not frame.empty else pd.Series(dtype="datetime64[ns, UTC]")
    release_fields = sorted(set(columns) & RELEASE_FIELD_CANDIDATES)
    release_date_fields = sorted(set(columns) & RELEASE_DATE_FIELD_CANDIDATES)
    vintage_fields = sorted(set(columns) & VINTAGE_FIELD_CANDIDATES)
    missing = [column for column in MACRO_COLUMNS if column not in frame.columns]
    return {
        "exists": True,
        "row_count": int(len(frame)),
        "columns": columns,
        "required_columns": list(MACRO_COLUMNS),
        "missing_required_columns": missing,
        "release_calendar_fields_present": bool(release_date_fields and vintage_fields),
        "release_calendar_fields": release_fields,
        "release_date_fields_present": bool(release_date_fields),
        "release_date_fields": release_date_fields,
        "vintage_fields_present": bool(vintage_fields),
        "vintage_fields": vintage_fields,
        "start_date": str(dates.min().date()) if not dates.empty else None,
        "end_date": str(dates.max().date()) if not dates.empty else None,
    }


def _source_checks(root: Path) -> dict[str, Any]:
    alpha_path = root / "quant_us/signals/us_etf_rotation_alpha.py"
    research_path = root / "quant_us/research/us_etf_macro_momentum_rotation.py"
    if not alpha_path.exists():
        alpha_path = PROJECT_ROOT / "quant_us/signals/us_etf_rotation_alpha.py"
    if not research_path.exists():
        research_path = PROJECT_ROOT / "quant_us/research/us_etf_macro_momentum_rotation.py"
    alpha_text = alpha_path.read_text(encoding="utf-8") if alpha_path.exists() else ""
    research_text = research_path.read_text(encoding="utf-8") if research_path.exists() else ""
    needle = "macro.shift(cfg.macro_lag_days)"
    return {
        "alpha_signal_module": _relpath(alpha_path, root),
        "research_module": _relpath(research_path, root),
        "alpha_uses_cfg_macro_lag_shift": needle in alpha_text,
        "research_uses_cfg_macro_lag_shift": needle in research_text,
        "shift_expression": needle,
    }


def _markdown(payload: Mapping[str, Any]) -> str:
    macro_source = _mapping(payload.get("macro_source"))
    policy = _mapping(payload.get("policy"))
    lines = [
        "# US Equity FRED 宏观发布滞后策略",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        "",
        f"- 状态：`{payload.get('status', '')}`",
        f"- 宏观数据行数：`{macro_source.get('row_count', 0)}`",
        f"- 覆盖区间：`{macro_source.get('start_date')}` 到 `{macro_source.get('end_date')}`",
        f"- 研究滞后天数：`{policy.get('macro_lag_days')}`",
        f"- release/vintage 字段存在：`{macro_source.get('release_calendar_fields_present')}`",
        "",
        "## 判断",
        "",
        "当前策略代码已使用 `macro_lag_days` 做研究级保守滞后，但现有 FRED CSV 没有 release calendar 或 realtime/vintage 字段，因此不能证明宏观开关达到生产级 point-in-time。",
        "",
        "## Blockers",
        "",
    ]
    blockers = _list_of_str(payload.get("blockers"))
    lines.extend(f"- `{item}`" for item in blockers)
    if not blockers:
        lines.append("- 无")
    lines.extend(["", "## 晋级所需证据", ""])
    lines.extend(f"- {item}" for item in _list_of_str(payload.get("accepted_evidence_for_promotion")))
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(content + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _dedupe(items: list[str]) -> list[str]:
    out = []
    seen = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build US equity macro release-lag policy report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--macro-path", default=str(DEFAULT_MACRO_PATH))
    parser.add_argument("--fred-import-report-path", default=str(DEFAULT_FRED_IMPORT_REPORT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_equity_macro_release_lag_policy_report(
        repo_root=Path(args.repo_root),
        macro_path=Path(args.macro_path),
        fred_import_report_path=Path(args.fred_import_report_path),
        output=Path(args.output),
        markdown_output=Path(args.markdown_output),
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
