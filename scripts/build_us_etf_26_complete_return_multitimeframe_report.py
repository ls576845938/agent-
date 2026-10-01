#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant_us.data.hf_etf_research_dataset import HFETFResearchDataset
from quant_us.research.us_etf_26_complete_return_multitimeframe import (
    BASE_COST_BPS,
    COST_LEVELS_BPS,
    MARGIN_INTEREST_ANNUAL,
    REQUESTED_TIMEFRAMES,
    SYNTHETIC_MARGIN_MULTIPLIER,
    run_symbol_complete_return_multitimeframe,
    summarize_matrix,
)
from tools.agent_governance.shared_data import (
    default_shared_data_root,
    resolve_manifest_file,
)


SCHEMA_VERSION = "us_etf_26_complete_return_multitimeframe_report_v1"
DEFAULT_MANIFEST = Path(
    ".agent/data_manifests/us-equity-hf-etf26-1min/"
    "hf-data-library-etf26-clean-1min-6d6b07e77962.json"
)
DEFAULT_OUTPUT_ROOT = Path(
    "artifacts/us_equity_etf_26_complete_return_multitimeframe/latest"
)


def build_us_etf_26_complete_return_multitimeframe_report(
    *,
    repo_root: Path,
    manifest_path: Path = DEFAULT_MANIFEST,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    start: str = "2018-01-01",
    end: str = "2026-07-10",
    workers: int = 2,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    manifest_abs = manifest_path if manifest_path.is_absolute() else root / manifest_path
    output_abs = output_root if output_root.is_absolute() else root / output_root
    output_abs.mkdir(parents=True, exist_ok=True)
    checkpoint_root = output_abs / "symbol_results"
    checkpoint_root.mkdir(parents=True, exist_ok=True)
    shared_root = default_shared_data_root(root)
    dataset_root = resolve_manifest_file(
        manifest_abs,
        shared_root=shared_root,
        verify_files=False,
    )
    dataset = HFETFResearchDataset(manifest_abs, dataset_root=dataset_root)
    tasks = [
        {
            "path": entry.path,
            "symbol": symbol,
            "start": start,
            "end": end,
            "timeframes": REQUESTED_TIMEFRAMES,
        }
        for symbol, entry in dataset.entries.items()
    ]
    if workers not in {1, 2}:
        raise ValueError("workers must be 1 or 2 for bounded-memory ETF research")
    code_commit = _git(["rev-parse", "--short", "HEAD"], cwd=root)
    checkpoint_contract = {
        "code_commit": code_commit,
        "data_version": dataset.data_version,
        "start": start,
        "end": end,
        "timeframes": list(REQUESTED_TIMEFRAMES),
    }
    symbol_results: list[dict[str, Any]] = []
    pending_tasks: list[dict[str, Any]] = []
    for task in tasks:
        checkpoint_path = checkpoint_root / f"{task['symbol']}.json"
        checkpoint = _read_json(checkpoint_path)
        if checkpoint.get("checkpoint_contract") == checkpoint_contract:
            symbol_results.append(dict(checkpoint["result"]))
            print(f"resumed checkpoint: {task['symbol']}", flush=True)
        else:
            pending_tasks.append(task)
    completed_count = len(symbol_results)
    for offset in range(0, len(pending_tasks), workers):
        batch = pending_tasks[offset : offset + workers]
        with ProcessPoolExecutor(max_workers=len(batch)) as executor:
            futures = {
                executor.submit(_run_task, task): str(task["symbol"])
                for task in batch
            }
            for future in as_completed(futures):
                symbol = futures[future]
                result = future.result()
                symbol_results.append(result)
                _write_json(
                    checkpoint_root / f"{symbol}.json",
                    {
                        "checkpoint_contract": checkpoint_contract,
                        "result": result,
                    },
                )
                completed_count += 1
                print(
                    f"completed {completed_count}/{len(tasks)}: {symbol}",
                    flush=True,
                )
    symbol_results.sort(key=lambda item: str(item["symbol"]))

    matrix_rows = [
        row for result in symbol_results for row in result["matrix_rows"]
    ]
    cost_rows = [
        row for result in symbol_results for row in result["cost_stress_rows"]
    ]
    fold_rows = [
        row for result in symbol_results for row in result["walk_forward_rows"]
    ]
    blockers = [
        blocker for result in symbol_results for blocker in result["blockers"]
    ]
    metadata = dataset.research_metadata()
    summary = summarize_matrix(matrix_rows)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "status": "complete_research_only" if not blockers else "partial_research_only",
        "decision": "complete_return_rule_cross_etf_multitimeframe_danger_reference_no_paper_no_live",
        "code_commit": code_commit,
        "branch": _git(["branch", "--show-current"], cwd=root),
        "data": {
            **metadata,
            "manifest_path": _relpath(manifest_abs, root),
            "dataset_root": str(dataset_root),
            "consumer_read_only": True,
            "immutable_version": True,
            "requested_start": start,
            "requested_end": end,
            "symbol_count": len(dataset.symbols),
        },
        "strategy_contract": {
            "source_strategy": "us_tqqq_complete_return_fixed_signal_rollover_danger_reference",
            "signal_asset": "each ETF uses its own completed OHLC bars",
            "traded_asset": "same ETF as signal asset",
            "signal_rule": "prior-session 50/200 EMA trend plus frozen Donchian breakout and 3 ATR trailing exit",
            "execution_rule": "signal shifts one bar; exposure changes at next bar open",
            "timeframes": list(REQUESTED_TIMEFRAMES),
            "parameter_selection_per_symbol_allowed": False,
            "parameter_selection_per_timeframe_allowed": False,
            "one_x_reference": True,
            "three_x_synthetic_margin_multiplier": SYNTHETIC_MARGIN_MULTIPLIER,
            "margin_interest_annual": MARGIN_INTEREST_ANNUAL,
            "base_cost_bps": BASE_COST_BPS,
            "cost_stress_bps": list(COST_LEVELS_BPS),
            "rollover_policy": "no_rollover_core_compounding_reference",
            "important_non_equivalence": "These 26 ETFs are unlevered. Three-times margin is three-times ETF exposure, not the original TQQQ three-times margin on top of TQQQ intrinsic leverage.",
        },
        "matrix_rows": matrix_rows,
        "cost_stress_rows": cost_rows,
        "walk_forward_rows": fold_rows,
        "walk_forward_contract": _research_sample_contract(),
        "no_lookahead_contract": {
            "status": "pass_for_research_replay",
            "feature_visibility_rule": "trend and channel inputs use prior completed bars only",
            "decision_time_rule": "raw signal is computed after the current completed bar",
            "execution_time_rule": "effective signal is shifted one bar and applied to the next bar open-to-open return",
            "future_adjustment_available_time_replay_complete": False,
        },
        "summary": summary,
        "outputs": {
            "json": _relpath(output_abs / "us_etf_26_complete_return_multitimeframe_report.json", root),
            "markdown": _relpath(output_abs / "us_etf_26_complete_return_multitimeframe_report.md", root),
            "matrix_csv": _relpath(output_abs / "us_etf_26_complete_return_multitimeframe_matrix.csv", root),
            "cost_stress_csv": _relpath(output_abs / "us_etf_26_complete_return_multitimeframe_cost_stress.csv", root),
            "walk_forward_csv": _relpath(output_abs / "us_etf_26_complete_return_multitimeframe_walk_forward.csv", root),
            "symbol_results_root": _relpath(checkpoint_root, root),
        },
        "research_blockers": blockers,
        "promotion_blockers": [
            *metadata["blockers"],
            "synthetic_margin_danger_reference_not_broker_executable",
            "event_driven_fill_position_cash_ledger_not_generated",
            "cross_etf_result_not_equivalent_to_original_tqqq_intrinsic_leverage",
            "historical_2018_2026_sample_used_for_candidate_selection_not_clean_holdout",
        ],
        "guardrails": {
            "research_only": True,
            "private_endpoint_used": False,
            "broker_endpoint_used": False,
            "order_endpoint_used": False,
            "real_order_submitted": False,
            "paper_queue_write_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
            "promotion_unlock_allowed": False,
        },
    }
    _write_json(
        output_abs / "us_etf_26_complete_return_multitimeframe_report.json",
        report,
    )
    _write_csv(
        output_abs / "us_etf_26_complete_return_multitimeframe_matrix.csv",
        matrix_rows,
    )
    _write_csv(
        output_abs / "us_etf_26_complete_return_multitimeframe_cost_stress.csv",
        cost_rows,
    )
    _write_csv(
        output_abs / "us_etf_26_complete_return_multitimeframe_walk_forward.csv",
        fold_rows,
    )
    (output_abs / "us_etf_26_complete_return_multitimeframe_report.md").write_text(
        _markdown(report),
        encoding="utf-8",
    )
    return report


