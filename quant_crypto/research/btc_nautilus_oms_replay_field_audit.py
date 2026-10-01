from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_crypto.monitoring.artifact_schema import apply_btc_artifact_schema, stable_payload_hash


SCHEMA_VERSION = "btc_nautilus_oms_replay_field_audit_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_nautilus_oms_replay_field_audit/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_nautilus_oms_replay_field_audit_report.json"
DEFAULT_MATRIX_PATH = DEFAULT_OUTPUT_DIR / "btc_nautilus_oms_replay_field_audit_matrix.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_nautilus_oms_replay_field_audit_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"


@dataclass(frozen=True)
class SourceText:
    source_id: str
    path: Path
    text: str

    @property
    def exists(self) -> bool:
        return bool(self.text)


def build_btc_nautilus_oms_replay_field_audit(
    *,
    repo_root: Path = Path("."),
    external_references_root: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    external_root = _resolve_external_root(root, external_references_root)
    generated = _ensure_utc(generated_at_utc or datetime.now(timezone.utc))
    output = _resolve(root, output_dir)
    output.mkdir(parents=True, exist_ok=True)

    sources = _load_sources(root=root, external_root=external_root)
    matrix = _audit_matrix(sources)
    blockers = _blockers(sources)
    warnings = _warnings(matrix)
    safety = _safety_bits()
    status = "complete_research_only" if not blockers else "blocked_research_only"
    decision = (
        "btc_nautilus_oms_replay_field_audit_complete_read_only_no_paper_no_live"
        if not blockers
        else "btc_nautilus_oms_replay_field_audit_blocked_read_only_no_paper_no_live"
    )
    report_path = output / DEFAULT_REPORT_PATH.name
    matrix_path = output / DEFAULT_MATRIX_PATH.name
    markdown_path = output / DEFAULT_MARKDOWN_PATH.name
    safety_path = output / DEFAULT_SAFETY_PATH.name
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "status": status,
        "scope": "nautilus_style_oms_replay_field_gap_audit_read_only",
        "external_references_root": _portable_path(external_root),
        "nautilus_reference": {
            "local_path": _portable_path(external_root / "nautilus_trader"),
            "commit": _git_head_short(external_root / "nautilus_trader"),
            "concepts_used": [
                "deterministic_event_driven_runtime",
                "research_live_execution_semantics_parity",
                "adapter_normalized_domain_model",
                "advanced_order_types_and_execution_instructions",
                "multi_venue_multi_instrument_backtest_live_model",
            ],
            "source_copy_policy": "no_third_party_source_copied_into_agent",
        },
        "source_paths": {source_id: _portable_path(source.path) for source_id, source in sources.items()},
        "source_exists": {source_id: source.exists for source_id, source in sources.items()},
        "matrix": matrix,
        "summary": _summary(matrix),
        "required_followup_tickets": _followup_tickets(matrix),
        "adoption_boundary": {
            "copies_nautilus_source": False,
            "adds_nautilus_runtime_dependency": False,
            "changes_strategy_logic": False,
            "connects_private_or_order_endpoint": False,
            "reduces_promotion_gate_blockers": False,
            "purpose": "identify_local_oms_replay_field_gaps_before_implementation",
        },
        "gate": safety,
        "guardrails": safety,
        "outputs": {
            "json": _portable_path(report_path),
            "matrix_csv": _portable_path(matrix_path),
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
        input_hashes=_source_hashes(sources),
    )
    _write_json(report_path, report)
    _write_matrix_csv(matrix_path, matrix)
    _write_text(markdown_path, render_btc_nautilus_oms_replay_field_audit_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_btc_nautilus_oms_replay_field_audit_markdown(report: Mapping[str, Any]) -> str:
    summary = _mapping(report.get("summary"))
    lines = [
        "# BTC Nautilus 风格 OMS / Replay 字段审计",
        "",
        f"- 当前状态：`{report.get('status')}`",
        f"- 已覆盖：`{summary.get('covered_count')}`",
        f"- 部分覆盖：`{summary.get('partial_count')}`",
        f"- 缺口：`{summary.get('missing_count')}`",
        f"- 禁止/诊断项：`{summary.get('diagnostic_or_prohibited_count')}`",
        "- 边界：只读审计，不复制 NautilusTrader 源码，不接 private/order endpoint，不写 paper/live。",
        "",
        "## 关键缺口",
        "",
    ]
    gaps = [row for row in _list_of_mappings(report.get("matrix")) if row.get("status") in {"missing", "partial"}]
    if not gaps:
        lines.append("- 暂无字段缺口。")
    else:
        for row in gaps:
            lines.append(f"- `{row.get('concept_id')}`：{row.get('gap_cn')} 下一步：{row.get('recommended_action_cn')}")
    lines.extend(
        [
            "",
            "## 不允许误用",
            "",
            "- 本报告不能减少 promotion gate blocker。",
            "- fixture/drill 能力不能当作 current paper gate evidence。",
            "- 高级订单语义只能先建字段和测试，不能直接接实盘下单。",
        ]
    )
    return "\n".join(lines) + "\n"


def _audit_matrix(sources: Mapping[str, SourceText]) -> list[dict[str, Any]]:
    local = "\n".join(source.text for source_id, source in sources.items() if source_id != "nautilus_readme").lower()
    order_intent = sources["order_types"].text.lower()
    replay = sources["runtime_replay"].text.lower()
    lifecycle = sources["lifecycle"].text.lower()
    session = sources["oms_session"].text.lower()
    execution_quality = sources["execution_quality"].text.lower()

    rows = [
        _row(
            "event_driven_research_live_parity",
            "研究、回放、paper/live 尽量共享同一事件语义",
            _all(replay, ["fixture_capability_passed", "historical_drill_passed", "current_observe_only"]),
            "已分层表达 fixture / drill / current observe-only，但仍不能替代真实 gate 样本。",
            "保持三层证据，不允许把 diagnostic drill 当 paper gate。",
            local_evidence=["btc_perpetual_paper_runtime_replay"],
        ),
        _row(
            "order_type_and_time_in_force",
            "订单类型和 time-in-force 显式建模",
            _all(order_intent, ["order_type", "time_in_force"]) and _all(session, ["ordertype.market", "timeinforce.ioc"]),
            "OrderIntent 有基础字段，replay 当前主要使用 MARKET/IOC。",
            "后续补 limit/stop/trailing 的 fixture 覆盖，仍不接真实下单。",
            local_evidence=["OrderIntent.order_type", "OrderIntent.time_in_force", "MARKET/IOC replay"],
        ),
        _row(
            "reduce_only_and_cancel_only",
            "BTC 永续 reduce-only / cancel-only 执行保护",
            _all(replay, ["reduce_only", "cancel_only_mode", "blocked_by_cancel_only_mode"]),
            "replay fixture 已有 reduce-only 和 cancel-only 诊断，但 OrderIntent 核心字段未显式化。",
            "把 reduce_only/cancel_only 从 metadata 候选提升为本地 order intent/risk decision 明确字段或 schema 字段。",
            local_evidence=["replay.reduce_only", "replay.cancel_only_mode"],
            force_status="partial",
        ),
        _row(
            "post_only_maker_taker",
            "post-only、maker/taker 执行语义",
            _any(local, ["post_only", "post-only"]) and _any(execution_quality + session, ["maker", "taker", "fee_side"]),
            "执行质量模块可能有成本字段，但 post-only 未成为 BTC replay/order contract 的一等字段。",
            "补 post_only 字段、maker/taker 假设、fee side 和拒单路径的 fixture。",
            local_evidence=["execution_quality", "replay/order contract"],
        ),
        _row(
            "advanced_contingency_orders",
            "OCO / OTO / OUO 等高级条件单",
            _any(local, ["oco", "oto", "ouo", "contingency"]),
            "本地当前没有把高级条件单作为可执行 contract；这是正确的 fail-closed 缺口。",
            "只建 prohibited/diagnostic schema，不允许作为 paper/live 下单能力声明。",
            local_evidence=[],
            force_status="diagnostic_or_prohibited",
        ),
        _row(
            "venue_instrument_account_metadata",
            "venue、instrument、account、position side、margin mode 元数据",
            _all(order_intent, ["symbol", "client_order_id"]) and _any(local, ["venue", "account_id", "margin_mode"]),
            "核心 OrderIntent 只有 symbol/client id，部分账户和交易所元数据在外围报告中；replay ledger 仍需统一。",
            "给 replay/order ledger 增加 venue、instrument_id、account_mode、position_mode、margin_mode 的必填/显式空值字段。",
            local_evidence=["OrderIntent.symbol", "AccountState.account_id"],
        ),
        _row(
            "order_lifecycle_and_reconciliation",
            "submitted/accepted/partial/fill/cancel/reject/expire/reconcile 全生命周期",
            _all(
                lifecycle,
                ["submitted", "accepted", "partially_filled", "filled", "cancelled", "rejected", "expired", "reconciled"],
            )
            and _all(session, ["order_records", "fill_records", "reconciliation_report", "unreconciled_count"]),
            "本地 OMS 生命周期和 replay session 对账已具备基础覆盖。",
            "继续用 fixture 覆盖乱序、重复 fill、unknown submit outcome。",
            local_evidence=["BTCPaperOrderStatus", "order_records", "fill_records", "reconciliation_report"],
        ),
        _row(
            "risk_mark_index_liquidation_fields",
            "BTC 永续 mark/index/liquidation buffer/risk decision 字段",
            _all(replay, ["mark_price", "index_price", "liquidation_buffer_bps", "risk_decision"]),
            "replay 行已要求 mark/index/liquidation buffer/risk decision。",
            "保持缺失即 fail-closed，并在非空 current 样本出现时验证完整链路。",
            local_evidence=["mark_price", "index_price", "liquidation_buffer_bps", "risk_decision"],
        ),
        _row(
            "execution_quality_metrics",
            "arrival/benchmark/fill price、implementation shortfall、fee/slippage",
            _all(execution_quality + session, ["arrival_price", "fill_price", "benchmark_price"])
            and _any(execution_quality + session, ["implementation_shortfall", "fee"]),
            "执行质量字段已有基础，但需统一写入 replay summary、order ledger 和 gate evidence。",
            "补统一字段矩阵：arrival_price、paper_price、fill_price、benchmark_price、fee、slippage、shortfall。",
            local_evidence=["BTCExecutionFill", "arrival_price", "benchmark_price"],
        ),
        _row(
            "depth_fill_mapping_contract",
            "depth-aware fill mapping 与样本不足/深度不可见/映射失败分层",
            _all(replay, ["depth_fill_mapping", "no_gate_eligible_fill", "depth_not_visible", "mapping_logic_failed"]),
            "replay 中已有下游 contract 字段，但真实 current gate fill 仍待非空样本。",
            "保持状态机分层，等待 current non-flat 样本后再确认 gate-eligible mapping。",
            local_evidence=["depth_fill_mapping_contract", "depth_fill_mapping_status"],
        ),
    ]
    return rows


def _row(
    concept_id: str,
    concept_cn: str,
    covered: bool,
    gap_cn: str,
    recommended_action_cn: str,
    *,
    local_evidence: Sequence[str],
    force_status: str | None = None,
) -> dict[str, Any]:
    status = force_status or ("covered" if covered else "missing")
    return {
        "concept_id": concept_id,
        "external_reference": "NautilusTrader design concept",
        "concept_cn": concept_cn,
        "status": status,
        "covered": status == "covered",
        "gap_cn": "已覆盖。" if status == "covered" else gap_cn,
        "recommended_action_cn": "保持现有 contract，继续等待 current gate evidence。" if status == "covered" else recommended_action_cn,
        "local_evidence": list(local_evidence),
        "paper_gate_credit": False,
        "live_unlock_credit": False,
    }


def _summary(matrix: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        "covered_count": sum(1 for row in matrix if row.get("status") == "covered"),
        "partial_count": sum(1 for row in matrix if row.get("status") == "partial"),
        "missing_count": sum(1 for row in matrix if row.get("status") == "missing"),
        "diagnostic_or_prohibited_count": sum(1 for row in matrix if row.get("status") == "diagnostic_or_prohibited"),
        "total_count": len(matrix),
    }


def _followup_tickets(matrix: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "ticket_id": f"followup_{row['concept_id']}",
            "source_concept_id": row["concept_id"],
            "status": row["status"],
            "next_action": row["recommended_action_cn"],
            "paper_live_boundary": "research_only_no_paper_no_live",
        }
        for row in matrix
        if row.get("status") in {"partial", "missing", "diagnostic_or_prohibited"}
    ]


def _load_sources(*, root: Path, external_root: Path) -> dict[str, SourceText]:
    paths = {
        "nautilus_readme": external_root / "nautilus_trader" / "README.md",
        "order_types": root / "quant_us" / "core" / "types.py",
        "lifecycle": root / "quant_crypto" / "oms" / "lifecycle.py",
        "oms_session": root / "quant_crypto" / "oms" / "paper_runtime_replay_session.py",
        "execution_quality": root / "quant_crypto" / "oms" / "execution_quality.py",
        "runtime_replay": root / "quant_crypto" / "research" / "btc_perpetual_paper_runtime_replay.py",
    }
    return {source_id: SourceText(source_id, path, _read_text(path)) for source_id, path in paths.items()}


def _blockers(sources: Mapping[str, SourceText]) -> list[str]:
    blockers = []
    required = ["nautilus_readme", "order_types", "lifecycle", "oms_session", "runtime_replay"]
    for source_id in required:
        if not sources[source_id].exists:
            blockers.append(f"source_missing:{source_id}")
    return blockers


def _warnings(matrix: Sequence[Mapping[str, Any]]) -> list[str]:
    warnings = []
    if any(row.get("status") == "missing" for row in matrix):
        warnings.append("nautilus_field_audit_has_missing_local_contracts")
    if any(row.get("status") == "partial" for row in matrix):
        warnings.append("nautilus_field_audit_has_partial_local_contracts")
    return _dedupe(warnings)


def _source_hashes(sources: Mapping[str, SourceText]) -> dict[str, str]:
    return {source_id: stable_payload_hash({"path": _portable_path(source.path), "text": source.text}) for source_id, source in sources.items()}


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
    return {
        "status": "research_only_no_paper_no_live",
        "decision": report.get("decision"),
        **_mapping(report.get("gate")),
        "artifact_hash": report.get("artifact_hash"),
    }


def _write_matrix_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = [
        "concept_id",
        "external_reference",
        "concept_cn",
        "status",
        "gap_cn",
        "recommended_action_cn",
        "paper_gate_credit",
        "live_unlock_credit",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _resolve_external_root(root: Path, external_references_root: Path | None) -> Path:
    if external_references_root is not None:
        return _resolve(root, external_references_root)
    sibling = root.parent / "external_references"
    if sibling.exists():
        return sibling.resolve()
    return (root / "external_references").resolve()


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _portable_path(path: Path) -> str:
    return str(path).replace("\\", "/")


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


def _all(text: str, tokens: Sequence[str]) -> bool:
    return all(token.lower() in text for token in tokens)


def _any(text: str, tokens: Sequence[str]) -> bool:
    return any(token.lower() in text for token in tokens)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
