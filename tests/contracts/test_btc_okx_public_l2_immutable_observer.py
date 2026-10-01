from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import pytest

from quant_crypto.data.immutable_okx_l2_export import ATTESTATION_NAME
from quant_crypto.data.okx_l2_capture_contract import OKX_L2_RAW_MANIFEST_FILE, OKX_L2_RAW_MESSAGES_FILE
from scripts.run_btc_okx_public_l2_immutable_observer import (
    MINIMUM_FREE_GIB,
    ObserverConfig,
    ObserverDependencies,
    WriterConflict,
    run_observer,
)


BASE = "9f53d61183a3e4c1aa00390b2800f89b80d8ec8b"
NOW = datetime(2026, 7, 29, 4, 0, tzinfo=timezone.utc)


def _config(tmp_path: Path, **overrides: Any) -> ObserverConfig:
    values = {
        "repo_root": Path(__file__).resolve().parents[2],
        "runtime_root": tmp_path / "external-runtime",
        "shared_data_root": tmp_path / "shared-data",
        "duration_hours": 24.0,
        "slice_seconds": 60.0,
        "max_messages": 100,
        "clock_samples": 9,
        "execute_network": True,
        "once": True,
        "minimum_free_gib": MINIMUM_FREE_GIB,
        "source_head": BASE,
    }
    values.update(overrides)
    return ObserverConfig(**values)


