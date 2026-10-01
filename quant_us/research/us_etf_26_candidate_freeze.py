"""Fail-closed service for freezing the sole exploratory 26-ETF candidate."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping


SCHEMA_VERSION = "us_etf_26_candidate_strategy_card_v1"
SOURCE_SCHEMA_VERSION = "us_etf_26_complete_return_multitimeframe_report_v1"
EXPECTED_COMBINATION_COUNT = 26 * 7
EXPECTED_COST_LEVELS = (0.0, 5.0, 10.0, 25.0, 50.0)


def build_candidate_strategy_card(
    *,
    repo_root: Path,
    config_path: Path,
    source_report_path: Path,
    output_root: Path,
    generated_at: str | None = None,
    code_commit: str | None = None,
) -> dict[str, Any]:
    """Validate source evidence and write a single replayable research-only card."""

    root = repo_root.resolve()
    config_abs = _absolute(config_path, root)
    report_abs = _absolute(source_report_path, root)
    output_abs = _absolute(output_root, root)
    config = _read_object(config_abs)
    source = _read_object(report_abs)
    audit = audit_source_batch(root=root, config=config, source=source)
    params_hash = _stable_hash(config["parameters"])
    cost_model_hash = _stable_hash(config["cost_model"])
    commit = code_commit or _git_head(root)
    if not commit:
        raise ValueError("current HEAD is required for candidate card freshness")

    source_artifacts = _source_artifact_inventory(root=root, source=source)
    card = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "status": "frozen_exploratory_research_only",
        "decision": "sole_candidate_frozen_for_future_independent_confirmation_no_promotion_no_paper_no_live",
        "candidate_id": config["candidate_id"],
        "strategy_version": config["strategy_version"],
        "code_commit": commit,
        "branch": _git_branch(root),
        "params_hash": params_hash,
        "cost_model_hash": cost_model_hash,
        "parameters": config["parameters"],
        "universe": config["universe"],
        "timeframes_screened": config["timeframes"],
        "selected_candidate": {
            **config["selection"],
            "source_metrics": audit["selected_source_metrics"],
        },
        "data": config["data"],
        "research_window": config["research_window"],
        "independent_confirmation_window": config["independent_confirmation_window"],
        "cost_model": config["cost_model"],
        "signal_rule": config["signal_rule"],
        "execution_rule": config["execution_rule"],
        "position_rule": config["position_rule"],
        "allowed_uses": config["allowed_uses"],
        "prohibited_uses": config["prohibited_uses"],
        "source_evidence": {
            "report_path": _relpath(report_abs, root),
            "report_sha256": _sha256_file(report_abs),
            "report_code_commit": source["code_commit"],
            "batch_audit": audit,
            "artifacts": source_artifacts,
        },
        "blockers": [
            *source.get("promotion_blockers", []),
            "exploratory_selection_sample_is_not_clean_holdout",
            "independent_confirmation_window_not_complete",
            "candidate_is_synthetic_margin_research_reference_not_broker_executable",
        ],
        "guardrails": {
            "research_only": True,
            "promotion_unlock_allowed": False,
            "paper_queue_write_allowed": False,
            "paper_order_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_used": False,
            "broker_endpoint_used": False,
            "order_endpoint_used": False,
            "real_order_submitted": False,
        },
    }
    output_abs.mkdir(parents=True, exist_ok=True)
    _write_json(output_abs / "us_etf_26_candidate_strategy_card.json", card)
    (output_abs / "us_etf_26_candidate_strategy_card.md").write_text(
        _markdown(card), encoding="utf-8"
    )
    return card


def audit_source_batch(
    *, root: Path, config: Mapping[str, Any], source: Mapping[str, Any]
) -> dict[str, Any]:
    """Enforce 26x7 completeness, no-lookahead, and monotonic cost contracts."""

    if source.get("schema_version") != SOURCE_SCHEMA_VERSION:
        raise ValueError("source report schema version mismatch")
    if source.get("status") != "complete_research_only":
        raise ValueError("source report is not complete_research_only")
    if source.get("data", {}).get("data_version") != config.get("data", {}).get("data_version"):
        raise ValueError("source report data version mismatch")
    if source.get("data", {}).get("batch_sha256") != config.get("data", {}).get("aggregate_sha256"):
        raise ValueError("source report aggregate hash mismatch")

    matrix = list(source.get("matrix_rows", []))
    expected_pairs = {
        (symbol, timeframe)
        for symbol in config.get("universe", [])
        for timeframe in config.get("timeframes", [])
    }
    actual_pairs = {(row.get("symbol"), row.get("timeframe")) for row in matrix}
    if len(matrix) != EXPECTED_COMBINATION_COUNT or actual_pairs != expected_pairs:
        raise ValueError("26x7 matrix completeness contract failed")

    cost_rows = list(source.get("cost_stress_rows", []))
    grouped_costs: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in cost_rows:
        grouped_costs.setdefault((str(row.get("symbol")), str(row.get("timeframe"))), []).append(row)
    if set(grouped_costs) != expected_pairs:
        raise ValueError("cost stress combination coverage failed")
    for pair, rows in grouped_costs.items():
        ordered = sorted(rows, key=lambda row: float(row["cost_bps"]))
        if tuple(float(row["cost_bps"]) for row in ordered) != EXPECTED_COST_LEVELS:
            raise ValueError(f"cost stress levels mismatch: {pair}")
        for previous, current in zip(ordered, ordered[1:]):
            if float(current["final_equity"]) > float(previous["final_equity"]) + 1e-6:
                raise ValueError(f"cost monotonic final equity violation: {pair}")
            if float(current["cost_drag_pct"]) + 1e-6 < float(previous["cost_drag_pct"]):
                raise ValueError(f"cost monotonic drag violation: {pair}")

    walk_rows = list(source.get("walk_forward_rows", []))
    walk_pairs = {(row.get("symbol"), row.get("timeframe")) for row in walk_rows}
    if walk_pairs != expected_pairs:
        raise ValueError("walk-forward combination coverage failed")
    if any(
        row.get("parameters_frozen") is not True
        or row.get("training_selection_used") is not False
        for row in walk_rows
    ):
        raise ValueError("walk-forward frozen-parameter contract failed")

    walk_contract = source.get("walk_forward_contract", {})
    if (
        walk_contract.get("sample_role") != "exploratory_selection_sample"
        or walk_contract.get("selection_sample_reused") is not True
        or walk_contract.get("holdout_reused_for_selection") is not True
        or walk_contract.get("clean_holdout") is not False
    ):
        raise ValueError("exploratory sample classification contract failed")
    lookahead = source.get("no_lookahead_contract", {})
    if (
        lookahead.get("status") != "pass_for_research_replay"
        or "shifted one bar" not in str(lookahead.get("execution_time_rule", ""))
        or lookahead.get("future_adjustment_available_time_replay_complete") is not False
    ):
        raise ValueError("no-lookahead research contract failed")

    surviving = [row for row in matrix if row.get("three_x_portfolio_zero") is False]
    selected = max(surviving, key=lambda row: float(row["three_x_total_return_pct"]))
    selection = config.get("selection", {})
    if (selected.get("symbol"), selected.get("timeframe")) != (
        selection.get("symbol"),
        selection.get("timeframe"),
    ):
        raise ValueError("configured candidate does not match frozen selection rule")
    if dict(selected.get("params", {})) != dict(config.get("parameters", {})):
        raise ValueError("configured parameters do not match selected source row")

    return {
        "status": "pass_research_only",
        "matrix_combination_count": len(matrix),
        "cost_stress_row_count": len(cost_rows),
        "walk_forward_row_count": len(walk_rows),
        "cost_monotonic_violation_count": 0,
        "no_lookahead_contract_passed": True,
        "exploratory_sample_classification_passed": True,
        "selected_source_metrics": {
            "total_return_pct": selected["three_x_total_return_pct"],
            "annual_return_pct": selected["three_x_annual_return_pct"],
            "sharpe": selected["three_x_sharpe"],
            "max_drawdown_abs_pct": selected["three_x_max_drawdown_abs_pct"],
            "portfolio_zero": selected["three_x_portfolio_zero"],
        },
    }


def _source_artifact_inventory(*, root: Path, source: Mapping[str, Any]) -> dict[str, Any]:
    inventory: dict[str, Any] = {}
    for key in ("json", "markdown", "matrix_csv", "cost_stress_csv", "walk_forward_csv"):
        raw_path = source.get("outputs", {}).get(key)
        if not raw_path:
            raise ValueError(f"source output path missing: {key}")
        path = _absolute(Path(str(raw_path)), root)
        if not path.is_file():
            raise ValueError(f"source output missing: {key}")
        record: dict[str, Any] = {
            "path": _relpath(path, root),
            "sha256": _sha256_file(path),
        }
        if path.suffix.lower() == ".csv":
            with path.open("r", encoding="utf-8", newline="") as handle:
                record["row_count"] = sum(1 for _ in csv.DictReader(handle))
        inventory[key] = record
    if "本报告不能解锁 paper/live" not in _absolute(
        Path(str(source["outputs"]["markdown"])), root
    ).read_text(encoding="utf-8"):
        raise ValueError("markdown research-only warning missing")
    return inventory


def _markdown(card: Mapping[str, Any]) -> str:
    confirmation = card["independent_confirmation_window"]
    return "\n".join(
        [
            "# 26 ETF 唯一候选策略卡",
            "",
            f"- Candidate ID：`{card['candidate_id']}`",
            f"- 状态：`{card['status']}`",
            f"- 当前代码：`{card['code_commit']}`",
            f"- 数据版本：`{card['data']['data_version']}`",
            f"- 参数哈希：`{card['params_hash']}`",
            f"- 成本模型哈希：`{card['cost_model_hash']}`",
            "- 已看过的 2018-2026 样本用于 ETF/周期选择，只能视为 exploratory，不是干净 holdout。",
            f"- 独立确认窗口：`{confirmation['start']}` 至 `{confirmation['end']}`；窗口结束前禁止评价或调参。",
            "- 本卡不能解锁 promotion、paper、live、private 或 order；所有交易安全旗标保持 false。",
            "",
            "## Blockers",
            "",
            *[f"- `{value}`" for value in card["blockers"]],
            "",
        ]
    )


def _read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _stable_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_head(root: Path) -> str:
    return _git(["rev-parse", "HEAD"], root)


def _git_branch(root: Path) -> str:
    return _git(["branch", "--show-current"], root)


def _git(args: list[str], root: Path) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=root, check=False, capture_output=True, text=True
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _absolute(path: Path, root: Path) -> Path:
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)
