from __future__ import annotations

import json
import hashlib
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.app.api import app_factory

from quant_crypto.adapters.btc_runtime_artifact_store import (
    OWNER_MARKER_NAME,
    BTCRuntimeArtifactWriter,
    build_btc_runtime_artifact_owner_marker,
)
from backend.app.api.btc_strategy_history import (
    build_btc_strategy_history_router as _build_btc_strategy_history_router,
)
from backend.app.services.strategy_workbench_versions import StrategyWorkbenchVersionStore
from quant_crypto.application.btc_strategy_history import (
    BTCStrategyHistoryInvalid,
    OKX_NATIVE_STRATEGY_ID,
    STABLE_STRATEGY_ID,
    load_btc_strategy_history,
    publish_btc_strategy_history_snapshot,
    validate_btc_strategy_history_source_report,
)


pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient


CANDIDATE = (
    "btc_ls_tf_formal_donchian_w240_d50_200_atr20_"
    "cd12_fail0_risknone_78f5f0a0e4"
)
WRITE_HEADERS = {"X-API-Key": "strategy-workbench-test-key"}


def build_btc_strategy_history_router(reader, **kwargs):
    # These tests exercise history contracts using an explicitly selected fixture.
    # Production root isolation is covered by test_strategy_parameter_evidence.
    with patch("backend.app.api.btc_strategy_history.configured_history_reader", return_value=reader):
        return _build_btc_strategy_history_router(reader, **kwargs)


def test_strategy_workbench_projection_preserves_current_run_diagnostics() -> None:
    report = StrategyWorkbenchVersionStore._report_projection({
        "summary": {"total_return_pct": 12.0},
        "chart": {"equity": [{"time": 1, "value": 100.0}], "drawdown": []},
        "strategy_details": [],
        "diagnostics": {
            "pnl_source": "ledger_fills",
            "ledger_equity_consistent": True,
            "monthly_returns": [{"period": "2026-01", "return_pct": 4.0}],
            "drawdown_periods": [{"duration_bars": 3}],
            "execution": {"total_fees": 1.25, "total_slippage": 0.5},
        },
    })

    assert report["diagnostics"]["pnl_source"] == "ledger_fills"
    assert report["diagnostics"]["monthly_returns"][0]["return_pct"] == 4.0
    assert report["diagnostics"]["drawdown_periods"][0]["duration_bars"] == 3
    assert report["diagnostics"]["execution"]["total_fees"] == 1.25


def _write_guard(x_api_key: str = Header(default="")) -> bool:
    if x_api_key != WRITE_HEADERS["X-API-Key"]:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return True


def _client(
    repo_root: Path,
    *,
    version_store: StrategyWorkbenchVersionStore | None = None,
    backtest_runner=None,
) -> TestClient:
    writer = _published_writer(repo_root)
    app = FastAPI()
    app.include_router(
        build_btc_strategy_history_router(
            writer,
            version_store=version_store,
            backtest_runner=backtest_runner,
            write_dependency=_write_guard,
        ),
        prefix="/api",
    )
    return TestClient(app)


def _published_writer(root: Path) -> BTCRuntimeArtifactWriter:
    writer = _artifact_writer(root)
    old_commit = _git_commit(writer.source_repo_root, "HEAD~1")
    current_commit = _git_commit(writer.source_repo_root)
    source = _write_report(
        root,
        code_commit=old_commit,
        source_code_commit=old_commit,
    )
    publish_btc_strategy_history_snapshot(
        writer,
        source_path=source,
        source_commit=old_commit,
        producer_commit=current_commit,
    )
    source.unlink()
    return writer