class Fakes:
    def __init__(
        self,
        *,
        clock_pass: bool = True,
        w32_degraded: bool = False,
        unrecovered: int = 0,
        publish_error: bool = False,
        coverage_seconds: float = 60.0,
        coverage_start: datetime = NOW,
        coverage_end: datetime | None = None,
        free_gib: float = 100.0,
    ) -> None:
        self.clock_pass = clock_pass
        self.w32_degraded = w32_degraded
        self.unrecovered = unrecovered
        self.publish_error = publish_error
        self.coverage_seconds = coverage_seconds
        self.coverage_start = coverage_start
        self.coverage_end = coverage_end or coverage_start + timedelta(seconds=coverage_seconds)
        self.free_gib = free_gib
        self.clock_calls = 0
        self.capture_calls = 0
        self.publish_calls = 0
        self.now_value = self.coverage_end

    def clock(self, **kwargs: Any) -> dict[str, Any]:
        self.clock_calls += 1
        output = Path(kwargs["output_dir"])
        output.mkdir(parents=True, exist_ok=True)
        payload = {
            "server_time_offset_verified": self.clock_pass,
            "sample_count_requested": kwargs["sample_count"],
            "server_time_metrics": {
                "abs_offset_p50_ms": 10.0,
                "abs_offset_p95_ms": 20.0,
                "abs_offset_max_ms": 30.0,
                "round_trip_p95_ms": 40.0,
            },
            "blockers": [] if self.clock_pass else ["okx_server_time_offset_exceeds_policy"],
        }
        (output / "btc_okx_server_time_preflight_report.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        return payload

    def capture(self, **kwargs: Any) -> dict[str, Any]:
        self.capture_calls += 1
        bundle = Path(kwargs["bundle_dir"])
        bundle.mkdir(parents=True, exist_ok=True)
        (bundle / OKX_L2_RAW_MESSAGES_FILE).write_text("{}\n", encoding="utf-8")
        (bundle / OKX_L2_RAW_MANIFEST_FILE).write_text("{}\n", encoding="utf-8")
        payload = {
            "status": "verified_preflight",
            "message_count": 60,
            "data_message_count": 59,
            "connection_count": 3,
            "forced_reconnect_count": 2,
            "channel_counts": {"books": 59},
            "blockers": [],
        }
        Path(kwargs["capture_report_path"]).write_text(json.dumps(payload), encoding="utf-8")
        return payload

    def export(self, **kwargs: Any) -> dict[str, Any]:
        output = Path(kwargs["output_dir"])
        output.mkdir(parents=True, exist_ok=False)
        attestation = {
            "schema_version": "btc_okx_l2_dataready_attestation_v1",
            "quality_checked": self.unrecovered == 0,
            "sequence_validation_status": "pass" if self.unrecovered == 0 else "blocked",
            "unrecovered_gap_count": self.unrecovered,
            "sequence_gap_count": 0,
            "duplicate_sequence_count": 0,
            "out_of_order_sequence_count": 0,
            "two_sided_coverage_pct": 100.0,
            "observed_history_seconds": self.coverage_seconds,
            "coverage_start": self.coverage_start.isoformat().replace("+00:00", "Z"),
            "coverage_end": self.coverage_end.isoformat().replace("+00:00", "Z"),
            "snapshot_count": 3,
            "update_count": 56,
            "reconnect_count": 2,
            "resync_snapshot_count": 2,
            "promotion_evidence_ready": False,
            "promotion_blockers": ["btc_okx_l2_history_below_30_natural_days"],
        }
        attestation_path = output / ATTESTATION_NAME
        attestation_path.write_text(json.dumps(attestation), encoding="utf-8")
        return {"status": "quality_checked", "attestation_path": str(attestation_path), "blockers": []}

    def publish(self, **kwargs: Any) -> dict[str, Any]:
        self.publish_calls += 1
        if self.publish_error:
            raise RuntimeError("injected_publisher_failure")
        source = Path(kwargs["source"])
        assert (source / "clock" / "btc_okx_server_time_preflight_report.json").is_file()
        assert (source / "capture" / OKX_L2_RAW_MESSAGES_FILE).is_file()
        assert (source / "immutable_export" / ATTESTATION_NAME).is_file()
        assert (source / "observer_slice_metadata.json").is_file()
        manifest = {
            "dataset_version": kwargs["dataset_version"],
            "aggregate_sha256": "a" * 64,
            "storage_relative_path": f"datasets/x/{kwargs['dataset_version']}",
        }
        output = Path(kwargs["manifest_output"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(manifest), encoding="utf-8")
        return {"status": "published", "path": str(kwargs["shared_root"] / "datasets"), "manifest": manifest}

    def dependencies(self) -> ObserverDependencies:
        return ObserverDependencies(
            clock=self.clock,
            capture=self.capture,
            export=self.export,
            publish=self.publish,
            now=lambda: self.now_value,
            sleep=lambda _: None,
            disk_free_bytes=lambda _: int(self.free_gib * (1024**3)),
            w32time=lambda: {
                "available": True,
                "degraded": self.w32_degraded,
                "leap_zero": not self.w32_degraded,
                "stratum_nonzero": not self.w32_degraded,
            },
        )


def test_happy_path_is_running_resumable_and_updates_pointer_last(tmp_path: Path) -> None:
    fakes = Fakes()
    result = run_observer(_config(tmp_path), dependencies=fakes.dependencies())
    assert result["status"] == "running_resumable"
    assert result["state"]["qualified_start_utc"]
    assert result["state"]["qualified_coverage_seconds"] == 60.0
    pointer = json.loads((_config(tmp_path).runtime_root / "latest_pointer.json").read_text(encoding="utf-8"))
    assert pointer["latest_pointer_updated_last"] is True
    assert Path(result["event_path"]).is_file()
    assert fakes.clock_calls == fakes.capture_calls == fakes.publish_calls == 1
    assert all(value is False for value in result["safety_flags"].values())


def test_single_writer_conflict_precedes_network_and_writes(tmp_path: Path) -> None:
    fakes = Fakes()

    @contextmanager
    def conflict(_: Path) -> Iterator[None]:
        raise WriterConflict("injected_conflict")
        yield

    deps = fakes.dependencies()
    deps.lock = conflict
    result = run_observer(_config(tmp_path), dependencies=deps)
    assert result["status"] == "blocked_writer_conflict"
    assert fakes.clock_calls == 0
    assert not _config(tmp_path).runtime_root.exists()


def test_direct_clock_failure_fails_closed_before_ws(tmp_path: Path) -> None:
    fakes = Fakes(clock_pass=False)
    result = run_observer(_config(tmp_path), dependencies=fakes.dependencies())
    assert result["status"] == "blocked_clock"
    assert fakes.clock_calls == 1
    assert fakes.capture_calls == 0


def test_w32_degraded_direct_clock_pass_can_publish(tmp_path: Path) -> None:
    fakes = Fakes(w32_degraded=True)
    result = run_observer(_config(tmp_path), dependencies=fakes.dependencies())
    health = json.loads(Path(result["health_path"]).read_text(encoding="utf-8"))
    assert result["status"] == "running_resumable"
    assert health["w32time_degraded"] is True
    assert health["direct_clock"]["verified"] is True


def test_unrecovered_sequence_gap_blocks_publication(tmp_path: Path) -> None:
    fakes = Fakes(unrecovered=1)
    result = run_observer(_config(tmp_path), dependencies=fakes.dependencies())
    assert result["status"] == "blocked_sequence"
    assert fakes.publish_calls == 0
    assert result["state"]["qualified_coverage_seconds"] == 0.0


def test_publisher_failure_is_resumable_without_recapture(tmp_path: Path) -> None:
    fakes = Fakes(publish_error=True)
    first = run_observer(_config(tmp_path), dependencies=fakes.dependencies())
    assert first["status"] == "blocked_publication"
    assert (_config(tmp_path).runtime_root / "inflight.json").is_file()
    fakes.publish_error = False
    second = run_observer(_config(tmp_path), dependencies=fakes.dependencies())
    assert second["status"] == "running_resumable"
    assert fakes.capture_calls == 1
    assert fakes.publish_calls == 2
    assert not (_config(tmp_path).runtime_root / "inflight.json").exists()


def test_storage_guard_at_20_gib_precedes_clock(tmp_path: Path) -> None:
    fakes = Fakes(free_gib=19.99)
    result = run_observer(_config(tmp_path), dependencies=fakes.dependencies())
    assert result["status"] == "blocked_storage"
    assert fakes.clock_calls == 0


def test_resume_adds_new_append_only_slice_without_overwrite(tmp_path: Path) -> None:
    fakes = Fakes()
    first = run_observer(_config(tmp_path), dependencies=fakes.dependencies())
    first_event = Path(first["event_path"])
    first_bytes = first_event.read_bytes()
    fakes.coverage_start = NOW + timedelta(minutes=2)
    fakes.coverage_end = fakes.coverage_start + timedelta(seconds=60)
    fakes.now_value = fakes.coverage_end
    second = run_observer(_config(tmp_path), dependencies=fakes.dependencies())
    assert Path(second["event_path"]) != first_event
    assert first_event.read_bytes() == first_bytes
    assert second["state"]["qualified_slice_count"] == 2


def test_sleep_and_observation_gap_are_not_counted_as_coverage(tmp_path: Path) -> None:
    fakes = Fakes(
        coverage_seconds=3_600.0,
        coverage_start=NOW,
        coverage_end=NOW + timedelta(hours=23),
    )
    result = run_observer(_config(tmp_path), dependencies=fakes.dependencies())
    assert result["status"] == "running_resumable"
    assert result["state"]["qualified_coverage_seconds"] == 3_600.0
    assert result["state"]["estimated_gap_seconds"] == 22 * 3_600.0
    assert result["state"]["complete"] is False


def test_cannot_complete_before_24h_even_with_claimed_coverage(tmp_path: Path) -> None:
    fakes = Fakes(
        coverage_seconds=24 * 3_600.0,
        coverage_start=NOW,
        coverage_end=NOW + timedelta(hours=23, minutes=59),
    )
    result = run_observer(_config(tmp_path), dependencies=fakes.dependencies())
    assert result["status"] == "running_resumable"
    assert result["state"]["complete"] is False


def test_completes_only_after_24h_elapsed_and_24h_qualified_coverage(tmp_path: Path) -> None:
    fakes = Fakes(
        coverage_seconds=24 * 3_600.0,
        coverage_start=NOW,
        coverage_end=NOW + timedelta(hours=24),
    )
    result = run_observer(_config(tmp_path), dependencies=fakes.dependencies())
    assert result["status"] == "complete_quality_checked_observe_only"
    assert result["state"]["qualified_coverage_seconds"] == 24 * 3_600.0
    assert result["state"]["estimated_gap_seconds"] == 0.0


def test_minimum_storage_guard_cannot_be_weakened(tmp_path: Path) -> None:
    fakes = Fakes()
    with pytest.raises(ValueError, match="observer_storage_guard_below_contract"):
        run_observer(_config(tmp_path, minimum_free_gib=19.0), dependencies=fakes.dependencies())
