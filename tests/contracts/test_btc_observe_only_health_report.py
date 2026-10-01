from __future__ import annotations

import csv
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from quant_crypto.research.btc_observe_only_health_report import build_btc_observe_only_health_report


TS = datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc)


def test_observe_only_health_blocks_under_30d_and_calendar_gaps(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path, dates=[date(2026, 6, 28), date(2026, 7, 1)])

    report = _build(tmp_path, paths)

    assert report["status"] == "blocked_research_only"
    assert report["summary"]["line_count"] == 3
    assert report["summary"]["minimum_30d_complete_count"] == 0
    assert report["summary"]["target_60d_complete_count"] == 0
    assert report["summary"]["safety_violation_count"] == 0
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    by_line = {row["line_id"]: row for row in report["matrix"]}
    assert by_line["long_short_donchian_top5"]["observation_days"] == 2
    assert by_line["long_short_donchian_top5"]["max_calendar_gap_days"] == 3
    assert "forward_observation_under_30d" in by_line["long_short_donchian_top5"]["line_blockers"]
    assert "observation_calendar_gap_gt_1d" in by_line["long_short_donchian_top5"]["line_blockers"]
    assert any("long_short_donchian_top5:forward_observation_under_30d" in item for item in report["blockers"])


def test_observe_only_health_detects_any_paper_live_or_order_true_flag(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path, dates=[date(2026, 7, 1)])
    long_short_report = json.loads(paths["long_short_report"].read_text(encoding="utf-8"))
    long_short_report["gate"]["live_unlock_allowed"] = True
    paths["long_short_report"].write_text(json.dumps(long_short_report), encoding="utf-8")
    rows = list(csv.DictReader(paths["long_short_rows"].open("r", encoding="utf-8", newline="")))
    rows[0]["paper_queue_write_allowed"] = "True"
    _write_csv(paths["long_short_rows"], rows)

    report = _build(tmp_path, paths)

    by_line = {row["line_id"]: row for row in report["matrix"]}
    assert by_line["long_short_donchian_top5"]["safety_violation_count"] == 2
    assert "paper_live_or_order_safety_flag_true" in by_line["long_short_donchian_top5"]["line_blockers"]
    assert any("long_short_donchian_top5:paper_live_or_order_safety_flag_true" in item for item in report["blockers"])
    assert report["guardrails"]["order_endpoint_used"] is False


def test_observe_only_health_detects_report_progress_csv_day_mismatch(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path, dates=[date(2026, 6, 28), date(2026, 7, 1)])
    attack_report = json.loads(paths["attack_report"].read_text(encoding="utf-8"))
    attack_report["observation_progress"]["observation_days"] = 3
    paths["attack_report"].write_text(json.dumps(attack_report), encoding="utf-8")

    report = _build(tmp_path, paths)

    by_line = {row["line_id"]: row for row in report["matrix"]}
    assert by_line["high_octane_attack_sleeve_v2"]["report_observation_days"] == 3
    assert by_line["high_octane_attack_sleeve_v2"]["observation_days"] == 2
    assert by_line["high_octane_attack_sleeve_v2"]["report_observation_days_matches_rows"] is False
    assert "report_progress_days_mismatch_csv_unique_days" in by_line["high_octane_attack_sleeve_v2"]["line_blockers"]


def test_observe_only_health_can_complete_after_60_consecutive_days_without_unlocking_paper_live(tmp_path: Path) -> None:
    dates = [date(2026, 5, 3) + timedelta(days=idx) for idx in range(60)]
    paths = _write_inputs(tmp_path, dates=dates)

    report = _build(tmp_path, paths)

    assert report["status"] == "complete_research_only"
    assert report["summary"]["minimum_30d_complete_count"] == 3
    assert report["summary"]["target_60d_complete_count"] == 3
    assert report["summary"]["all_lines_continuity_passed"] is True
    assert report["blockers"] == []
    assert report["gate"]["paper_order_intake_allowed"] is False
    assert report["gate"]["position_increase_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_order_allowed"] is False
    assert safety["real_order_submitted"] is False


