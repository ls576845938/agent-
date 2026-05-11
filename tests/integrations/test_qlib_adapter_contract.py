from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from integrations.qlib_adapter.schemas import load_universe_config

from tests.integrations.helpers import (
    adapter_module_or_xfail,
    invoke_adapter_callable,
    locate_single_file,
    make_bar_frame,
    run_module_main,
    write_cleaned_bars,
    write_qlib_run_inputs,
    write_universe_yaml,
)


def _export_kwargs(
    *,
    data_root: Path,
    artifacts_root: Path,
    universe_path: Path,
    run_id: str = "qlib_export_contract",
) -> dict[str, object]:
    return {
        "data_root": data_root,
        "artifacts_root": artifacts_root,
        "run_id": run_id,
        "universe_path": universe_path,
        "start_date": "2026-01-05",
        "end_date": "2026-01-09",
        "symbols": ["AAPL", "MSFT"],
    }


def test_export_to_qlib_writes_expected_schema(
    tmp_path: Path,
    fake_market_root: Path,
) -> None:
    universe_path = write_universe_yaml(tmp_path / "configs" / "universe.yaml", ["AAPL", "MSFT"])
    artifacts_root = tmp_path / "artifacts"

    result = invoke_adapter_callable(
        "integrations.qlib_adapter.export_to_qlib",
        ("export_to_qlib_input",),
        **_export_kwargs(
            data_root=fake_market_root,
            artifacts_root=artifacts_root / "qlib_runs",
            universe_path=universe_path,
        ),
    )
    assert result.status == "completed"

    manifest_path = locate_single_file(artifacts_root, "dataset_manifest.json")
    dataset_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert dataset_manifest["run_id"] == "qlib_export_contract"

    exported_path = sorted(manifest_path.parent.rglob("*.parquet"))
    assert exported_path, "expected at least one qlib input parquet file"
    exported = pd.read_parquet(exported_path[0])
    assert {
        "datetime",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "factor",
        "data_version",
        "source_manifest_hash",
    }.issubset(exported.columns)
    assert exported[["datetime", "symbol"]].duplicated().sum() == 0


@pytest.mark.parametrize(
    ("symbol", "frame_mutator", "message_hint"),
    [
        (
            "AAPL",
            lambda frame: frame.assign(high=frame["close"] - 5.0),
            "high",
        ),
        (
            "AAPL",
            lambda frame: frame.assign(volume=[-1.0, *frame["volume"].tolist()[1:]]),
            "volume",
        ),
    ],
)
def test_export_to_qlib_rejects_invalid_data(
    tmp_path: Path,
    symbol: str,
    frame_mutator,
    message_hint: str,
) -> None:
    data_root = tmp_path / "data"
    frame = make_bar_frame("AAPL", [100.0, 101.0, 102.0])
    write_cleaned_bars(data_root, symbol, frame_mutator(frame))
    write_cleaned_bars(data_root, "MSFT", make_bar_frame("MSFT", [200.0, 201.0, 202.0]))
    universe_path = write_universe_yaml(tmp_path / "configs" / "universe.yaml", ["AAPL", "MSFT"])

    result = invoke_adapter_callable(
        "integrations.qlib_adapter.export_to_qlib",
        ("export_to_qlib_input",),
        **_export_kwargs(
            data_root=data_root,
            artifacts_root=tmp_path / "artifacts" / "qlib_runs",
            universe_path=universe_path,
            run_id=f"reject_{message_hint}",
        ),
    )

    assert result.status == "failed"
    assert result.error is not None
    assert message_hint.lower() in result.error.lower()
    assert not any((tmp_path / "artifacts").rglob("qlib_provider"))


def test_export_to_qlib_rejects_missing_symbol_without_implicit_download(
    tmp_path: Path,
    fake_market_root: Path,
) -> None:
    universe_path = write_universe_yaml(tmp_path / "configs" / "universe.yaml", ["AAPL", "MSFT", "QQQ"])

    result = invoke_adapter_callable(
        "integrations.qlib_adapter.export_to_qlib",
        ("export_to_qlib_input",),
        **_export_kwargs(
            data_root=fake_market_root,
            artifacts_root=tmp_path / "artifacts" / "qlib_runs",
            universe_path=universe_path,
            run_id="missing_symbol",
        ),
    )

    assert result.status == "failed"
    assert result.error is not None
    message = result.error.lower()
    assert "qqq" in message
    assert "implicit download" in message or "forbids implicit downloads" in message


