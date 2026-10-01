#!/usr/bin/env python3
"""Build a fail-closed remediation plan for US equity data lineage blockers."""

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


SCHEMA_VERSION = "us_equity_data_lineage_remediation_report_v1"
DEFAULT_DATA_STATUS = Path("artifacts/us_equity_data_status/latest/data_status_report.json")
DEFAULT_PROVIDER_VERIFICATION = Path("artifacts/us_equity_data_lineage/latest/provider_verification_report.json")
DEFAULT_PRODUCTION_PREFLIGHT = Path("artifacts/us_equity_data_lineage/latest/production_bundle_preflight_report.json")
DEFAULT_TIINGO_IMPORT = Path("artifacts/us_equity_data_status/latest/tiingo_eod_import_report.json")
DEFAULT_FRED_IMPORT = Path("artifacts/us_equity_data_status/latest/fred_macro_import_report.json")
DEFAULT_FRESHNESS = Path("artifacts/us_equity_data_status/latest/us_equity_data_freshness_daily_report.json")
DEFAULT_MACRO_RELEASE_LAG_POLICY = Path("artifacts/us_equity_data_lineage/latest/us_equity_macro_release_lag_policy_report.json")
DEFAULT_OUTPUT = Path("artifacts/us_equity_data_lineage/latest/us_equity_data_lineage_remediation_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 数据血缘修复计划.md")

REMEDIATION_CATALOG = {
    "point_in_time_universe": {
        "blockers": {
            "universe_snapshot_manifest_derived_only",
            "point_in_time_universe_not_confirmed",
            "membership_events_missing",
            "historical_membership_missing",
        },
        "accepted_evidence": [
            "Historical membership table with symbol, effective_start, effective_end, source, and as_of_date.",
            "Universe construction replay proving each rebalance only sees membership known on that date.",
            "Provider capability statement or local production bundle manifest naming the PIT membership source.",
        ],
    },
    "corporate_actions_and_adjustments": {
        "blockers": {
            "corporate_action_event_source_missing",
            "split_events_source_missing",
            "dividend_events_source_missing",
            "symbol_change_events_source_missing",
            "price_adjustment_reproducibility_missing",
            "adjustment_reproducibility_missing",
            "adjustment_mode_unknown",
        },
        "accepted_evidence": [
            "Split, dividend, and symbol-change event tables with event_date, ex_date, factor_or_amount, source, and capture timestamp.",
            "Raw-to-adjusted price reproducibility report for sampled symbols and known event windows.",
            "Explicit adjustment policy covering splits, cash dividends, special dividends, and ticker changes.",
        ],
    },
    "delisting_and_survivorship": {
        "blockers": {
            "delisting_coverage_missing",
            "survivorship_status_not_clean",
            "delisting_events_missing",
        },
        "accepted_evidence": [
            "Delisted symbol coverage with delisting date, last trade date, terminal return handling, and source.",
            "Survivorship audit comparing current constituents against historical tradable universe snapshots.",
            "Backtest replay showing delisted assets remain available before their delisting date and unavailable after it.",
        ],
    },
    "provider_and_identifier_lineage": {
        "blockers": {
            "selected_provider_not_promotion_clean_capable",
            "provider_capability_not_verification",
            "provider_required_tables_missing",
            "provider_required_fields_missing",
            "identifier_mapping_missing",
            "source_type_not_production",
            "promotion_clean_not_allowed",
            "local_csv_provider_disabled",
            "production_bundle_root_empty",
            "production_bundle_missing",
            "explicit_bundle_selection_missing",
            "production_bundle_preflight_failed",
            "provider_not_verified_for_promotion",
            "data_lineage_not_promotion_clean",
        },
        "accepted_evidence": [
            "Selected production provider or local bundle manifest with prices, identifiers, PIT membership, delistings, and corporate actions.",
            "Identifier mapping table covering ticker, permanent id, CUSIP/FIGI when available, and effective dates.",
            "Production bundle preflight report with explicit bundle root and promotion_clean=true only after all required tables pass.",
        ],
    },
    "macro_release_lag": {
        "blockers": {
            "macro_release_lag_policy_missing",
            "fred_release_calendar_missing",
            "macro_release_calendar_missing",
            "macro_release_lag_not_production_pit",
        },
        "accepted_evidence": [
            "FRED series observations plus explicit release lag or release-calendar policy.",
            "Production bundle macro_release_calendar.csv with series_id, observation period, release_date, available_time_utc, and source_record_id.",
            "Backtest macro feature builder using data available as of the rebalance date, not final revised future data.",
        ],
    },
}