def _run_task(task: Mapping[str, Any]) -> dict[str, Any]:
    return run_symbol_complete_return_multitimeframe(
        path=Path(task["path"]),
        symbol=str(task["symbol"]),
        start=str(task["start"]),
        end=str(task["end"]),
        timeframes=tuple(task["timeframes"]),
    )


def _research_sample_contract() -> dict[str, Any]:
    """Classify the already-screened history as exploratory, never clean OOS."""

    return {
        "test_window": "calendar_year_from_2020",
        "parameters_frozen": True,
        "training_selection": "none",
        "sample_role": "exploratory_selection_sample",
        "selection_sample_reused": True,
        "holdout_reused_for_selection": True,
        "clean_holdout": False,
        "new_independent_confirmation_window_required": True,
    }


def _markdown(report: Mapping[str, Any]) -> str:
    surviving = [
        row for row in report["matrix_rows"] if not row["three_x_portfolio_zero"]
    ]
    top = sorted(
        surviving,
        key=lambda row: float(row["three_x_total_return_pct"]),
        reverse=True,
    )[:20]
    lines = [
        "# 26 ETF 万倍收益规则多周期危险参考",
        "",
        f"- 状态：`{report['status']}`",
        f"- 数据版本：`{report['data']['data_version']}`",
        f"- 组合数：`{report['summary']['combination_count']}`",
        f"- 归零组合：`{report['summary']['portfolio_zero_count']}`",
        "- 3×仅为合成保证金研究，不等同原 TQQQ 的内生 3× 再叠加保证金。",
        "- 本报告不能解锁 paper/live。",
        "",
        "| 标的 | 周期 | 3×总收益 | 年化 | Sharpe | 最大回撤 | 1×总收益 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in top:
        lines.append(
            f"| {row['symbol']} | {row['timeframe']} | {row['three_x_total_return_pct']}% | "
            f"{row['three_x_annual_return_pct']}% | {row['three_x_sharpe']} | "
            f"{row['three_x_max_drawdown_abs_pct']}% | {row['one_x_total_return_pct']}% |"
        )
    lines.extend(["", "## Promotion blockers", ""])
    lines.extend(f"- `{value}`" for value in report["promotion_blockers"])
    lines.append("")
    return "\n".join(lines)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _git(args: list[str], *, cwd: Path) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply the frozen complete-return danger-reference rule to 26 ETFs and six timeframes."
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--end", default="2026-07-10")
    parser.add_argument("--workers", type=int, choices=[1, 2], default=2)
    args = parser.parse_args()
    report = build_us_etf_26_complete_return_multitimeframe_report(
        repo_root=Path(args.repo_root),
        manifest_path=Path(args.manifest),
        output_root=Path(args.output_root),
        start=args.start,
        end=args.end,
        workers=args.workers,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "summary": report["summary"],
                "promotion_blockers": report["promotion_blockers"],
                "guardrails": report["guardrails"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
