from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from quant_crypto.research.bankroll_attack_forward_observer import DEFAULT_REPORT_PATH as DEFAULT_ATTACK_OBSERVER_REPORT
from quant_crypto.research.high_yield_v2_followup import DEFAULT_REPORT_PATH as DEFAULT_HIGH_YIELD_FOLLOWUP_REPORT
from quant_crypto.research.long_short_top5_forward_observer import DEFAULT_REPORT_PATH as DEFAULT_LONG_SHORT_OBSERVER_REPORT
from quant_crypto.research.small_account_high_yield_near_miss_review import _git_commit, _portable_path


SCHEMA_VERSION = "btc_perpetual_execution_evidence_pack_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_perpetual_execution_evidence/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_execution_evidence_report.json"
DEFAULT_CHECKLIST_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_execution_evidence_checklist.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_execution_evidence_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

DEFAULT_CONFIG_PATH = Path("configs/data/btc_perpetual_sources.yaml")
DEFAULT_PROVIDER_REPORT = Path("artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json")
DEFAULT_COST_MODEL_REPORT = Path("artifacts/btc_cost_model/latest/btc_cost_model_report.json")
DEFAULT_FUNDING_LEDGER_REPORT = Path("artifacts/btc_cost_model/latest/btc_funding_ledger_report.json")
DEFAULT_PERPETUAL_POLICY_REPORT = Path("artifacts/btc_perpetual_policy/latest/btc_perpetual_policy_status_report.json")
DEFAULT_EXCHANGE_RUNTIME_CONTRACT = Path("artifacts/btc_exchange_runtime/latest/btc_exchange_runtime_contract.json")
DEFAULT_EXCHANGE_RUNTIME_REPLAY_GAP_REPORT = Path("artifacts/btc_exchange_runtime/latest/btc_exchange_runtime_replay_gap_report.json")
DEFAULT_BINANCE_VISION_BOOK_DEPTH_REPORT = Path("artifacts/btc_cost_model/latest/btc_binance_vision_book_depth_diagnostic_report.json")
DEFAULT_LIQUIDATION_RISK_CONTRACT = Path("artifacts/btc_completion_evidence/latest/liquidation_risk_contract.json")


