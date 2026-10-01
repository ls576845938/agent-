from __future__ import annotations

import hashlib
import json
import shutil
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

import jsonschema
import pytest

from quant_crypto.data.immutable_okx_10s_microstructure_export import (
    ATTESTATION_NAME,
    MicrostructureExportBlocked,
    MicrostructureSegmentSource,
    export_immutable_okx_10s_microstructure,
)
from quant_crypto.data.okx_l2_capture_contract import (
    OKX_L2_CAPTURE_MANIFEST_SCHEMA_VERSION,
    OKX_L2_RAW_MANIFEST_FILE,
    OKX_L2_RAW_MESSAGES_FILE,
)
from scripts.run_btc_okx_10s_microstructure_immutable_feed import (
    EXACT_CHANNELS,
    FeedConfig,
    FeedDependencies,
    WriterConflict,
    run_feed_continuously,
    run_feed_slice,
)


ROOT = Path(__file__).resolve().parents[2]
HEAD = "4" * 40
BASE_TIME = datetime(2026, 8, 27, 0, 0, 1, tzinfo=timezone.utc)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frame(
    sequence: int,
    receive: str,
    monotonic_ns: int,
    channel: str,
    payload: dict[str, Any],
    *,
    connection: int = 1,
) -> dict[str, Any]:
    return {
        "capture_sequence": sequence,
        "connection_sequence": connection,
        "local_receive_ts": receive,
        "monotonic_ns": monotonic_ns,
        "channel": channel,
        "instId": "BTC-USDT-SWAP",
        "event": None,
        "action": payload.get("action"),
        "raw": json.dumps(payload, separators=(",", ":")),
    }


def _messages() -> list[dict[str, Any]]:
    return [
        _frame(
            1,
            "2026-08-27T00:00:00.100Z",
            1_000_000_000,
            "books",
            {
                "arg": {"channel": "books", "instId": "BTC-USDT-SWAP"},
                "action": "snapshot",
                "data": [{"ts": "1787788800000", "seqId": 100, "prevSeqId": 99, "checksum": 0, "bids": [["100", "10", "0", "1"]], "asks": [["101", "10", "0", "1"]]}],
            },
        ),
        _frame(
            2,
            "2026-08-27T00:00:00.200Z",
            1_100_000_000,
            "trades",
            {
                "arg": {"channel": "trades", "instId": "BTC-USDT-SWAP"},
                "data": [{"tradeId": "t1", "ts": "1787788800150", "px": "100.5", "sz": "1", "side": "buy"}],
            },
        ),
        _frame(
            3,
            "2026-08-27T00:00:00.300Z",
            1_200_000_000,
            "books",
            {
                "arg": {"channel": "books", "instId": "BTC-USDT-SWAP"},
                "action": "update",
                "data": [{"ts": "1787788800250", "seqId": 101, "prevSeqId": 100, "checksum": 0, "bids": [["100", "9", "0", "1"]], "asks": []}],
            },
        ),
        _frame(
            4,
            "2026-08-27T00:00:00.400Z",
            1_300_000_000,
            "trades",
            {
                "arg": {"channel": "trades", "instId": "BTC-USDT-SWAP"},
                "data": [{"tradeId": "t2", "ts": "1787788800350", "px": "100.4", "sz": "2", "side": "sell"}],
            },
        ),
    ]


