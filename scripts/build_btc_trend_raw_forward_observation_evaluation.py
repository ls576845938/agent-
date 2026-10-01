#!/usr/bin/env python3
"""Build BTC raw trend forward-observation evaluation report."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_btc_only_trend_v0_report import _load_daily_bars  # noqa: E402
from scripts.check_btc_trend_raw_forward_observation_readiness import (  # noqa: E402
    DEFAULT_BUNDLE_DIR,
    DEFAULT_LEDGER_ROOT,
    EXPECTED_PRIMARY_CANDIDATE,
    EXPECTED_PRIMARY_FAMILY,
    EXPECTED_STRATEGY_ID,
)
from scripts.run_btc_trend_raw_forward_observation_roll import MOMENTUM_WINDOW_DAYS  # noqa: E402


SCHEMA_VERSION = "btc_trend_raw_forward_observation_evaluation_v1"
DEFAULT_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_trend_raw_forward_observation_evaluation_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/BTC 趋势原始策略前向观察评估.md")
MIN_COMPLETE_DAYS = 30
MILESTONES = (30, 60, 90)
DEFAULT_FEE_BPS = 5.0


def build_btc_trend_raw_forward_observation_evaluation(
    *,
    repo_root: Path | None = None,
    ledger_root: Path = DEFAULT_LEDGER_ROOT,
    bundle_dir: Path = DEFAULT_BUNDLE_DIR,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    strategy_id: str = EXPECTED_STRATEGY_ID,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    ledger = _resolve(root, ledger_root)
    bundle_path = _resolve(root, bundle_dir)
    output_path = _resolve(root, output)
    markdown_path = _resolve(root, markdown_output)

    targets = _read_jsonl(ledger / "target_positions.jsonl")
    fills = _read_jsonl(ledger / "fills.jsonl")
    snapshots = _read_jsonl(ledger / "portfolio_snapshots.jsonl")
    state = _read_json(ledger / "validation_state.json")
    daily = _load_daily_safely(bundle_path)

    ledger_consistency = _ledger_consistency(snapshots=snapshots)
    signal_consistency = _signal_consistency(targets=targets, daily=daily, strategy_id=strategy_id)
    metrics = _metrics(targets=targets, fills=fills, snapshots=snapshots)
    blockers: list[str] = []
    if not ledger.exists():
        blockers.append("btc_trend_raw_forward_ledger_missing")
    if not snapshots:
        blockers.append("btc_trend_raw_forward_snapshots_missing")
    if targets and len(targets) != len(snapshots):
        blockers.append("btc_trend_raw_forward_target_snapshot_count_mismatch")
    if not ledger_consistency["passed"]:
        blockers.append("btc_trend_raw_forward_ledger_reconciliation_failed")
    if not signal_consistency["passed"]:
        blockers.append("btc_trend_raw_forward_signal_consistency_failed")
    if state and str(state.get("strategy_id", "")) != strategy_id:
        blockers.append("btc_trend_raw_forward_strategy_id_mismatch")
    if state and bool(state.get("private_endpoint_used", False)):
        blockers.append("btc_trend_raw_forward_private_endpoint_used")
    if state and bool(state.get("order_endpoint_used", False)):
        blockers.append("btc_trend_raw_forward_order_endpoint_used")
    if state and bool(state.get("live_order_allowed", False)):
        blockers.append("btc_trend_raw_forward_live_order_allowed")

    if blockers:
        status = "raw_forward_blocked"
    elif int(metrics["observation_days"]) >= MIN_COMPLETE_DAYS:
        status = "raw_forward_complete_for_manual_review"
    else:
        status = "raw_forward_observing"

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": status,
        "asset": "btc",
        "symbol": "BTCUSDT",
        "strategy_id": strategy_id,
        "family_id": EXPECTED_PRIMARY_FAMILY,
        "candidate_id": EXPECTED_PRIMARY_CANDIDATE,
        "ledger_root": _relpath(ledger, root),
        "bundle_dir": _relpath(bundle_path, root),
        "minimum_complete_days": MIN_COMPLETE_DAYS,
        "milestones": list(MILESTONES),
        "metrics": metrics,
        "ledger_consistency": ledger_consistency,
        "signal_consistency": signal_consistency,
        "state": state,
        "guardrails": {
            "forward_observation_is_not_alpha_validation": True,
            "evaluation_does_not_output_live_ready": True,
            "paper_candidate_ready_not_implied": True,
            "live_ready": False,
            "live_order_allowed": False,
            "broker_calls_used": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "manual_review_required": True,
        },
        "continue_observing_allowed": status in {"raw_forward_observing", "raw_forward_complete_for_manual_review"},
        "blockers": _dedupe(blockers),
    }
    _write_json(output_path, payload)
    _write_text(markdown_path, _markdown(payload))
    return payload


def _metrics(
    *,
    targets: list[Mapping[str, Any]],
    fills: list[Mapping[str, Any]],
    snapshots: list[Mapping[str, Any]],
) -> dict[str, Any]:
    equities = [_float_or(row.get("equity"), 0.0) for row in snapshots if _float_or(row.get("equity"), 0.0) > 0]
    initial = _float_or(snapshots[0].get("prior_equity"), equities[0] if equities else 0.0) if snapshots else 0.0
    final = equities[-1] if equities else initial
    total_return = ((final / initial) - 1.0) * 100.0 if initial > 0 else 0.0
    target_changes = sum(
        1
        for row in targets
        if abs(_float_or(row.get("target_exposure"), 0.0) - _float_or(row.get("prior_exposure"), 0.0)) > 1e-12
    )
    total_fees = sum(_float_or(row.get("simulated_fee"), 0.0) for row in fills)
    return {
        "observation_days": len(snapshots),
        "target_position_count": len(targets),
        "target_position_change_count": target_changes,
        "simulated_fill_count": len(fills),
        "initial_equity": round(initial, 6),
        "final_equity": round(final, 6),
        "total_return_pct": round(total_return, 6),
        "max_drawdown_abs_pct": round(_max_drawdown_abs_pct(equities), 6),
        "total_simulated_fees": round(total_fees, 6),
        "milestone_progress": {str(day): len(snapshots) >= day for day in MILESTONES},
    }


def _ledger_consistency(*, snapshots: list[Mapping[str, Any]]) -> dict[str, Any]:
    bad = []
    for index, row in enumerate(snapshots, start=1):
        prior = _float_or(row.get("prior_equity"), 0.0)
        target = _float_or(row.get("target_exposure"), 0.0)
        daily_return = _float_or(row.get("daily_return"), 0.0)
        turnover = _float_or(row.get("turnover"), 0.0)
        fee_bps = _float_or(row.get("fee_bps"), DEFAULT_FEE_BPS)
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
    daily: pd.DataFrame | None,
    strategy_id: str,
) -> dict[str, Any]:
    if daily is None or daily.empty:
        return {
            "passed": False,
            "checked_rows": 0,
            "mismatch_count": 1,
            "mismatches": [{"reason": "daily_bundle_unreadable_or_empty"}],
        }
    frame = daily.copy().sort_index()
    close = frame["close"].astype(float)
    by_timestamp = {_timestamp_text(ts): pos for pos, ts in enumerate(close.index)}
    mismatches = []
    for index, row in enumerate(targets, start=1):
        if str(row.get("strategy_id", "")) != strategy_id:
            mismatches.append({"row": index, "timestamp": row.get("timestamp", ""), "reason": "strategy_id_mismatch"})
            continue
        effective_text = str(row.get("effective_timestamp") or row.get("timestamp") or "")
        effective_pos = by_timestamp.get(effective_text)
        if effective_pos is None:
            mismatches.append({"row": index, "timestamp": row.get("timestamp", ""), "reason": "effective_timestamp_missing_from_daily_bundle"})
            continue
        signal_pos = effective_pos - 1
        lookback_pos = signal_pos - MOMENTUM_WINDOW_DAYS
        if signal_pos < 0 or lookback_pos < 0:
            mismatches.append({"row": index, "timestamp": row.get("timestamp", ""), "reason": "insufficient_history_for_signal"})
            continue
        expected_signal_ts = _timestamp_text(close.index[signal_pos])
        expected_lookback_ts = _timestamp_text(close.index[lookback_pos])
        expected_signal_close = float(close.iloc[signal_pos])
        expected_lookback_close = float(close.iloc[lookback_pos])
        expected_raw = 1.0 if expected_lookback_close > 0 and expected_signal_close > expected_lookback_close else 0.0
        actual_signal_text = str(row.get("signal_timestamp", ""))
        actual_raw = _float_or(row.get("raw_signal"), 0.0)
        actual_target = _float_or(row.get("target_exposure"), 0.0)
        if actual_signal_text != expected_signal_ts:
            mismatches.append({"row": index, "timestamp": row.get("timestamp", ""), "reason": "signal_timestamp_mismatch"})
            continue
        if str(row.get("lookback_timestamp", "")) and str(row.get("lookback_timestamp", "")) != expected_lookback_ts:
            mismatches.append({"row": index, "timestamp": row.get("timestamp", ""), "reason": "lookback_timestamp_mismatch"})
            continue
        if not _timestamp_less(actual_signal_text, effective_text):
            mismatches.append({"row": index, "timestamp": row.get("timestamp", ""), "reason": "t_plus_one_violation"})
            continue
        if abs(actual_raw - expected_raw) > 1e-9 or abs(actual_target - expected_raw) > 1e-9:
            mismatches.append({"row": index, "timestamp": row.get("timestamp", ""), "reason": "raw_signal_or_target_exposure_mismatch"})
            continue
    return {
        "passed": not mismatches,
        "checked_rows": len(targets),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:20],
    }


def _load_daily_safely(bundle_dir: Path) -> pd.DataFrame | None:
    try:
        return _load_daily_bars(bundle_dir)
    except Exception:
        return None


def _markdown(payload: Mapping[str, Any]) -> str:
    metrics = _mapping(payload.get("metrics"))
    guardrails = _mapping(payload.get("guardrails"))
    lines = [
        "# BTC 趋势原始策略前向观察评估",
        "",
        f"生成时间：{payload.get('generated_at', '')}",
        "",
        "## 结论",
        "",
        f"状态：`{payload.get('status', '')}`",
        "",
        "本报告只评估 forward observation 账本、信号一致性和 T+1 运行质量；不输出 live-ready，不允许自动实盘或纸盘晋级。",
        "",
        "## 指标",
        "",
        "| 指标 | 数值 |",
        "| --- | ---: |",
        f"| 观察天数 | {metrics.get('observation_days', 0)} |",
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
        f"- 原始规则/T+1 一致性：`{_mapping(payload.get('signal_consistency')).get('passed', False)}`",
        f"- live ready：`{guardrails.get('live_ready', False)}`",
        f"- live order allowed：`{guardrails.get('live_order_allowed', False)}`",
        "",
    ]
    blockers = payload.get("blockers", [])
    if blockers:
        lines.extend(["## Blockers", ""])
        lines.extend(f"- `{item}`" for item in blockers)
        lines.append("")
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
        tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
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


def _timestamp_text(value: object) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.isoformat().replace("+00:00", "Z")


def _timestamp_less(left: str, right: str) -> bool:
    try:
        return pd.Timestamp(left) < pd.Timestamp(right)
    except Exception:
        return False


def _dedupe(values: list[str]) -> list[str]:
    out = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build BTC raw trend forward-observation evaluation report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--ledger-root", default=str(DEFAULT_LEDGER_ROOT))
    parser.add_argument("--bundle-dir", default=str(DEFAULT_BUNDLE_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--strategy-id", default=EXPECTED_STRATEGY_ID)
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_btc_trend_raw_forward_observation_evaluation(
        repo_root=Path(args.repo_root),
        ledger_root=Path(args.ledger_root),
        bundle_dir=Path(args.bundle_dir),
        output=Path(args.output),
        markdown_output=Path(args.markdown_output),
        strategy_id=args.strategy_id,
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
