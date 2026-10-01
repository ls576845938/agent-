from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_crypto.research import high_yield_5m_ga_mining as module
from quant_crypto.research.high_yield_5m_ga_mining import (
    CostScenario,
    HighYield5mGAMiningError,
    HighYield5mGenome,
    build_high_yield_5m_target,
    load_committed_5m_market_frame,
    run_btc_high_yield_5m_ga_mining,
    run_high_yield_5m_ga_on_frame,
    simulate_high_yield_5m_next_open,
)


def _genome() -> HighYield5mGenome:
    return HighYield5mGenome(
        entry_window=48,
        exit_ratio=0.5,
        atr_window=14,
        atr_mult=2.0,
        cooldown_bars=6,
        failed_breakout_bars=3,
        breakout_buffer_atr=0.1,
        regime_fast_bars=288,
        regime_slow_bars=1152,
        volatility_window_bars=288,
        target_volatility_pct=60.0,
        max_leverage=1.5,
        drawdown_gate_pct=15.0,
    )


def _frame(rows: int = 40_000) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=rows, freq="5min", tz="UTC")
    x = np.arange(rows, dtype=float)
    regime = np.where((x // 6000) % 2 == 0, 1.0, -1.0)
    drift = np.cumsum(regime * 0.00008 + 0.00035 * np.sin(x / 41.0))
    close = 30_000.0 * np.exp(drift)
    open_price = np.concatenate(([close[0]], close[:-1]))
    high = np.maximum(open_price, close) * (1.0 + 0.0008 + 0.0002 * np.sin(x / 17.0) ** 2)
    low = np.minimum(open_price, close) * (1.0 - 0.0008 - 0.0002 * np.cos(x / 19.0) ** 2)
    volume = 100.0 + 10.0 * np.sin(x / 23.0) ** 2
    return pd.DataFrame(
        {
            "open_time_ms": (index.astype("int64") // 1_000_000).astype("int64"),
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=index,
    )


def _provenance(frame: pd.DataFrame) -> dict[str, object]:
    return {
        "data_version": "synthetic-high-yield-5m-contract-v1",
        "manifest_checksum": "a" * 64,
        "manifest_interval": "5m",
        "manifest_start": frame.index[0].isoformat(),
        "manifest_end": frame.index[-1].isoformat(),
        "manifest_row_count": len(frame),
        "resolved_row_count": len(frame),
        "resolved_slice_sha256": "b" * 64,
        "physical_access_mode": "synthetic_contract_fixture",
    }


def test_high_yield_5m_genome_is_bounded_and_origin_is_not_a_return_claim() -> None:
    genome = _genome()

    assert genome.exit_window == 24
    assert genome.to_dict()["position_policy"] == "volatility_target_capped_synthetic_leverage"
    assert len(genome.genome_hash) == 64
    with pytest.raises(HighYield5mGAMiningError, match="genome_values_invalid"):
        HighYield5mGenome(**{**genome.__dict__, "max_leverage": 10.0})


def test_completed_bar_target_does_not_change_when_only_future_rows_change() -> None:
    frame = _frame(10_000)
    changed = frame.copy()
    cutoff = 8_000
    changed.iloc[cutoff + 1 :, changed.columns.get_loc("high")] *= 1.30
    changed.iloc[cutoff + 1 :, changed.columns.get_loc("low")] *= 0.70
    changed.iloc[cutoff + 1 :, changed.columns.get_loc("close")] *= 1.15

    original_target = build_high_yield_5m_target(frame, _genome())
    changed_target = build_high_yield_5m_target(changed, _genome())

    pd.testing.assert_series_equal(
        original_target.iloc[: cutoff + 1],
        changed_target.iloc[: cutoff + 1],
        check_names=True,
    )


def test_execution_waits_for_next_open_and_ledger_reconciles() -> None:
    index = pd.date_range("2026-01-01", periods=3, freq="5min", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": [100.0, 100.0, 110.0],
            "high": [100.0, 110.0, 110.0],
            "low": [100.0, 100.0, 110.0],
            "close": [100.0, 110.0, 110.0],
            "volume": [1.0, 1.0, 1.0],
        },
        index=index,
    )
    target = pd.Series([1.0, 1.0, 1.0], index=index)
    zero_cost = CostScenario("zero", 0.0, 0.0, 0.0)

    metrics, ledger = simulate_high_yield_5m_next_open(
        frame,
        target,
        cost_scenario=zero_cost,
        drawdown_gate_pct=25.0,
    )

    assert metrics["total_return"] == pytest.approx(0.10)
    assert metrics["trade_count"] == 1
    assert ledger["fill_samples_first"][0]["decision_time"] == index[0].isoformat()
    assert ledger["fill_samples_first"][0]["execution_time"] == index[1].isoformat()
    assert ledger["ending_equity"] == pytest.approx(1.10)
    assert ledger["pnl_derived_from_fills_positions_cash"] is True
    assert ledger["signal_at_completed_close_execution_at_next_open"] is True
    assert ledger["reconciled"] is True


def test_fixed_seed_selection_is_reproducible_and_tail_is_not_used(tmp_path: Path) -> None:
    frame = _frame()
    changed = frame.copy()
    selection_end = int(len(frame) * 0.80)
    changed.iloc[selection_end:, changed.columns.get_loc("open")] *= 1.10
    changed.iloc[selection_end:, changed.columns.get_loc("high")] *= 1.12
    changed.iloc[selection_end:, changed.columns.get_loc("low")] *= 1.08
    changed.iloc[selection_end:, changed.columns.get_loc("close")] *= 1.10

    first = run_high_yield_5m_ga_on_frame(
        frame=frame,
        data_provenance=_provenance(frame),
        output_root=tmp_path / "first",
        seed=20260826,
        population_size=8,
        generations=1,
        fold_count=2,
        max_candidates=2,
        generated_at_utc=pd.Timestamp("2026-08-26T00:00:00Z").to_pydatetime(),
    )
    second = run_high_yield_5m_ga_on_frame(
        frame=changed,
        data_provenance=_provenance(frame),
        output_root=tmp_path / "second",
        seed=20260826,
        population_size=8,
        generations=1,
        fold_count=2,
        max_candidates=2,
        generated_at_utc=pd.Timestamp("2026-08-26T00:00:00Z").to_pydatetime(),
    )

    first_selection = [
        (row["genome_hash"], row["selection_fitness"], row["walk_forward"])
        for row in first["top_candidates"]
    ]
    second_selection = [
        (row["genome_hash"], row["selection_fitness"], row["walk_forward"])
        for row in second["top_candidates"]
    ]
    assert first_selection == second_selection
    assert first["validation_design"]["holdout_used_for_selection"] is False
    assert first["validation_design"]["promotion_eligible_holdout"] is False


def test_report_is_research_only_and_candidate_definitions_never_unlock_demo(tmp_path: Path) -> None:
    frame = _frame()
    report = run_high_yield_5m_ga_on_frame(
        frame=frame,
        data_provenance=_provenance(frame),
        output_root=tmp_path,
        seed=7,
        population_size=8,
        generations=1,
        fold_count=2,
        max_candidates=2,
        generated_at_utc=pd.Timestamp("2026-08-26T00:00:00Z").to_pydatetime(),
    )
    definitions = json.loads(
        (tmp_path / "btc_high_yield_5m_ga_candidate_definitions.json").read_text(
            encoding="utf-8"
        )
    )

    assert report["status"] == "complete_research_only"
    assert report["origin_contract"]["strategy_id"] == "high_yield_donchian_v2"
    assert "historical_10000x_label" in report["origin_contract"]["not_inherited_as_evidence"]
    assert report["promotion"]["demo_strategy_registration_allowed"] is False
    assert report["promotion"]["paper_auto_start"] is False
    assert report["promotion"]["live_enabled"] is False
    assert report["safety"]["private_endpoints_allowed"] is False
    assert report["safety"]["order_endpoints_allowed"] is False
    assert report["safety"]["real_orders_created"] is False
    assert report["safety"]["public_network_called"] is False
    assert definitions["demo_strategy_registration_allowed"] is False
    assert definitions["paper_queue_write_allowed"] is False
    assert definitions["live_unlock_allowed"] is False


def test_non_5m_manifest_fails_before_database_access(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "load_data_manifest", lambda _: {"interval": "15m"})

    with pytest.raises(HighYield5mGAMiningError, match="manifest_interval_mismatch"):
        run_btc_high_yield_5m_ga_mining(
            market_db_path=Path("missing.sqlite"),
            manifest_path=Path("manifest.json"),
            output_root=Path("unused"),
        )


def test_default_consumer_binding_is_not_legacy_sqlite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Failure-first contract: the default path must resolve the committed selector."""
    legacy_calls: list[str] = []

    def legacy_manifest(_: Path) -> dict[str, object]:
        legacy_calls.append("manifest")
        raise AssertionError("legacy manifest loader must not be used by default")

    def legacy_frame(**_: object) -> tuple[pd.DataFrame, dict[str, object]]:
        legacy_calls.append("sqlite")
        raise AssertionError("mutable SQLite loader must not be used by default")

    monkeypatch.setattr(module, "load_data_manifest", legacy_manifest)
    monkeypatch.setattr(module, "load_manifest_bounded_market_frame", legacy_frame)
    monkeypatch.setattr(
        module,
        "load_committed_5m_market_frame",
        lambda **_: (_frame(40_000), {"physical_access_mode": "immutable_shared_data_jsonl"}),
    )
    result = run_btc_high_yield_5m_ga_mining(
        output_root=tmp_path,
        population_size=8,
        generations=1,
        fold_count=2,
    )
    assert result["data_provenance"]["physical_access_mode"] == "immutable_shared_data_jsonl"
    assert legacy_calls == []


def test_selector_failure_never_falls_back_to_mutable_sqlite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def missing_selector(**_: object) -> tuple[pd.DataFrame, dict[str, object]]:
        raise HighYield5mGAMiningError("high_yield_5m_selector_committed_object_unavailable")

    monkeypatch.setattr(
        module,
        "load_committed_5m_market_frame",
        missing_selector,
    )
    monkeypatch.setattr(module, "load_data_manifest", lambda _: pytest.fail("legacy fallback"))
    monkeypatch.setattr(
        module,
        "load_manifest_bounded_market_frame",
        lambda **_: pytest.fail("SQLite fallback"),
    )
    with pytest.raises(HighYield5mGAMiningError, match="selector_committed_object_unavailable"):
        run_btc_high_yield_5m_ga_mining(output_root=tmp_path)


def test_legacy_pair_requires_both_arguments() -> None:
    with pytest.raises(HighYield5mGAMiningError, match="legacy_pair_required"):
        run_btc_high_yield_5m_ga_mining(
            market_db_path=Path("explicit.sqlite"),
            output_root=Path("unused"),
        )


def test_close_event_derives_open_index_without_aliasing_close_timestamp(tmp_path: Path) -> None:
    rows = []
    for offset in (0, 5):
        event = pd.Timestamp("2026-01-01T00:04:59.999000Z") + pd.Timedelta(minutes=offset)
        rows.append(
            {
                "available_time": event.isoformat().replace("+00:00", "Z"),
                "close": 101.0 + offset,
                "data_version": "version",
                "event_time": event.isoformat().replace("+00:00", "Z"),
                "exchange": "binance_spot",
                "high": 102.0 + offset,
                "interval": "5m",
                "is_finalized": True,
                "low": 100.0 + offset,
                "open": 100.5 + offset,
                "symbol": "BTCUSDT",
                "volume": 1.0,
            }
        )
    path = tmp_path / "part-00000.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    frame, payload = module._load_5m_jsonl(
        path,
        expected_data_version="version",
        expected_rows=2,
        expected_coverage_start="2026-01-01T00:04:59.999000Z",
        expected_coverage_end="2026-01-01T00:09:59.999000Z",
        generated_at=datetime(2026, 1, 1, 0, 15, tzinfo=timezone.utc),
        checked_at=datetime(2026, 1, 1, 0, 20, tzinfo=timezone.utc),
    )
    assert frame.index.tolist() == [
        pd.Timestamp("2026-01-01T00:00:00Z"),
        pd.Timestamp("2026-01-01T00:05:00Z"),
    ]
    assert frame["open_time_ms"].iloc[0] == int(pd.Timestamp("2026-01-01T00:00:00Z").timestamp() * 1000)
    assert payload["physical_close_time_start"] == "2026-01-01T00:04:59.999000Z"


def test_current_qcv2r1_selector_and_5m_file_smoke() -> None:
    frame, provenance = load_committed_5m_market_frame(now=datetime.now(timezone.utc))
    assert len(frame) == 278_928
    assert frame.index[0] == pd.Timestamp("2024-01-01T00:00:00Z")
    assert frame.index[-1] == pd.Timestamp("2026-08-26T11:55:00Z")
    assert (frame["open_time_ms"].diff().dropna() == 300_000).all()
    assert provenance["manifest_git_sha256"] == "ad6981dc7c8d5124b594ff4212192e5e94ff87c965bd3e3470f247da56efa9ee"
    assert provenance["physical_manifest_sha256"] == "0ee09f51f53608c16c9306334c5e4fbe7ede86f948c625ba91bbd36d7f327068"
    assert provenance["five_minute_file_sha256"] == "76e8654cd11fc40b873b30d4a6fa8b2ed618256721e3b7840e180bd0f0359c08"
    assert provenance["consumer_readiness_blockers"] == [
        "btc_execution_latency_model_missing",
        "btc_queue_model_missing",
        "btc_kline_dataready_not_promotion_evidence",
    ]
    assert provenance["public_network_called"] is False


def _committed_selector_raw() -> bytes:
    return subprocess.check_output(
        ["git", "show", f"HEAD:{module.DEFAULT_SELECTOR_PATH.as_posix()}"],
        cwd=Path.cwd(),
    )


def test_unknown_selector_blocker_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    selector = json.loads(_committed_selector_raw())
    selector["immutable_publication"]["blockers"].append("unknown_data_quality_blocker")
    tampered = json.dumps(selector, separators=(",", ":")).encode("utf-8")
    original = module._git_show_bytes

    def show(repo_root: Path, spec: str, label: str) -> bytes:
        return tampered if label == "selector" else original(repo_root, spec, label)

    monkeypatch.setattr(module, "_git_show_bytes", show)
    with pytest.raises(HighYield5mGAMiningError, match="unknown_blocker"):
        load_committed_5m_market_frame()


def test_committed_manifest_hash_tamper_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    original = module._git_show_bytes

    def show(repo_root: Path, spec: str, label: str) -> bytes:
        raw = original(repo_root, spec, label)
        if label == "manifest":
            payload = json.loads(raw)
            payload["dataset_version"] = "tampered-version"
            return json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return raw

    monkeypatch.setattr(module, "_git_show_bytes", show)
    with pytest.raises(HighYield5mGAMiningError, match="manifest_git_hash_mismatch"):
        load_committed_5m_market_frame()


def test_physical_manifest_hash_tamper_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    original = module.shared_data.sha256_file

    def sha256(path: Path, *args: object, **kwargs: object) -> str:
        if path.name == module.shared_data.MANIFEST_NAME:
            return "0" * 64
        return original(path, *args, **kwargs)

    monkeypatch.setattr(module.shared_data, "sha256_file", sha256)
    with pytest.raises(HighYield5mGAMiningError, match="physical_manifest_hash_mismatch"):
        load_committed_5m_market_frame()


def test_declared_payload_file_hash_tamper_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    original = module.shared_data.sha256_file

    def sha256(path: Path, *args: object, **kwargs: object) -> str:
        if path.name.startswith("part-00000"):
            return "1" * 64
        return original(path, *args, **kwargs)

    monkeypatch.setattr(module.shared_data, "sha256_file", sha256)
    with pytest.raises(HighYield5mGAMiningError, match="physical_dataset_invalid"):
        load_committed_5m_market_frame()


def test_explicit_legacy_pair_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = _frame(40_000)
    calls: list[str] = []
    monkeypatch.setattr(module, "load_data_manifest", lambda _: {"interval": "5m"})
    monkeypatch.setattr(
        module,
        "load_manifest_bounded_market_frame",
        lambda **_: (frame, {"physical_access_mode": "sqlite_uri_mode_ro_query_only"}),
    )
    monkeypatch.setattr(
        module,
        "run_high_yield_5m_ga_on_frame",
        lambda **kwargs: calls.append(str(kwargs["data_provenance"]["physical_access_mode"])) or kwargs,
    )
    result = run_btc_high_yield_5m_ga_mining(
        market_db_path=Path("explicit.sqlite"),
        manifest_path=Path("explicit.json"),
        output_root=Path("unused"),
    )
    assert calls == ["legacy_sqlite_opt_in"]
    assert result["data_provenance"]["mutable_sqlite_consumed"] is True


def test_frozen_unseen_holdout_requires_exact_single_candidate_contract(
    tmp_path: Path,
) -> None:
    frame = _frame()
    cutoff = frame.index[29_999].to_pydatetime()
    holdout_start = frame.index[30_000].to_pydatetime()
    common = {
        "frame": frame,
        "data_provenance": _provenance(frame),
        "seed": 20260827,
        "population_size": 8,
        "generations": 1,
        "fold_count": 2,
        "frozen_unseen_holdout_start_utc": holdout_start,
        "prior_research_cutoff_utc": cutoff,
        "experiment_id": "contract-frozen-holdout",
        "generated_at_utc": pd.Timestamp("2026-08-27T00:00:00Z").to_pydatetime(),
    }

    with pytest.raises(
        HighYield5mGAMiningError,
        match="prior_exposure_must_be_false",
    ):
        run_high_yield_5m_ga_on_frame(
            **common,
            output_root=tmp_path / "prior-exposure",
            max_candidates=1,
        )
    with pytest.raises(
        HighYield5mGAMiningError,
        match="requires_single_candidate",
    ):
        run_high_yield_5m_ga_on_frame(
            **common,
            output_root=tmp_path / "multiple-candidates",
            max_candidates=2,
            prior_shared_tail_exposure=False,
        )
    with pytest.raises(
        HighYield5mGAMiningError,
        match="boundary_not_contiguous",
    ):
        run_high_yield_5m_ga_on_frame(
            **{
                **common,
                "frozen_unseen_holdout_start_utc": frame.index[30_001].to_pydatetime(),
            },
            output_root=tmp_path / "gap",
            max_candidates=1,
            prior_shared_tail_exposure=False,
        )


def test_selection_gate_failure_preserves_unseen_holdout_and_lock_is_tail_invariant(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    frame = _frame()
    changed = frame.copy()
    selection_end = 30_000
    changed.iloc[selection_end:, changed.columns.get_loc("open")] *= 1.25
    changed.iloc[selection_end:, changed.columns.get_loc("high")] *= 1.30
    changed.iloc[selection_end:, changed.columns.get_loc("low")] *= 0.75
    changed.iloc[selection_end:, changed.columns.get_loc("close")] *= 0.80
    original_builder = module.build_high_yield_5m_target
    observed_lengths: list[int] = []

    def build(selection_frame: pd.DataFrame, genome: HighYield5mGenome) -> pd.Series:
        observed_lengths.append(len(selection_frame))
        return original_builder(selection_frame, genome)

    monkeypatch.setattr(module, "build_high_yield_5m_target", build)
    monkeypatch.setattr(
        module,
        "_selection_gate_reasons",
        lambda **_: ["forced_selection_gate_failure"],
    )
    common = {
        "data_provenance": _provenance(frame),
        "seed": 20260827,
        "population_size": 8,
        "generations": 1,
        "fold_count": 2,
        "max_candidates": 1,
        "prior_shared_tail_exposure": False,
        "frozen_unseen_holdout_start_utc": frame.index[selection_end].to_pydatetime(),
        "prior_research_cutoff_utc": frame.index[selection_end - 1].to_pydatetime(),
        "experiment_id": "contract-preserved-holdout",
        "generated_at_utc": pd.Timestamp("2026-08-27T00:00:00Z").to_pydatetime(),
    }
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first = run_high_yield_5m_ga_on_frame(
        frame=frame,
        output_root=first_root,
        **common,
    )
    second = run_high_yield_5m_ga_on_frame(
        frame=changed,
        output_root=second_root,
        **common,
    )

    assert set(observed_lengths) == {selection_end}
    assert first["decision"] == "reject_selection_batch_holdout_not_revealed"
    assert first["validation_design"]["holdout_revealed"] is False
    assert first["validation_design"]["holdout_exposure_after_run"] == "preserved_unseen"
    assert first["top_candidates"][0]["frozen_unseen_holdout"]["cost_stress"] is None
    assert first["frozen_holdout_lock"]["reveal_authorized"] is False
    first_lock = json.loads(
        (first_root / "btc_high_yield_5m_frozen_holdout_lock.json").read_text(
            encoding="utf-8"
        )
    )
    second_lock = json.loads(
        (second_root / "btc_high_yield_5m_frozen_holdout_lock.json").read_text(
            encoding="utf-8"
        )
    )
    assert first_lock == second_lock
    assert first["frozen_holdout_lock"]["semantic_sha256"] == second[
        "frozen_holdout_lock"
    ]["semantic_sha256"]
    with pytest.raises(
        HighYield5mGAMiningError,
        match="output_root_must_be_new",
    ):
        run_high_yield_5m_ga_on_frame(
            frame=frame,
            output_root=first_root,
            **common,
        )


def test_frozen_unseen_holdout_reveals_only_locked_champion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    frame = _frame()
    selection_end = 30_000
    output_root = tmp_path / "official"
    lock_path = output_root / "btc_high_yield_5m_frozen_holdout_lock.json"
    original_builder = module.build_high_yield_5m_target
    full_frame_builds = 0

    def build(candidate_frame: pd.DataFrame, genome: HighYield5mGenome) -> pd.Series:
        nonlocal full_frame_builds
        if len(candidate_frame) == len(frame):
            full_frame_builds += 1
            assert lock_path.exists(), "candidate lock must exist before holdout reveal"
        else:
            assert len(candidate_frame) == selection_end
        return original_builder(candidate_frame, genome)

    monkeypatch.setattr(module, "build_high_yield_5m_target", build)
    monkeypatch.setattr(module, "_selection_gate_reasons", lambda **_: [])
    report = run_high_yield_5m_ga_on_frame(
        frame=frame,
        data_provenance=_provenance(frame),
        output_root=output_root,
        seed=20260827,
        population_size=8,
        generations=1,
        fold_count=2,
        max_candidates=1,
        prior_shared_tail_exposure=False,
        frozen_unseen_holdout_start_utc=frame.index[selection_end].to_pydatetime(),
        prior_research_cutoff_utc=frame.index[selection_end - 1].to_pydatetime(),
        experiment_id="contract-single-reveal",
        generated_at_utc=pd.Timestamp("2026-08-27T00:00:00Z").to_pydatetime(),
    )

    assert full_frame_builds == 1
    assert report["validation_design"]["holdout_revealed"] is True
    assert report["validation_design"]["holdout_candidate_count_revealed"] == 1
    assert report["validation_design"]["holdout_exposure_after_run"] == "consumed_once"
    assert report["frozen_holdout_lock"]["reveal_authorized"] is True
    assert report["top_candidates"][0]["frozen_unseen_holdout"]["cost_stress"]


def test_qcv2r1_frozen_holdout_preregistration_matches_engine_contract() -> None:
    prereg = json.loads(
        Path(
            "docs/research/BTC_HIGH_YIELD_5M_QCV2R1_FROZEN_HOLDOUT_GA_01_PREREG.json"
        ).read_text(encoding="utf-8")
    )
    protocol = prereg["search_protocol"]
    windows = prereg["frozen_windows"]
    data = prereg["data_binding"]
    stable = lambda value: json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    assert prereg["status"] == "frozen_before_search"
    assert protocol["seed"] == 20260827
    assert protocol["population_size"] == 64
    assert protocol["generations"] == 16
    assert protocol["population_slots_this_round"] == 1024
    assert protocol["max_candidates"] == 1
    assert protocol["gene_space_sha256"] == hashlib.sha256(
        stable(module._gene_space()).encode("utf-8")
    ).hexdigest()
    assert protocol["cost_scenarios_sha256"] == hashlib.sha256(
        stable([scenario.to_dict() for scenario in module.COST_SCENARIOS]).encode(
            "utf-8"
        )
    ).hexdigest()
    assert windows["selection_rows"] == 248_270
    assert windows["unseen_holdout_rows"] == 30_658
    assert windows["selection_end_open_time"] == "2026-05-12T01:05:00Z"
    assert windows["unseen_holdout_start_open_time"] == "2026-05-12T01:10:00Z"
    assert data["dataset_version"].endswith("-qc2r1")
    assert data["five_minute_file_sha256"] == (
        "76e8654cd11fc40b873b30d4a6fa8b2ed618256721e3b7840e180bd0f0359c08"
    )
    assert prereg["guardrails"]["promotion_allowed"] is False
    assert prereg["guardrails"]["paper_allowed"] is False
    assert prereg["guardrails"]["live_allowed"] is False