def _artifact_writer(root: Path) -> BTCRuntimeArtifactWriter:
    source_root = root / "source-repo"
    source_root.mkdir(exist_ok=True)
    if not (source_root / ".git").is_dir():
        _run_git(source_root, "init", "-q")
        _run_git(source_root, "config", "user.email", "tests@example.invalid")
        _run_git(source_root, "config", "user.name", "strategy-history-tests")
        (source_root / "data").mkdir(exist_ok=True)
        (source_root / "data" / "market_data.sqlite").write_bytes(b"market-data-v1")
        (source_root / "data" / "derivatives.json").write_text(
            "{}\n",
            encoding="utf-8",
        )
        (source_root / "strategy_source.py").write_text(
            "STRATEGY_VERSION = 'historical'\n",
            encoding="utf-8",
        )
        _run_git(source_root, "add", ".")
        _run_git(source_root, "commit", "-q", "-m", "historical strategy source")
        (source_root / "strategy_source.py").write_text(
            "STRATEGY_VERSION = 'current'\n",
            encoding="utf-8",
        )
        _run_git(source_root, "add", "strategy_source.py")
        _run_git(source_root, "commit", "-q", "-m", "current strategy source")
    artifact_root = root / "external-runtime-artifacts"
    artifact_root.mkdir(exist_ok=True)
    identity = "sha256:" + "a" * 64
    (artifact_root / OWNER_MARKER_NAME).write_text(
        json.dumps(build_btc_runtime_artifact_owner_marker(identity)),
        encoding="utf-8",
    )
    writer = BTCRuntimeArtifactWriter(
        source_repo_root=source_root,
        artifact_root=artifact_root,
        repository_identity=identity,
        worktree_roots=(source_root,),
    )
    return writer


def _run_git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _git_commit(repo_root: Path, revision: str = "HEAD") -> str:
    return _run_git(repo_root, "rev-parse", revision)


