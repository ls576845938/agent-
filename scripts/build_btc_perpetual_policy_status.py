from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.monitoring.perpetual_policy_status import (
    build_btc_perpetual_policy_status,
    render_btc_perpetual_policy_status_markdown,
)


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_perpetual_policy/latest")
DEFAULT_DAILY_OBSERVATION = Path("artifacts/btc_trend_v0/latest/btc_trend_raw_forward_observation_daily_run_report.json")
DEFAULT_SOURCES = {
    "perpetual_route_request": Path("artifacts/btc_perpetual_route_request/latest/btc_perpetual_route_request_report.json"),
    "paper_validation_replay": Path("artifacts/btc_paper_validation/latest/btc_paper_validation_replay_report.json"),
    "live_readiness": Path("artifacts/btc_live_readiness/latest/btc_live_readiness_risk_constitution_report.json"),
    "funding_ledger": Path("artifacts/btc_cost_model/latest/btc_funding_ledger_report.json"),
    "cost_model": Path("artifacts/btc_cost_model/latest/btc_cost_model_report.json"),
    "liquidation_risk_contract": Path("artifacts/btc_completion_evidence/latest/liquidation_risk_contract.json"),
}


def build_btc_perpetual_policy_status_file(
    *,
    repo_root: Path = Path("."),
    daily_observation: Path = DEFAULT_DAILY_OBSERVATION,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> dict[str, Any]:
    root = repo_root.resolve()
    generated_at = datetime.now(timezone.utc)
    daily_path = _resolve(root, daily_observation)
    daily = _load_json(daily_path) or {}
    target_path = _latest_target_path(daily)
    sources: dict[str, Mapping[str, Any] | None] = {
        "daily_observation": daily,
        "latest_target": _load_json(_resolve(root, target_path)) if target_path else None,
    }
    source_paths: dict[str, str] = {
        "daily_observation": _relpath(daily_path, root),
        "latest_target": _relpath(_resolve(root, target_path), root) if target_path else "",
    }
    for name, path in DEFAULT_SOURCES.items():
        resolved = _resolve(root, path)
        sources[name] = _load_json(resolved)
        source_paths[name] = _relpath(resolved, root)

    output_dir = _resolve(root, output_root)
    json_path = output_dir / "btc_perpetual_policy_status_report.json"
    markdown_path = output_dir / "btc_perpetual_policy_status_summary_cn.md"
    payload = build_btc_perpetual_policy_status(
        generated_at_utc=generated_at,
        sources=sources,
        source_paths=source_paths,
        report_paths={
            "json": _relpath(json_path, root),
            "markdown_cn": _relpath(markdown_path, root),
        },
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(render_btc_perpetual_policy_status_markdown(payload), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Build BTC perpetual route policy status report.")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--daily-observation", type=Path, default=DEFAULT_DAILY_OBSERVATION)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    payload = build_btc_perpetual_policy_status_file(
        repo_root=args.repo_root,
        daily_observation=args.daily_observation,
        output_root=args.output_root,
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "decision": payload["decision"],
                "policy_decision": payload["policy_decision"],
                "blockers": payload["blockers"],
                "warnings": payload["warnings"],
                "report_paths": payload.get("report_paths", {}),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _load_json(path: Path) -> Mapping[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, Mapping) else None


def _latest_target_path(daily: Mapping[str, Any]) -> Path | None:
    chain = daily.get("forecast_target_order_chain")
    if not isinstance(chain, Mapping):
        return None
    raw_path = chain.get("target_artifact")
    return Path(str(raw_path)) if raw_path else None


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
