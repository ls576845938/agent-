from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import jsonschema
import pytest

from quant_crypto.application.btc_current_head_authoritative_data_pointer import (
    AUTHORITATIVE_MANIFEST_GIT_SPEC,
    PublicationDependencies,
    PublicationError,
    _git_state,
    publish_current_head_authoritative_data_pointer,
)
from quant_crypto.application.btc_current_head_gate_rebuild import (
    DEFAULT_OKX_POINTER_PATH,
    validate_authoritative_okx_pointer,
)
from quant_crypto.research.btc_okx_native_promotion_gate import (
    FROZEN_PREREG_BLOB_SHA256,
    evaluate_active_criteria_contract,
)
from quant_crypto.adapters.btc_runtime_artifact_store import (
    BTCRuntimeArtifactStoreError,
    BTCRuntimeArtifactWriter,
    OWNER_MARKER_NAME,
    WRITER_LOCK_NAME,
    build_btc_runtime_artifact_owner_marker,
)


HEAD = "f" * 40
DATA_VERSION = "btc-okx-10s-feed-00000001-20260827t111218925177z-src4e615032a6"
DATASET_ID = "btc-okx-10s-microstructure-immutable-feed"
AGGREGATE = "2fa444de042e742e9763b6a4988205b7f05d5374d6cf66fa94d20c7efd26fd70"
HASH = "a" * 64


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _writer(tmp_path: Path) -> BTCRuntimeArtifactWriter:
    root = tmp_path / "external-artifacts"
    root.mkdir()
    repository_identity = f"sha256:{'1' * 64}"
    (root / OWNER_MARKER_NAME).write_text(
        json.dumps(build_btc_runtime_artifact_owner_marker(repository_identity)),
        encoding="utf-8",
    )
    return BTCRuntimeArtifactWriter(
        source_repo_root=tmp_path,
        artifact_root=root,
        repository_identity=repository_identity,
        worktree_roots=(tmp_path / "repo",),
    )


def _metrics() -> dict[str, object]:
    information = {
        horizon: {
            "potential_non_overlap_windows": 0,
            "eligible_labeled_windows": 0,
            "autocorrelation_adjusted_ess": 0.0,
            "joined_coverage_pct": 100.0,
            "future_label_availability_pct": 0.0,
        }
        for horizon in ("10s", "30s", "60s")
    }
    return {
        "raw_counts": {"trade_rows": 10, "ordered_l2_message_count": 20},
        "information_by_horizon": information,
        "utc_4h_bucket_independent_60s_windows": [0] * 6,
        "weekday_independent_60s_windows": [0] * 7,
        "regime_cell_ess": [0.0] * 9,
        "quality": {
            "duplicate_count": 0,
            "out_of_order_count": 0,
            "unrecovered_sequence_gap_count": 0,
            "crossed_book_count": 0,
            "one_sided_book_count": 0,
            "reconnect_snapshot_reset_verified": True,
            "gap_resync_embargo_seconds": 60,
            "receive_lag_p99_ms": 1.0,
            "trade_book_alignment_p99_ms": 1.0,
        },
        "cost": {
            "sample_completeness_pct": 100.0,
            "spread_available": True,
            "fee_available": True,
            "depth_impact_available": True,
            "stratified_stability_verified": False,
        },
        "coverage": {
            "max_verified_capture_span_seconds": 55.997,
            "ordered_l2_two_sided_coverage_pct": 100.0,
            "utc_hour_coverage_complete": False,
            "weekday_coverage_complete": False,
            "volatility_liquidity_regime_coverage_complete": False,
        },
        "reference_data": {},
        "fields": {
            "unique_tick_trade_ids": True,
            "exchange_timestamps": True,
            "aggressor_side": True,
            "two_sided_bbo": True,
            "trade_bbo_joined": True,
            "trade_ordered_l2_joined": True,
            "l2_price_levels": True,
            "ordered_l2_updates": True,
            "volume_depth_shock": True,
            "recovery_events": True,
            "time_aligned_open_interest": False,
            "liquidation_events": False,
        },
    }