def _build(tmp_path: Path, paths: dict[str, Path]) -> dict[str, object]:
    return build_btc_observe_only_health_report(
        output_dir=tmp_path / "out",
        long_short_report_path=paths["long_short_report"],
        long_short_rows_path=paths["long_short_rows"],
        attack_report_path=paths["attack_report"],
        attack_rows_path=paths["attack_rows"],
        high_yield_report_path=paths["high_yield_report"],
        high_yield_rows_path=paths["high_yield_rows"],
        generated_at_utc=TS,
    )


def _write_inputs(tmp_path: Path, *, dates: list[date]) -> dict[str, Path]:
    paths = {
        "long_short_report": tmp_path / "long_short_report.json",
        "long_short_rows": tmp_path / "long_short_rows.csv",
        "attack_report": tmp_path / "attack_report.json",
        "attack_rows": tmp_path / "attack_rows.csv",
        "high_yield_report": tmp_path / "high_yield_report.json",
        "high_yield_rows": tmp_path / "high_yield_rows.csv",
    }
    _write_report(paths["long_short_report"], observer_id="btc_long_short_donchian_top5_observe_only_v1", observation_days=len(dates))
    _write_report(paths["attack_report"], observer_id="btc_bankroll_attack_top_10x_observe_only_v1", observation_days=len(dates))
    _write_high_yield_report(paths["high_yield_report"], observation_days=len(dates))
    _write_csv(paths["long_short_rows"], [_row(line="long_short", row_date=item) for item in dates])
    _write_csv(paths["attack_rows"], [_row(line="attack", row_date=item) for item in dates])
    _write_csv(paths["high_yield_rows"], [_row(line="high_yield", row_date=item) for item in dates])
    return paths


def _write_report(path: Path, *, observer_id: str, observation_days: int) -> None:
    payload = {
        "status": "complete_research_only",
        "observer_design": {"observer_id": observer_id},
        "observation_progress": {"observation_days": observation_days, "observation_count": observation_days},
        "holdout_lock": _lock(),
        "gate": {"paper_queue_write_allowed": False, "live_unlock_allowed": False},
        "guardrails": {"order_endpoint_used": False, "private_endpoint_used": False, "real_order_submitted": False},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_high_yield_report(path: Path, *, observation_days: int) -> None:
    payload = {
        "status": "complete_research_only",
        "step_1_daily_observation_automation": {
            "observation_days": observation_days,
            "observation_count": observation_days,
            "holdout_lock": _lock(),
        },
        "gate": {"paper_queue_write_allowed": False, "live_unlock_allowed": False},
        "guardrails": {"order_endpoint_used": False, "private_endpoint_used": False, "real_order_submitted": False},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _lock() -> dict[str, object]:
    return {
        "lock_config_present": True,
        "observe_only_violation_count": 0,
        "selection_use_blocked_by_lock": True,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _row(*, line: str, row_date: date) -> dict[str, object]:
    decision_time = f"{row_date.isoformat()}T03:59:59.999000+00:00"
    base = {
        "decision_time": decision_time,
        "generated_at_utc": f"{row_date.isoformat()}T08:00:00+00:00",
        "paper_queue_write_allowed": "False",
        "paper_candidate_created": "False",
        "strategy_skeleton_generated": "False",
        "live_unlock_allowed": "False",
        "order_endpoint_used": "False",
        "private_endpoint_used": "False",
        "real_order_submitted": "False",
    }
    if line == "long_short":
        base.update(
            {
                "observer_id": "btc_long_short_donchian_top5_observe_only_v1",
                "candidate_id": "candidate_a",
                "variant_id": "variant_a",
                "decision_signal": '{"side":"flat","value":0.0}',
                "theoretical_exposure": '{"side":"flat","value":0.0}',
            }
        )
    elif line == "attack":
        base.update(
            {
                "observer_id": "btc_bankroll_attack_top_10x_observe_only_v1",
                "top_scenario_id": "attack_top",
                "daily_signal.side": "flat",
                "theoretical_sleeve_exposure.exposed_sleeve_count": "0",
            }
        )
    else:
        base.update(
            {
                "observer_id": "btc_high_yield_v2_frozen_observe_only_v1",
                "variant_id": "hy_v2",
                "theoretical_side": "flat",
                "theoretical_exposure": "0.0",
            }
        )
    return base


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
