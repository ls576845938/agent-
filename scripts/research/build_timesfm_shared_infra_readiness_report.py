from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quant_shared.forecasting.contracts import FORECASTING_CONTRACT_VERSION
from quant_shared.forecasting.timesfm_adapter import (
    TIMESFM_DEFAULT_CHECKPOINT,
    inspect_timesfm_environment,
)


SCHEMA_VERSION = "timesfm_shared_infra_readiness_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/shared_forecasting/timesfm/latest")
OFFICIAL_SOURCES = [
    {
        "name": "Google Research TimesFM GitHub",
        "url": "https://github.com/google-research/timesfm",
    },
    {
        "name": "TimesFM PyPI",
        "url": "https://pypi.org/project/timesfm/",
    },
    {
        "name": "TimesFM 2.5 Hugging Face checkpoint",
        "url": "https://huggingface.co/google/timesfm-2.5-200m-pytorch",
    },
]


def build_timesfm_shared_infra_readiness_report(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    timesfm_available: bool | None = None,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at_utc or datetime.now(timezone.utc)
    env = inspect_timesfm_environment()
    if timesfm_available is not None:
        env["timesfm_python_package_present"] = bool(timesfm_available)

    ready_for_smoke = bool(env["python_supported"] and env["timesfm_python_package_present"])
    status = "READY_FOR_P1_RESEARCH_SMOKE" if ready_for_smoke else "DESIGN_READY_OPTIONAL_DEPENDENCY_MISSING"
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at.isoformat(),
        "status": status,
        "scope": "shared_p1_research_tool_and_risk_auxiliary_model",
        "contract_version": FORECASTING_CONTRACT_VERSION,
        "environment": env,
        "model": {
            "provider": "Google Research",
            "model_family": "TimesFM",
            "default_checkpoint": TIMESFM_DEFAULT_CHECKPOINT,
            "integration_mode": "optional_adapter",
            "dependency_policy": "not_installed_in_default_runtime",
        },
        "module_boundary": {
            "shared_package": "quant_shared.forecasting",
            "asset_specific_consumers": ["quant_crypto", "quant_us"],
            "allowed_outputs": [
                "research forecast artifact",
                "risk auxiliary diagnostic",
                "model quality evidence",
            ],
            "disallowed_outputs": [
                "strategy skeleton generation",
                "paper queue write",
                "OMS or broker command",
                "live gate unlock",
            ],
        },
        "safety_flags": {
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
            "oms_access_allowed": False,
            "broker_access_allowed": False,
            "order_intent_allowed": False,
        },
        "rollout_plan": [
            {
                "phase": "P1_contract",
                "status": "complete_in_code",
                "description": "Shared request/result contract with point-in-time history validation.",
            },
            {
                "phase": "P1_optional_adapter",
                "status": "ready_when_dependency_installed" if ready_for_smoke else "waiting_for_dependency_install",
                "description": "Optional TimesFM adapter fails closed when the package or Python version is unsuitable.",
            },
            {
                "phase": "P1_asset_smoke",
                "status": "not_started",
                "description": "Run BTC and US-equity offline forecasts into artifacts only, then compare to existing baselines.",
            },
            {
                "phase": "P2_risk_auxiliary",
                "status": "blocked_until_p1_evidence_passes",
                "description": "Use forecast dispersion or error diagnostics as risk overlay input after OOS evidence review.",
            },
        ],
        "validation_gates": [
            "event_time <= decision_time for every input row",
            "walk-forward or purged OOS validation before any risk use",
            "baseline comparison against current BTC and US-equity signals",
            "drawdown and regime attribution before promotion discussion",
            "manual review required before paper candidate consideration",
        ],
        "notes_cn": [
            "这是全系统共享基础设施，不归 BTC 单独所有。",
            "当前只允许研究和风控辅助用途，不写 paper 队列，不解锁 live。",
            "TimesFM 是可选依赖；未安装时必须 fail-closed。",
        ],
        "sources": OFFICIAL_SOURCES,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "timesfm_shared_infra_readiness_report.json"
    markdown_path = output_dir / "timesfm_shared_infra_readiness_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    report["report_paths"] = {
        "json": str(json_path),
        "markdown_cn": str(markdown_path),
    }
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _render_markdown(report: dict[str, Any]) -> str:
    status = report["status"]
    env = report["environment"]
    safety = report["safety_flags"]
    lines = [
        "# TimesFM 共享预测基础设施 P1 readiness",
        "",
        f"- 状态：`{status}`",
        f"- 作用域：`{report['scope']}`",
        f"- 共享包：`{report['module_boundary']['shared_package']}`",
        f"- 默认 checkpoint：`{report['model']['default_checkpoint']}`",
        f"- Python 支持：`{env['python_supported']}`，TimesFM 已安装：`{env['timesfm_python_package_present']}`",
        "",
        "## 安全边界",
        "",
        f"- 写入 paper 队列：`{safety['paper_queue_write_allowed']}`",
        f"- 解锁 live：`{safety['live_unlock_allowed']}`",
        f"- 访问 OMS：`{safety['oms_access_allowed']}`",
        f"- 访问 broker：`{safety['broker_access_allowed']}`",
        "",
        "## 下一步",
        "",
        "1. 先跑 BTC 与美股离线 smoke，只产出 artifact。" if env["timesfm_python_package_present"] else "1. 在隔离研究环境安装 TimesFM 可选依赖。",
        "2. 与现有基线比较，并做样本外、行情分段、回撤归因后再讨论 paper candidate。",
        "3. 任何候选仍不得写入 paper 队列或解锁 live。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build TimesFM shared infra readiness report.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    report = build_timesfm_shared_infra_readiness_report(output_dir=args.output_dir)
    print(json.dumps({"status": report["status"], "report_paths": report["report_paths"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
