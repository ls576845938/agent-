from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.services.research_readonly_views import (
    ResearchReadonlyViewError,
    ResearchReadonlyViews,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _symlink_directory_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlink unavailable: {exc}")


def test_records_are_sorted_and_pending_review_is_a_safe_projection(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "data/research/experiments/older/manifest.json",
        {"experiment_id": "older", "created_at": "2026-09-12T00:00:00Z"},
    )
    _write_json(
        tmp_path / "data/research/experiments/newer/manifest.json",
        {"experiment_id": "newer", "created_at": "2026-09-13T00:00:00Z"},
    )
    _write_json(
        tmp_path / "data/research/paper_reviews/pending/review.json",
        {
            "paper_review_id": "pending",
            "strategy_manifest_id": "manifest",
            "status": "PENDING_HUMAN_REVIEW",
            "reviewer": "must-not-leak",
            "created_at": "2026-09-13T01:00:00Z",
        },
    )
    _write_json(
        tmp_path / "data/research/paper_reviews/approved/review.json",
        {
            "paper_review_id": "approved",
            "strategy_manifest_id": "manifest",
            "status": "APPROVED_FOR_PAPER_ONLY",
            "created_at": "2026-09-13T02:00:00Z",
        },
    )
    views = ResearchReadonlyViews(repo_root=tmp_path)

    assert [item["experiment_id"] for item in views.list_experiments()] == [
        "newer",
        "older",
    ]
    pending = views.list_pending_reviews()
    assert [item["paper_review_id"] for item in pending] == ["pending"]
    assert "reviewer" not in pending[0]


@pytest.mark.parametrize(
    ("call", "expected_code"),
    (
        (lambda views: views.list_experiments(data_root="../data"), "research_readonly_selector_is_server_owned"),
        (lambda views: views.list_candidates(data_root="C:/outside"), "research_readonly_selector_is_server_owned"),
        (lambda views: views.list_portfolio_runs(artifacts_root="D:/outside"), "research_readonly_selector_is_server_owned"),
        (lambda views: views.get_portfolio_run("../escape"), "research_readonly_portfolio_run_id_invalid"),
    ),
)
def test_caller_controlled_roots_and_invalid_ids_are_rejected(
    tmp_path: Path,
    call,
    expected_code: str,
) -> None:
    views = ResearchReadonlyViews(repo_root=tmp_path)

    with pytest.raises(ResearchReadonlyViewError) as exc_info:
        call(views)

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == expected_code


def test_damaged_json_is_conflict_not_empty_success(tmp_path: Path) -> None:
    path = tmp_path / "data/research/candidates/broken/candidate.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ResearchReadonlyViewError) as exc_info:
        ResearchReadonlyViews(repo_root=tmp_path).list_candidates()

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "research_readonly_record_unreadable"


def test_server_owned_data_root_symlink_escape_is_rejected(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    outside_root = tmp_path / "outside"
    repo_root.mkdir()
    _write_json(
        outside_root / "research/experiments/escaped/manifest.json",
        {"experiment_id": "escaped"},
    )
    _symlink_directory_or_skip(repo_root / "data", outside_root)

    with pytest.raises(ResearchReadonlyViewError) as exc_info:
        ResearchReadonlyViews(repo_root=repo_root).list_experiments()

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "research_readonly_server_root_escape"


def test_record_directory_symlink_escape_is_rejected(tmp_path: Path) -> None:
    experiments_root = tmp_path / "repo/data/research/experiments"
    outside_record = tmp_path / "outside/escaped"
    experiments_root.mkdir(parents=True)
    _write_json(outside_record / "manifest.json", {"experiment_id": "escaped"})
    _symlink_directory_or_skip(experiments_root / "escaped", outside_record)

    with pytest.raises(ResearchReadonlyViewError) as exc_info:
        ResearchReadonlyViews(repo_root=tmp_path / "repo").list_experiments()

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "research_readonly_path_escape"


def test_server_owned_root_resolve_escape_is_rejected_before_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    views = ResearchReadonlyViews(repo_root=repo_root)
    data_root = views.data_root
    outside_root = tmp_path / "outside"
    original_resolve = Path.resolve

    def resolved(path: Path, *args, **kwargs) -> Path:
        if path == data_root:
            return outside_root
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolved)

    with pytest.raises(ResearchReadonlyViewError) as exc_info:
        views.list_experiments()

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "research_readonly_server_root_escape"


def test_record_directory_resolve_escape_is_rejected_before_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    escaped_directory = repo_root / "data/research/experiments/escaped"
    escaped_directory.mkdir(parents=True)
    views = ResearchReadonlyViews(repo_root=repo_root)
    outside_directory = tmp_path / "outside/escaped"
    original_resolve = Path.resolve

    def resolved(path: Path, *args, **kwargs) -> Path:
        if path == escaped_directory:
            return outside_directory
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolved)

    with pytest.raises(ResearchReadonlyViewError) as exc_info:
        views.list_experiments()

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "research_readonly_path_escape"


def test_portfolio_summary_reads_latest_weight_sum_and_row_count(tmp_path: Path) -> None:
    pd = pytest.importorskip("pandas")
    run_root = tmp_path / "artifacts/portfolio_runs/run_ok"
    run_root.mkdir(parents=True)
    _write_json(
        run_root / "run_manifest.json",
        {"source_score_run_id": "score_1", "config": {"optimizer": "hrp"}},
    )
    pd.DataFrame(
        [
            {"datetime": "2026-09-12T00:00:00Z", "target_weight": 1.0},
            {"datetime": "2026-09-13T00:00:00Z", "target_weight": 0.4},
            {"datetime": "2026-09-13T00:00:00Z", "target_weight": 0.6},
        ]
    ).to_parquet(run_root / "target_weights.parquet", index=False)

    payload = ResearchReadonlyViews(repo_root=tmp_path).list_portfolio_runs()

    summary = payload["runs"][0]
    assert summary["status"] == "RESEARCH_ONLY_COMPLETED"
    assert summary["target_weight_rows"] == 3
    assert summary["latest_weight_sum"] == pytest.approx(1.0)


def test_portfolio_summary_rejects_corrupt_weights(tmp_path: Path) -> None:
    weights_path = (
        tmp_path
        / "artifacts/portfolio_runs/run_broken/target_weights.parquet"
    )
    weights_path.parent.mkdir(parents=True)
    weights_path.write_bytes(b"not-parquet")

    with pytest.raises(ResearchReadonlyViewError) as exc_info:
        ResearchReadonlyViews(repo_root=tmp_path).list_portfolio_runs()

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "research_readonly_portfolio_artifact_unreadable"


def test_missing_directories_are_read_as_empty_without_being_created(tmp_path: Path) -> None:
    views = ResearchReadonlyViews(repo_root=tmp_path)

    assert views.list_experiments() == []
    assert views.list_candidates() == []
    assert views.list_pending_reviews() == []
    assert not (tmp_path / "data").exists()


def test_system_overview_is_explicitly_unknown_and_fail_closed(tmp_path: Path) -> None:
    payload = ResearchReadonlyViews(repo_root=tmp_path).system_overview()

    assert payload["mode"] == "research_readonly"
    assert payload["health"]["status"] == "unknown"
    assert payload["broker_credentials"]["checked"] is False
    assert payload["execution"]["permission"] is False
    assert payload["paper_review"]["entry_allowed"] is False
    assert payload["paper_review"]["creation"]["creation_allowed"] is False