def test_export_to_qlib_rejects_incomplete_daily_coverage(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    aapl = make_bar_frame("AAPL", [100.0, 101.0, 102.0, 103.0, 104.0]).drop(index=[2]).reset_index(drop=True)
    msft = make_bar_frame("MSFT", [200.0, 201.0, 202.0, 203.0, 204.0])
    write_cleaned_bars(data_root, "AAPL", aapl)
    write_cleaned_bars(data_root, "MSFT", msft)
    universe_path = write_universe_yaml(tmp_path / "configs" / "universe.yaml", ["AAPL", "MSFT"])

    result = invoke_adapter_callable(
        "integrations.qlib_adapter.export_to_qlib",
        ("export_to_qlib_input",),
        **_export_kwargs(
            data_root=data_root,
            artifacts_root=tmp_path / "artifacts" / "qlib_runs",
            universe_path=universe_path,
            run_id="missing_daily_rows",
        ),
    )

    assert result.status == "failed"
    assert result.error is not None
    message = result.error.lower()
    assert "missing daily bars" in message
    assert "aapl" in message


def test_run_qlib_workflow_reports_missing_dependency_clearly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not Path("integrations/qlib_adapter/run_qlib_workflow.py").exists():
        pytest.xfail("pending adapter implementation: integrations.qlib_adapter.run_qlib_workflow")

    config_path = tmp_path / "configs" / "qlib.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("model: lgbm\n", encoding="utf-8")

    from integrations.qlib_adapter import run_qlib_workflow as workflow_module
    from integrations.qlib_adapter.schemas import MissingDependencyError

    def missing_dependency(*args, **kwargs):
        raise MissingDependencyError("simulated missing qlib dependency")

    monkeypatch.setattr(workflow_module, "optional_import", missing_dependency)

    result = workflow_module.run_qlib_workflow(
        config_path=config_path,
        run_id="missing_dependency",
        artifacts_root=tmp_path / "artifacts" / "qlib_runs",
    )

    assert result.status == "failed"
    message = str(result.error).lower()
    assert "qlib" in message
    assert "install" in message or "dependency" in message


def test_build_qlib_dataset_reports_dependency_failure_clearly(
    tmp_path: Path,
    fake_market_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    universe_path = write_universe_yaml(tmp_path / "configs" / "universe.yaml", ["AAPL", "MSFT"])
    from integrations.qlib_adapter import build_qlib_dataset as build_module
    from integrations.qlib_adapter.schemas import MissingDependencyError

    def missing_dependency(*args, **kwargs):
        raise MissingDependencyError("simulated missing pyqlib")

    monkeypatch.setattr(build_module, "optional_import_any", missing_dependency)
    monkeypatch.setattr(build_module, "optional_import", missing_dependency)

    result = build_module.build_qlib_dataset(
        universe_path=universe_path,
        start_date="2026-01-05",
        end_date="2026-01-09",
        data_root=fake_market_root,
        artifacts_root=tmp_path / "artifacts" / "qlib_runs",
        run_id="provider_dep_missing",
    )

    assert result.status == "failed"
    assert result.error is not None
    assert "pyqlib" in result.error.lower() or "qlib" in result.error.lower()
    provider_manifest = json.loads(locate_single_file(tmp_path / "artifacts", "provider_manifest.json").read_text(encoding="utf-8"))
    assert provider_manifest["dependency_status"] == "missing"


def test_run_qlib_workflow_dry_run_validates_existing_manifests(
    tmp_path: Path,
    fake_market_root: Path,
) -> None:
    universe_path = write_universe_yaml(tmp_path / "configs" / "universe.yaml", ["AAPL", "MSFT"])
    artifacts_root = tmp_path / "artifacts" / "qlib_runs"
    invoke_adapter_callable(
        "integrations.qlib_adapter.build_qlib_dataset",
        ("build_qlib_dataset",),
        universe_path=universe_path,
        start_date="2026-01-05",
        end_date="2026-01-09",
        data_root=fake_market_root,
        artifacts_root=artifacts_root,
        run_id="workflow_dry_run",
        dry_run=True,
    )
    config_path = tmp_path / "configs" / "qlib_workflow.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "workflow:\n"
        "  run_id: workflow_dry_run\n"
        "model:\n"
        "  name: lgbm_alpha158\n",
        encoding="utf-8",
    )

    result = invoke_adapter_callable(
        "integrations.qlib_adapter.run_qlib_workflow",
        ("run_qlib_workflow",),
        config_path=config_path,
        artifacts_root=artifacts_root,
        dry_run=True,
    )

    assert result.status == "dry_run"
    workflow_result = json.loads(locate_single_file(tmp_path / "artifacts", "workflow_run_result.json").read_text(encoding="utf-8"))
    assert workflow_result["run_id"] == "workflow_dry_run"


def test_import_pred_score_computes_cross_sectional_rank(
    tmp_path: Path,
    fake_scores_frame: pd.DataFrame,
) -> None:
    run_root = write_qlib_run_inputs(tmp_path / "artifacts", "qlib_rank_case", fake_scores_frame)

    result = invoke_adapter_callable(
        "integrations.qlib_adapter.import_pred_score",
        ("import_pred_score", "import_scores", "run"),
        run_id="qlib_rank_case",
        artifacts_root=tmp_path / "artifacts" / "qlib_runs",
        qlib_run_root=run_root,
    )
    assert result.status == "completed"

    imported_path = locate_single_file(tmp_path / "artifacts", "research_model_scores.parquet")
    imported = pd.read_parquet(imported_path).sort_values(["datetime", "rank", "symbol"]).reset_index(drop=True)
    assert {
        "run_id",
        "model_id",
        "source",
        "data_version",
        "datetime",
        "symbol",
        "score",
        "rank",
    }.issubset(imported.columns)

    grouped = imported.groupby("datetime", sort=True)
    for _, group in grouped:
        scores = group.sort_values("rank")["score"].tolist()
        assert scores == sorted(scores, reverse=True)
        assert group["rank"].tolist() == list(range(1, len(group) + 1))


def test_import_pred_score_rejects_duplicate_datetime_symbol(
    tmp_path: Path,
    fake_scores_frame: pd.DataFrame,
) -> None:
    duplicate_scores = pd.concat([fake_scores_frame, fake_scores_frame.iloc[[0]]], ignore_index=True)
    write_qlib_run_inputs(tmp_path / "artifacts", "qlib_duplicate_case", duplicate_scores)

    result = invoke_adapter_callable(
        "integrations.qlib_adapter.import_pred_score",
        ("import_pred_score", "import_scores", "run"),
        run_id="qlib_duplicate_case",
        artifacts_root=tmp_path / "artifacts" / "qlib_runs",
    )

    assert result.status == "failed"
    assert result.error is not None
    assert "duplicate" in result.error.lower()


def test_compile_qlib_strategy_manifest_stays_candidate_only(
    tmp_path: Path,
    fake_scores_frame: pd.DataFrame,
) -> None:
    write_qlib_run_inputs(tmp_path / "artifacts", "qlib_manifest_case", fake_scores_frame)
    invoke_adapter_callable(
        "integrations.qlib_adapter.import_pred_score",
        ("import_pred_score", "import_scores", "run"),
        run_id="qlib_manifest_case",
        artifacts_root=tmp_path / "artifacts" / "qlib_runs",
    )

    config_path = tmp_path / "configs" / "qlib.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "mode: research_only\nmodel:\n  name: lgbm_daily\n  strategy_version: qlib_test_v1\n",
        encoding="utf-8",
    )

    invoke_adapter_callable(
        "integrations.qlib_adapter.compile_qlib_strategy_manifest",
        ("compile_qlib_strategy_manifest", "compile_manifest", "run"),
        run_id="qlib_manifest_case",
        config_path=config_path,
        artifacts_root=tmp_path / "artifacts" / "qlib_runs",
    )

    manifest_candidates = [
        path
        for path in (tmp_path / "artifacts").rglob("*.json")
        if "manifest" in path.name and path.name != "dataset_manifest.json"
    ]
    assert manifest_candidates, "expected a compiled qlib manifest JSON artifact"

    payload = json.loads(manifest_candidates[0].read_text(encoding="utf-8"))
    status = str(payload.get("promotion_status", payload.get("status", ""))).lower()
    assert status == "candidate"
    text = json.dumps(payload).lower()
    assert "paper_ready" not in text
    assert "live_ready" not in text
    restrictions = {str(item).lower() for item in payload.get("restrictions", [])}
    assert "candidate_only" in restrictions


