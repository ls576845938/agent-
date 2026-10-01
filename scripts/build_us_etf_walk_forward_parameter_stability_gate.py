#!/usr/bin/env python3
"""Build independent walk-forward and parameter-stability gate."""

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

SCHEMA_VERSION = "us_etf_walk_forward_parameter_stability_gate_v1"
DEFAULT_INPUT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_macro_rotation_walk_forward_stability_report.json")
DEFAULT_OUTPUT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_walk_forward_parameter_stability_gate_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US ETF Walk Forward 参数稳定性门禁.md")


def build_us_etf_walk_forward_parameter_stability_gate(
    *,
    repo_root: Path | None = None,
    input_report: Path = DEFAULT_INPUT,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    input_abs = _resolve(root, input_report)
    report = _read_json(input_abs)
    blockers: list[str] = []
    if not report:
        blockers.append("us_etf_wf_stability_source_report_missing")
    stability = _mapping(report.get("stability"))
    walk = _mapping(report.get("walk_forward"))
    fold_count = int(walk.get("fold_count", 0) or 0)
    alive_rate = _float_or(stability.get("alive_rate"), 0.0)
    candidate_count = int(stability.get("candidate_count", 0) or 0)
    stable_flag = stability.get("stable_enough_for_next_research_stage") is True
    if fold_count < 5:
        blockers.append("us_etf_wf_stability_fold_count_lt_5")
    if candidate_count < 12:
        blockers.append("us_etf_wf_stability_parameter_grid_too_small")
    if alive_rate < 0.5:
        blockers.append("us_etf_wf_stability_alive_rate_lt_50pct")
    if not stable_flag:
        blockers.append("us_etf_wf_stability_source_not_stable_enough")
    if report.get("paper_ready") is True or report.get("live_ready") is True:
        blockers.append("us_etf_wf_stability_source_has_forbidden_ready_flag")
    status = "research_only_manual_review_required" if not blockers else "blocked"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": status,
        "asset": "us_equity",
        "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
        "source_report": _relpath(input_abs, root),
        "fold_count": fold_count,
        "candidate_count": candidate_count,
        "alive_rate": alive_rate,
        "stable_enough_for_next_research_stage": stable_flag,
        "aggregate_oos_metrics": _mapping(walk.get("aggregate_oos_metrics")),
        "stability_summary": {
            "min": _mapping(stability.get("min")),
            "median": _mapping(stability.get("median")),
            "max": _mapping(stability.get("max")),
        },
        "blockers": _dedupe(blockers),
        "guardrails": {
            "research_only": True,
            "not_strategy_validation_pass": True,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US ETF Walk Forward 参数稳定性门禁",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        f"- 状态：`{payload.get('status', '')}`",
        f"- fold count：`{payload.get('fold_count', 0)}`",
        f"- candidate count：`{payload.get('candidate_count', 0)}`",
        f"- alive rate：`{payload.get('alive_rate', 0)}`",
        "",
        "该门禁只证明存在独立参数稳定性证据，不等于策略验证通过，不解锁 paper/live。",
        "",
        "## Blockers",
        "",
    ]
    blockers = _list(payload.get("blockers"))
    lines.extend([f"- `{item}`" for item in blockers] if blockers else ["- 无"])
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


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _float_or(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _dedupe(items: list[str]) -> list[str]:
    out = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build US ETF walk-forward parameter-stability gate.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--input-report", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_etf_walk_forward_parameter_stability_gate(
        repo_root=Path(args.repo_root),
        input_report=Path(args.input_report),
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