def _segment(tmp_path: Path, *, rows: list[dict[str, Any]] | None = None) -> MicrostructureSegmentSource:
    segment = tmp_path / "segment-01"
    segment.mkdir(parents=True)
    selected = rows or _messages()
    raw = segment / OKX_L2_RAW_MESSAGES_FILE
    raw.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in selected), encoding="utf-8", newline="\n")
    counts: dict[str, int] = {}
    for row in selected:
        if row["channel"] in {"trades", "books"}:
            message = json.loads(row["raw"])
            if isinstance(message.get("data"), list):
                counts[row["channel"]] = counts.get(row["channel"], 0) + 1
    manifest = {
        "schema_version": OKX_L2_CAPTURE_MANIFEST_SCHEMA_VERSION,
        "data_version": "fixture-segment-01",
        "capture_start": selected[0]["local_receive_ts"],
        "capture_end": selected[-1]["local_receive_ts"],
        "capture_duration_seconds": (selected[-1]["monotonic_ns"] - selected[0]["monotonic_ns"]) / 1e9,
        "capture_started_monotonic_ns": selected[0]["monotonic_ns"],
        "capture_ended_monotonic_ns": selected[-1]["monotonic_ns"],
        "public_ws_url": "wss://ws.okx.com:8443/ws/v5/public",
        "source_endpoint_category": "okx_public_market_data_websocket",
        "collector_commit": HEAD,
        "runtime_identity": {"fixture": "true"},
        "venue": "okx",
        "venue_symbol": "BTC-USDT-SWAP",
        "symbol": "BTCUSDT",
        "public_channels": ["trades", "books"],
        "public_ws_only": True,
        "api_key_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "broker_calls_used": False,
        "clock_source": "system_utc_and_python_monotonic_ns",
        "required_time_bases": ["local_receive_ts", "monotonic_ns", "exchange_ts_when_present"],
        "heartbeat_policy": "fixture",
        "checksum_or_sequence_policy": "raw_ws_capture_before_order_book_replay_sequence_validation",
        "message_count": len(selected),
        "data_message_count": sum(counts.values()),
        "channel_counts": counts,
        "connection_count": max(row["connection_sequence"] for row in selected),
        "forced_reconnect_after_messages": 0,
        "forced_reconnect_count": max(row["connection_sequence"] for row in selected) - 1,
        "error_count": 0,
        "gap_count": max(row["connection_sequence"] for row in selected) - 1,
    }
    manifest_path = segment / OKX_L2_RAW_MANIFEST_FILE
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return MicrostructureSegmentSource(segment, _sha(raw), _sha(manifest_path))