def test_prepare_real_daily_data_dry_run_exports_and_builds_provider(
    tmp_path: Path,
    fake_market_root: Path,
) -> None:
    universe_path = write_universe_yaml(tmp_path / "configs" / "universe.yaml", ["AAPL", "MSFT"])

    result = invoke_adapter_callable(
        "integrations.qlib_adapter.prepare_real_daily_data",
        ("prepare_real_daily_data",),
        universe_path=universe_path,
        start_date="2026-01-05",
        end_date="2026-01-09",
        data_root=fake_market_root,
        artifacts_root=tmp_path / "artifacts" / "qlib_runs",
        run_id="prepare_dry_run",
        sync_yfinance=True,
        build_provider=True,
        dry_run=True,
    )

    assert result.status == "dry_run"
    prepare_manifest = json.loads(locate_single_file(tmp_path / "artifacts", "daily_data_prepare_manifest.json").read_text(encoding="utf-8"))
    assert prepare_manifest["prepare_command"]["sync_yfinance"] is True
    assert prepare_manifest["provider_result"]["status"] == "dry_run"
    assert prepare_manifest["export_result"]["status"] == "completed"


def test_prepare_real_daily_data_missing_symbol_does_not_implicitly_download(
    tmp_path: Path,
    fake_market_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    universe_path = write_universe_yaml(
        tmp_path / "configs" / "universe.yaml",
        ["AAPL", "MSFT", "QQQ"],
    )
    sync_calls: list[str] = []

    def fail_if_called(self, *, symbol: str, **kwargs):  # type: ignore[no-untyped-def]
        sync_calls.append(symbol)
        raise AssertionError("implicit data sync/download must not be called")

    from quant_us.data import pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module.DataLakeService, "sync_bars", fail_if_called)

    result = invoke_adapter_callable(
        "integrations.qlib_adapter.prepare_real_daily_data",
        ("prepare_real_daily_data",),
        universe_path=universe_path,
        start_date="2026-01-05",
        end_date="2026-01-09",
        data_root=fake_market_root,
        artifacts_root=tmp_path / "artifacts" / "qlib_runs",
        run_id="prepare_missing_no_sync",
        sync_yfinance=False,
        build_provider=False,
        dry_run=False,
    )

    assert sync_calls == []
    assert result.status == "failed"
    assert result.error is not None
    assert "qqq" in result.error.lower()
    assert "implicit download" in result.error.lower() or "forbids implicit downloads" in result.error.lower()
    prepare_manifest = json.loads(locate_single_file(tmp_path / "artifacts", "daily_data_prepare_manifest.json").read_text(encoding="utf-8"))
    before = {
        item["symbol"]: item["status"]
        for item in prepare_manifest["manifest_candidates_before_sync"]
    }
    after = {
        item["symbol"]: item["status"]
        for item in prepare_manifest["manifest_candidates_after_sync"]
    }
    assert before["QQQ"] == "missing"
    assert after["QQQ"] == "missing"
    assert prepare_manifest["sync_results"] == []


def test_real_universe_config_is_13_symbol_daily_only() -> None:
    config = load_universe_config("configs/universe/us_core_liquid.yaml")

    assert len(config.symbols) == 13
    assert config.expected_symbol_count == 13
    assert config.strict_calendar_coverage is True
    assert config.allow_implicit_downloads is False


def test_build_qlib_dataset_module_entrypoint_exists() -> None:
    adapter_module_or_xfail("integrations.qlib_adapter.build_qlib_dataset")
    result = run_module_main(
        "integrations.qlib_adapter.build_qlib_dataset",
        ["--help"],
    )
    assert result.exit_code == 0
    assert "data-version" in result.stdout.lower() or "universe" in result.stdout.lower()