def build_us_equity_data_lineage_remediation_report(
    *,
    repo_root: Path | None = None,
    data_status_path: Path = DEFAULT_DATA_STATUS,
    provider_verification_path: Path = DEFAULT_PROVIDER_VERIFICATION,
    production_preflight_path: Path = DEFAULT_PRODUCTION_PREFLIGHT,
    tiingo_import_path: Path = DEFAULT_TIINGO_IMPORT,
    fred_import_path: Path = DEFAULT_FRED_IMPORT,
    freshness_path: Path = DEFAULT_FRESHNESS,
    macro_release_lag_policy_path: Path = DEFAULT_MACRO_RELEASE_LAG_POLICY,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    data_status = _read_json(_resolve(root, data_status_path))
    provider = _read_json(_resolve(root, provider_verification_path))
    preflight = _read_json(_resolve(root, production_preflight_path))
    tiingo = _read_json(_resolve(root, tiingo_import_path))
    fred = _read_json(_resolve(root, fred_import_path))
    freshness = _read_json(_resolve(root, freshness_path))
    macro_release_lag_policy = _read_json(_resolve(root, macro_release_lag_policy_path))

    blockers = _dedupe(
        _list_of_str(data_status.get("blockers"))
        + _list_of_str(provider.get("blockers"))
        + _list_of_str(preflight.get("blockers"))
        + _list_of_str(macro_release_lag_policy.get("blockers"))
    )
    remediation_groups = _build_remediation_groups(blockers)
    current_evidence = _current_evidence(
        data_status=data_status,
        provider=provider,
        preflight=preflight,
        tiingo=tiingo,
        fred=fred,
        freshness=freshness,
        macro_release_lag_policy=macro_release_lag_policy,
    )
    promotion_clean = bool(_mapping(data_status.get("data_lineage_maturity")).get("promotion_clean"))
    status = "remediation_not_required" if promotion_clean and not blockers else "remediation_required"
    if not data_status:
        status = "blocked_missing_data_status"
        blockers = _dedupe(blockers + ["us_equity_data_status_report_missing"])

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": status,
        "asset": "us_equity",
        "data_status_report": _relpath(_resolve(root, data_status_path), root),
        "provider_verification_report": _relpath(_resolve(root, provider_verification_path), root),
        "production_bundle_preflight_report": _relpath(_resolve(root, production_preflight_path), root),
        "current_evidence": current_evidence,
        "data_lineage_maturity": _mapping(data_status.get("data_lineage_maturity")),
        "blockers": blockers,
        "remediation_groups": remediation_groups,
        "remediation_task_count": sum(len(group["matched_blockers"]) for group in remediation_groups),
        "next_actions": _next_actions(remediation_groups),
        "guardrails": {
            "remediation_report_is_not_data_fix": True,
            "promotion_clean_granted_by_this_report": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "do_not_infer_alpha_validity": True,
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _build_remediation_groups(blockers: list[str]) -> list[dict[str, Any]]:
    blocker_set = set(blockers)
    groups = []
    for group_id, definition in REMEDIATION_CATALOG.items():
        matched = sorted(blocker_set & set(definition["blockers"]))
        if not matched:
            continue
        groups.append(
            {
                "group_id": group_id,
                "status": "required",
                "matched_blockers": matched,
                "accepted_evidence": list(definition["accepted_evidence"]),
                "paper_or_live_unlock_allowed": False,
            }
        )
    return groups


def _current_evidence(
    *,
    data_status: Mapping[str, Any],
    provider: Mapping[str, Any],
    preflight: Mapping[str, Any],
    tiingo: Mapping[str, Any],
    fred: Mapping[str, Any],
    freshness: Mapping[str, Any],
    macro_release_lag_policy: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "data_status": data_status.get("status", "missing"),
        "selected_provider": provider.get("selected_provider") or provider.get("provider"),
        "provider_promotion_clean": bool(provider.get("promotion_clean", False)),
        "production_bundle_preflight_blockers": _list_of_str(preflight.get("blockers")),
        "tiingo_eod_status": tiingo.get("status", "missing"),
        "tiingo_source_type": tiingo.get("source_type"),
        "tiingo_symbol_count": tiingo.get("symbol_count") or _nested(tiingo, "summary.available_symbol_count"),
        "fred_macro_status": fred.get("status", "missing"),
        "fred_latest_common_date": fred.get("latest_common_date"),
        "fred_token_written_to_artifacts": bool(fred.get("token_written_to_artifacts", False)),
        "freshness_status": freshness.get("status", "missing"),
        "macro_release_lag_policy_status": macro_release_lag_policy.get("status", "missing"),
        "macro_lag_days": _nested(macro_release_lag_policy, "policy.macro_lag_days"),
        "macro_release_calendar_fields_present": _nested(
            macro_release_lag_policy,
            "macro_source.release_calendar_fields_present",
        ),
        "provider_macro_release_calendar_available": bool(provider.get("macro_release_calendar_available", False)),
        "price_data_available": bool(_mapping(data_status.get("data_lineage_maturity")).get("price_data_available")),
        "promotion_clean": bool(_mapping(data_status.get("data_lineage_maturity")).get("promotion_clean")),
    }


def _next_actions(groups: list[Mapping[str, Any]]) -> list[str]:
    order = [str(group.get("group_id")) for group in groups]
    actions = []
    if "provider_and_identifier_lineage" in order:
        actions.append("select_or_build_production_data_bundle_with_identifier_mapping")
    if "point_in_time_universe" in order:
        actions.append("ingest_point_in_time_membership_events")
    if "corporate_actions_and_adjustments" in order:
        actions.append("ingest_corporate_action_events_and_build_adjustment_reproducibility_report")
    if "delisting_and_survivorship" in order:
        actions.append("ingest_delisting_coverage_and_rebuild_survivorship_audit")
    if "macro_release_lag" in order:
        actions.append("ingest_macro_release_calendar_with_available_time_before_macro_promotion")
    actions.append("rerun_data_status_strategy_validation_and_production_line_after_evidence_is_present")
    return _dedupe(actions)


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity 数据血缘修复计划",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        "",
        f"- 状态：`{payload.get('status', '')}`",
        f"- 生产级 promotion clean：`{_mapping(payload.get('data_lineage_maturity')).get('promotion_clean', False)}`",
        f"- Tiingo EOD：`{_nested(payload, 'current_evidence.tiingo_eod_status')}`",
        f"- FRED macro：`{_nested(payload, 'current_evidence.fred_macro_status')}`",
        f"- 数据新鲜度：`{_nested(payload, 'current_evidence.freshness_status')}`",
        "",
        "## 结论",
        "",
        "现有 Tiingo/FRED 证据可以支持研究和运行观察，但还不能证明美股系统达到生产级数据血缘。PIT 成分、退市覆盖、公司行动事件源、复权可复算和永久标识映射仍必须保持阻断。",
        "",
        "## 修复分组",
        "",
    ]
    for group in _list(payload.get("remediation_groups")):
        lines.extend(
            [
                f"### {group.get('group_id', '')}",
                "",
                "Blockers:",
            ]
        )
        lines.extend(f"- `{item}`" for item in _list_of_str(group.get("matched_blockers")))
        lines.extend(["", "可接受证据:"])
        lines.extend(f"- {item}" for item in _list_of_str(group.get("accepted_evidence")))
        lines.append("")
    lines.extend(["## 下一步", ""])
    lines.extend(f"- `{item}`" for item in _list_of_str(payload.get("next_actions")))
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- 本报告只是修复门禁和证据清单，不修复数据本身。",
            "- 本报告不能解锁 paper/live。",
            "- 任何真实下单仍保持禁止。",
        ]
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
    parser = argparse.ArgumentParser(description="Build US equity data lineage remediation report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--data-status-path", default=str(DEFAULT_DATA_STATUS))
    parser.add_argument("--provider-verification-path", default=str(DEFAULT_PROVIDER_VERIFICATION))
    parser.add_argument("--production-preflight-path", default=str(DEFAULT_PRODUCTION_PREFLIGHT))
    parser.add_argument("--tiingo-import-path", default=str(DEFAULT_TIINGO_IMPORT))
    parser.add_argument("--fred-import-path", default=str(DEFAULT_FRED_IMPORT))
    parser.add_argument("--freshness-path", default=str(DEFAULT_FRESHNESS))
    parser.add_argument("--macro-release-lag-policy-path", default=str(DEFAULT_MACRO_RELEASE_LAG_POLICY))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_equity_data_lineage_remediation_report(
        repo_root=Path(args.repo_root),
        data_status_path=Path(args.data_status_path),
        provider_verification_path=Path(args.provider_verification_path),
        production_preflight_path=Path(args.production_preflight_path),
        tiingo_import_path=Path(args.tiingo_import_path),
        fred_import_path=Path(args.fred_import_path),
        freshness_path=Path(args.freshness_path),
        macro_release_lag_policy_path=Path(args.macro_release_lag_policy_path),
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