def build_btc_perpetual_execution_evidence_pack(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    config_path: Path = DEFAULT_CONFIG_PATH,
    provider_report_path: Path = DEFAULT_PROVIDER_REPORT,
    cost_model_report_path: Path = DEFAULT_COST_MODEL_REPORT,
    funding_ledger_report_path: Path = DEFAULT_FUNDING_LEDGER_REPORT,
    perpetual_policy_report_path: Path = DEFAULT_PERPETUAL_POLICY_REPORT,
    exchange_runtime_contract_path: Path = DEFAULT_EXCHANGE_RUNTIME_CONTRACT,
    exchange_runtime_replay_gap_report_path: Path = DEFAULT_EXCHANGE_RUNTIME_REPLAY_GAP_REPORT,
    binance_vision_book_depth_report_path: Path = DEFAULT_BINANCE_VISION_BOOK_DEPTH_REPORT,
    liquidation_risk_contract_path: Path = DEFAULT_LIQUIDATION_RISK_CONTRACT,
    long_short_observer_report_path: Path = DEFAULT_LONG_SHORT_OBSERVER_REPORT,
    attack_observer_report_path: Path = DEFAULT_ATTACK_OBSERVER_REPORT,
    high_yield_followup_report_path: Path = DEFAULT_HIGH_YIELD_FOLLOWUP_REPORT,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    checklist_csv_path = output_dir / DEFAULT_CHECKLIST_CSV_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    config = _read_yaml(config_path)
    provider = _read_json(provider_report_path)
    cost_model = _read_json(cost_model_report_path)
    funding_ledger = _read_json(funding_ledger_report_path)
    policy = _read_json(perpetual_policy_report_path)
    exchange_runtime = _read_json(exchange_runtime_contract_path)
    runtime_replay_gap = _read_json(exchange_runtime_replay_gap_report_path)
    binance_vision_book_depth = _read_json(binance_vision_book_depth_report_path)
    liquidation_contract = _read_json(liquidation_risk_contract_path)
    long_short = _read_json(long_short_observer_report_path)
    attack = _read_json(attack_observer_report_path)
    high_yield = _read_json(high_yield_followup_report_path)

    selected = _selected_bundle(config, provider_report=provider)
    manifest = _read_json(selected.get("_manifest_path_abs"))
    manifest_roles = _manifest_roles(manifest)
    latest_strategy_decision_time = _latest_strategy_decision_time(long_short=long_short, attack=attack, high_yield=high_yield)
    data_lag = _data_lag_status(
        manifest=manifest,
        manifest_roles=manifest_roles,
        latest_strategy_decision_time=latest_strategy_decision_time,
    )
    l2 = _l2_diagnostics(
        config_path=config_path,
        selected=selected,
        manifest_roles=manifest_roles,
        binance_vision_book_depth=binance_vision_book_depth,
    )
    checklist = _checklist(
        selected=selected,
        manifest=manifest,
        manifest_roles=manifest_roles,
        provider=provider,
        cost_model=cost_model,
        funding_ledger=funding_ledger,
        policy=policy,
        exchange_runtime=exchange_runtime,
        runtime_replay_gap=runtime_replay_gap,
        liquidation_contract=liquidation_contract,
        data_lag=data_lag,
        l2=l2,
    )
    blockers = _blockers_from_checklist(checklist)
    waivers = _waivers_from_checklist(checklist)
    promotion_disable_reasons = _promotion_disable_reasons(blockers=blockers, waivers=waivers)
    line_assessments = _line_assessments(
        long_short=long_short,
        attack=attack,
        high_yield=high_yield,
        blockers=blockers,
        latest_strategy_decision_time=latest_strategy_decision_time,
    )
    decision = (
        "perpetual_execution_evidence_incomplete_fail_closed_no_paper_no_live"
        if blockers
        else "perpetual_execution_evidence_present_manual_review_required_no_auto_paper_no_live"
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "incomplete_research_only" if blockers else "complete_research_only",
        "decision": decision,
        "scope": "btc_perpetual_mark_index_funding_fee_depth_liquidation_outage_evidence_gate",
        "code_commit": _git_commit(),
        "input": {
            "config_path": _portable_path(config_path),
            "provider_report_path": _portable_path(provider_report_path),
            "cost_model_report_path": _portable_path(cost_model_report_path),
            "funding_ledger_report_path": _portable_path(funding_ledger_report_path),
            "perpetual_policy_report_path": _portable_path(perpetual_policy_report_path),
            "exchange_runtime_contract_path": _portable_path(exchange_runtime_contract_path),
            "exchange_runtime_replay_gap_report_path": _portable_path(exchange_runtime_replay_gap_report_path),
            "binance_vision_book_depth_report_path": _portable_path(binance_vision_book_depth_report_path),
            "liquidation_risk_contract_path": _portable_path(liquidation_risk_contract_path),
            "long_short_observer_report_path": _portable_path(long_short_observer_report_path),
            "attack_observer_report_path": _portable_path(attack_observer_report_path),
            "high_yield_followup_report_path": _portable_path(high_yield_followup_report_path),
        },
        "selected_bundle": _public_selected_bundle(selected),
        "selected_bundle_manifest": {
            "exists": bool(manifest),
            "bundle_id": manifest.get("bundle_id"),
            "source_provider": manifest.get("source_provider"),
            "source_type": manifest.get("source_type"),
            "market_type": manifest.get("market_type"),
            "symbol": manifest.get("symbol"),
            "sample_start": manifest.get("sample_start"),
            "sample_end": manifest.get("sample_end"),
            "roles": manifest_roles,
            "manifest_blockers": manifest.get("blockers", []),
        },
        "latest_strategy_decision_time": latest_strategy_decision_time,
        "data_lag_status": data_lag,
        "l2_depth_diagnostics": l2,
        "source_status": {
            "provider": _source_status(provider_report_path, provider),
            "cost_model": _source_status(cost_model_report_path, cost_model),
            "funding_ledger": _source_status(funding_ledger_report_path, funding_ledger),
            "perpetual_policy": _source_status(perpetual_policy_report_path, policy),
            "exchange_runtime_contract": _source_status(exchange_runtime_contract_path, exchange_runtime),
            "exchange_runtime_replay_gap": _source_status(exchange_runtime_replay_gap_report_path, runtime_replay_gap),
            "binance_vision_book_depth": _source_status(binance_vision_book_depth_report_path, binance_vision_book_depth),
            "liquidation_risk_contract": _source_status(liquidation_risk_contract_path, liquidation_contract),
        },
        "evidence_checklist": checklist,
        "requirement_status_cn": _requirement_status_cn(checklist),
        "summary": _summary(checklist=checklist, blockers=blockers, line_assessments=line_assessments),
        "line_assessments": line_assessments,
        "gate": _gate(blockers=blockers, promotion_disable_reasons=promotion_disable_reasons),
        "guardrails": _guardrails(),
        "warnings": _warnings(checklist=checklist, blockers=blockers),
        "blockers": blockers,
        "fail_closed_waivers": waivers,
        "outputs": {
            "json": _portable_path(report_path),
            "checklist_csv": _portable_path(checklist_csv_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_csv(checklist_csv_path, checklist)
    _write_text(markdown_path, render_btc_perpetual_execution_evidence_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_btc_perpetual_execution_evidence_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary", {})
    selected = report.get("selected_bundle", {})
    gate = report.get("gate", {})
    lines = [
        "# BTC 永续真实执行证据包",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 当前配置选择：`{selected.get('config_selected_provider')}` / `{selected.get('config_selected_bundle_id')}`",
        f"- provider 报告选择：`{selected.get('provider_report_selected_provider')}` / `{selected.get('provider_report_selected_bundle_id')}`",
        f"- 最新策略观察时间：`{report.get('latest_strategy_decision_time')}`",
        f"- 通过检查：`{summary.get('pass_count')}`，失败检查：`{summary.get('fail_count')}`，警告检查：`{summary.get('warn_count')}`",
        f"- 阻断项数量：`{summary.get('blocker_count')}`",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 当前结论",
        "",
    ]
    if report.get("blockers"):
        lines.append("永续执行证据仍不完整，不能进入 paper/live。主要缺口：")
        for blocker in report.get("blockers", [])[:20]:
            lines.append(f"- `{blocker}`")
    else:
        lines.append("证据字段已满足本包检查，但仍只能进入人工复核，不能自动 paper/live。")
    lines.extend(
        [
            "",
            "## 中文证据状态表",
            "",
            "| 证据项 | 状态 | 当前证据 | 仍缺什么 |",
            "|---|---|---|---|",
        ]
    )
    for row in report.get("requirement_status_cn", []):
        lines.append(
            f"| {row.get('requirement_cn')} | `{row.get('status_cn')}` | {row.get('evidence_cn')} | {row.get('missing_cn')} |"
        )
    lines.extend(
        [
            "",
            "## 策略线影响",
            "",
            "| 策略线 | 需要永续证据 | 当前结论 | paper/live |",
            "|---|---:|---|---|",
        ]
    )
    for row in report.get("line_assessments", []):
        lines.append(
            f"| `{row.get('line_id')}` | `{row.get('requires_perpetual_execution_evidence')}` | `{row.get('decision')}` | `{row.get('paper_live_boundary')}` |"
        )
    lines.extend(
        [
            "",
            "本包只整合真实执行证据状态，不生成策略骨架，不写 paper 队列，不连接 broker/OMS，不解锁 live。",
        ]
    )
    return "\n".join(lines) + "\n"


def _selected_bundle(config: Mapping[str, Any], *, provider_report: Mapping[str, Any]) -> dict[str, Any]:
    provider_name = str(config.get("selected_provider", "") or "")
    providers = config.get("providers", {}) if isinstance(config.get("providers"), Mapping) else {}
    provider_cfg = providers.get(provider_name, {}) if isinstance(providers.get(provider_name), Mapping) else {}
    root = Path(str(provider_cfg.get("root", ""))) if provider_cfg else Path("")
    bundle_id = str(provider_cfg.get("selected_bundle_id", "") or "")
    manifest_path = root / "bundles" / bundle_id / "btc_perpetual_bundle_manifest.json" if root and bundle_id else Path("")
    provider_selected_provider = provider_report.get("selected_provider")
    provider_selected_bundle = provider_report.get("selected_bundle_id")
    return {
        "config_selected_provider": provider_name,
        "config_selected_bundle_id": bundle_id,
        "config_provider_enabled": bool(provider_cfg.get("enabled")),
        "config_allow_network": bool(provider_cfg.get("allow_network")),
        "config_allow_private_endpoints": bool(provider_cfg.get("allow_private_endpoints")),
        "config_allow_order_endpoints": bool(provider_cfg.get("allow_order_endpoints")),
        "provider_report_selected_provider": provider_selected_provider,
        "provider_report_selected_bundle_id": provider_selected_bundle,
        "provider_report_matches_config": provider_selected_provider == provider_name and provider_selected_bundle == bundle_id,
        "manifest_path": _portable_path(manifest_path) if str(manifest_path) else None,
        "_manifest_path_abs": manifest_path,
    }


def _public_selected_bundle(selected: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in selected.items() if not str(key).startswith("_")}


def _checklist(
    *,
    selected: Mapping[str, Any],
    manifest: Mapping[str, Any],
    manifest_roles: Mapping[str, Any],
    provider: Mapping[str, Any],
    cost_model: Mapping[str, Any],
    funding_ledger: Mapping[str, Any],
    policy: Mapping[str, Any],
    exchange_runtime: Mapping[str, Any],
    runtime_replay_gap: Mapping[str, Any],
    liquidation_contract: Mapping[str, Any],
    data_lag: Mapping[str, Any],
    l2: Mapping[str, Any],
) -> list[dict[str, Any]]:
    mark = _mapping(cost_model.get("mark_price_model"))
    funding = _mapping(cost_model.get("funding_model"))
    fee = _mapping(cost_model.get("fee_model"))
    slippage = _mapping(cost_model.get("slippage_model"))
    liquidation = _mapping(cost_model.get("liquidation_data"))
    return [
        _row("bundle", "selected_provider_bundle_matches_config", selected.get("provider_report_matches_config") is True, "provider report must match current config selection", _public_selected_bundle(selected)),
        _row("bundle", "selected_bundle_manifest_present", bool(manifest), "selected bundle manifest is readable", {"bundle_id": manifest.get("bundle_id")}),
        _row("bundle", "perp_data_covers_latest_strategy_decision", data_lag.get("covers_latest_strategy_decision") is True, "perp mark/funding data must reach latest strategy observation", data_lag),
        _row("mark_index", "mark_price_history_verified", provider.get("mark_price_klines_verified") is True and mark.get("mark_price_klines_available") is True, "historical mark price klines verified", mark),
        _row("mark_index", "premium_or_index_history_verified", provider.get("premium_index_klines_verified") is True and mark.get("premium_index_klines_available") is True, "premium/index history verified", mark),
        _row("mark_index", "current_mark_price_available", mark.get("mark_price_current_available") is True, "current mark price is available at decision time", mark),
        _row("mark_index", "mark_used_for_liquidation_risk", mark.get("mark_price_used_for_liquidation_risk") is True, "liquidation risk must use mark/current mark, not spot close proxy", mark),
        _row("funding", "funding_rate_history_verified", provider.get("funding_rate_verified") is True and funding.get("funding_rate_available") is True, "funding rate history verified", funding),
        _row("funding", "funding_info_verified", provider.get("funding_info_verified") is True and funding.get("funding_info_available") is True, "funding interval metadata verified", funding),
        _row("funding", "funding_payment_in_ledger", funding_ledger.get("funding_payment_in_ledger") is True and funding.get("funding_payment_in_ledger") is True, "funding payments are separated in ledger", funding_ledger),
        _row("fees", "fee_tier_verified", fee.get("fee_tier_verified") is True, "maker/taker fee tier is verified", fee),
        _row("fees", "fee_in_ledger", fee.get("fee_in_ledger") is True, "fees are present in ledger/cost model", fee),
        _row("slippage_depth", "slippage_positive_or_depth_aware", _float(slippage.get("slippage_bps")) > 0.0 or bool(slippage.get("depth_aware")), "0 bps slippage is not execution evidence", slippage),
        _row("slippage_depth", "order_book_depth_diagnostic_present", l2.get("depth_sample_present") is True, "order book depth sample exists for diagnostics", l2, warn_only=True),
        _row(
            "slippage_depth",
            "depth_aware_slippage_history_verified",
            slippage.get("depth_aware_slippage_history_verified") is True,
            "depth must be selected-venue OKX, time-aligned, broad enough, and mapped to strategy fills",
            {
                **dict(l2),
                "cost_model_depth_aware_slippage_history_verified": slippage.get(
                    "depth_aware_slippage_history_verified"
                ),
                "gate_source": "cost_model_selected_venue_depth_slippage_report",
                "cross_venue_l2_diagnostic_ignored_for_gate": True,
            },
        ),
        _row("liquidation", "liquidation_risk_contract_present", bool(liquidation_contract) and not liquidation_contract.get("blockers"), "liquidation risk contract exists", _source_payload(liquidation_contract)),
        _row(
            "liquidation",
            "exact_exchange_liquidation_formula_verified",
            _liquidation_formula_and_tiers_verified(provider=provider, policy=policy),
            "exchange exact liquidation formula and tiers verified",
            {
                "provider_liquidation_formula_verified": provider.get("liquidation_formula_verified"),
                "provider_maintenance_margin_tiers_verified": provider.get("maintenance_margin_tiers_verified"),
                "provider_exact_exchange_liquidation_formula_verified": provider.get("exact_exchange_liquidation_formula_verified"),
                "provider_liquidation_formula_report_path": provider.get("liquidation_formula_report_path"),
                "provider_liquidation_formula_blockers": provider.get("liquidation_formula_blockers"),
                "policy_liquidation_formula_verified": policy.get("liquidation_formula_verified"),
                "policy_maintenance_margin_tiers_verified": policy.get("maintenance_margin_tiers_verified"),
            },
        ),
        _row(
            "liquidation",
            "liquidation_history_or_snapshots_available",
            liquidation.get("complete_liquidation_history_available") is True
            or provider.get("liquidation_snapshot_gate_eligible") is True,
            "historical liquidation/snapshot evidence available",
            {
                **dict(liquidation),
                "promotion_impact_when_missing": "fail_closed_waiver_disables_leverage_and_perpetual_promotion",
            },
            fail_closed_waiver=True,
        ),
        _row("runtime_outage", "exchange_runtime_contract_present", bool(exchange_runtime), "runtime contract artifact exists", _runtime_details(exchange_runtime=exchange_runtime, runtime_replay_gap=runtime_replay_gap), warn_only=True),
        _row("runtime_outage", "exchange_runtime_replay_gap_report_present", bool(runtime_replay_gap), "runtime replay gap report exists and explains current runtime evidence boundaries", _runtime_details(exchange_runtime=exchange_runtime, runtime_replay_gap=runtime_replay_gap), warn_only=True),
        _row("runtime_outage", "exchange_runtime_real_or_paper_replay_ready", _runtime_ready(exchange_runtime, runtime_replay_gap), "outage/gapfill/reconcile evidence must be replay-ready, not merely documented", _runtime_details(exchange_runtime=exchange_runtime, runtime_replay_gap=runtime_replay_gap)),
        _row("runtime_outage", "perpetual_policy_allows_current_strategy", policy.get("current_strategy_uses_perpetual") is True and policy.get("gate", {}).get("perpetual_allowed") is True, "current strategy route must explicitly allow perpetual before paper", policy),
    ]


def _line_assessments(
    *,
    long_short: Mapping[str, Any],
    attack: Mapping[str, Any],
    high_yield: Mapping[str, Any],
    blockers: Sequence[str],
    latest_strategy_decision_time: str | None,
) -> list[dict[str, Any]]:
    incomplete = bool(blockers)
    lines = [
        {
            "line_id": "long_short_donchian_top5",
            "source_status": long_short.get("status"),
            "latest_decision_time": _nested_get(long_short, ["holdout_lock", "latest_decision_time"]) or latest_strategy_decision_time,
            "requires_perpetual_execution_evidence": True,
            "reason": "long/short BTC execution requires a perpetual or margin venue for short side",
        },
        {
            "line_id": "high_octane_attack_sleeve_v2",
            "source_status": attack.get("status"),
            "latest_decision_time": _nested_get(attack, ["holdout_lock", "latest_decision_time"]) or latest_strategy_decision_time,
            "requires_perpetual_execution_evidence": True,
            "reason": "10x sleeve exposure requires exact mark/index/liquidation/funding/depth evidence",
        },
        {
            "line_id": "high_yield_v2_frozen",
            "source_status": high_yield.get("status"),
            "latest_decision_time": _nested_get(high_yield, ["step_1_daily_observation_automation", "latest_decision_time"]),
            "requires_perpetual_execution_evidence": True,
            "reason": "2.5x long/short high-yield route requires perpetual execution evidence before paper",
        },
    ]
    for row in lines:
        row["decision"] = (
            "blocked_by_perpetual_execution_evidence_gap_no_paper_no_live"
            if incomplete
            else "evidence_present_manual_review_only_no_auto_paper_no_live"
        )
        row["paper_live_boundary"] = "paper_queue_write_allowed=false; live_unlock_allowed=false"
    return lines


def _requirement_status_cn(checklist: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(row.get("check_id")): row for row in checklist}

    def status_for(required: Sequence[str], *, warn_ids: Sequence[str] = ()) -> str:
        statuses = [str(_mapping(by_id.get(check_id)).get("status", "")) for check_id in required]
        if all(status == "pass" for status in statuses):
            return "通过"
        if any(status == "waived_fail_closed" for status in statuses):
            return "fail_closed_waived"
        if any(status == "fail" for status in statuses):
            return "阻断"
        if any(str(_mapping(by_id.get(check_id)).get("status", "")) == "warn" for check_id in warn_ids):
            return "诊断"
        return "缺失"

    def blockers(required: Sequence[str]) -> list[str]:
        return [f"btc_perp_exec_{check_id}" for check_id in required if _mapping(by_id.get(check_id)).get("status") == "fail"]

    rows = [
        {
            "requirement_id": "mark_index",
            "requirement_cn": "标记价 / 指数价",
            "status_cn": status_for(
                [
                    "mark_price_history_verified",
                    "premium_or_index_history_verified",
                    "current_mark_price_available",
                    "mark_used_for_liquidation_risk",
                ]
            ),
            "evidence_cn": "历史 mark price、premium/index、当前 mark price、强平风险使用 mark price。",
            "missing_cn": "无" if not blockers(["mark_price_history_verified", "premium_or_index_history_verified", "current_mark_price_available", "mark_used_for_liquidation_risk"]) else "；".join(blockers(["mark_price_history_verified", "premium_or_index_history_verified", "current_mark_price_available", "mark_used_for_liquidation_risk"])),
        },
        {
            "requirement_id": "funding",
            "requirement_cn": "资金费率结算",
            "status_cn": status_for(["funding_rate_history_verified", "funding_info_verified", "funding_payment_in_ledger"]),
            "evidence_cn": "funding rate、funding interval 元数据和 funding ledger 分账。",
            "missing_cn": "无" if not blockers(["funding_rate_history_verified", "funding_info_verified", "funding_payment_in_ledger"]) else "；".join(blockers(["funding_rate_history_verified", "funding_info_verified", "funding_payment_in_ledger"])),
        },
        {
            "requirement_id": "fees",
            "requirement_cn": "手续费",
            "status_cn": status_for(["fee_tier_verified", "fee_in_ledger"]),
            "evidence_cn": "OKX 手续费层级和 ledger/cost model 手续费字段。",
            "missing_cn": "无" if not blockers(["fee_tier_verified", "fee_in_ledger"]) else "；".join(blockers(["fee_tier_verified", "fee_in_ledger"])),
        },
        {
            "requirement_id": "depth_slippage",
            "requirement_cn": "深度滑点",
            "status_cn": status_for(["slippage_positive_or_depth_aware", "depth_aware_slippage_history_verified"], warn_ids=["order_book_depth_diagnostic_present"]),
            "evidence_cn": "已有正滑点下限和公开盘口诊断；Binance Vision 只能作为跨交易所诊断。",
            "missing_cn": "OKX 时间对齐、覆盖足够长、能绑定策略成交的 depth-aware slippage 历史。",
        },
        {
            "requirement_id": "liquidation_formula",
            "requirement_cn": "强平公式 / 维持保证金档位",
            "status_cn": status_for(["liquidation_risk_contract_present", "exact_exchange_liquidation_formula_verified"]),
            "evidence_cn": "强平风险 contract、OKX 公式和维持保证金档位。",
            "missing_cn": "无" if not blockers(["liquidation_risk_contract_present", "exact_exchange_liquidation_formula_verified"]) else "；".join(blockers(["liquidation_risk_contract_present", "exact_exchange_liquidation_formula_verified"])),
        },
        {
            "requirement_id": "liquidation_history",
            "requirement_cn": "强平历史 / 快照",
            "status_cn": status_for(["liquidation_history_or_snapshots_available"]),
            "evidence_cn": "当前只有诊断或短尾数据，不能证明完整 1H 历史覆盖。",
            "missing_cn": "免费来源下仍缺 gate 级别的完整 OKX/BTC 永续强平历史或可审计快照。",
        },
        {
            "requirement_id": "runtime_outage",
            "requirement_cn": "断线 / outage / runtime replay",
            "status_cn": status_for(["exchange_runtime_real_or_paper_replay_ready"], warn_ids=["exchange_runtime_contract_present", "exchange_runtime_replay_gap_report_present"]),
            "evidence_cn": "已有 runtime contract 和 replay gap 报告，但仍是 simulated probe 或不适用于当前永续路线。",
            "missing_cn": "当前 BTC 永续 paper runtime replay、真实/纸盘成交回放、断线恢复、队列/延迟证据。",
        },
    ]
    for row in rows:
        row["paper_queue_write_allowed"] = False
        row["live_unlock_allowed"] = False
    return rows


def _summary(*, checklist: Sequence[Mapping[str, Any]], blockers: Sequence[str], line_assessments: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "pass_count": sum(1 for row in checklist if row.get("status") == "pass"),
        "fail_count": sum(1 for row in checklist if row.get("status") == "fail"),
        "warn_count": sum(1 for row in checklist if row.get("status") == "warn"),
        "fail_closed_waiver_count": sum(1 for row in checklist if row.get("status") == "waived_fail_closed"),
        "blocker_count": len(blockers),
        "strategy_line_count": len(line_assessments),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _gate(*, blockers: Sequence[str] = (), promotion_disable_reasons: Sequence[str] = ()) -> dict[str, Any]:
    reasons = list(promotion_disable_reasons) or ["manual_review_required_no_auto_paper_no_live"]
    return {
        "research_only": True,
        "perpetual_execution_evidence_ready_for_paper_review": False,
        "perpetual_promotion_allowed": False,
        "perpetual_promotion_disabled": True,
        "leverage_promotion_allowed": False,
        "leverage_promotion_disabled": True,
        "promotion_disable_reasons": reasons,
        "liquidation_gap_disables_leverage_perp_promotion": (
            "btc_perp_exec_liquidation_history_or_snapshots_available" in reasons
        ),
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "reason": "Perpetual execution evidence pack is fail-closed and cannot promote strategies by itself.",
    }


def _guardrails() -> dict[str, bool]:
    return {
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    gate = _mapping(report.get("gate"))
    return {
        "schema_version": "btc_perpetual_execution_evidence_safety_status_v1",
        "status": "research_only",
        "decision": report.get("decision"),
        "perpetual_execution_evidence_ready_for_paper_review": False,
        "perpetual_promotion_allowed": False,
        "perpetual_promotion_disabled": True,
        "leverage_promotion_allowed": False,
        "leverage_promotion_disabled": True,
        "promotion_disable_reasons": list(gate.get("promotion_disable_reasons", []) or []),
        "liquidation_gap_disables_leverage_perp_promotion": bool(
            gate.get("liquidation_gap_disables_leverage_perp_promotion")
        ),
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "blockers": list(report.get("blockers", [])),
    }


def _warnings(*, checklist: Sequence[Mapping[str, Any]], blockers: Sequence[str]) -> list[str]:
    warnings = ["btc_perpetual_execution_evidence_research_only_no_paper_no_live"]
    if blockers:
        warnings.append("btc_perpetual_execution_evidence_incomplete_fail_closed")
    if any(row.get("status") == "warn" for row in checklist):
        warnings.append("diagnostic_depth_or_runtime_evidence_is_not_gate_evidence")
    return warnings


def _blockers_from_checklist(checklist: Sequence[Mapping[str, Any]]) -> list[str]:
    return [f"btc_perp_exec_{row['check_id']}" for row in checklist if row.get("status") == "fail"]


def _waivers_from_checklist(checklist: Sequence[Mapping[str, Any]]) -> list[str]:
    return [
        f"btc_perp_exec_{row['check_id']}"
        for row in checklist
        if row.get("status") == "waived_fail_closed"
    ]


def _promotion_disable_reasons(*, blockers: Sequence[str], waivers: Sequence[str]) -> list[str]:
    return _dedupe([*blockers, *waivers])


def _dedupe(items: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _row(
    area: str,
    check_id: str,
    passed: bool,
    evidence: str,
    details: Mapping[str, Any],
    *,
    warn_only: bool = False,
    fail_closed_waiver: bool = False,
) -> dict[str, Any]:
    status = "pass" if passed else ("waived_fail_closed" if fail_closed_waiver else ("warn" if warn_only else "fail"))
    return {
        "area": area,
        "check_id": check_id,
        "status": status,
        "evidence": evidence,
        "details": _json_compact(details),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _data_lag_status(
    *,
    manifest: Mapping[str, Any],
    manifest_roles: Mapping[str, Any],
    latest_strategy_decision_time: str | None,
) -> dict[str, Any]:
    price_roles = ("klines_1h", "mark_price_klines_1h", "premium_index_klines_1h")
    funding_role = "funding_rate"
    required_roles = (*price_roles, funding_role)
    role_sample_ends = {
        role: _mapping(manifest_roles.get(role)).get("sample_end")
        for role in required_roles
        if _mapping(manifest_roles.get(role)).get("sample_end")
    }
    role_available_ends = {
        role: (_mapping(manifest_roles.get(role)).get("available_end") or _mapping(manifest_roles.get(role)).get("sample_end"))
        for role in required_roles
        if _mapping(manifest_roles.get(role)).get("available_end") or _mapping(manifest_roles.get(role)).get("sample_end")
    }
    missing_roles = [role for role in required_roles if role not in role_available_ends]
    missing_price_roles = [role for role in price_roles if role not in role_available_ends]
    parsed_price_ends = [_timestamp(role_available_ends[role]) for role in price_roles if role in role_available_ends]
    price_available_ts = min(parsed_price_ends) if parsed_price_ends and not missing_price_roles else None
    funding_ts = _timestamp(role_available_ends[funding_role]) if funding_role in role_available_ends else None
    sample_end = price_available_ts.isoformat() if price_available_ts else manifest.get("sample_end")
    if price_available_ts is None or funding_ts is None or not latest_strategy_decision_time:
        return {
            "sample_end": sample_end,
            "manifest_sample_end": manifest.get("sample_end"),
            "role_sample_ends": role_sample_ends,
            "role_available_ends": role_available_ends,
            "missing_roles": missing_roles,
            "latest_strategy_decision_time": latest_strategy_decision_time,
            "covers_latest_strategy_decision": False,
            "lag_hours": None,
            "reason": "missing_core_role_sample_end_or_strategy_decision_time",
        }
    decision_ts = _timestamp(latest_strategy_decision_time)
    if price_available_ts is None:
        price_lag_hours = None
    else:
        price_lag_hours = max(0.0, (decision_ts - price_available_ts).total_seconds() / 3600.0)
    funding_lag_hours = None if funding_ts is None else max(0.0, (decision_ts - funding_ts).total_seconds() / 3600.0)
    funding_fresh = funding_lag_hours is not None and funding_lag_hours <= 12.0
    price_covers = price_available_ts is not None and price_available_ts >= decision_ts
    return {
        "sample_end": price_available_ts.isoformat() if price_available_ts else manifest.get("sample_end"),
        "manifest_sample_end": manifest.get("sample_end"),
        "role_sample_ends": role_sample_ends,
        "role_available_ends": role_available_ends,
        "missing_roles": missing_roles,
        "latest_strategy_decision_time": decision_ts.isoformat(),
        "price_available_end": price_available_ts.isoformat() if price_available_ts else None,
        "price_covers_latest_strategy_decision": price_covers,
        "price_lag_hours": round(price_lag_hours, 6) if price_lag_hours is not None else None,
        "funding_available_end": funding_ts.isoformat() if funding_ts else None,
        "funding_lag_hours": round(funding_lag_hours, 6) if funding_lag_hours is not None else None,
        "funding_freshness_max_hours": 12.0,
        "funding_fresh_for_latest_strategy_decision": funding_fresh,
        "covers_latest_strategy_decision": price_covers and funding_fresh,
        "lag_hours": round(price_lag_hours, 6) if price_lag_hours is not None else None,
    }


def _l2_diagnostics(
    *,
    config_path: Path,
    selected: Mapping[str, Any],
    manifest_roles: Mapping[str, Any],
    binance_vision_book_depth: Mapping[str, Any],
) -> dict[str, Any]:
    selected_depth = manifest_roles.get("order_book_depth") or {}
    bundles_root = Path(str(selected.get("_manifest_path_abs") or "")).parent.parent if selected.get("_manifest_path_abs") else Path("")
    l2_manifests = sorted(bundles_root.glob("*/l2_alignment_manifest.json")) if bundles_root.exists() else []
    binance_interpretation = (
        binance_vision_book_depth.get("execution_gate_interpretation", {})
        if isinstance(binance_vision_book_depth.get("execution_gate_interpretation"), Mapping)
        else {}
    )
    binance_coverage = (
        binance_vision_book_depth.get("coverage", {})
        if isinstance(binance_vision_book_depth.get("coverage"), Mapping)
        else {}
    )
    return {
        "config_path": _portable_path(config_path),
        "selected_depth_role_present": bool(selected_depth),
        "selected_depth_record_count": selected_depth.get("record_count"),
        "selected_depth_sample_start": selected_depth.get("sample_start"),
        "selected_depth_sample_end": selected_depth.get("sample_end"),
        "depth_sample_present": bool(selected_depth) or bool(l2_manifests),
        "l2_alignment_manifest_count": len(l2_manifests),
        "l2_alignment_manifest_examples": [_portable_path(path) for path in l2_manifests[:5]],
        "free_public_cross_venue_depth_diagnostic_present": bool(binance_vision_book_depth),
        "free_public_cross_venue_depth_diagnostic_status": binance_vision_book_depth.get("status"),
        "free_public_cross_venue_depth_row_count": binance_vision_book_depth.get("row_count"),
        "free_public_cross_venue_depth_coverage_days": binance_coverage.get("coverage_days"),
        "free_public_cross_venue_depth_gate_eligible_for_selected_venue": binance_interpretation.get(
            "gate_eligible_for_selected_venue", False
        ),
        "depth_aware_slippage_history_verified": False,
        "reason": (
            "L2/depth samples and Binance Vision bookDepth are diagnostics; no broad OKX time-aligned depth-aware "
            "slippage model or paper fill replay is attached to strategy fills."
        ),
    }


def _manifest_roles(manifest: Mapping[str, Any]) -> dict[str, Any]:
    roles: dict[str, Any] = {}
    files = manifest.get("files", [])
    if not isinstance(files, list):
        return roles
    for item in files:
        if isinstance(item, Mapping) and item.get("role"):
            roles[str(item["role"])] = dict(item)
    return roles


def _latest_strategy_decision_time(*, long_short: Mapping[str, Any], attack: Mapping[str, Any], high_yield: Mapping[str, Any]) -> str | None:
    candidates = [
        _nested_get(long_short, ["holdout_lock", "latest_decision_time"]),
        _nested_get(attack, ["holdout_lock", "latest_decision_time"]),
        _nested_get(attack, ["latest_observation", "decision_time"]),
        _nested_get(high_yield, ["step_1_daily_observation_automation", "latest_decision_time"]),
    ]
    parsed = [_timestamp(value) for value in candidates if value]
    if not parsed:
        return None
    return max(parsed).isoformat()


def _runtime_ready(exchange_runtime: Mapping[str, Any], runtime_replay_gap: Mapping[str, Any] | None = None) -> bool:
    if not exchange_runtime:
        return False
    if exchange_runtime.get("status") != "complete":
        return False
    notes = exchange_runtime.get("notes", {})
    if isinstance(notes, Mapping) and notes.get("evidence_type") == "simulated_contract_probe":
        return False
    if runtime_replay_gap:
        if runtime_replay_gap.get("status") != "complete_research_only":
            return False
        if runtime_replay_gap.get("blockers"):
            return False
    return bool(exchange_runtime.get("decision") in {"runtime_tradeable_for_simulated_paper", "runtime_ready_for_paper"})


def _runtime_details(*, exchange_runtime: Mapping[str, Any], runtime_replay_gap: Mapping[str, Any]) -> dict[str, Any]:
    gap_summary = runtime_replay_gap.get("summary", {}) if isinstance(runtime_replay_gap.get("summary"), Mapping) else {}
    gap_analysis = runtime_replay_gap.get("gap_analysis", {}) if isinstance(runtime_replay_gap.get("gap_analysis"), Mapping) else {}
    return {
        **_source_payload(exchange_runtime),
        "runtime_replay_gap_status": runtime_replay_gap.get("status"),
        "runtime_replay_gap_decision": runtime_replay_gap.get("decision"),
        "runtime_replay_gap_blockers": runtime_replay_gap.get("blockers", []),
        "runtime_replay_gap_summary": gap_summary,
        "runtime_contract_is_simulated_probe": gap_analysis.get("runtime_contract_is_simulated_probe"),
        "public_ws_coverage_contract_satisfied": gap_analysis.get("public_ws_coverage_contract_satisfied"),
        "paper_runtime_replay_ready": gap_analysis.get("paper_runtime_replay_ready"),
    }


def _source_status(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": _portable_path(path),
        "exists": path.exists(),
        "schema_version": payload.get("schema_version") or payload.get("btc_artifact_schema_version") or payload.get("exchange_runtime_contract_version"),
        "status": payload.get("status"),
        "decision": payload.get("decision") or payload.get("policy_decision"),
        "blockers": payload.get("blockers", []),
    }


def _source_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": payload.get("schema_version") or payload.get("exchange_runtime_contract_version") or payload.get("btc_artifact_schema_version"),
        "status": payload.get("status"),
        "decision": payload.get("decision"),
        "blockers": payload.get("blockers", []),
        "notes": payload.get("notes", {}),
    }


def _read_json(path: Path | str | None) -> dict[str, Any]:
    if path in {None, ""}:
        return {}
    path = Path(path)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(str(key))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fields})


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _nested_get(payload: Mapping[str, Any], keys: Sequence[str]) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _bool_any(source_a: Mapping[str, Any], source_b: Mapping[str, Any], keys: Sequence[str]) -> bool:
    for source in (source_a, source_b):
        for key in keys:
            if source.get(key) is True:
                return True
    return False


def _liquidation_formula_and_tiers_verified(*, provider: Mapping[str, Any], policy: Mapping[str, Any]) -> bool:
    return (
        provider.get("exact_exchange_liquidation_formula_verified") is True
        or (
            provider.get("liquidation_formula_verified") is True
            and provider.get("maintenance_margin_tiers_verified") is True
        )
        or (
            policy.get("liquidation_formula_verified") is True
            and policy.get("maintenance_margin_tiers_verified") is True
        )
    )


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _timestamp(value: Any) -> datetime:
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _json_compact(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=_json_default)


def _json_default(value: Any) -> str:
    if isinstance(value, Path):
        return _portable_path(value)
    return str(value)
