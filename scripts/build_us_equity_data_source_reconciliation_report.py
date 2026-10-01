#!/usr/bin/env python3
"""Reconcile US equity research data sources against the selected source."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SCHEMA_VERSION = "us_equity_data_source_reconciliation_report_v1"
DEFAULT_RESEARCH_REPORT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_macro_rotation_research_report.json")
DEFAULT_TIINGO_IMPORT = Path("artifacts/us_equity_data_status/latest/tiingo_eod_import_report.json")
DEFAULT_DATA_STATUS = Path("artifacts/us_equity_data_status/latest/data_status_report.json")
DEFAULT_EXTERNAL_QUALITY = Path("artifacts/us_equity_etf_macro_rotation/latest/external_etf_kline_quality_report.json")
DEFAULT_MACRO_RELEASE_LAG = Path("artifacts/us_equity_data_lineage/latest/us_equity_macro_release_lag_policy_report.json")
DEFAULT_OUTPUT = Path("artifacts/us_equity_data_status/latest/us_equity_data_source_reconciliation_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 数据源对账报告.md")


def build_us_equity_data_source_reconciliation_report(
    *,
    repo_root: Path | None = None,
    research_report_path: Path = DEFAULT_RESEARCH_REPORT,
    tiingo_import_path: Path = DEFAULT_TIINGO_IMPORT,
    data_status_path: Path = DEFAULT_DATA_STATUS,
    external_quality_path: Path = DEFAULT_EXTERNAL_QUALITY,
    macro_release_lag_path: Path = DEFAULT_MACRO_RELEASE_LAG,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    research = _read_json(_resolve(root, research_report_path))
    tiingo = _read_json(_resolve(root, tiingo_import_path))
    data_status = _read_json(_resolve(root, data_status_path))
    external_quality = _read_json(_resolve(root, external_quality_path))
    macro_lag = _read_json(_resolve(root, macro_release_lag_path))

    data = _mapping(research.get("data"))
    required_symbols = _list_of_str(data.get("required_symbols"))
    available_symbols = _list_of_str(data.get("available_symbols"))
    missing_symbols = sorted(set(required_symbols) - set(available_symbols))
    selected_source = str(data.get("price_source", "") or "")
    selected_coverage = _mapping(data.get("coverage"))
    tiingo_coverage = _mapping(data.get("tiingo_eod_coverage"))
    canonical_coverage = _mapping(data.get("canonical_cleaned_coverage"))
    external_coverage = _mapping(data.get("external_data_lake_coverage"))
    rows = _symbol_rows(required_symbols, selected_coverage, tiingo_coverage, canonical_coverage, external_coverage)

    blockers: list[str] = []
    warnings: list[str] = []
    if not research:
        blockers.append("us_equity_research_report_missing")
    if selected_source != "tiingo_eod":
        warnings.append("us_equity_selected_price_source_not_tiingo_eod")
    if tiingo.get("status") != "pass":
        blockers.append("us_equity_tiingo_import_not_pass")
    if missing_symbols:
        blockers.append("us_equity_selected_source_missing_required_symbols")
    stale_mismatches = _latest_date_mismatches(rows)
    if stale_mismatches:
        warnings.append("us_equity_source_latest_date_mismatch")
    if not bool(data_status.get("promotion_clean", False)):
        blockers.append("us_equity_data_lineage_not_promotion_clean")
    if macro_lag and str(macro_lag.get("status", "")) == "blocked":
        blockers.append("us_equity_macro_release_lag_policy_blocked")

    reconciled = bool(research) and tiingo.get("status") == "pass" and not missing_symbols
    if blockers:
        status = "research_reconciled_promotion_blocked" if reconciled else "blocked"
    else:
        status = "pass"

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": status,
        "asset": "us_equity",
        "selected_price_source": selected_source,
        "selected_price_root": data.get("price_root"),
        "research_report": _relpath(_resolve(root, research_report_path), root),
        "tiingo_import_report": _relpath(_resolve(root, tiingo_import_path), root),
        "data_status_report": _relpath(_resolve(root, data_status_path), root),
        "external_quality_report": _relpath(_resolve(root, external_quality_path), root),
        "macro_release_lag_report": _relpath(_resolve(root, macro_release_lag_path), root),
        "summary": {
            "required_symbol_count": len(required_symbols),
            "available_symbol_count": len(available_symbols),
            "missing_symbols": missing_symbols,
            "tiingo_import_status": tiingo.get("status"),
            "tiingo_latest_common_date": _nested(tiingo, "summary.latest_common_date"),
            "research_price_source": selected_source,
            "research_status": research.get("status"),
            "data_status": data_status.get("status"),
            "data_promotion_clean": bool(data_status.get("promotion_clean", False)),
            "external_quality_status": external_quality.get("status"),
            "macro_release_lag_status": macro_lag.get("status"),
        },
        "symbol_reconciliation": rows,
        "latest_date_mismatches": stale_mismatches,
        "blockers": _dedupe(blockers),
        "warnings": _dedupe(warnings),
        "guardrails": {
            "reconciliation_report_is_not_production_clean_evidence": True,
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


def _symbol_rows(
    symbols: list[str],
    selected: Mapping[str, Any],
    tiingo: Mapping[str, Any],
    canonical: Mapping[str, Any],
    external: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows = []
    for symbol in symbols:
        selected_row = _mapping(selected.get(symbol))
        tiingo_row = _mapping(tiingo.get(symbol))
        canonical_row = _mapping(canonical.get(symbol))
        external_row = _mapping(external.get(symbol))
        rows.append(
            {
                "symbol": symbol,
                "selected_status": selected_row.get("status", "missing"),
                "selected_start": selected_row.get("start"),
                "selected_end": selected_row.get("end"),
                "selected_rows": selected_row.get("rows"),
                "tiingo_status": tiingo_row.get("status", "missing"),
                "tiingo_start": tiingo_row.get("start"),
                "tiingo_end": tiingo_row.get("end"),
                "tiingo_rows": tiingo_row.get("rows"),
                "canonical_status": canonical_row.get("status", "missing"),
                "canonical_start": canonical_row.get("start"),
                "canonical_end": canonical_row.get("end"),
                "canonical_rows": canonical_row.get("rows"),
                "external_status": external_row.get("status", "missing"),
                "external_start": external_row.get("start"),
                "external_end": external_row.get("end"),
                "external_rows": external_row.get("rows"),
            }
        )
    return rows


def _latest_date_mismatches(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    mismatches = []
    for row in rows:
        selected_end = row.get("selected_end")
        tiingo_end = row.get("tiingo_end")
        if selected_end and tiingo_end and selected_end != tiingo_end:
            mismatches.append(
                {
                    "symbol": row.get("symbol"),
                    "selected_end": selected_end,
                    "tiingo_end": tiingo_end,
                    "reason": "selected_source_differs_from_tiingo_latest_date",
                }
            )
    return mismatches


def _markdown(payload: Mapping[str, Any]) -> str:
    summary = _mapping(payload.get("summary"))
    lines = [
        "# US Equity 数据源对账报告",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        "",
        f"- 状态：`{payload.get('status', '')}`",
        f"- 研究使用价格源：`{payload.get('selected_price_source', '')}`",
        f"- 必需标的数：`{summary.get('required_symbol_count', 0)}`",
        f"- 可用标的数：`{summary.get('available_symbol_count', 0)}`",
        f"- Tiingo 最新共同日期：`{summary.get('tiingo_latest_common_date')}`",
        f"- 数据 promotion clean：`{summary.get('data_promotion_clean')}`",
        "",
        "## 结论",
        "",
        "本报告只证明研究运行使用的数据源与导入覆盖可对账；它不证明 PIT 成分、退市覆盖、公司行动和复权可复算已经生产级通过。",
        "",
        "## Blockers",
        "",
    ]
    blockers = _list_of_str(payload.get("blockers"))
    lines.extend(f"- `{item}`" for item in blockers)
    if not blockers:
        lines.append("- 无")
    lines.extend(["", "## Symbol Snapshot", "", "| symbol | selected | selected_end | tiingo_end | canonical | external_end |", "| --- | --- | --- | --- | --- | --- |"])
    for row in _list(payload.get("symbol_reconciliation"))[:30]:
        if not isinstance(row, Mapping):
            continue
        lines.append(
            f"| `{row.get('symbol')}` | `{row.get('selected_status')}` | `{row.get('selected_end')}` | `{row.get('tiingo_end')}` | `{row.get('canonical_status')}` | `{row.get('external_end')}` |"
        )
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


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _nested(payload: Mapping[str, Any], dotted: str, default: Any = None) -> Any:
    current: Any = payload
    for key in dotted.split("."):
        if not isinstance(current, Mapping):
            return default
        current = current.get(key)
    return current if current is not None else default


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
    parser = argparse.ArgumentParser(description="Build US equity data source reconciliation report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--research-report-path", default=str(DEFAULT_RESEARCH_REPORT))
    parser.add_argument("--tiingo-import-path", default=str(DEFAULT_TIINGO_IMPORT))
    parser.add_argument("--data-status-path", default=str(DEFAULT_DATA_STATUS))
    parser.add_argument("--external-quality-path", default=str(DEFAULT_EXTERNAL_QUALITY))
    parser.add_argument("--macro-release-lag-path", default=str(DEFAULT_MACRO_RELEASE_LAG))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_equity_data_source_reconciliation_report(
        repo_root=Path(args.repo_root),
        research_report_path=Path(args.research_report_path),
        tiingo_import_path=Path(args.tiingo_import_path),
        data_status_path=Path(args.data_status_path),
        external_quality_path=Path(args.external_quality_path),
        macro_release_lag_path=Path(args.macro_release_lag_path),
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