def _write_report(
    repo_root: Path,
    *,
    generated_at_utc: str = "2026-06-29T01:02:03Z",
    code_commit: str | None = None,
    source_code_commit: str | None = None,
) -> Path:
    path = repo_root / "input" / "btc_long_short_top5_review_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    source_root = repo_root / "source-repo"
    if not (source_root / ".git").is_dir():
        _artifact_writer(repo_root)
    historical_commit = _git_commit(source_root, "HEAD~1")
    code_commit = code_commit or historical_commit
    source_code_commit = source_code_commit or historical_commit
    payload = {
        "schema_version": "btc_long_short_top5_review_v1",
        "status": "complete_research_only",
        "decision": "btc_long_short_top5_review_research_only_no_paper_no_live",
        "generated_at_utc": generated_at_utc,
        "code_commit": code_commit,
        "guardrails": {
            "broker_access_allowed": False,
            "live_order_allowed": False,
            "live_unlock_allowed": False,
            "oms_access_allowed": False,
            "order_endpoint_used": False,
            "paper_candidate_created": False,
            "paper_queue_write_allowed": False,
            "private_endpoint_used": False,
            "real_order_submitted": False,
            "research_only": True,
        },
        "input": {
            "market_db_path": "data/market_data.sqlite",
            "derivatives_rows_path": "data/derivatives.json",
            "exchange": "binance_spot",
            "symbol": "BTCUSDT",
            "source_interval": "1h",
            "decision_interval": "4h",
            "bar_4h_start": "2024-01-01T03:59:59Z",
            "bar_4h_end": "2026-06-28T23:59:59Z",
            "market_1h_rows": 21841,
            "bar_4h_rows": 5460,
            "bar_1d_rows": 910,
            "bar_1w_rows": 130,
            "bar_1mo_rows": 29,
        },
        "source": {
            "source_code_commit": source_code_commit,
            "source_schema_version": "btc_long_short_trend_following_lab_v1",
        },
        "review_design": {
            "holdout_locked_for_this_review": True,
            "clean_pre_selection_holdout": False,
        },
        "warnings": ["clean_pre_selection_holdout_false_requires_future_data"],
        "candidate_reviews": [
            {
                "candidate_id": CANDIDATE,
                "variant_id": (
                    "formal_donchian_w240_d50_200_atr20_"
                    "cd12_fail0_risknone"
                ),
                "label": "Formal narrow symmetric Donchian",
                "params": {
                    "entry_window": 240,
                    "daily_fast": 50,
                    "daily_slow": 200,
                    "cooldown_bars": 12,
                },
                "full_metrics": {
                    "annual_return_pct": 36.25,
                    "total_return_pct": 116.22,
                    "max_drawdown_pct": -11.46,
                    "sharpe_ratio": 1.97,
                    "trading_cost_return_pct": -4.0,
                },
                "annual_attribution": {
                    "segments": [
                        {
                            "year": 2024,
                            "passed": True,
                            "metrics": {"total_return_pct": 37.18},
                        }
                    ]
                },
                "confirmation_holdout": {
                    "passed": True,
                    "metrics": {"total_return_pct": 39.70},
                },
                "source_row": {
                    "walk_forward": {
                        "passed": True,
                        "pass_rate": 1.0,
                        "folds": [{"fold": 1, "passed": True}],
                    },
                    "cost_stress": {
                        "survival_rate": 1.0,
                        "scenarios": [{"cost_bps": 20.0, "survives": True}],
                    },
                },
                "market_regime_attribution": {
                    "pass_rate": 0.75,
                    "segments": [
                        {"regime_label": "bull_trend", "passed": True}
                    ],
                },
                "return_concentration": {
                    "trade_count": 20,
                    "positive_trade_count": 10,
                    "best_trades": [{"side": "long", "total_return_pct": 30.02}],
                    "worst_trades": [{"side": "long", "total_return_pct": -3.88}],
                },
                "failure_review": {
                    "flags": [
                        "top_trade_return_concentration_expected_for_trend_following"
                    ]
                },
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_exact_candidate_history_is_compact_identity_bound_and_read_only(
    tmp_path: Path,
) -> None:
    _write_report(tmp_path)
    response = _client(tmp_path).get(
        f"/api/research/btc/strategy-history/{STABLE_STRATEGY_ID}/{CANDIDATE}"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["strategy_id"] == STABLE_STRATEGY_ID
    assert payload["candidate_id"] == CANDIDATE
    assert payload["source_candidate_id"] == CANDIDATE
    assert payload["relationship"] == "exact_candidate_historical_research_report"
    assert len(payload["history_runs"]) == 1
    assert payload["selected_run_id"] == payload["history_runs"][0]["run_id"]
    assert payload["canonical"]["strategy_identity"]["candidate_id"] == CANDIDATE
    assert (
        payload["canonical_report"]["artifact_binding"]["pointer_path"]
        == "artifacts/btc_strategy_history/latest_pointer.json"
    )
    assert payload["details"]["annual_attribution"]["segments"][0]["year"] == 2024
    assert payload["details"]["walk_forward"]["pass_rate"] == 1.0
    assert payload["details"]["cost_stress"]["scenarios"][0]["cost_bps"] == 20.0
    assert (
        payload["details"]["market_regime_attribution"]["segments"][0][
            "regime_label"
        ]
        == "bull_trend"
    )
    assert payload["canonical_report"]["series"]["equity"] == []
    assert payload["canonical_report"]["series"]["trades"] == []
    assert set(payload["safety"].values()) == {False}
    assert "candidate_reviews" not in payload


def test_historical_report_stays_false_and_caller_cannot_relabel_current_head(
    tmp_path: Path,
) -> None:
    writer = _artifact_writer(tmp_path)
    historical_commit = _git_commit(writer.source_repo_root, "HEAD~1")
    current_commit = _git_commit(writer.source_repo_root)
    source = _write_report(
        tmp_path,
        code_commit=historical_commit[:8],
        source_code_commit=historical_commit[:8],
    )
    publish_btc_strategy_history_snapshot(
        writer,
        source_path=source,
        source_commit=historical_commit,
        producer_commit=current_commit,
    )

    app = FastAPI()
    app.include_router(
        build_btc_strategy_history_router(writer, write_dependency=_write_guard),
        prefix="/api",
    )
    response = TestClient(app).get(
        f"/api/research/btc/strategy-history/{STABLE_STRATEGY_ID}/{CANDIDATE}"
    )
    assert response.status_code == 200
    freshness = response.json()["canonical"]["artifact_freshness"]
    assert freshness["current_head_match"] is False
    assert freshness["current_head"] == current_commit
    assert freshness["code_commit"] == historical_commit

    with pytest.raises(
        BTCStrategyHistoryInvalid,
        match="source_commit does not match report code_commit",
    ):
        publish_btc_strategy_history_snapshot(
            writer,
            source_path=source,
            source_commit=current_commit,
            producer_commit=current_commit,
        )


def test_current_head_rebuild_publishes_and_reader_reports_current_match(
    tmp_path: Path,
) -> None:
    writer = _artifact_writer(tmp_path)
    historical_commit = _git_commit(writer.source_repo_root, "HEAD~1")
    current_commit = _git_commit(writer.source_repo_root)
    source = _write_report(
        tmp_path,
        code_commit=current_commit[:8],
        source_code_commit=historical_commit[:8],
        generated_at_utc="2026-08-18T01:02:03Z",
    )
    receipt = publish_btc_strategy_history_snapshot(
        writer,
        source_path=source,
        source_commit=current_commit,
        producer_commit=current_commit,
    )
    assert receipt["provenance_schema_version"] == "btc_strategy_history_provenance_v2"
    assert receipt["source_commit"] == current_commit
    assert receipt["producer_commit"] == current_commit
    assert receipt["data_lineage"]["data_lineage_sha256"]

    app = FastAPI()
    app.include_router(
        build_btc_strategy_history_router(writer, write_dependency=_write_guard),
        prefix="/api",
    )
    client = TestClient(app)
    catalog = client.get("/api/research/btc/strategy-history/catalog")
    detail = client.get(
        f"/api/research/btc/strategy-history/{STABLE_STRATEGY_ID}/{CANDIDATE}"
    )
    assert catalog.status_code == 200
    assert catalog.json()["artifact_freshness"]["current_head_match"] is True
    assert detail.status_code == 200
    freshness = detail.json()["canonical"]["artifact_freshness"]
    assert freshness["current_head_match"] is True
    assert freshness["current_head"] == current_commit
    assert freshness["data_lineage_valid"] is True
    assert detail.json()["source"]["source_commit"] == current_commit


def test_unrelated_or_stale_producer_commit_is_rejected(
    tmp_path: Path,
) -> None:
    writer = _artifact_writer(tmp_path)
    historical_commit = _git_commit(writer.source_repo_root, "HEAD~1")
    current_commit = _git_commit(writer.source_repo_root)
    source = _write_report(
        tmp_path,
        code_commit=historical_commit,
        source_code_commit=historical_commit,
    )
    with pytest.raises(
        BTCStrategyHistoryInvalid,
        match="producer_commit must match current Git HEAD",
    ):
        publish_btc_strategy_history_snapshot(
            writer,
            source_path=source,
            source_commit=historical_commit,
            producer_commit=historical_commit,
        )
    assert current_commit != historical_commit


def test_report_data_lineage_and_source_commit_relationship_are_fail_closed(
    tmp_path: Path,
) -> None:
    writer = _artifact_writer(tmp_path)
    historical_commit = _git_commit(writer.source_repo_root, "HEAD~1")
    current_commit = _git_commit(writer.source_repo_root)

    invalid_lineage = _write_report(
        tmp_path,
        code_commit=current_commit,
        source_code_commit=historical_commit,
    )
    payload = json.loads(invalid_lineage.read_text(encoding="utf-8"))
    payload["input"]["market_db_path"] = "data/../outside.sqlite"
    invalid_lineage.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    with pytest.raises(
        BTCStrategyHistoryInvalid,
        match="data lineage path invalid",
    ):
        publish_btc_strategy_history_snapshot(
            writer,
            source_path=invalid_lineage,
            source_commit=current_commit,
            producer_commit=current_commit,
        )

    invalid_source_lineage = _write_report(
        tmp_path,
        code_commit=historical_commit,
        source_code_commit=current_commit,
    )
    with pytest.raises(
        BTCStrategyHistoryInvalid,
        match="source code lineage is not an ancestor",
    ):
        publish_btc_strategy_history_snapshot(
            writer,
            source_path=invalid_source_lineage,
            source_commit=historical_commit,
            producer_commit=current_commit,
        )


def test_okx_native_candidate_is_explicit_same_formula_historical_baseline(
    tmp_path: Path,
) -> None:
    _write_report(tmp_path)
    native_candidate = f"okx_native_{CANDIDATE}"
    response = _client(tmp_path).get(
        f"/api/research/btc/strategy-history/"
        f"{OKX_NATIVE_STRATEGY_ID}/{native_candidate}"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_id"] == native_candidate
    assert payload["source_candidate_id"] == CANDIDATE
    assert (
        payload["relationship"]
        == "same_formula_historical_research_baseline"
    )
    assert (
        payload["canonical"]["mapping"]["relationship_detail"]
        == "same_frozen_formula_different_strategy_and_data_identity"
    )
    assert payload["canonical"]["mapping"]["is_okx_native_backtest"] is False
    assert "不是 OKX-native 原生回测" in payload["relationship_label"]
    assert any("okx_native_original_backtest_missing" in item for item in payload["blockers"])


def test_unknown_or_cross_line_candidate_fails_closed_without_fallback(
    tmp_path: Path,
) -> None:
    _write_report(tmp_path)
    client = _client(tmp_path)

    unknown = client.get(
        f"/api/research/btc/strategy-history/{STABLE_STRATEGY_ID}/unknown"
    )
    cross_line = client.get(
        f"/api/research/btc/strategy-history/{STABLE_STRATEGY_ID}/"
        f"okx_native_{CANDIDATE}"
    )

    assert unknown.status_code == 404
    assert cross_line.status_code == 404
    assert "candidate" in unknown.json()["detail"]


def test_run_selection_is_candidate_bound_and_unknown_run_is_404(
    tmp_path: Path,
) -> None:
    _write_report(tmp_path)
    client = _client(tmp_path)
    endpoint = (
        f"/api/research/btc/strategy-history/{STABLE_STRATEGY_ID}/{CANDIDATE}"
    )
    initial = client.get(endpoint).json()

    selected = client.get(
        endpoint,
        params={"run_id": initial["selected_run_id"]},
    )
    missing = client.get(endpoint, params={"run_id": "another-candidate-run"})

    assert selected.status_code == 200
    assert selected.json()["selected_run_id"] == initial["selected_run_id"]
    assert missing.status_code == 404


def test_two_publications_keep_old_candidate_run_readable_by_run_id(
    tmp_path: Path,
) -> None:
    writer = _artifact_writer(tmp_path)
    first_source = _write_report(
        tmp_path,
        generated_at_utc="2026-06-28T01:02:03Z",
    )
    historical_commit = _git_commit(writer.source_repo_root, "HEAD~1")
    current_commit = _git_commit(writer.source_repo_root)
    publish_btc_strategy_history_snapshot(
        writer,
        source_path=first_source,
        source_commit=historical_commit,
        producer_commit=current_commit,
    )
    second_source = _write_report(
        tmp_path,
        generated_at_utc="2026-06-29T01:02:03Z",
    )
    publish_btc_strategy_history_snapshot(
        writer,
        source_path=second_source,
        source_commit=historical_commit,
        producer_commit=current_commit,
    )
    app = FastAPI()
    app.include_router(build_btc_strategy_history_router(writer, write_dependency=_write_guard), prefix="/api")
    client = TestClient(app)
    endpoint = (
        f"/api/research/btc/strategy-history/{STABLE_STRATEGY_ID}/{CANDIDATE}"
    )

    latest = client.get(endpoint)
    assert latest.status_code == 200
    latest_payload = latest.json()
    assert len(latest_payload["history_runs"]) == 2
    assert latest_payload["selected_run_id"] == latest_payload["history_runs"][0]["run_id"]
    old_run_id = latest_payload["history_runs"][1]["run_id"]

    old = client.get(endpoint, params={"run_id": old_run_id})
    assert old.status_code == 200
    assert old.json()["selected_run_id"] == old_run_id
    assert old.json()["source"]["generated_at_utc"] == "2026-06-28T01:02:03Z"
    assert [item["run_id"] for item in old.json()["history_runs"]] == [
        item["run_id"] for item in latest_payload["history_runs"]
    ]

    catalog = client.get("/api/research/btc/strategy-history/catalog")
    assert catalog.status_code == 200
    stable = next(
        item
        for item in catalog.json()["candidates"]
        if item["strategy_id"] == STABLE_STRATEGY_ID
    )
    assert stable["history_run_count"] == 2
    assert [item["run_id"] for item in stable["history_runs"]] == [
        item["run_id"] for item in latest_payload["history_runs"]
    ]


def test_source_contract_rejects_unknown_schema_or_unsafe_guardrail(
    tmp_path: Path,
) -> None:
    source = _write_report(tmp_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["schema_version"] = "unknown_report_v1"
    with pytest.raises(BTCStrategyHistoryInvalid, match="schema mismatch"):
        validate_btc_strategy_history_source_report(payload)

    payload["schema_version"] = "btc_long_short_top5_review_v1"
    payload["guardrails"]["paper_queue_write_allowed"] = True
    with pytest.raises(BTCStrategyHistoryInvalid, match="guardrail mismatch"):
        validate_btc_strategy_history_source_report(payload)

    source.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BTCStrategyHistoryInvalid, match="guardrail mismatch"):
        publish_btc_strategy_history_snapshot(
            _artifact_writer(tmp_path),
            source_path=source,
            source_commit=_git_commit(tmp_path / "source-repo", "HEAD~1"),
            producer_commit=_git_commit(tmp_path / "source-repo"),
        )


def test_path_traversal_and_arbitrary_file_read_are_unavailable(
    tmp_path: Path,
) -> None:
    _write_report(tmp_path)
    secret = tmp_path / "secret.json"
    secret.write_text('{"secret":"must-not-leak"}', encoding="utf-8")
    client = _client(tmp_path)

    traversal = client.get(
        f"/api/research/btc/strategy-history/{STABLE_STRATEGY_ID}/..%2Fsecret"
    )
    arbitrary = client.get(
        f"/api/research/btc/strategy-history/{STABLE_STRATEGY_ID}/secret.json"
    )

    assert traversal.status_code in {404, 422}
    assert arbitrary.status_code in {404, 422}
    assert "must-not-leak" not in traversal.text
    assert "must-not-leak" not in arbitrary.text
    with pytest.raises(Exception, match="invalid BTC strategy history identity"):
        load_btc_strategy_history(
            _published_writer(tmp_path),
            strategy_id=STABLE_STRATEGY_ID,
            candidate_id=r"..\secret.json",
        )


def test_catalog_exposes_stable_and_native_cards_without_full_report(
    tmp_path: Path,
) -> None:
    _write_report(tmp_path)
    response = _client(tmp_path).get(
        "/api/research/btc/strategy-history/catalog"
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["strategy_id"] for item in payload["candidates"]] == [
        STABLE_STRATEGY_ID,
        OKX_NATIVE_STRATEGY_ID,
    ]
    assert payload["candidates"][1]["candidate_id"] == f"okx_native_{CANDIDATE}"
    assert "candidate_reviews" not in response.text
    assert set(payload["safety"].values()) == {False}


def test_canonical_strategy_source_is_exact_allowlisted_loaded_source(
    tmp_path: Path,
) -> None:
    response = _client(tmp_path).get(
        f"/api/research/btc/strategy-source/{STABLE_STRATEGY_ID}/{CANDIDATE}"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["strategy_id"] == STABLE_STRATEGY_ID
    assert payload["candidate_id"] == CANDIDATE
    assert payload["canonical_signal_available"] is True
    assert payload["source_ref"] == "quant_crypto/application/btc_strategy_registry.py"
    assert len(payload["sections"]) == 3
    assert payload["sections"][0]["source_ref"].startswith("quant_crypto/")
    assert payload["sections"][1]["symbol"] == "raw_long_short_trend_signal"
    assert payload["sections"][2]["symbol"] == "_signal_symmetric_donchian"
    assert "shift(1)" in payload["sections"][2]["content"]
    assert 'params["entry_window"]' in payload["sections"][2]["content"]
    assert 'params["exit_window"]' in payload["sections"][2]["content"]
    assert payload["sections"][2]["content_sha256"] == hashlib.sha256(
        payload["sections"][2]["content"].encode("utf-8")
    ).hexdigest()
    assert "def generate_" in payload["content"]
    assert "def raw_long_short_trend_signal" in payload["content"]
    assert payload["content_sha256"] == hashlib.sha256(
        payload["content"].encode("utf-8")
    ).hexdigest()
    assert set(payload["safety"].values()) == {False}
    assert str(tmp_path) not in response.text
    assert "must-not-leak" not in response.text


def test_strategy_source_fails_closed_for_unknown_identity_only_and_path_like_ids(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    unknown = client.get(
        f"/api/research/btc/strategy-source/{STABLE_STRATEGY_ID}/..%2Fsecret"
    )
    identity_only = client.get(
        "/api/research/btc/strategy-source/"
        "high_yield_donchian_v2/"
        "hy_v2_donchian_w240_d50_200_cd12_vt120_max2p5_dd25_liq1200_trendoff"
    )
    post = client.post(
        f"/api/research/btc/strategy-source/{STABLE_STRATEGY_ID}/{CANDIDATE}"
    )

    assert unknown.status_code in {404, 422}
    assert identity_only.status_code == 409
    assert post.status_code == 405
    assert "secret" not in unknown.text


def _allowlisted_backtest_fixture(request: dict[str, object]) -> dict[str, object]:
    assert request["strategy_id"] == STABLE_STRATEGY_ID
    assert request["candidate_id"] == CANDIDATE
    assert request["source"] == "sqlite"
    assert request["leverage"] == 1.0
    assert "source_content" not in request
    return {
        "summary": {
            "total_return_pct": 10.0,
            "annual_return_pct": 8.0,
            "max_drawdown_pct": -4.0,
            "sharpe_ratio": 1.2,
            "trade_count": 8,
        },
        "chart": {"equity": [{"time": 1, "value": 100.0}], "drawdown": [{"time": 1, "value": 0.0}]},
        "strategy_details": [],
    }


def test_research_versions_are_immutable_and_only_canonical_source_can_run_allowlisted_backtest(
    tmp_path: Path,
) -> None:
    store = StrategyWorkbenchVersionStore(tmp_path / "strategy-workbench-store")
    client = _client(tmp_path, version_store=store, backtest_runner=_allowlisted_backtest_fixture)
    source = client.get(f"/api/research/btc/strategy-source/{STABLE_STRATEGY_ID}/{CANDIDATE}").json()
    create = client.post(
        "/api/research/btc/strategy-versions",
        headers=WRITE_HEADERS,
        json={
            "strategy_id": STABLE_STRATEGY_ID,
            "candidate_id": CANDIDATE,
            "base_source_sha256": source["content_sha256"],
            "source_content": source["content"],
            "label": "canonical replay",
        },
    )
    assert create.status_code == 200
    version = create.json()
    assert version["execution"]["runnable"] is True
    assert version["approved_research_only"] is False
    assert set(version["safety"].values()) == {False}
    assert source["content"] == client.get(f"/api/research/btc/strategy-source/{STABLE_STRATEGY_ID}/{CANDIDATE}").json()["content"]

    run = client.post(
        f"/api/research/btc/strategy-versions/{version['version_id']}/backtests",
        headers=WRITE_HEADERS,
        json={"start": "2024-01-01T00:00:00Z", "end": "2024-02-01T00:00:00Z", "capital": 100000, "data_version": "fixture-data-v1"},
    )
    assert run.status_code == 200
    assert run.json()["status"] == "completed"
    assert run.json()["report"]["summary"]["trade_count"] == 8

    approval = client.post(
        f"/api/research/btc/strategy-versions/{version['version_id']}/approve",
        headers=WRITE_HEADERS,
        json={"confirmation": "APPROVE RESEARCH VERSION"},
    )
    assert approval.status_code == 200
    assert approval.json()["approved_research_only"] is True
    selection = client.post(
        f"/api/research/btc/strategy-versions/{version['version_id']}/select-runnable",
        headers=WRITE_HEADERS,
        json={"confirmation": "SELECT RUNNABLE CANDIDATE"},
    )
    assert selection.status_code == 200
    assert selection.json()["selected_runnable_candidate"] is True
    assert selection.json()["selection_scope"] == "future_demo_reader_requires_separate_runtime_admission"
    assert set(selection.json()["safety"].values()) == {False}
    restored = client.get(f"/api/research/btc/strategy-versions/{version['version_id']}")
    assert restored.status_code == 200
    assert restored.json()["latest_backtest"]["run_id"] == run.json()["run_id"]


def test_edited_version_is_saved_as_draft_but_fails_closed_before_runner_or_approval(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    def runner(request: dict[str, object]) -> dict[str, object]:
        calls.append(request)
        return _allowlisted_backtest_fixture(request)

    store = StrategyWorkbenchVersionStore(tmp_path / "strategy-workbench-store")
    client = _client(tmp_path, version_store=store, backtest_runner=runner)
    source = client.get(f"/api/research/btc/strategy-source/{STABLE_STRATEGY_ID}/{CANDIDATE}").json()
    create = client.post(
        "/api/research/btc/strategy-versions",
        headers=WRITE_HEADERS,
        json={
            "strategy_id": STABLE_STRATEGY_ID,
            "candidate_id": CANDIDATE,
            "base_source_sha256": source["content_sha256"],
            "source_content": source["content"] + "\n# local research edit",
            "label": "edited draft",
        },
    )
    assert create.status_code == 200
    version_id = create.json()["version_id"]
    assert create.json()["execution"]["runnable"] is False
    run = client.post(
        f"/api/research/btc/strategy-versions/{version_id}/backtests",
        headers=WRITE_HEADERS,
        json={"start": "2024-01-01T00:00:00Z", "end": "2024-02-01T00:00:00Z", "capital": 100000, "data_version": "fixture-data-v1"},
    )
    assert run.status_code == 422
    assert "edited source" in run.json()["detail"]
    assert calls == []
    approval = client.post(
        f"/api/research/btc/strategy-versions/{version_id}/approve",
        headers=WRITE_HEADERS,
        json={"confirmation": "APPROVE RESEARCH VERSION"},
    )
    assert approval.status_code == 422
    selection = client.post(
        f"/api/research/btc/strategy-versions/{version_id}/select-runnable",
        headers=WRITE_HEADERS,
        json={"confirmation": "SELECT RUNNABLE CANDIDATE"},
    )
    assert selection.status_code == 422
    malformed = client.post(
        "/api/research/btc/strategy-versions",
        headers=WRITE_HEADERS,
        json={"strategy_id": STABLE_STRATEGY_ID, "candidate_id": CANDIDATE, "base_source_sha256": "0" * 64, "source_content": source["content"], "label": "bad"},
    )
    assert malformed.status_code == 422


def test_app_factory_injects_registered_runner_and_rejects_unauthenticated_version_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class _RegisteredResearchService:
        def run_crypto_event(self, request: dict[str, object]) -> dict[str, object]:
            calls.append(request)
            return _allowlisted_backtest_fixture(request)

    monkeypatch.setenv("QS_STRATEGY_WORKBENCH_VERSION_ROOT", str(tmp_path / "workbench"))
    monkeypatch.setattr(app_factory, "research_service", _RegisteredResearchService())
    monkeypatch.setattr(
        app_factory,
        "settings",
        replace(app_factory.settings, web_api_key="factory-contract-key"),
    )
    app = app_factory.create_app()
    client = TestClient(app)
    source_path = f"/api/research/btc/strategy-source/{STABLE_STRATEGY_ID}/{CANDIDATE}"
    source = client.get(source_path).json()
    request_payload = {
        "strategy_id": STABLE_STRATEGY_ID,
        "candidate_id": CANDIDATE,
        "base_source_sha256": source["content_sha256"],
        "source_content": source["content"],
        "label": "factory wiring",
    }
    endpoint = "/api/research/btc/strategy-versions"
    assert client.post(endpoint, json=request_payload).status_code == 403
    assert client.post(endpoint, headers={"X-API-Key": "wrong"}, json=request_payload).status_code == 403
    created = client.post(endpoint, headers={"X-API-Key": "REDACTED_CREDENTIAL_LITERAL"}, json=request_payload)
    assert created.status_code == 200
    version_id = created.json()["version_id"]
    run = client.post(
        f"{endpoint}/{version_id}/backtests",
        headers={"X-API-Key": "REDACTED_CREDENTIAL_LITERAL"},
        json={"start": "2024-01-01T00:00:00Z", "end": "2024-02-01T00:00:00Z", "capital": 100000, "data_version": "fixture-data-v1"},
    )
    assert run.status_code == 200
    assert len(calls) == 1
    assert calls[0]["strategy_id"] == STABLE_STRATEGY_ID
    assert calls[0]["source"] == "sqlite"
    assert "source_content" not in calls[0]


def test_version_journal_serializes_threadpool_writers_and_selection_is_append_only(
    tmp_path: Path,
) -> None:
    store = StrategyWorkbenchVersionStore(tmp_path / "strategy-workbench-store")
    client = _client(tmp_path, version_store=store, backtest_runner=_allowlisted_backtest_fixture)
    source = client.get(
        f"/api/research/btc/strategy-source/{STABLE_STRATEGY_ID}/{CANDIDATE}"
    ).json()
    payload = {
        "strategy_id": STABLE_STRATEGY_ID,
        "candidate_id": CANDIDATE,
        "base_source_sha256": source["content_sha256"],
        "source_content": source["content"],
    }

    def create(index: int) -> dict[str, object]:
        return store.create_version(
            payload={**payload, "label": f"concurrent-{index}"},
            canonical_source=source,
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        versions = list(executor.map(create, range(4)))
    assert len({item["version_id"] for item in versions}) == 4
    assert len(list((store.root / "versions").glob("*.json"))) == 4
    assert not list(store.root.rglob("*.tmp"))

    selected = store.select_runnable_candidate
    # Approval remains required; the assertion below proves selection has no
    # mutable pointer file even when the serialized journal rejects the call.
    with pytest.raises(Exception, match="approved research version"):
        selected(version_id=str(versions[0]["version_id"]), confirmation="SELECT RUNNABLE CANDIDATE")
    assert not (store.root / "selected.json").exists()