def test_export_preserves_same_capture_and_never_joins_future_book(tmp_path: Path) -> None:
    source = _segment(tmp_path)
    output = tmp_path / "immutable"
    result = export_immutable_okx_10s_microstructure(
        segments=(source,), output_dir=output, dataset_version="fixture-v1", source_head=HEAD, now=BASE_TIME
    )
    assert result["status"] == "quality_checked"
    rows = []
    for path in output.joinpath("normalized-trades").rglob("*.jsonl"):
        rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    assert [row["trade_id"] for row in rows] == ["t1", "t2"]
    assert [row["book_capture_sequence"] for row in rows] == [1, 3]
    assert all(row["book_capture_sequence"] < row["capture_sequence"] for row in rows)
    assert all(row["book_available_time"] <= row["available_time"] for row in rows)
    attestation = json.loads((output / ATTESTATION_NAME).read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "schemas/btc_okx_10s_microstructure_immutable_feed.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(attestation, schema)
    assert attestation["public_channels"] == EXACT_CHANNELS
    assert attestation["duplicate_trade_count"] == 0
    assert all(value is False for key, value in attestation["guardrails"].items() if key != "raw_frames_preserved")


def test_duplicate_trade_is_rejected(tmp_path: Path) -> None:
    rows = _messages()
    second_trade = json.loads(rows[3]["raw"])
    second_trade["data"][0]["tradeId"] = "t1"
    rows[3]["raw"] = json.dumps(second_trade)
    source = _segment(tmp_path, rows=rows)
    with pytest.raises(MicrostructureExportBlocked, match="duplicate_trade_id"):
        export_immutable_okx_10s_microstructure(
            segments=(source,), output_dir=tmp_path / "out", dataset_version="fixture-v1", source_head=HEAD, now=BASE_TIME
        )


def test_heartbeat_frames_preserve_global_capture_sequence(tmp_path: Path) -> None:
    rows = _messages()
    heartbeat = {
        "capture_sequence": 3,
        "connection_sequence": 1,
        "local_receive_ts": "2026-08-27T00:00:00.250Z",
        "monotonic_ns": 1_150_000_000,
        "channel": "event",
        "instId": "BTC-USDT-SWAP",
        "event": "pong",
        "action": None,
        "raw": "pong",
    }
    for row in rows[2:]:
        row["capture_sequence"] += 1
    rows.insert(2, heartbeat)
    source = _segment(tmp_path, rows=rows)
    output = tmp_path / "heartbeat-output"
    result = export_immutable_okx_10s_microstructure(
        segments=(source,), output_dir=output, dataset_version="fixture-heartbeat-v1", source_head=HEAD, now=BASE_TIME
    )
    assert result["status"] == "quality_checked"
    attestation = json.loads((output / ATTESTATION_NAME).read_text(encoding="utf-8"))
    assert attestation["source_segments"][0]["message_count"] == 5


@pytest.mark.parametrize(
    ("mutation", "blocker"),
    [
        ("sequence_gap", "l2_sequence_gap"),
        ("sequence_out_of_order", "l2_sequence_out_of_order"),
        ("checksum", "l2_checksum_mismatch"),
        ("reconnect_without_snapshot", "l2_reconnect_requires_new_snapshot"),
    ],
)
def test_book_integrity_failures_are_forwarded(tmp_path: Path, mutation: str, blocker: str) -> None:
    rows = _messages()
    book = json.loads(rows[2]["raw"])
    if mutation == "sequence_gap":
        book["data"][0]["prevSeqId"] = 98
    elif mutation == "sequence_out_of_order":
        book["data"][0]["seqId"] = 99
    elif mutation == "checksum":
        book["data"][0]["checksum"] = 123
    else:
        rows[2]["connection_sequence"] = 2
        rows[3]["connection_sequence"] = 2
    rows[2]["raw"] = json.dumps(book)
    source = _segment(tmp_path, rows=rows)
    with pytest.raises(MicrostructureExportBlocked, match=blocker):
        export_immutable_okx_10s_microstructure(
            segments=(source,), output_dir=tmp_path / "out", dataset_version="fixture-v1", source_head=HEAD, now=BASE_TIME
        )


def _config(tmp_path: Path) -> FeedConfig:
    return FeedConfig(
        repo_root=ROOT,
        runtime_root=tmp_path / "runtime",
        shared_data_root=tmp_path / "shared",
        duration_seconds=60,
        execute_network=True,
        source_head=HEAD,
    )


class RunnerFakes:
    def __init__(
        self,
        *,
        publish_error: bool = False,
        prune_error: bool = False,
    ) -> None:
        self.publish_error = publish_error
        self.prune_error = prune_error
        self.capture_calls = 0
        self.capture_durations: list[float] = []
        self.export_calls = 0
        self.publish_calls = 0
        self.published_targets: list[Path] = []
        self.removed_targets: list[Path] = []

    def clock(self, **kwargs: Any) -> dict[str, Any]:
        output = Path(kwargs["output_dir"])
        output.mkdir(parents=True, exist_ok=True)
        value = {"server_time_offset_verified": True, "blockers": []}
        (output / "btc_okx_server_time_preflight_report.json").write_text(json.dumps(value), encoding="utf-8")
        return value

    def capture(self, **kwargs: Any) -> dict[str, Any]:
        self.capture_calls += 1
        self.capture_durations.append(float(kwargs["duration_seconds"]))
        assert kwargs["channels"] == ["trades", "books"]
        assert kwargs["public_ws_url"] == "wss://ws.okx.com:8443/ws/v5/public"
        bundle = Path(kwargs["bundle_dir"])
        bundle.mkdir(parents=True, exist_ok=True)
        (bundle / OKX_L2_RAW_MESSAGES_FILE).write_text("{}\n", encoding="utf-8")
        (bundle / OKX_L2_RAW_MANIFEST_FILE).write_text("{}\n", encoding="utf-8")
        value = {"status": "verified_preflight", "channels": ["trades", "books"], "message_count": 2, "channel_counts": {"trades": 1, "books": 1}, "blockers": []}
        Path(kwargs["capture_report_path"]).write_text(json.dumps(value), encoding="utf-8")
        return value

    def export(self, **kwargs: Any) -> dict[str, Any]:
        self.export_calls += 1
        output = Path(kwargs["output_dir"])
        output.mkdir(parents=True, exist_ok=False)
        value = {
            "schema_version": "btc_okx_10s_microstructure_immutable_feed_v1",
            "coverage_start": "2026-08-27T00:00:00Z",
            "coverage_end": "2026-08-27T00:01:00Z",
            "guardrails": {"private_endpoint_used": False, "order_endpoint_used": False},
        }
        path = output / ATTESTATION_NAME
        path.write_text(json.dumps(value), encoding="utf-8")
        return {"status": "quality_checked", "attestation_path": str(path)}

    def publish(self, **kwargs: Any) -> dict[str, Any]:
        self.publish_calls += 1
        if self.publish_error:
            raise RuntimeError("injected_publish_failure")
        storage_relative = (
            f"datasets/{kwargs['dataset_id']}/{kwargs['dataset_version']}"
        )
        target = Path(kwargs["shared_root"]) / storage_relative
        target.mkdir(parents=True, exist_ok=False)
        (target / "immutable-copy.marker").write_text(
            "immutable fake copy\n", encoding="utf-8"
        )
        self.published_targets.append(target)
        source = Path(kwargs["source"])
        files = []
        for prefix in ("capture", "immutable_export"):
            for item in (source / prefix).rglob("*"):
                if item.is_file():
                    files.append(
                        {
                            "path": item.relative_to(source).as_posix(),
                            "sha256": _sha(item),
                            "bytes": item.stat().st_size,
                        }
                    )
        manifest = {
            "dataset_id": kwargs["dataset_id"],
            "dataset_version": kwargs["dataset_version"],
            "aggregate_sha256": "a" * 64,
            "storage_relative_path": storage_relative,
            "files": files,
        }
        path = Path(kwargs["manifest_output"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return {"status": "published", "manifest": manifest}

    def resolve_published(self, manifest: Mapping[str, Any], **kwargs: Any) -> Path:
        assert kwargs["verify_files"] is True
        target = Path(kwargs["shared_root"]) / str(
            manifest["storage_relative_path"]
        )
        assert target.is_dir()
        return target

    def remove_tree(self, path: Path) -> None:
        self.removed_targets.append(path)
        if self.prune_error:
            raise OSError("injected_prune_failure")
        shutil.rmtree(path)

    def dependencies(self) -> FeedDependencies:
        @contextmanager
        def proxy(_: str) -> Iterator[None]:
            yield

        return FeedDependencies(
            clock=self.clock,
            capture=self.capture,
            export=self.export,
            publish=self.publish,
            now=lambda: BASE_TIME,
            disk_free_bytes=lambda _: 100 * 1024**3,
            proxy=proxy,
            resolve_published=self.resolve_published,
            remove_tree=self.remove_tree,
        )


def test_feed_accepts_600_second_slice_and_passes_duration_unchanged(
    tmp_path: Path,
) -> None:
    fakes = RunnerFakes()
    config = replace(_config(tmp_path), duration_seconds=600)
    result = run_feed_slice(config, dependencies=fakes.dependencies())
    assert result["status"] == "published_quality_checked"
    assert fakes.capture_durations == [600.0]


def test_feed_rejects_duration_above_600_before_capture(tmp_path: Path) -> None:
    fakes = RunnerFakes()
    config = replace(_config(tmp_path), duration_seconds=600.001)
    with pytest.raises(ValueError, match="feed_duration_must_be_60_to_600_seconds"):
        run_feed_slice(config, dependencies=fakes.dependencies())
    assert fakes.capture_calls == 0


def test_feed_rejects_duration_below_60_before_capture(tmp_path: Path) -> None:
    fakes = RunnerFakes()
    config = replace(_config(tmp_path), duration_seconds=59.999)
    with pytest.raises(ValueError, match="feed_duration_must_be_60_to_600_seconds"):
        run_feed_slice(config, dependencies=fakes.dependencies())
    assert fakes.capture_calls == 0


def test_writer_conflict_precedes_owner_network_and_write(tmp_path: Path) -> None:
    fakes = RunnerFakes()

    @contextmanager
    def conflict(_: Path) -> Iterator[None]:
        raise WriterConflict("injected_writer_conflict")
        yield

    deps = fakes.dependencies()
    deps.lock = conflict
    result = run_feed_slice(_config(tmp_path), dependencies=deps)
    assert result["status"] == "blocked_writer_conflict"
    assert fakes.capture_calls == 0
    assert not _config(tmp_path).runtime_root.exists()


def test_publish_failure_resumes_same_slice_without_recapture(tmp_path: Path) -> None:
    fakes = RunnerFakes(publish_error=True)
    first = run_feed_slice(_config(tmp_path), dependencies=fakes.dependencies())
    assert first["status"] == "blocked_publication"
    assert (_config(tmp_path).runtime_root / "inflight.json").exists()
    fakes.publish_error = False
    second = run_feed_slice(_config(tmp_path), dependencies=fakes.dependencies())
    assert second["status"] == "published_quality_checked"
    assert fakes.capture_calls == 1
    assert fakes.export_calls == 1
    assert fakes.publish_calls == 2
    pointer = json.loads((_config(tmp_path).runtime_root / "latest_pointer.json").read_text(encoding="utf-8"))
    assert pointer["latest_pointer_updated_last"] is True
    assert all(value is False for value in second["safety_flags"].values())


def test_owner_conflict_fails_closed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.runtime_root.mkdir(parents=True)
    (config.runtime_root / "owner.json").write_text('{"other":true}\n', encoding="utf-8")
    result = run_feed_slice(config, dependencies=RunnerFakes().dependencies())
    assert result["status"] == "blocked_owner_conflict"


def test_continuous_mode_publishes_two_auditable_slices(tmp_path: Path) -> None:
    fakes = RunnerFakes()
    result = run_feed_continuously(
        _config(tmp_path),
        dependencies=fakes.dependencies(),
        max_slices=2,
        initial_backoff_seconds=0,
        max_backoff_seconds=0,
    )
    assert result["status"] == "continuous_max_slices_reached"
    assert result["published_slice_count"] == 2
    assert result["attempt_count"] == 2
    assert fakes.capture_calls == 2
    assert fakes.publish_calls == 2
    assert len(fakes.published_targets) == 2
    assert all(target.is_dir() for target in fakes.published_targets)
    slices = list((_config(tmp_path).runtime_root / "slices").iterdir())
    assert len(slices) == 2
    assert all(not (path / "capture").exists() for path in slices)
    assert all(not (path / "immutable_export").exists() for path in slices)
    assert all((path / "publication_result.json").is_file() for path in slices)
    assert len(
        list((_config(tmp_path).runtime_root / "prune_receipts").glob("*-pruned.json"))
    ) == 2
    audit = Path(result["audit_path"]).read_text(encoding="utf-8").splitlines()
    assert len(audit) == 2
    assert all(json.loads(line)["result"]["status"] == "published_quality_checked" for line in audit)


def test_continuous_publication_retry_reuses_capture(tmp_path: Path) -> None:
    fakes = RunnerFakes(publish_error=True)
    delays: list[float] = []

    def recover_after_backoff(delay: float) -> None:
        delays.append(delay)
        fakes.publish_error = False

    result = run_feed_continuously(
        _config(tmp_path),
        dependencies=fakes.dependencies(),
        max_slices=1,
        initial_backoff_seconds=1,
        max_backoff_seconds=4,
        sleep=recover_after_backoff,
    )
    assert result["status"] == "continuous_max_slices_reached"
    assert result["attempt_count"] == 2
    assert delays == [1]
    assert fakes.capture_calls == 1
    assert fakes.export_calls == 1
    assert fakes.publish_calls == 2


def test_continuous_l2_snapshot_resync_uses_new_slice_and_new_capture(
    tmp_path: Path,
) -> None:
    fakes = RunnerFakes()
    original_export = fakes.export
    delays: list[float] = []

    def export_with_one_snapshot_resync_failure(**kwargs: Any) -> dict[str, Any]:
        if fakes.export_calls == 0:
            fakes.export_calls += 1
            raise MicrostructureExportBlocked(
                [
                    "l2_clock_lag_exceeds_limit",
                    "l2_update_requires_new_snapshot",
                ]
            )
        return original_export(**kwargs)

    deps = fakes.dependencies()
    deps.export = export_with_one_snapshot_resync_failure
    result = run_feed_continuously(
        _config(tmp_path),
        dependencies=deps,
        max_slices=1,
        initial_backoff_seconds=1,
        max_backoff_seconds=4,
        sleep=delays.append,
    )

    assert result["status"] == "continuous_max_slices_reached"
    assert result["attempt_count"] == 2
    assert result["published_slice_count"] == 1
    assert delays == [1]
    assert fakes.capture_calls == 2
    assert fakes.export_calls == 2
    slices = sorted((_config(tmp_path).runtime_root / "slices").iterdir())
    assert len(slices) == 2
    assert (slices[0] / "capture" / OKX_L2_RAW_MESSAGES_FILE).is_file()
    assert not (slices[0] / "immutable_export").exists()
    first_event = json.loads(
        next(
            (_config(tmp_path).runtime_root / "events").glob(
                f"{slices[0].name}-blocked_public_network.json"
            )
        ).read_text(encoding="utf-8")
    )
    first_health = json.loads(
        (
            _config(tmp_path).runtime_root
            / str(first_event["health_path"])
        ).read_text(encoding="utf-8")
    )
    assert first_health["evidence"]["recovery_action"] == (
        "new_slice_new_connection_wait_for_snapshot"
    )
    assert first_health["evidence"]["blockers"] == [
        "l2_clock_lag_exceeds_limit",
        "l2_update_requires_new_snapshot",
    ]
    assert all(value is False for value in first_health["safety_flags"].values())


@pytest.mark.parametrize(
    "blockers",
    [
        ["l2_sequence_gap"],
        ["l2_checksum_mismatch"],
        [
            "l2_clock_lag_exceeds_limit",
            "l2_update_requires_new_snapshot",
            "l2_sequence_gap",
        ],
        ["unknown_export_blocker"],
    ],
)
def test_continuous_non_resync_export_blockers_remain_terminal(
    tmp_path: Path,
    blockers: list[str],
) -> None:
    fakes = RunnerFakes()
    delays: list[float] = []

    def blocked_export(**_: Any) -> dict[str, Any]:
        fakes.export_calls += 1
        raise MicrostructureExportBlocked(blockers)

    deps = fakes.dependencies()
    deps.export = blocked_export
    result = run_feed_continuously(
        _config(tmp_path),
        dependencies=deps,
        max_slices=1,
        sleep=delays.append,
    )

    assert result["status"] == "continuous_terminal_blocked"
    assert result["attempt_count"] == 1
    assert result["last_result"]["status"] == "blocked_export"
    assert result["last_result"]["retryable"] is False
    assert delays == []
    assert fakes.capture_calls == 1
    assert fakes.export_calls == 1


def test_continuous_terminal_blocker_stops_without_retry(tmp_path: Path) -> None:
    fakes = RunnerFakes()
    deps = fakes.dependencies()
    deps.disk_free_bytes = lambda _: 1
    delays: list[float] = []
    result = run_feed_continuously(
        _config(tmp_path),
        dependencies=deps,
        max_slices=2,
        sleep=delays.append,
    )
    assert result["status"] == "continuous_terminal_blocked"
    assert result["last_result"]["status"] == "blocked_storage"
    assert result["attempt_count"] == 1
    assert delays == []
    assert fakes.capture_calls == 0


def test_continuous_network_disabled_config_is_terminal(tmp_path: Path) -> None:
    base = _config(tmp_path)
    config = FeedConfig(**{**base.__dict__, "execute_network": False})
    fakes = RunnerFakes()
    delays: list[float] = []
    result = run_feed_continuously(
        config,
        dependencies=fakes.dependencies(),
        max_slices=1,
        sleep=delays.append,
    )
    assert result["status"] == "continuous_terminal_blocked"
    assert result["last_result"]["status"] == "blocked_public_network"
    assert result["last_result"]["retryable"] is False
    assert delays == []
    assert fakes.capture_calls == 0


def test_continuous_stop_sentinel_prevents_slice(tmp_path: Path) -> None:
    config = _config(tmp_path)
    sentinel = config.runtime_root / "STOP"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("operator stop\n", encoding="utf-8")
    fakes = RunnerFakes()
    result = run_feed_continuously(
        config,
        dependencies=fakes.dependencies(),
        stop_sentinel=sentinel,
    )
    assert result["status"] == "continuous_stopped_by_sentinel"
    assert result["attempt_count"] == 0
    assert fakes.capture_calls == 0


def test_prune_never_runs_before_publication_finalize(tmp_path: Path) -> None:
    base = _config(tmp_path)
    config = FeedConfig(
        **{**base.__dict__, "prune_published_runtime_payload": True}
    )
    fakes = RunnerFakes(publish_error=True)
    result = run_feed_slice(config, dependencies=fakes.dependencies())
    assert result["status"] == "blocked_publication"
    slice_root = next((config.runtime_root / "slices").iterdir())
    assert (slice_root / "capture").is_dir()
    assert (slice_root / "immutable_export").is_dir()
    assert not (config.runtime_root / "prune_receipts").exists()
    assert fakes.removed_targets == []


def test_prune_failure_is_terminal_but_publication_remains(tmp_path: Path) -> None:
    fakes = RunnerFakes(prune_error=True)
    result = run_feed_continuously(
        _config(tmp_path),
        dependencies=fakes.dependencies(),
        max_slices=2,
        initial_backoff_seconds=0,
        max_backoff_seconds=0,
    )
    assert result["status"] == "continuous_terminal_blocked"
    assert result["last_result"]["status"] == "blocked_runtime_prune"
    assert result["last_result"]["publication_committed"] is True
    assert result["published_slice_count"] == 1
    assert fakes.capture_calls == 1
    assert len(fakes.published_targets) == 1
    assert fakes.published_targets[0].is_dir()
    receipts = list(
        (_config(tmp_path).runtime_root / "prune_receipts").glob("*-failed-*.json")
    )
    assert len(receipts) == 1


def test_startup_idempotently_prunes_finalized_unpruned_slice(tmp_path: Path) -> None:
    config = _config(tmp_path)
    fakes = RunnerFakes()
    first = run_feed_slice(config, dependencies=fakes.dependencies())
    assert first["status"] == "published_quality_checked"
    first_slice = next((config.runtime_root / "slices").iterdir())
    assert (first_slice / "capture").is_dir()
    pruning = FeedConfig(
        **{**config.__dict__, "prune_published_runtime_payload": True}
    )
    deps = fakes.dependencies()
    deps.disk_free_bytes = lambda _: 1
    second = run_feed_slice(pruning, dependencies=deps)
    assert second["status"] == "blocked_storage"
    assert not (first_slice / "capture").exists()
    assert not (first_slice / "immutable_export").exists()
    receipt = (
        pruning.runtime_root
        / "prune_receipts"
        / f"{first_slice.name}-pruned.json"
    )
    assert receipt.is_file()
    before = receipt.read_bytes()
    third = run_feed_slice(pruning, dependencies=deps)
    assert third["status"] == "blocked_storage"
    assert receipt.read_bytes() == before
    assert fakes.published_targets[0].is_dir()
