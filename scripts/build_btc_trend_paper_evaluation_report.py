#!/usr/bin/env python3
"""Build BTC trend v0 paper evaluation report."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_btc_trend_paper_readiness import DEFAULT_LEDGER_ROOT, EXPECTED_SELECTED_CANDIDATE  # noqa: E402


SCHEMA_VERSION = "btc_trend_paper_evaluation_report_v1"
DEFAULT_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_trend_paper_evaluation_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/BTC 趋势日线纸盘评估.md")
DEFAULT_BACKTEST_LEDGER = Path("artifacts/btc_trend_v0/latest/btc_trend_v0_position_ledger.csv")
MIN_COMPLETE_DAYS = 30


def build_btc_trend_paper_evaluation_report(
    *,
    repo_root: Path | None = None,
    ledger_root: Path = DEFAULT_LEDGER_ROOT,
    backtest_position_ledger: Path = DEFAULT_BACKTEST_LEDGER,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    strategy_id: str = EXPECTED_SELECTED_CANDIDATE,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    ledger = _resolve(root, ledger_root)
    output_path = _resolve(root, output)
    markdown_path = _resolve(root, markdown_output)
    backtest_ledger_path = _resolve(root, backtest_position_ledger)
    targets = _read_jsonl(ledger / "target_positions.jsonl")
    fills = _read_jsonl(ledger / "fills.jsonl")
    snapshots = _read_jsonl(ledger / "portfolio_snapshots.jsonl")
    state = _read_json(ledger / "validation_state.json")
    signal_consistency = _signal_consistency(
        targets=targets,
        backtest_position_ledger=backtest_ledger_path,
        strategy_id=strategy_id,
    )
    ledger_consistency = _ledger_consistency(snapshots=snapshots, fee_bps=5.0)
    metrics = _paper_metrics(targets=targets, fills=fills, snapshots=snapshots)
    blockers: list[str] = []
    if not ledger.exists():
        blockers.append("btc_trend_paper_ledger_missing")
    if not snapshots:
        blockers.append("btc_trend_paper_snapshots_missing")
    if not ledger_consistency["passed"]:
        blockers.append("btc_trend_paper_ledger_reconciliation_failed")
    if not signal_consistency["passed"]:
        blockers.append("btc_trend_paper_signal_consistency_failed")
    if str(state.get("strategy_id", strategy_id)) != strategy_id and state:
        blockers.append("btc_trend_paper_strategy_id_mismatch")
    if blockers:
        status = "trend_paper_blocked"
    elif int(metrics["paper_days"]) >= MIN_COMPLETE_DAYS:
        status = "trend_paper_complete_for_manual_review"
    else:
        status = "trend_paper_observing"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": status,
        "asset": "btc",
        "symbol": "BTCUSDT",
        "strategy_id": strategy_id,
        "ledger_root": _relpath(ledger, root),
        "backtest_position_ledger": _relpath(backtest_ledger_path, root),
        "minimum_complete_days": MIN_COMPLETE_DAYS,
        "metrics": metrics,
        "ledger_consistency": ledger_consistency,
        "signal_consistency": signal_consistency,
        "state": state,
        "guardrails": {
            "paper_evaluation_is_forward_record_not_alpha_validation": True,
            "strategy_validation_gate_required_before_strategy_claims": True,
            "live_ready": False,
            "live_order_allowed": False,
            "broker_calls_used": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "manual_review_required": True,
        },
        "continue_observing_allowed": status in {"trend_paper_observing", "trend_paper_complete_for_manual_review"},
        "blockers": _dedupe(blockers),
    }
    _write_json(output_path, payload)
    _write_text(markdown_path, _markdown(payload))
    return payload


def _paper_metrics(
    *,
    targets: list[Mapping[str, Any]],
    fills: list[Mapping[str, Any]],
    snapshots: list[Mapping[str, Any]],
) -> dict[str, Any]:
    equities = [_float_or(row.get("equity"), 0.0) for row in snapshots if _float_or(row.get("equity"), 0.0) > 0]
    initial = _float_or(snapshots[0].get("prior_equity"), equities[0] if equities else 0.0) if snapshots else 0.0
    final = equities[-1] if equities else initial
    total_return = ((final / initial) - 1.0) * 100.0 if initial > 0 else 0.0
    target_changes = sum(1 for row in targets if abs(_float_or(row.get("target_exposure"), 0.0) - _float_or(row.get("prior_exposure"), 0.0)) > 1e-12)
    total_fees = sum(_float_or(row.get("simulated_fee"), 0.0) for row in fills)
    return {
        "paper_days": len(snapshots),
        "target_position_count": len(targets),
        "target_position_change_count": target_changes,
        "simulated_fill_count": len(fills),
        "initial_equity": round(initial, 6),
        "final_equity": round(final, 6),
        "total_return_pct": round(total_return, 6),
        "max_drawdown_abs_pct": round(_max_drawdown_abs_pct(equities), 6),
        "total_simulated_fees": round(total_fees, 6),
    }


def _ledger_consistency(*, snapshots: list[Mapping[str, Any]], fee_bps: float) -> dict[str, Any]:
    bad = []
    for index, row in enumerate(snapshots, start=1):
        prior = _float_or(row.get("prior_equity"), 0.0)
        target = _float_or(row.get("target_exposure"), 0.0)
        daily_return = _float_or(row.get("daily_return"), 0.0)
        turnover = _float_or(row.get("turnover"), 0.0)
        expected = prior * (1.0 + target * daily_return - turnover * (fee_bps / 10_000.0))
        actual = _float_or(row.get("equity"), 0.0)
        if not math.isfinite(actual) or abs(expected - actual) > 0.01:
            bad.append(
                {
                    "row": index,
                    "timestamp": row.get("timestamp", ""),
                    "expected_equity": round(expected, 6),
                    "actual_equity": round(actual, 6),
                    "difference": round(abs(expected - actual), 8),
                }
            )
    return {"passed": not bad, "checked_rows": len(snapshots), "bad_rows": bad[:20]}


def _signal_consistency(
    *,
    targets: list[Mapping[str, Any]],
    backtest_position_ledger: Path,
    strategy_id: str,
) -> dict[str, Any]:
    if not backtest_position_ledger.exists():
        return {"passed": False, "checked_rows": 0, "mismatch_count": 0, "mismatches": [{"reason": "backtest_position_ledger_missing"}]}
    by_key: dict[tuple[str, str], dict[str, str]] = {}
    with backtest_position_ledger.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("strategy_id") == strategy_id:
                by_key[(str(row.get("strategy_id", "")), str(row.get("timestamp", "")))] = dict(row)
    mismatches = []
    for row in targets:
        key = (strategy_id, str(row.get("timestamp", "")))
        expected = by_key.get(key)
        if expected is None:
            mismatches.append({"timestamp": row.get("timestamp", ""), "reason": "missing_backtest_ledger_row"})
            continue
        if abs(_float_or(row.get("target_exposure"), 0.0) - _float_or(expected.get("exposure"), 0.0)) > 1e-9:
            mismatches.append({"timestamp": row.get("timestamp", ""), "reason": "target_exposure_mismatch"})
            continue
        if str(row.get("signal_timestamp", "")) != str(expected.get("signal_timestamp", "")):
            mismatches.append({"timestamp": row.get("timestamp", ""), "reason": "signal_timestamp_mismatch"})
    return {
        "passed": not mismatches,
        "checked_rows": len(targets),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:20],
    }


def _markdown(payload: Mapping[str, Any]) -> str:
    metrics = _mapping(payload.get("metrics"))
    lines = [
        "# BTC 趋势日线纸盘评估",
        "",
        f"生成时间：{payload.get('generated_at', '')}",
        "",
        "## 结论",
        "",
        f"状态：`{payload.get('status', '')}`",
        "",
        "本评估不输出 live-ready；任何实盘或进一步晋级都需要人工审阅。",
        "",
        "## 指标",
        "",
        "| 指标 | 数值 |",
        "| --- | ---: |",
        f"| 纸盘天数 | {metrics.get('paper_days', 0)} |",
        f"| 目标仓位记录 | {metrics.get('target_position_count', 0)} |",
        f"| 目标仓位变化 | {metrics.get('target_position_change_count', 0)} |",
        f"| 模拟成交数 | {metrics.get('simulated_fill_count', 0)} |",
        f"| 总收益率 | {metrics.get('total_return_pct', 0)}% |",
        f"| 最大回撤 | {metrics.get('max_drawdown_abs_pct', 0)}% |",
        f"| 模拟费用 | {metrics.get('total_simulated_fees', 0)} |",
        "",
        "## 检查",
        "",
        f"- 账本一致性：`{_mapping(payload.get('ledger_consistency')).get('passed', False)}`",
        f"- 回测信号一致性：`{_mapping(payload.get('signal_consistency')).get('passed', False)}`",
        f"- live ready：`{_mapping(payload.get('guardrails')).get('live_ready', False)}`",
        "",
    ]
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, Mapping):
            rows.append(dict(payload))
    return rows


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _float_or(value: object, default: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _max_drawdown_abs_pct(equity: list[float]) -> float:
    peak = 0.0
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return abs(worst) * 100.0


def _dedupe(values: list[str]) -> list[str]:
    out = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build BTC trend v0 paper evaluation report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--ledger-root", default=str(DEFAULT_LEDGER_ROOT))
    parser.add_argument("--backtest-position-ledger", default=str(DEFAULT_BACKTEST_LEDGER))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--strategy-id", default=EXPECTED_SELECTED_CANDIDATE)
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_btc_trend_paper_evaluation_report(
        repo_root=Path(args.repo_root),
        ledger_root=Path(args.ledger_root),
        backtest_position_ledger=Path(args.backtest_position_ledger),
        output=Path(args.output),
        markdown_output=Path(args.markdown_output),
        strategy_id=args.strategy_id,
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