def _prereg() -> dict[str, object]:
    path = Path("docs/research/BTC_10S_MICROSTRUCTURE_DATA_CONTRACT_01_PREREG.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _deps(*, dirty: bool = False, free_gib: float = 100.0) -> PublicationDependencies:
    binding = {
        "manifest_git_spec": AUTHORITATIVE_MANIFEST_GIT_SPEC,
        "manifest_blob_sha256": HASH,
        "dataset_id": DATASET_ID,
        "dataset_version": DATA_VERSION,
        "aggregate_sha256": AGGREGATE,
        "file_count": 24,
        "total_bytes": 11_703_883,
        "coverage": {
            "start": "2026-08-27T11:12:39.209Z",
            "end": "2026-08-27T11:13:35.206Z",
        },
        "resolution_status": "resolved_verified",
        "full_file_hash_verified": True,
        "fallback_used": False,
        "blockers": [],
        "_resolved_root": Path("ignored-physical-root"),
        "_manifest": {"files": []},
    }
    return PublicationDependencies(
        git_state=lambda _: {
            "head": HEAD,
            "branch": "main",
            "dirty_paths": ["x.py"] if dirty else [],
        },
        resolve_source=lambda **_: dict(binding),
        inspect_source=lambda value: {**dict(value), "measured": {}},
        derive_metrics=lambda _: _metrics(),
        load_prereg=lambda *_args, **_kwargs: (_prereg(), _sha(Path(
            "docs/research/BTC_10S_MICROSTRUCTURE_DATA_CONTRACT_01_PREREG.json"
        ).read_bytes())),
        disk_free_bytes=lambda _: int(free_gib * (1024**3)),
    )


def test_publication_is_current_head_atomic_pointer_last_and_fail_closed(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    receipt = publish_current_head_authoritative_data_pointer(
        repo_root=Path.cwd(),
        artifact_writer=writer,
        expected_head=HEAD,
        run_id="btc-current-head-pointer-fixture-01",
        generated_at_utc="2026-08-29T00:00:00Z",
        dependencies=_deps(),
    )

    pointer = json.loads(writer.resolve(DEFAULT_OKX_POINTER_PATH).read_text(encoding="utf-8"))
    active = json.loads(writer.resolve(
        "artifacts/btc_promotion_gate_active_criteria/latest/btc_promotion_gate_active_criteria.json"
    ).read_text(encoding="utf-8"))
    validation = validate_authoritative_okx_pointer(
        repo_root=Path.cwd(),
        current_head=HEAD,
        artifact_reader=writer,
    )

    assert validation["status"] == "valid_current_head"
    assert pointer["source_code_commit"] == HEAD
    assert pointer["dataset_id"] == DATASET_ID
    assert pointer["data_version"] == DATA_VERSION
    assert pointer["aggregate_sha256"] == AGGREGATE
    assert pointer["manifest_sha256"] == validation["manifest"]["actual_sha256"]
    assert pointer["evidence_sha256"] == validation["evidence"]["actual_sha256"]
    assert active["immutable_manifest_sha256"] == pointer["manifest_sha256"]
    assert active["immutable_evidence_sha256"] == pointer["evidence_sha256"]
    assert active["active_strategy_family"] == "trade_imbalance_continuation"
    assert active["active_horizon"] == "10s"
    selected = active["measured_metrics"]["information_by_horizon"]["10s"]
    assert selected["eligible_labeled_windows"] == 0
    assert selected["autocorrelation_adjusted_ess"] == 0.0
    assert active["decision"] == "blocked_insufficient_information"
    assert "historical_timestamp_aligned_depth_fill_mapping_missing" in json.dumps(
        pointer
    )
    assert "ignored-physical-root" not in json.dumps(receipt)
    assert "ignored-physical-root" not in json.dumps(pointer)
    assert pointer["active_criteria"]["authority"] == "immutable_pointer_member"
    assert pointer["active_criteria"]["path"].endswith("/active_criteria.json")
    assert pointer["active_criteria_mirror"]["authority"] == "non_authoritative_cache_only"
    for path in receipt["artifact_paths"].values():
        payload_path = writer.resolve(path)
        if payload_path.is_file():
            assert "ignored-physical-root" not in payload_path.read_text(encoding="utf-8")
    assert all(value is False for value in receipt["safety"].values())

    schema = json.loads(Path(
        "schemas/btc_current_head_authoritative_data_pointer_receipt.schema.json"
    ).read_text(encoding="utf-8"))
    jsonschema.validate(receipt, schema)


@pytest.mark.parametrize(
    ("deps", "error"),
    [
        (_deps(dirty=True), "publication_git_worktree_dirty"),
        (_deps(free_gib=49.99), "publication_storage_below_50_gib"),
    ],
)
def test_dirty_or_low_storage_fails_before_pointer_write(
    tmp_path: Path,
    deps: PublicationDependencies,
    error: str,
) -> None:
    writer = _writer(tmp_path)
    with pytest.raises(PublicationError, match=error):
        publish_current_head_authoritative_data_pointer(
            repo_root=Path.cwd(),
            artifact_writer=writer,
            expected_head=HEAD,
            run_id="btc-current-head-pointer-fixture-02",
            generated_at_utc="2026-08-29T00:00:00Z",
            dependencies=deps,
        )
    assert not writer.resolve(DEFAULT_OKX_POINTER_PATH).exists()


def test_wrong_head_and_non_main_fail_closed(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    deps = _deps()
    deps = PublicationDependencies(
        **{**deps.__dict__, "git_state": lambda _: {
            "head": "e" * 40,
            "branch": "feature",
            "dirty_paths": [],
        }}
    )
    with pytest.raises(PublicationError, match="publication_must_run_from_current_main"):
        publish_current_head_authoritative_data_pointer(
            repo_root=Path.cwd(),
            artifact_writer=writer,
            expected_head=HEAD,
            run_id="btc-current-head-pointer-fixture-03",
            generated_at_utc="2026-08-29T00:00:00Z",
            dependencies=deps,
        )


def test_pointer_is_not_replaced_when_pre_pointer_step_fails(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    publish_current_head_authoritative_data_pointer(
        repo_root=Path.cwd(),
        artifact_writer=writer,
        expected_head=HEAD,
        run_id="btc-current-head-pointer-fixture-old",
        generated_at_utc="2026-08-29T00:00:00Z",
        dependencies=_deps(),
    )
    old_pointer = json.loads(
        writer.resolve(DEFAULT_OKX_POINTER_PATH).read_text(encoding="utf-8")
    )
    deps = _deps()
    deps = PublicationDependencies(
        **{**deps.__dict__, "before_pointer_publish": lambda: (_ for _ in ()).throw(
            PublicationError("injected_before_pointer_failure")
        )}
    )
    with pytest.raises(PublicationError, match="injected_before_pointer_failure"):
        publish_current_head_authoritative_data_pointer(
            repo_root=Path.cwd(),
            artifact_writer=writer,
            expected_head=HEAD,
            run_id="btc-current-head-pointer-fixture-04",
            generated_at_utc="2026-08-29T00:00:00Z",
            dependencies=deps,
        )
    assert json.loads(writer.resolve(DEFAULT_OKX_POINTER_PATH).read_text(encoding="utf-8")) == old_pointer
    mirror = json.loads(writer.resolve(
        "artifacts/btc_promotion_gate_active_criteria/latest/btc_promotion_gate_active_criteria.json"
    ).read_text(encoding="utf-8"))
    pointer_validation = validate_authoritative_okx_pointer(
        repo_root=Path.cwd(), current_head=HEAD, artifact_reader=writer
    )
    split = evaluate_active_criteria_contract(
        report=mirror,
        current_head=HEAD,
        expected_preregistration=_prereg(),
        expected_prereg_blob_sha256=FROZEN_PREREG_BLOB_SHA256,
        pointer_validation=pointer_validation,
    )
    assert split["pointer_lineage_binding_valid"] is False
    assert "btc_okx_native:active_criteria_pointer_lineage_mismatch" in split["promotion_blockers"]

    publish_current_head_authoritative_data_pointer(
        repo_root=Path.cwd(),
        artifact_writer=writer,
        expected_head=HEAD,
        run_id="btc-current-head-pointer-fixture-recovered",
        generated_at_utc="2026-08-29T00:00:02Z",
        dependencies=_deps(),
    )
    repaired_pointer = validate_authoritative_okx_pointer(
        repo_root=Path.cwd(), current_head=HEAD, artifact_reader=writer
    )
    repaired_mirror = json.loads(writer.resolve(
        "artifacts/btc_promotion_gate_active_criteria/latest/btc_promotion_gate_active_criteria.json"
    ).read_text(encoding="utf-8"))
    repaired = evaluate_active_criteria_contract(
        report=repaired_mirror,
        current_head=HEAD,
        expected_preregistration=_prereg(),
        expected_prereg_blob_sha256=FROZEN_PREREG_BLOB_SHA256,
        pointer_validation=repaired_pointer,
    )
    assert repaired["pointer_lineage_binding_valid"] is True
    assert repaired["information_coverage_evidence_valid"] is False


def test_unrelated_dirty_does_not_block_but_related_source_dirty_does(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
    related = repo / "docs/research/BTC_10S_MICROSTRUCTURE_DATA_CONTRACT_01_PREREG.json"
    related.parent.mkdir(parents=True)
    related.write_text("{}\n", encoding="utf-8")
    unrelated = repo / "notes.txt"
    unrelated.write_text("clean\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", related.relative_to(repo), unrelated.relative_to(repo)], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "fixture"], cwd=repo, check=True, capture_output=True)

    unrelated.write_text("unrelated dirty\n", encoding="utf-8")
    assert _git_state(repo)["dirty_paths"] == []

    related.write_text("{\"dirty\": true}\n", encoding="utf-8")
    assert _git_state(repo)["dirty_paths"] == [
        "docs/research/BTC_10S_MICROSTRUCTURE_DATA_CONTRACT_01_PREREG.json"
    ]


def test_wrong_or_unverified_immutable_binding_never_publishes(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    deps = _deps()
    bad = deps.resolve_source()
    bad["full_file_hash_verified"] = False
    bad["manifest_git_spec"] = "HEAD:.agent/data_manifests/latest.json"
    deps = PublicationDependencies(
        **{**deps.__dict__, "resolve_source": lambda **_: bad}
    )
    with pytest.raises(PublicationError, match="authoritative_immutable_binding_invalid"):
        publish_current_head_authoritative_data_pointer(
            repo_root=Path.cwd(),
            artifact_writer=writer,
            expected_head=HEAD,
            run_id="btc-current-head-pointer-fixture-05",
            generated_at_utc="2026-08-29T00:00:00Z",
            dependencies=deps,
        )
    assert not writer.resolve(DEFAULT_OKX_POINTER_PATH).exists()


def test_attestation_hash_or_membership_tamper_is_rejected(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    publish_current_head_authoritative_data_pointer(
        repo_root=Path.cwd(),
        artifact_writer=writer,
        expected_head=HEAD,
        run_id="btc-current-head-pointer-fixture-06",
        generated_at_utc="2026-08-29T00:00:00Z",
        dependencies=_deps(),
    )
    pointer_path = writer.resolve(DEFAULT_OKX_POINTER_PATH)
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    attestation_ref = next(
        row for row in pointer["input_lineage"] if row["kind"] == "data_steward_attestation"
    )
    writer.resolve(attestation_ref["path"]).write_text("{}\n", encoding="utf-8")
    validation = validate_authoritative_okx_pointer(
        repo_root=Path.cwd(),
        current_head=HEAD,
        artifact_reader=writer,
    )
    assert validation["status"] == "blocked_fail_closed"
    assert any(value.startswith("attestation:") for value in validation["validation_errors"])

    pointer["input_lineage"].append(dict(attestation_ref))
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    validation = validate_authoritative_okx_pointer(
        repo_root=Path.cwd(),
        current_head=HEAD,
        artifact_reader=writer,
    )
    assert "attestation:lineage_reference_not_unique" in validation["validation_errors"]


def test_owner_marker_or_writer_lock_failure_does_not_replace_pointer(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    lock = writer.artifact_root / WRITER_LOCK_NAME
    lock.write_text("{}\n", encoding="utf-8")
    with pytest.raises(BTCRuntimeArtifactStoreError, match="writer_lock_held"):
        publish_current_head_authoritative_data_pointer(
            repo_root=Path.cwd(),
            artifact_writer=writer,
            expected_head=HEAD,
            run_id="btc-current-head-pointer-fixture-07",
            generated_at_utc="2026-08-29T00:00:00Z",
            dependencies=_deps(),
        )
    assert not writer.resolve(DEFAULT_OKX_POINTER_PATH).exists()

    lock.unlink()
    (writer.artifact_root / OWNER_MARKER_NAME).write_text("{}\n", encoding="utf-8")
    with pytest.raises(BTCRuntimeArtifactStoreError, match="owner_marker_schema_invalid"):
        publish_current_head_authoritative_data_pointer(
            repo_root=Path.cwd(),
            artifact_writer=writer,
            expected_head=HEAD,
            run_id="btc-current-head-pointer-fixture-08",
            generated_at_utc="2026-08-29T00:00:00Z",
            dependencies=_deps(),
        )


def test_multiple_exact_manifests_verified_ess_and_real_mapping_are_bound(tmp_path: Path) -> None:
    specs = [
        f"{'a' * 40}:.agent/data_manifests/btc-feed/feed-a.json",
        f"{'b' * 40}:.agent/data_manifests/btc-feed/feed-b.json",
    ]
    ess_spec = f"{'c' * 40}:.agent/data_manifests/btc-ess/ess-artifact.json"
    mapping_spec = f"{'d' * 40}:.agent/data_manifests/btc-depth/mapping-artifact.json"
    bindings = {
        spec: {
            "manifest_git_spec": spec,
            "manifest_blob_sha256": _sha(spec.encode()),
            "dataset_id": DATASET_ID,
            "dataset_version": f"feed-{index}",
            "aggregate_sha256": _sha(f"aggregate-{index}".encode()),
            "file_count": 2,
            "total_bytes": 100,
            "coverage": {"start": f"2026-08-2{index}T00:00:00Z", "end": f"2026-08-2{index}T00:01:00Z"},
            "resolution_status": "resolved_verified",
            "full_file_hash_verified": True,
            "fallback_used": False,
            "blockers": [],
            "_resolved_root": Path(f"ignored-root-{index}"),
            "_manifest": {
                "producer_role": "data_steward",
                "readiness_class": "quality_checked",
                "files": [],
            },
        }
        for index, spec in enumerate(specs, start=1)
    }
    ess = {
        "schema_version": "btc_10s_microstructure_ess_artifact_v1",
        "source_head": HEAD,
        "source_manifest_git_specs": specs,
        "measured_metrics": _metrics(),
        "full_manifest_pool_verified": True,
        "fallback_used": False,
        "safety": {name: False for name in ("promotion", "paper", "live", "private", "order", "real_order", "transfer", "withdraw")},
    }
    mapping = {
        "schema_version": "btc_depth_slippage_fill_mapping_report_v2",
        "source_head": HEAD,
        "immutable_l2_manifest_git_specs": specs,
        "strategy_fill_mapping_verified": True,
        "fill_mapping_state": "verified",
        "natural_fill_ledger_sha256": "9" * 64,
        "promotion_evidence_ready": True,
        "blockers": [],
        "safety": {name: False for name in ("promotion", "paper", "live", "private", "order", "real_order", "transfer", "withdraw")},
        "gate": {
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "withdraw_allowed": False,
        },
    }
    payloads = {ess_spec: ess, mapping_spec: mapping}
    deps = _deps()
    deps = PublicationDependencies(
        **{
            **deps.__dict__,
            "resolve_source": lambda **kwargs: dict(bindings[kwargs["manifest_git_spec"]]),
            "read_git_json": lambda _root, spec: (dict(payloads[spec]), _sha(json.dumps(payloads[spec], sort_keys=True).encode())),
        }
    )
    writer = _writer(tmp_path)
    receipt = publish_current_head_authoritative_data_pointer(
        repo_root=Path.cwd(),
        artifact_writer=writer,
        expected_head=HEAD,
        manifest_git_specs=specs,
        ess_artifact_git_spec=ess_spec,
        depth_fill_mapping_git_spec=mapping_spec,
        run_id="btc-current-head-pointer-multi-manifest",
        generated_at_utc="2026-08-29T00:00:00Z",
        dependencies=deps,
    )
    pointer = json.loads(writer.resolve(DEFAULT_OKX_POINTER_PATH).read_text(encoding="utf-8"))

    assert pointer["source_manifest_git_specs"] == specs
    assert len([row for row in pointer["input_lineage"] if row["kind"] == "immutable_shared_data_manifest"]) == 2
    assert pointer["ess_artifact"]["git_spec"] == ess_spec
    assert pointer["depth_fill_mapping"]["git_spec"] == mapping_spec
    assert pointer["depth_fill_mapping"]["natural_fill_ledger_sha256"] == "9" * 64
    assert "btc_okx_native:historical_timestamp_aligned_depth_fill_mapping_missing" not in pointer["blockers"]
    assert all(receipt["safety"][name] is False for name in receipt["safety"])


def test_multi_manifest_publication_rejects_latest_and_artifact_binding_mismatch(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    with pytest.raises(PublicationError, match="exact_committed_manifest_git_spec_required"):
        publish_current_head_authoritative_data_pointer(
            repo_root=Path.cwd(),
            artifact_writer=writer,
            expected_head=HEAD,
            manifest_git_specs=["HEAD:.agent/data_manifests/latest.json"],
            dependencies=_deps(),
        )

    spec = f"{'a' * 40}:.agent/data_manifests/btc-feed/feed-a.json"
    ess_spec = f"{'c' * 40}:.agent/data_manifests/btc-ess/ess-artifact.json"
    mapping_spec = f"{'d' * 40}:.agent/data_manifests/btc-depth/mapping-artifact.json"
    binding = _deps().resolve_source()
    binding["manifest_git_spec"] = spec
    binding["dataset_version"] = "feed-a"
    binding["aggregate_sha256"] = _sha(b"feed-a")
    binding["_manifest"] = {
        "producer_role": "data_steward",
        "readiness_class": "quality_checked",
        "files": [],
    }
    bad_ess = {
        "source_head": "e" * 40,
        "source_manifest_git_specs": [spec],
        "measured_metrics": _metrics(),
        "full_manifest_pool_verified": True,
        "fallback_used": False,
    }
    mapping = {
        "source_head": HEAD,
        "immutable_l2_manifest_git_specs": [spec],
        "strategy_fill_mapping_verified": True,
        "natural_fill_ledger_sha256": "9" * 64,
        "promotion_evidence_ready": True,
        "blockers": [],
        "safety": {name: False for name in ("promotion", "paper", "live", "private", "order", "real_order", "transfer", "withdraw")},
    }
    payloads = {ess_spec: bad_ess, mapping_spec: mapping}
    deps = _deps()
    deps = PublicationDependencies(
        **{
            **deps.__dict__,
            "resolve_source": lambda **_: dict(binding),
            "read_git_json": lambda _root, selected: (dict(payloads[selected]), _sha(json.dumps(payloads[selected], sort_keys=True).encode())),
        }
    )
    with pytest.raises(PublicationError, match="verified_ess_artifact_binding_invalid"):
        publish_current_head_authoritative_data_pointer(
            repo_root=Path.cwd(),
            artifact_writer=writer,
            expected_head=HEAD,
            manifest_git_specs=[spec],
            ess_artifact_git_spec=ess_spec,
            depth_fill_mapping_git_spec=mapping_spec,
            dependencies=deps,
        )


def test_multi_manifest_publication_rejects_blocked_export_slice(tmp_path: Path) -> None:
    spec = f"{'a' * 40}:.agent/data_manifests/btc-feed/blocked-slice.json"
    binding = _deps().resolve_source()
    binding.update(
        {
            "manifest_git_spec": spec,
            "dataset_version": "blocked-slice",
            "aggregate_sha256": _sha(b"blocked-slice"),
            "_manifest": {
                "producer_role": "data_steward",
                "readiness_class": "quality_checked",
                "quality_status": "blocked_export",
                "status": "blocked_export",
                "files": [],
            },
        }
    )
    deps = _deps()
    deps = PublicationDependencies(
        **{**deps.__dict__, "resolve_source": lambda **_: dict(binding)}
    )
    with pytest.raises(PublicationError, match="authoritative_immutable_binding_invalid"):
        publish_current_head_authoritative_data_pointer(
            repo_root=Path.cwd(),
            artifact_writer=_writer(tmp_path),
            expected_head=HEAD,
            manifest_git_specs=[spec],
            dependencies=deps,
        )
