from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.exchange.runtime import build_btc_exchange_runtime_local_probe_artifact  # noqa: E402


DEFAULT_OUTPUT_DIR = Path("artifacts/btc_exchange_runtime/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_exchange_runtime_local_probe_report.json"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_exchange_runtime_local_probe_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "btc_exchange_runtime_local_probe_safety_status.json"


def build_btc_exchange_runtime_local_probe_report(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    cancel_only: bool = True,
) -> dict[str, Any]:
    generated = (generated_at_utc or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    report = build_btc_exchange_runtime_local_probe_artifact(
        observed_at_utc=generated,
        local_receive_time_utc=generated,
        exchange_server_time_utc=generated + timedelta(milliseconds=350),
        venue="okx",
        instrument_id="BTC-USDT-SWAP",
        public_ws_sequences=(100, 101, 104, 105),
        public_gapfill_sequences=(102, 103),
        metadata_version="okx_btc_usdt_swap_local_probe_v1",
        rate_limit_budget_remaining=42,
        order_rate_budget_remaining=0 if cancel_only else 12,
        cancel_only=cancel_only,
        mode="read_only",
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name
    report["outputs"] = {
        "json": _portable_path(report_path),
        "summary_cn": _portable_path(markdown_path),
        "safety_status": _portable_path(safety_path),
    }
    _write_json(report_path, report)
    _write_text(markdown_path, render_btc_exchange_runtime_local_probe_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_btc_exchange_runtime_local_probe_markdown(report: Mapping[str, Any]) -> str:
    server_time = _mapping(report.get("server_time_offset_diagnostics"))
    replay = _mapping(report.get("ws_sequence_gapfill_replay"))
    cancel = _mapping(report.get("cancel_only_state"))
    rate = _mapping(report.get("rate_limit_budget_explanation"))
    public_budget = _mapping(rate.get("public_rest_or_ws_budget"))
    order_budget = _mapping(rate.get("order_entry_budget"))
    metadata = _mapping(report.get("metadata_version_diagnostics"))
    guardrails = _mapping(report.get("guardrails"))
    lines = [
        "# BTC Exchange Runtime 本地 Replay/Probe 报告",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- blocker 数：`{len(list(report.get('blockers', [])))}`",
        f"- paper 队列：`{guardrails.get('paper_queue_write_allowed')}`",
        f"- live 解锁：`{guardrails.get('live_unlock_allowed')}`",
        f"- private/order endpoint：`{guardrails.get('private_endpoint_used')}` / `{guardrails.get('order_endpoint_used')}`",
        "",
        "## 本地探针检查项",
        "",
        f"- server time offset：`{server_time.get('offset_ms')}` ms，阈值 `{server_time.get('threshold_ms')}` ms，通过：`{server_time.get('within_threshold')}`",
        f"- metadata version：`{metadata.get('metadata_version')}`，存在：`{metadata.get('present')}`",
        f"- public WS sequence：缺口 `{replay.get('missing_sequences')}`，已补 `{replay.get('recovered_sequences')}`，未补 `{replay.get('unrecovered_sequences')}`",
        f"- cancel-only：`{cancel.get('cancel_only')}`，新开仓/加仓阻断：`{cancel.get('new_orders_blocked')}`",
        f"- public budget：剩余 `{public_budget.get('remaining')}` / 阈值 `{public_budget.get('threshold')}`，状态 `{public_budget.get('status')}`",
        f"- order budget：剩余 `{order_budget.get('remaining')}` / 阈值 `{order_budget.get('threshold')}`，状态 `{order_budget.get('status')}`",
        "",
        "## 为什么仍然不能放行",
        "",
        "- 这是本地 deterministic replay/probe，只验证 SRE 合约逻辑，不代表真实交易所 runtime 已接通。",
        "- 本报告没有触碰 private/account/order endpoint，没有真实订单、真实成交或真实撤单证据。",
        "- cancel-only 状态下只能验证阻断逻辑，不能允许新订单。",
        "- private WS 没有接入，所以订单/成交事件链仍然必须 fail-closed。",
    ]
    blockers = list(report.get("blockers", []))
    if blockers:
        lines.extend(["", "## 当前 blockers", ""])
        lines.extend(f"- `{item}`" for item in blockers)
    return "\n".join(lines) + "\n"


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_exchange_runtime_local_probe_safety_status_v1",
        "status": "research_only",
        "decision": report.get("decision"),
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "paper_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "blockers": list(report.get("blockers", [])),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC exchange runtime local replay/probe report.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--no-cancel-only", action="store_true", help="Run the deterministic fixture without cancel-only.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_exchange_runtime_local_probe_report(
        output_dir=args.output_dir,
        cancel_only=not args.no_cancel_only,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "blocker_count": len(report["blockers"]),
                "server_time_offset_ms": report["server_time_offset_diagnostics"]["offset_ms"],
                "ws_gap_recovered": report["ws_sequence_gapfill_replay"]["recovered"],
                "cancel_only": report["cancel_only_state"]["cancel_only"],
                "private_endpoint_used": report["guardrails"]["private_endpoint_used"],
                "order_endpoint_used": report["guardrails"]["order_endpoint_used"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _portable_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
