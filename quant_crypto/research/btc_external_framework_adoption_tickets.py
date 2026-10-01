from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_crypto.monitoring.artifact_schema import apply_btc_artifact_schema, stable_payload_hash


SCHEMA_VERSION = "btc_external_framework_adoption_tickets_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_external_framework_adoption_tickets/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_external_framework_adoption_tickets_report.json"
DEFAULT_TICKETS_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_external_framework_adoption_tickets.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_external_framework_adoption_tickets_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"


@dataclass(frozen=True)
class ReferenceRepo:
    framework_id: str
    display_name: str
    local_dir: str
    upstream_url: str
    license_id: str
    source_copy_policy: str
    current_commit: str
    exists: bool


def build_btc_external_framework_adoption_tickets(
    *,
    repo_root: Path = Path("."),
    external_references_root: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    generated = _ensure_utc(generated_at_utc or datetime.now(timezone.utc))
    external_root = _resolve_external_root(root, external_references_root)
    output = _resolve(root, output_dir)
    output.mkdir(parents=True, exist_ok=True)

    references = _reference_repos(external_root)
    local_coverage = _local_coverage(root)
    implementation_status = _implementation_status(root)
    tickets = _tickets(
        root=root,
        external_root=external_root,
        local_coverage=local_coverage,
        references=references,
        implementation_status=implementation_status,
    )
    blockers = _blockers(external_root, references)
    warnings = _warnings(references, local_coverage)
    safety = _safety_bits()
    report_path = output / DEFAULT_REPORT_PATH.name
    csv_path = output / DEFAULT_TICKETS_CSV_PATH.name
    markdown_path = output / DEFAULT_MARKDOWN_PATH.name
    safety_path = output / DEFAULT_SAFETY_PATH.name
    status = "complete_research_only" if not blockers else "blocked_research_only"
    decision = (
        "btc_external_framework_adoption_tickets_complete_read_only_no_paper_no_live"
        if not blockers
        else "btc_external_framework_adoption_tickets_blocked_read_only_no_paper_no_live"
    )
    source_hashes = _source_hashes(root=root, external_root=external_root, references=references)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "status": status,
        "scope": "external_framework_reference_to_internal_btc_engine_tickets_only",
        "external_references_root": _portable_path(external_root),
        "reference_repos": [repo.__dict__ for repo in references],
        "local_coverage": local_coverage,
        "implementation_status": implementation_status,
        "tickets": tickets,
        "ticket_count": len(tickets),
        "ticket_ids": [ticket["ticket_id"] for ticket in tickets],
        "adoption_policy": {
            "copy_third_party_source_into_agent": "allowed_only_after_license_and_provenance_review",
            "use_as_runtime_dependency_without_review": False,
            "allow_third_party_to_submit_orders": False,
            "allowed_use": "read_reference_design_or_copy_permissive_snippets_with_attribution_then_build_local_adapter_or_contract",
            "license_review_required_before_copying_code": True,
            "permissive_copy_allowed": ["Apache-2.0", "MIT"],
            "copyleft_core_copy_prohibited": ["GPL-3.0", "LGPL-3.0"],
            "copy_requirements": [
                "record upstream repo, commit, source path and license",
                "copy only minimal code needed for adapter/parser/metadata helpers",
                "keep broker/private/order endpoints disabled unless local gate later permits them",
                "add local tests proving fail-closed behavior and no paper/live unlock",
            ],
        },
        "gate": safety,
        "guardrails": safety,
        "outputs": {
            "json": _portable_path(report_path),
            "tickets_csv": _portable_path(csv_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    report = apply_btc_artifact_schema(
        payload,
        decision=decision,
        generated_at_utc=generated,
        as_of_utc=generated,
        blockers=blockers,
        warnings=warnings,
        input_hashes=source_hashes,
    )
    _write_json(report_path, report)
    _write_tickets_csv(csv_path, tickets)
    _write_text(markdown_path, render_btc_external_framework_adoption_tickets_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_btc_external_framework_adoption_tickets_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# BTC 外部开源框架借鉴票据",
        "",
        f"- 当前状态：`{report.get('status')}`",
        f"- 票据数量：`{report.get('ticket_count')}`",
        "- 边界：只读参考，不写 paper 队列，不解锁 live，不接 broker/order。",
        "- 原则：MIT/Apache 代码可在许可证和来源审计后复制适配；GPL/LGPL 只做设计参考或隔离依赖。",
        "",
        "## 票据",
        "",
        "| 优先级 | 票据 | 参考框架 | 采纳状态 | 当前本地覆盖 | 下一步 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for ticket in _list_of_mappings(report.get("tickets")):
        lines.append(
            "| {priority} | `{ticket_id}` | {frameworks} | `{implementation_status}` | {coverage} | {next_action} |".format(
                priority=ticket.get("priority", ""),
                ticket_id=ticket.get("ticket_id", ""),
                frameworks=", ".join(_list_of_strings(ticket.get("reference_frameworks"))),
                implementation_status=ticket.get("implementation_status", ""),
                coverage=ticket.get("current_local_coverage", ""),
                next_action=ticket.get("next_action", ""),
            )
        )
    lines.extend(
        [
            "",
            "## 禁止动作",
            "",
            "- 不未经许可证和来源审计复制第三方源码到 `agent-`。",
            "- 不让外部 bot 或 connector 直接拥有下单权。",
            "- 不绕过 Risk / OMS / Ledger / Promotion Gate。",
            "- 不把 diagnostic / fixture 当成 paper gate 证据。",
        ]
    )
    return "\n".join(lines) + "\n"


def _tickets(
    *,
    root: Path,
    external_root: Path,
    local_coverage: Mapping[str, Any],
    references: Sequence[ReferenceRepo],
    implementation_status: Mapping[str, Any],
) -> list[dict[str, Any]]:
    ref_map = {repo.framework_id: repo for repo in references}
    return [
        {
            "ticket_id": "btc_nautilus_oms_replay_field_audit",
            "priority": "P0",
            "title_cn": "用 NautilusTrader 对照 OMS / replay 字段审计",
            "reference_frameworks": ["NautilusTrader"],
            "reference_paths": [
                _portable_path(external_root / ref_map["nautilus_trader"].local_dir / "README.md"),
                _portable_path(external_root / ref_map["nautilus_trader"].local_dir / "nautilus_trader"),
            ],
            "local_modules": [
                "quant_crypto/oms/lifecycle.py",
                "quant_crypto/oms/paper_runtime_replay_session.py",
                "quant_crypto/research/btc_perpetual_paper_runtime_replay.py",
            ],
            "current_local_coverage": _coverage_state(
                local_coverage,
                [
                    "oms_partial_cancel_reject_reconcile",
                    "replay_mark_index_liquidation_risk_fields",
                    "replay_order_fill_ledgers",
                ],
            ),
            "implementation_status": _nested_status(
                implementation_status,
                "btc_nautilus_oms_replay_field_audit",
            ),
            "latest_artifact": _nested_path(
                implementation_status,
                "btc_nautilus_oms_replay_field_audit",
            ),
            "do_not_copy": True,
            "copy_allowed_after_review": False,
            "copy_policy": ref_map["nautilus_trader"].source_copy_policy,
            "license_id": ref_map["nautilus_trader"].license_id,
            "implementation_boundary": "只对照字段和事件语义，必要时在本地 OMS/replay 增加字段或测试。",
            "acceptance_criteria": [
                "列出 OrderIntent / lifecycle / fill / risk decision 与 Nautilus-style execution domain 的字段差距。",
                "确认 time-in-force、post-only、reduce-only、cancel-only、OCO/contingency 只作为字段或禁止项建模，不接真实下单。",
                "输出 gap matrix，不减少 promotion gate blocker，除非当前 observe-only gate evidence 真实满足。",
            ],
            "tests_required": [
                "OMS partial/cancel/reject/reconcile ledger contract",
                "runtime replay row must include mark/index/liquidation buffer/risk decision",
                "fixture capability cannot clear paper gate",
            ],
            "next_action": "剩余 reduce/cancel-only 与高级条件单继续保持诊断/禁止边界；不接交易所 private/order endpoint。",
        },
        {
            "ticket_id": "btc_freqtrade_style_leakage_cli",
            "priority": "P0",
            "title_cn": "借鉴 Freqtrade 的 lookahead / recursive 分析入口",
            "reference_frameworks": ["Freqtrade"],
            "reference_paths": [
                _portable_path(external_root / ref_map["freqtrade"].local_dir / "README.md"),
                _portable_path(external_root / ref_map["freqtrade"].local_dir / "freqtrade"),
            ],
            "local_modules": [
                "quant_crypto/research/btc_strategy_leakage_overfit_audit.py",
                "quant_crypto/research/btc_strategy_bar_replay_visibility.py",
                "scripts/research/build_btc_strategy_leakage_overfit_audit.py",
            ],
            "current_local_coverage": _coverage_state(
                local_coverage,
                ["leakage_audit_module_exists", "bar_replay_visibility_module_exists"],
            ),
            "implementation_status": _nested_status(
                implementation_status,
                "btc_freqtrade_style_leakage_cli",
            ),
            "latest_artifact": _nested_path(
                implementation_status,
                "btc_freqtrade_style_leakage_cli",
            ),
            "do_not_copy": True,
            "copy_allowed_after_review": False,
            "copy_policy": ref_map["freqtrade"].source_copy_policy,
            "license_id": ref_map["freqtrade"].license_id,
            "implementation_boundary": "只统一本地 leakage/overfit 检查命令体验，不复用 Freqtrade 策略运行器。",
            "acceptance_criteria": [
                "新增或整理一个 BTC leakage check CLI，统一输出 future-function、same-bar、future sentiment、parameter-mining 检查。",
                "报告显式区分规则策略、GA、TimesFM、attack sleeve 的可见性边界。",
                "任何审计通过都不能自动打开 paper/live。",
            ],
            "tests_required": [
                "future sentiment available_time > decision_time counted as violation",
                "current raw signal only affects next tradable bar",
                "high-octane same-bar proxy remains research-only blocker",
            ],
            "next_action": "保持为操作员可读入口；新增策略线时同步纳入 lookahead/recursive 清单。",
        },
        {
            "ticket_id": "btc_hummingbot_ccxt_okx_metadata_runtime_probe",
            "priority": "P0",
            "title_cn": "借鉴 Hummingbot / CCXT 核对 OKX 永续 metadata 与 public runtime",
            "reference_frameworks": ["Hummingbot", "CCXT"],
            "reference_paths": [
                _portable_path(external_root / ref_map["hummingbot"].local_dir / "README.md"),
                _portable_path(external_root / ref_map["ccxt"].local_dir / "README.md"),
            ],
            "local_modules": [
                "quant_crypto/exchange/runtime.py",
                "scripts/build_btc_exchange_public_runtime_dry_probe.py",
                "scripts/build_btc_exchange_runtime_contract.py",
            ],
            "current_local_coverage": _coverage_state(
                local_coverage,
                ["exchange_runtime_file_exists", "public_runtime_dry_probe_exists", "exchange_runtime_contract_exists"],
            ),
            "implementation_status": _nested_status(
                implementation_status,
                "btc_hummingbot_ccxt_okx_metadata_runtime_probe",
            ),
            "latest_artifact": _nested_path(
                implementation_status,
                "btc_hummingbot_ccxt_okx_metadata_runtime_probe",
            ),
            "do_not_copy": False,
            "copy_allowed_after_review": True,
            "copy_policy": "Apache-2.0/MIT helpers may be copied after provenance review; private/order surfaces remain prohibited",
            "license_id": "Apache-2.0 + MIT",
            "implementation_boundary": "可复制 Hummingbot/CCXT 的少量 public metadata、symbol rule、rate-limit helper 思路或代码片段；不读取或输出真实 key，不接 private/order。",
            "acceptance_criteria": [
                "OKX perpetual symbol rules、tick size、lot size、min notional、contract size、rate limit 均进入 public runtime preflight。",
                "server time offset、metadata version、WS sequence/gapfill、rate-limit budget 有可读解释。",
                "private/order endpoint 继续 disabled，paper/live/order 标志全 false。",
            ],
            "tests_required": [
                "public runtime probe never imports broker/private/order modules",
                "missing metadata fails closed with exact blocker",
                "rate-limit budget and server time offset recorded in report",
            ],
            "next_action": "public metadata/runtime 已本地适配；后续只在许可证和来源审计后复制小片段。",
        },
    ]


def _implementation_status(root: Path) -> dict[str, Any]:
    nautilus_path = root / "artifacts/btc_nautilus_oms_replay_field_audit/latest/btc_nautilus_oms_replay_field_audit_report.json"
    freqtrade_path = root / "artifacts/btc_freqtrade_style_leakage_cli/latest/btc_freqtrade_style_leakage_cli_report.json"
    runtime_path = root / "artifacts/btc_exchange_runtime/latest/btc_exchange_public_runtime_dry_probe_report.json"
    nautilus = _read_json(nautilus_path)
    freqtrade = _read_json(freqtrade_path)
    runtime = _read_json(runtime_path)
    nautilus_summary = _mapping(nautilus.get("summary"))
    freqtrade_summary = _mapping(freqtrade.get("summary"))
    runtime_metadata = _mapping(runtime.get("normalized_market_metadata_contract"))
    return {
        "btc_nautilus_oms_replay_field_audit": {
            "status": (
                "implemented_with_deliberate_boundaries"
                if nautilus.get("status") == "complete_research_only"
                and _int(nautilus_summary.get("missing_count")) == 0
                else ("pending_or_stale_artifact" if not nautilus else "needs_followup")
            ),
            "artifact_path": _portable_path(nautilus_path),
            "artifact_decision": nautilus.get("decision"),
            "covered_count": _int(nautilus_summary.get("covered_count")),
            "partial_count": _int(nautilus_summary.get("partial_count")),
            "missing_count": _int(nautilus_summary.get("missing_count")),
            "diagnostic_or_prohibited_count": _int(nautilus_summary.get("diagnostic_or_prohibited_count")),
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        },
        "btc_freqtrade_style_leakage_cli": {
            "status": (
                "implemented_research_only_with_warnings"
                if freqtrade.get("status") == "complete_research_only"
                and _int(freqtrade_summary.get("fail_count")) == 0
                else ("pending_or_stale_artifact" if not freqtrade else "needs_followup")
            ),
            "artifact_path": _portable_path(freqtrade_path),
            "artifact_decision": freqtrade.get("decision"),
            "check_count": _int(freqtrade_summary.get("check_count")),
            "fail_count": _int(freqtrade_summary.get("fail_count")),
            "warn_count": _int(freqtrade_summary.get("warn_count")),
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        },
        "btc_hummingbot_ccxt_okx_metadata_runtime_probe": {
            "status": (
                "implemented_public_runtime_verified"
                if runtime.get("status") == "verified_research_only"
                and runtime_metadata.get("contract_valid") is True
                else ("pending_or_stale_artifact" if not runtime else "needs_followup")
            ),
            "artifact_path": _portable_path(runtime_path),
            "artifact_decision": runtime.get("decision"),
            "runtime_layer_status": _mapping(runtime.get("runtime_layer")).get("status"),
            "normalized_market_metadata_contract_valid": runtime_metadata.get("contract_valid") is True,
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        },
    }


def _local_coverage(root: Path) -> dict[str, Any]:
    lifecycle = _read_text(root / "quant_crypto/oms/lifecycle.py")
    replay = _read_text(root / "quant_crypto/research/btc_perpetual_paper_runtime_replay.py")
    runtime = _read_text(root / "quant_crypto/exchange/runtime.py")
    return {
        "oms_partial_cancel_reject_reconcile": all(
            token in lifecycle
            for token in ["PARTIALLY_FILLED", "CANCEL_REQUESTED", "REJECTED", "EXPIRED", "RECONCILED"]
        ),
        "replay_mark_index_liquidation_risk_fields": all(
            token in replay for token in ["mark_price", "index_price", "liquidation_buffer_bps", "risk_decision"]
        ),
        "replay_order_fill_ledgers": all(token in replay for token in ["order_ledger", "fill_ledger"]),
        "leakage_audit_module_exists": (root / "quant_crypto/research/btc_strategy_leakage_overfit_audit.py").exists(),
        "bar_replay_visibility_module_exists": (
            root / "quant_crypto/research/btc_strategy_bar_replay_visibility.py"
        ).exists(),
        "exchange_runtime_file_exists": bool(runtime),
        "public_runtime_dry_probe_exists": (root / "scripts/build_btc_exchange_public_runtime_dry_probe.py").exists(),
        "exchange_runtime_contract_exists": (root / "scripts/build_btc_exchange_runtime_contract.py").exists(),
        "exchange_runtime_public_probe_tokens": {
            "server_time": "server_time" in runtime or "server time" in runtime.lower(),
            "ws_gapfill": "gapfill" in runtime.lower() or "gap" in runtime.lower(),
            "rate_limit": "rate" in runtime.lower() and "limit" in runtime.lower(),
            "metadata": "metadata" in runtime.lower(),
        },
    }


def _reference_repos(external_root: Path) -> list[ReferenceRepo]:
    specs = [
        (
            "nautilus_trader",
            "NautilusTrader",
            "nautilus_trader",
            "https://github.com/nautechsystems/nautilus_trader.git",
            "LGPL-3.0",
            "design_reference_or_dependency_only_no_core_source_copy",
        ),
        (
            "freqtrade",
            "Freqtrade",
            "freqtrade",
            "https://github.com/freqtrade/freqtrade.git",
            "GPL-3.0",
            "design_reference_only_no_core_source_copy",
        ),
        (
            "hummingbot",
            "Hummingbot",
            "hummingbot",
            "https://github.com/hummingbot/hummingbot.git",
            "Apache-2.0",
            "selected_source_copy_allowed_after_provenance_review",
        ),
        (
            "ccxt",
            "CCXT",
            "ccxt",
            "https://github.com/ccxt/ccxt.git",
            "MIT",
            "selected_source_copy_allowed_after_provenance_review",
        ),
    ]
    repos: list[ReferenceRepo] = []
    for framework_id, display_name, local_dir, upstream_url, license_id, source_copy_policy in specs:
        path = external_root / local_dir
        repos.append(
            ReferenceRepo(
                framework_id=framework_id,
                display_name=display_name,
                local_dir=local_dir,
                upstream_url=upstream_url,
                license_id=license_id,
                source_copy_policy=source_copy_policy,
                current_commit=_git_head_short(path),
                exists=path.exists(),
            )
        )
    return repos


def _resolve_external_root(root: Path, external_references_root: Path | None) -> Path:
    if external_references_root is not None:
        return _resolve(root, external_references_root)
    sibling = root.parent / "external_references"
    if sibling.exists():
        return sibling.resolve()
    return (root / "external_references").resolve()


def _blockers(external_root: Path, references: Sequence[ReferenceRepo]) -> list[str]:
    blockers: list[str] = []
    if not external_root.exists():
        blockers.append("external_references_root_missing")
    if not any(repo.exists for repo in references):
        blockers.append("external_reference_repos_all_missing")
    return blockers


def _warnings(references: Sequence[ReferenceRepo], local_coverage: Mapping[str, Any]) -> list[str]:
    warnings = [f"external_reference_repo_missing:{repo.framework_id}" for repo in references if not repo.exists]
    if not all(bool(value) for key, value in local_coverage.items() if key != "exchange_runtime_public_probe_tokens"):
        warnings.append("some_local_coverage_checks_false_review_ticket_details")
    return _dedupe(warnings)


def _source_hashes(*, root: Path, external_root: Path, references: Sequence[ReferenceRepo]) -> dict[str, str]:
    values: dict[str, str] = {
        "external_framework_reuse_notes": _file_hash(external_root / "btc_framework_reuse_notes.md"),
        "local_lifecycle_py": _file_hash(root / "quant_crypto/oms/lifecycle.py"),
        "local_runtime_replay_py": _file_hash(root / "quant_crypto/research/btc_perpetual_paper_runtime_replay.py"),
        "local_exchange_runtime_py": _file_hash(root / "quant_crypto/exchange/runtime.py"),
    }
    values.update({f"reference_commit:{repo.framework_id}": repo.current_commit for repo in references})
    return values


def _coverage_state(local_coverage: Mapping[str, Any], keys: Sequence[str]) -> str:
    passed = [key for key in keys if bool(local_coverage.get(key))]
    if len(passed) == len(keys):
        return "baseline_exists_needs_external_field_gap_review"
    if passed:
        return "partial_baseline_exists_needs_missing_local_contracts"
    return "missing_local_baseline"


def _git_head_short(repo_path: Path) -> str:
    head_path = repo_path / ".git" / "HEAD"
    try:
        head = head_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if head.startswith("ref:"):
        ref = head.split("ref:", 1)[1].strip()
        try:
            return (repo_path / ".git" / ref).read_text(encoding="utf-8").strip()[:7]
        except OSError:
            return ""
    return head[:7]


def _safety_bits() -> dict[str, bool]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "live_unlock_allowed": False,
        "broker_or_order_allowed": False,
        "private_endpoint_allowed": False,
        "third_party_runtime_dependency_added": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    gate = dict(_mapping(report.get("gate")))
    return {
        "status": "research_only_no_paper_no_live",
        "decision": report.get("decision"),
        **gate,
        "artifact_hash": report.get("artifact_hash"),
    }


def _write_tickets_csv(path: Path, tickets: Sequence[Mapping[str, Any]]) -> None:
    fields = [
        "ticket_id",
        "priority",
        "title_cn",
        "reference_frameworks",
        "implementation_status",
        "latest_artifact",
        "current_local_coverage",
        "next_action",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for ticket in tickets:
            writer.writerow(
                {
                    "ticket_id": ticket.get("ticket_id", ""),
                    "priority": ticket.get("priority", ""),
                    "title_cn": ticket.get("title_cn", ""),
                    "reference_frameworks": ",".join(_list_of_strings(ticket.get("reference_frameworks"))),
                    "implementation_status": ticket.get("implementation_status", ""),
                    "latest_artifact": ticket.get("latest_artifact", ""),
                    "current_local_coverage": ticket.get("current_local_coverage", ""),
                    "next_action": ticket.get("next_action", ""),
                }
            )


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _file_hash(path: Path) -> str:
    if not path.exists():
        return ""
    return stable_payload_hash({"path": _portable_path(path), "content": _read_text(path)})


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _portable_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _nested_status(status: Mapping[str, Any], key: str) -> str:
    return str(_mapping(status.get(key)).get("status") or "pending_or_stale_artifact")


def _nested_path(status: Mapping[str, Any], key: str) -> str:
    return str(_mapping(status.get(key)).get("artifact_path") or "")


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _list_of_strings(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
