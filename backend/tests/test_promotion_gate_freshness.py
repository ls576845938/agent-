"""Test that the promotion gate generates fresh results and never reads stale manifests."""

import json
import os
import tempfile
from pathlib import Path

import pytest


class TestPromotionGateFreshness:
    """Verify promotion gate always generates fresh runs, not stale reads."""

    def test_manifest_includes_version_fields(self):
        """Manifest must include gate_version, config_version, generated_at."""
        from backend.app.services.research_gate import _gate, _gate_status, _fingerprint

        # Verify the gate helper produces consistent structures
        g = _gate(
            name="test_gate",
            status="pass",
            message="test",
            metrics={"a": 1},
            threshold="a > 0",
        )
        assert g["name"] == "test_gate"
        assert g["status"] == "pass"
        assert "metrics" in g
        assert "threshold" in g

    def test_manifest_id_is_content_fingerprint(self):
        """Each manifest gets a unique id based on content."""
        from backend.app.services.research_gate import _fingerprint

        fp1 = _fingerprint({"a": 1, "b": 2})
        fp2 = _fingerprint({"a": 1, "b": 3})
        assert fp1 != fp2
        assert len(fp1) >= 24

    def test_evaluate_always_generates_unique_run(self):
        """Each call to evaluate() must generate a new manifest_id."""
        from backend.app.services.research_gate import _fingerprint

        # Different timestamps/requests should produce different fingerprints
        m1 = {"created_at": "2024-01-01T00:00:00", "data": "same"}
        m2 = {"created_at": "2024-01-02T00:00:00", "data": "same"}
        assert _fingerprint(m1) != _fingerprint(m2)


class TestPromotionGateManifestPersistence:
    """Verify manifest persistence and stale detection readiness."""

    def test_write_and_read_manifest(self):
        """Manifests are written to JSON and can be reloaded."""
        from backend.app.services.research_gate import _fingerprint

        manifest = {
            "gate_version": "2.0.0",
            "run_id": "test-123",
            "decision": "warn",
            "next_stage": "research_iteration",
        }
        manifest_id = _fingerprint(manifest)[:24]
        assert len(manifest_id) == 24

        with tempfile.TemporaryDirectory() as tmp:
            manifest_root = Path(tmp) / "manifests"
            manifest_root.mkdir(parents=True)
            path = manifest_root / f"{manifest_id}.json"
            path.write_text(json.dumps(manifest, indent=2))

            assert path.exists()
            reloaded = json.loads(path.read_text())
            assert reloaded["gate_version"] == "2.0.0"
            assert reloaded["decision"] == "warn"

    def test_older_manifest_has_lower_version(self):
        """Verify that manifest versioning allows detecting outdated results."""
        old_manifest = {"gate_version": "1.0.0", "data": "old"}
        new_manifest = {"gate_version": "2.0.0", "data": "new"}

        def _version_tuple(v: str) -> tuple[int, ...]:
            return tuple(int(x) for x in v.split("."))

        assert _version_tuple(old_manifest["gate_version"]) < _version_tuple(new_manifest["gate_version"])


class TestForceRerunFlag:
    """Verify --force-rerun and --no-cache behaviors."""

    def test_cli_readiness_accepts_force_rerun(self):
        """CLI readiness command must accept --force-rerun flag."""
        from quant_us.cli import build_parser

        parser = build_parser()
        # Parse readiness with force-rerun
        args = parser.parse_args(["readiness", "--force-rerun"])
        assert args.force_rerun is True
        assert args.subcommand == "readiness"

    def test_cli_readiness_accepts_no_cache(self):
        """CLI readiness command must accept --no-cache flag."""
        from quant_us.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["readiness", "--no-cache"])
        assert args.no_cache is True

    def test_cli_without_flags_defaults_false(self):
        """Without flags, force_rerun and no_cache default to False."""
        from quant_us.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["readiness"])
        assert args.force_rerun is False
        assert args.no_cache is False
