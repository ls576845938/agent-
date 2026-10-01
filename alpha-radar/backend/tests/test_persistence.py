"""Tests for the JSON-file persistence module."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from backend.persistence import (
    save_audit_result,
    load_audit_result,
    find_audit_results_by_target,
)


class TestSaveAndLoad:
    def test_save_and_load_roundtrip(self):
        data = {
            "audit_id": "test-001",
            "target_type": "signal",
            "target_id": "sig_abc",
            "audit_score": 85.0,
            "audit_status": "HIGH_CONVICTION",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = save_audit_result(data, data_dir=tmpdir)
            assert path.exists()
            assert path.name == "test-001.json"

            loaded = load_audit_result("test-001", data_dir=tmpdir)
            assert loaded == data

    def test_load_nonexistent_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = load_audit_result("does-not-exist", data_dir=tmpdir)
            assert result is None

    def test_save_missing_audit_id_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="audit_id"):
                save_audit_result({"score": 1.0}, data_dir=tmpdir)

    def test_save_empty_audit_id_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="audit_id"):
                save_audit_result({"audit_id": ""}, data_dir=tmpdir)

    def test_data_dir_is_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nested = Path(tmpdir) / "a" / "b" / "c"
            data = {"audit_id": "x", "score": 1.0}
            path = save_audit_result(data, data_dir=nested)
            assert path.exists()
            assert nested.exists()


class TestFindByTarget:
    def test_find_matches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            save_audit_result(
                {"audit_id": "a1", "target_type": "factor", "target_id": "f_abc"},
                data_dir=tmpdir,
            )
            save_audit_result(
                {"audit_id": "a2", "target_type": "factor", "target_id": "f_abc"},
                data_dir=tmpdir,
            )
            save_audit_result(
                {"audit_id": "a3", "target_type": "signal", "target_id": "s_xyz"},
                data_dir=tmpdir,
            )

            results = find_audit_results_by_target("factor", "f_abc", data_dir=tmpdir)
            assert len(results) == 2
            assert {r["audit_id"] for r in results} == {"a1", "a2"}

    def test_find_no_matches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            save_audit_result(
                {"audit_id": "a1", "target_type": "signal", "target_id": "s_abc"},
                data_dir=tmpdir,
            )
            results = find_audit_results_by_target("factor", "f_nonexistent", data_dir=tmpdir)
            assert results == []

    def test_find_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = find_audit_results_by_target("signal", "s_abc", data_dir=tmpdir)
            assert results == []

    def test_find_skips_bad_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # valid file
            save_audit_result(
                {"audit_id": "good", "target_type": "signal", "target_id": "s_abc"},
                data_dir=tmpdir,
            )
            # corrupt file
            (Path(tmpdir) / "bad.json").write_text("not json", encoding="utf-8")
            # unrelated file
            (Path(tmpdir) / "readme.txt").write_text("hello", encoding="utf-8")

            results = find_audit_results_by_target("signal", "s_abc", data_dir=tmpdir)
            assert len(results) == 1
            assert results[0]["audit_id"] == "good"
